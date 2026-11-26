# ============================================================================
#  store —— 磁盘上的项目与系列（元信息 JSON + 内容 Markdown）
#
#    data/projects/<id>/project.json     元信息，唯一真相源
#                      /*.md             文案、规划、清单……
#                      /.history/        被覆盖或删除的旧版
#                      /releases/v1/     确认制作时的快照，不再改动
#                      /video/v1.mp4     成片
#                      /video/t7-cover.jpg  任务 7 的封面（同一任务的各版共用）
#    data/series/<id>/series.json        系列元信息
#                    /设定.md             系列设定，每一集都会带给 AI
#    data/trash/                         删除的项目移到这里
# ============================================================================
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.db import now_iso

NAME = re.compile(r"[^\s./\\\x00-\x1f<>\"'][^/\\\x00-\x1f<>\"']{0,79}\.md")
ID = re.compile(r"[ps]-[0-9a-f]{10}")
SERIES_DOC = "设定.md"
MAX_FILE = 1_000_000


class StoreError(ValueError):
    """输入不合法（对应 422）。"""


class Missing(LookupError):
    """对象不存在（对应 404）。"""


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Store:
    def __init__(self, root: Path):
        self.root = root
        for d in ("projects", "series", "trash", "tmp"):
            (root / d).mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 路径
    def dir(self, oid: str) -> Path:
        if not ID.fullmatch(oid):
            raise Missing(f"不存在：{oid}")
        return self.root / ("projects" if oid[0] == "p" else "series") / oid

    def _meta(self, oid: str) -> Path:
        return self.dir(oid) / ("project.json" if oid[0] == "p" else "series.json")

    def video(self, pid: str, version: int) -> Path:
        return self.dir(pid) / "video" / f"v{version}.mp4"

    def cover(self, pid: str, tid: int) -> Path | None:
        """封面按任务存：交付前、甚至传视频前上传都能挂到这个任务产出的版本上。"""
        return next((self.dir(pid) / "video").glob(f"t{tid}-cover.*"), None)

    # ---------------------------------------------------------------- 元信息
    def get(self, oid: str) -> dict:
        path = self._meta(oid)
        if not path.is_file():
            raise Missing(f"不存在：{oid}")
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, oid: str, **fields) -> dict:
        meta = {**self.get(oid), **fields, "updated_at": now_iso()}
        return self._save(oid, meta)

    def _save(self, oid: str, meta: dict) -> dict:
        write_atomic(self._meta(oid), json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        return meta

    def _list(self, kind: str) -> list[dict]:
        found = (self.root / kind).glob(f"*/{'project' if kind == 'projects' else 'series'}.json")
        return [json.loads(p.read_text(encoding="utf-8")) for p in found]

    def projects(self) -> list[dict]:
        return sorted(self._list("projects"), key=lambda m: m["updated_at"], reverse=True)

    def series(self) -> list[dict]:
        return sorted(self._list("series"), key=lambda m: m["created_at"], reverse=True)

    def episodes(self, sid: str) -> list[dict]:
        rows = [p for p in self._list("projects") if p["series_id"] == sid]
        return sorted(rows, key=lambda p: p["position"])

    # ---------------------------------------------------------------- 创建
    def create_project(self, title: str, brief: str = "", series_id: str | None = None) -> dict:
        position = self._next_position(series_id) if series_id else None
        oid = "p-" + secrets.token_hex(5)
        return self._save(oid, {
            "id": oid, "title": title, "brief": brief, "series_id": series_id, "position": position,
            "releases": 0, "created_at": now_iso(), "updated_at": now_iso(),
        })  # fmt: skip

    def _next_position(self, sid: str) -> int:
        self.get(sid)  # 系列必须存在
        return max((p["position"] for p in self.episodes(sid)), default=0) + 1

    def create_series(self, name: str, description: str = "") -> dict:
        oid = "s-" + secrets.token_hex(5)
        meta = self._save(oid, {
            "id": oid, "name": name, "description": description,
            "created_at": now_iso(), "updated_at": now_iso(),
        })  # fmt: skip
        self.write_file(
            oid,
            SERIES_DOC,
            f"# {name} · 系列设定\n\n- 受众：\n- 语气：\n- 声音与语速：\n- 每集骨架：\n- 不讲什么：\n",
        )
        return meta

    def to_series(self, pid: str, name: str) -> dict:
        """把单个视频变成新系列的第 1 集。"""
        project = self.get(pid)
        if project["series_id"]:
            raise StoreError("这个视频已经属于一个系列")
        series = self.create_series(name, project["brief"])
        self.update(pid, series_id=series["id"], position=1)
        return series

    def set_series(self, pid: str, sid: str | None) -> dict:
        if self.get(pid)["series_id"] == sid:
            return self.get(pid)
        return self.update(pid, series_id=sid, position=self._next_position(sid) if sid else None)

    def reorder(self, sid: str, ids: list[str]) -> None:
        if sorted(ids) != sorted(p["id"] for p in self.episodes(sid)):
            raise StoreError("顺序列表和系列里的视频对不上")
        for i, pid in enumerate(ids, 1):
            self.update(pid, position=i)

    def trash(self, oid: str) -> None:
        self.get(oid)
        if oid[0] == "s" and self.episodes(oid):
            raise StoreError("系列里还有视频，先把它们移出系列")
        shutil.move(self.dir(oid), self.root / "trash" / f"{oid}-{secrets.token_hex(3)}")

    # ---------------------------------------------------------------- Markdown 文件
    def _file(self, oid: str, name: str) -> Path:
        if not NAME.fullmatch(name):
            raise StoreError("文件名必须以 .md 结尾，且不能包含路径分隔符")
        return self.dir(oid) / name

    def files(self, oid: str) -> list[dict]:
        self.get(oid)
        paths = sorted(p for p in self.dir(oid).glob("*.md") if NAME.fullmatch(p.name))
        return [{"name": p.name, "size": p.stat().st_size, "updated_at": _mtime(p)} for p in paths]

    def read_file(self, oid: str, name: str) -> str:
        path = self._file(oid, name)
        if not path.is_file():
            raise Missing(f"没有这个文件：{name}")
        return path.read_text(encoding="utf-8")

    def write_file(self, oid: str, name: str, content: str) -> None:
        self.get(oid)
        if len(content.encode()) > MAX_FILE:
            raise StoreError("文件太大（上限 1 MB）")
        path = self._file(oid, name)
        self._archive(path)
        write_atomic(path, content)

    def delete_file(self, oid: str, name: str) -> None:
        path = self._file(oid, name)
        if not path.is_file():
            raise Missing(f"没有这个文件：{name}")
        self._archive(path)
        path.unlink()

    def _archive(self, path: Path) -> None:
        if path.is_file():
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            keep = path.parent / ".history" / f"{path.stem}.{stamp}.md"
            keep.parent.mkdir(exist_ok=True)
            shutil.copy2(path, keep)

    def history(self, oid: str, name: str) -> list[dict]:
        stem = self._file(oid, name).stem
        pattern = re.compile(re.escape(stem) + r"\.(\d{8}-\d{6}-\d{6})\.md")
        hits = [m for p in (self.dir(oid) / ".history").glob("*.md") if (m := pattern.fullmatch(p.name))]
        return [{"version": m[1]} for m in sorted(hits, key=lambda m: m[1], reverse=True)]

    def read_history(self, oid: str, name: str, version: str) -> str:
        if not re.fullmatch(r"\d{8}-\d{6}-\d{6}", version):
            raise Missing("没有这个版本")
        path = self.dir(oid) / ".history" / f"{self._file(oid, name).stem}.{version}.md"
        if not path.is_file():
            raise Missing("没有这个版本")
        return path.read_text(encoding="utf-8")

    # ---------------------------------------------------------------- 制作快照
    def snapshot(self, pid: str) -> int:
        files = self.files(pid)
        if not files:
            raise StoreError("还没有任何文件，先和 AI 把文案整理成文件")
        meta = self.get(pid)
        n = meta["releases"] + 1
        dest = self.dir(pid) / "releases" / f"v{n}"
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(self.dir(pid) / f["name"], dest / f["name"])
        doc = self.dir(meta["series_id"]) / SERIES_DOC if meta["series_id"] else None
        if doc and doc.is_file():
            shutil.copy2(doc, dest / f"系列{SERIES_DOC}")
        self.update(pid, releases=n)
        return n

    def release(self, pid: str, n: int) -> dict[str, str]:
        src = self.dir(pid) / "releases" / f"v{n}"
        return {p.name: p.read_text(encoding="utf-8") for p in sorted(src.glob("*.md"))}


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
