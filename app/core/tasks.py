# ============================================================================
#  tasks —— 制作任务的状态机与视频版本
#
#    queued ─领取─▶ working ─交片─▶ review ─通过─▶ done
#                     │               └─打回─▶ rejected（同时生成带意见的新任务）
#                     ├─失败─▶ failed ─重试─▶ 新任务
#                     └─租约过期─▶ 可被重新领取
#
#  领取是一条原子 UPDATE；claim 是本次领取的凭证，过期被抢走后旧 worker 的写入会被拒绝。
# ============================================================================
from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path

from app.core.store import Missing, Store, StoreError
from app.db import DB, now_iso


class Conflict(Exception):
    """状态不允许（对应 409）。"""


class Tasks:
    def __init__(self, db: DB, store: Store, lease_minutes: int):
        self.db, self.store, self.lease = db, store, lease_minutes

    # ---------------------------------------------------------------- 查询
    def get(self, tid: int) -> dict:
        row = self.db.one("SELECT * FROM tasks WHERE id = ?", tid)
        if not row:
            raise Missing("任务不存在")
        return row

    def of_project(self, pid: str) -> list[dict]:
        rows = self.db.all("SELECT * FROM tasks WHERE project_id = ? ORDER BY id DESC", pid)
        return [{k: v for k, v in r.items() if k != "claim"} for r in rows]

    def videos(self, pid: str) -> list[dict]:
        rows = self.db.all("SELECT * FROM videos WHERE project_id = ? ORDER BY version DESC", pid)
        for r in rows:  # cover = 封面修改时间，前端拿来做 poster 的缓存戳；没有封面为 None
            path = self.store.cover(pid, r["task_id"])
            r["cover"] = int(path.stat().st_mtime) if path else None
        return rows

    def status(self, pid: str) -> str:
        row = self.db.one("SELECT status FROM tasks WHERE project_id = ? ORDER BY id DESC LIMIT 1", pid)
        return row["status"] if row else "planning"

    # ---------------------------------------------------------------- 人的动作
    def _enqueue(self, pid: str, release: int, feedback: str | None = None) -> int:
        try:
            return self.db.run(
                "INSERT INTO tasks (project_id, release, status, feedback, created_at, updated_at) "
                "VALUES (?, ?, 'queued', ?, ?, ?)", pid, release, feedback, now_iso(), now_iso(),
            )  # fmt: skip
        except sqlite3.IntegrityError:
            raise Conflict("这个视频已经有进行中的任务") from None

    def confirm(self, pid: str) -> int:
        self.store.get(pid)
        if self.status(pid) in ("queued", "working", "review"):
            raise Conflict("这个视频已经有进行中的任务")
        return self._enqueue(pid, self.store.snapshot(pid))

    def _move(self, tid: int, to: str, *allowed: str) -> dict:
        marks = ", ".join("?" * len(allowed))
        n = self.db.changed(
            f"UPDATE tasks SET status = ?, claim = NULL, updated_at = ? WHERE id = ? AND status IN ({marks})",
            to, now_iso(), tid, *allowed,
        )  # fmt: skip
        if not n:
            raise Conflict(f"任务当前是 {self.get(tid)['status']}，不能执行这个操作")
        return self.get(tid)

    def approve(self, tid: int) -> None:
        self._move(tid, "done", "review")
        self._mark_latest(tid, "approved")

    def reject(self, tid: int, feedback: str) -> int:
        if not feedback.strip():
            raise StoreError("请写明要改什么")
        task = self._move(tid, "rejected", "review")
        self._mark_latest(tid, "rejected")
        return self._enqueue(task["project_id"], task["release"], feedback.strip())

    def retry(self, tid: int) -> int:
        task = self.get(tid)
        if task["status"] not in ("failed", "canceled"):
            raise Conflict("只有失败或取消的任务可以重试")
        return self._enqueue(task["project_id"], task["release"], task["feedback"])

    def cancel(self, tid: int) -> None:
        self._move(tid, "canceled", "queued", "working")

    def _mark_latest(self, tid: int, status: str) -> None:
        self.db.run(
            "UPDATE videos SET status = ? WHERE id = (SELECT max(id) FROM videos WHERE task_id = ?)",
            status,
            tid,
        )

    # ---------------------------------------------------------------- 制作端的动作
    def claim(self, worker: str) -> dict | None:
        token, now = secrets.token_urlsafe(16), now_iso()
        # 领取成功后 claim 唯一，按它取回即可
        n = self.db.changed(
            "UPDATE tasks SET status = 'working', claim = ?, worker = ?, lease_until = ?, progress = NULL, updated_at = ? "
            "WHERE id = (SELECT id FROM tasks WHERE status = 'queued' OR (status = 'working' AND lease_until < ?) "
            "ORDER BY id LIMIT 1)",
            token, worker[:80], now_iso(self.lease), now, now,
        )  # fmt: skip
        if not n:
            return None
        return self._brief(self.db.one("SELECT * FROM tasks WHERE claim = ?", token))

    def _brief(self, task: dict) -> dict:
        p = self.store.get(task["project_id"])
        return {
            "task_id": task["id"],
            "claim": task["claim"],
            "lease_until": task["lease_until"],
            "project": {k: p[k] for k in ("id", "title", "brief", "position")},
            "series": self.store.get(p["series_id"])["name"] if p["series_id"] else None,
            "release": task["release"],
            "feedback": task["feedback"],
            "files": self.store.release(p["id"], task["release"]),
        }

    def check(self, tid: int, claim: str) -> dict:
        task = self.get(tid)
        if task["status"] != "working" or not secrets.compare_digest(task["claim"] or "", claim):
            raise Conflict("这次领取已失效（任务被取消、交付或被重新领取）")
        return task

    def progress(self, tid: int, claim: str, text: str) -> str:
        until = now_iso(self.lease)
        self._write(tid, claim, "progress = ?, lease_until = ?", text[:500], until)
        return until

    def fail(self, tid: int, claim: str, error: str) -> None:
        self._write(tid, claim, "status = 'failed', error = ?, claim = NULL", error[:2000])

    def _write(self, tid: int, claim: str, sets: str, *args) -> None:
        self.check(tid, claim)
        n = self.db.changed(
            f"UPDATE tasks SET {sets}, updated_at = ? WHERE id = ? AND claim = ? AND status = 'working'",
            *args, now_iso(), tid, claim,
        )  # fmt: skip
        if not n:
            raise Conflict("这次领取已失效")

    def add_video(self, tid: int, claim: str, tmp: Path) -> dict:
        """把传完的临时文件登记成一个新版本；同一次领取重复上传会产生新版本。"""
        pid = self.check(tid, claim)["project_id"]
        with self.db.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT coalesce(max(version), 0) + 1 AS v FROM videos WHERE project_id = ?", (pid,)
            )
            version = row.fetchone()["v"]
            dest = self.store.video(pid, version)
            dest.parent.mkdir(exist_ok=True)
            os.replace(tmp, dest)
            c.execute(
                "INSERT INTO videos (project_id, task_id, version, size, status, created_at) VALUES (?, ?, ?, ?, 'uploaded', ?)",
                (pid, tid, version, dest.stat().st_size, now_iso()),
            )
        return {"version": version, "size": dest.stat().st_size}

    def set_cover(self, tid: int, claim: str, tmp: Path, ext: str) -> None:
        """同一任务只留一张封面，重复上传即替换。"""
        pid = self.check(tid, claim)["project_id"]
        folder = self.store.dir(pid) / "video"
        folder.mkdir(exist_ok=True)
        for old in folder.glob(f"t{tid}-cover.*"):
            old.unlink()
        os.replace(tmp, folder / f"t{tid}-cover.{ext}")

    def cover_path(self, vid: int) -> Path:
        row = self.db.one("SELECT project_id, task_id FROM videos WHERE id = ?", vid)
        path = self.store.cover(row["project_id"], row["task_id"]) if row else None
        if not path:
            raise Missing("这个版本没有封面")
        return path

    def submit(self, tid: int, claim: str, note: str) -> None:
        self.check(tid, claim)
        video = self.db.one("SELECT max(id) AS id FROM videos WHERE task_id = ? AND status = 'uploaded'", tid)
        if not video["id"]:
            raise Conflict("还没有上传视频，先 PUT mp4 再提交")
        self._write(tid, claim, "status = 'review', claim = NULL")
        self.db.run("UPDATE videos SET status = 'review', note = ? WHERE id = ?", note[:2000], video["id"])

    # ---------------------------------------------------------------- 视频文件
    def video_path(self, vid: int) -> tuple[dict, Path]:
        row = self.db.one("SELECT * FROM videos WHERE id = ?", vid)
        path = self.store.video(row["project_id"], row["version"]) if row else None
        if not path or not path.is_file():
            raise Missing("视频不存在")
        return row, path

    def delete_video(self, vid: int) -> None:
        row, path = self.video_path(vid)
        if row["status"] in ("review", "approved"):
            raise Conflict("待审或已通过的视频不能删除")
        path.unlink()
        self.db.run("DELETE FROM videos WHERE id = ?", vid)
