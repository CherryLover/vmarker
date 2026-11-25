# 制作闭环：确认 → 领取 → 上传 → 交付 → 打回 / 通过 → 播放 / 下载
from __future__ import annotations

import pytest

from tests.conftest import MP4, make_key


@pytest.fixture
def ready(user, pid):
    user.put(f"/api/v1/files/{pid}/文字稿.md", json={"content": "v1"})
    assert user.post(f"/api/v1/projects/{pid}/confirm").status_code == 201
    return user.app.state.tasks


def upload(user, h, task, data=MP4, claim=None):
    headers = {**h, "X-Claim": claim or task["claim"]}
    return user.put(f"/api/v1/tasks/{task['task_id']}/video", content=data, headers=headers)


def test_confirm_needs_files_and_is_single(user, pid):
    assert user.post(f"/api/v1/projects/{pid}/confirm").status_code == 422
    user.put(f"/api/v1/files/{pid}/a.md", json={"content": "x"})
    assert user.post(f"/api/v1/projects/{pid}/confirm").status_code == 201
    assert user.post(f"/api/v1/projects/{pid}/confirm").status_code == 409


def test_claim_gets_frozen_snapshot_once(user, ready, pid):
    user.put(f"/api/v1/files/{pid}/文字稿.md", json={"content": "改过了"})
    task = ready.claim("w1")
    assert task["files"] == {"文字稿.md": "v1"} and ready.claim("w2") is None
    # 凭证不出现在项目接口里
    assert task["claim"] not in user.get(f"/api/v1/projects/{pid}").text


def test_full_loop(user, ready, pid, cfg):
    h = make_key(user, "produce")
    task = ready.claim("w")
    up = upload(user, h, task).json()
    assert up == {"version": 1, "size": len(MP4)}
    assert (cfg.data_dir / "projects" / pid / "video" / "v1.mp4").read_bytes() == MP4
    ready.submit(task["task_id"], task["claim"], "初版")
    assert user.post(f"/api/v1/tasks/{task['task_id']}/reject", json={"feedback": " "}).status_code == 422
    assert (
        user.post(f"/api/v1/tasks/{task['task_id']}/reject", json={"feedback": "片头太长"}).status_code == 201
    )
    again = ready.claim("w")
    assert again["feedback"] == "片头太长" and again["release"] == 1
    upload(user, h, again)
    ready.submit(again["task_id"], again["claim"], "改了片头")
    assert user.post(f"/api/v1/tasks/{again['task_id']}/approve").status_code == 204
    p = user.get(f"/api/v1/projects/{pid}").json()
    assert p["status"] == "done" and [v["status"] for v in p["videos"]] == ["approved", "rejected"]
    assert user.post(f"/api/v1/tasks/{again['task_id']}/approve").status_code == 409
    # 播放支持拖动，下载带文件名
    vid = p["videos"][0]["id"]
    part = user.get(f"/api/v1/videos/{vid}", headers={"Range": "bytes=4-11"})
    assert (
        part.status_code == 206 and part.content == MP4[4:12] and part.headers["content-type"] == "video/mp4"
    )
    assert (
        user.get(f"/api/v1/videos/{vid}?download=1").headers["content-disposition"].startswith("attachment")
    )
    assert user.delete(f"/api/v1/videos/{vid}").status_code == 409
    assert user.delete(f"/api/v1/videos/{p['videos'][1]['id']}").status_code == 204


def test_bad_uploads_leave_nothing(user, ready, pid, cfg):
    h, task = make_key(user, "produce"), ready.claim("w")
    assert upload(user, h, task, b"not a video at all").status_code == 422
    assert upload(user, h, task, b"").status_code == 422
    assert upload(user, h, task, claim="wrong").status_code == 409
    assert upload(user, make_key(user, "plan"), task).status_code == 403
    assert list((cfg.data_dir / "tmp").iterdir()) == []
    assert user.get(f"/api/v1/projects/{pid}").json()["videos"] == []


def test_expired_lease_is_reclaimed_and_old_worker_rejected(user, ready):
    old = ready.claim("w1")
    user.app.state.db.run("UPDATE tasks SET lease_until = '2000-01-01T00:00:00Z'")
    new = ready.claim("w2")
    assert new["task_id"] == old["task_id"] and new["claim"] != old["claim"]
    assert upload(user, make_key(user, "produce"), old).status_code == 409


def test_fail_retry_cancel(user, ready, pid):
    t = ready.claim("w")
    ready.fail(t["task_id"], t["claim"], "缺素材")
    assert user.get(f"/api/v1/projects/{pid}").json()["status"] == "failed"
    new = user.post(f"/api/v1/tasks/{t['task_id']}/retry").json()["task_id"]
    assert user.post(f"/api/v1/tasks/{t['task_id']}/retry").status_code == 409
    assert user.post(f"/api/v1/tasks/{new}/cancel").status_code == 204
    assert ready.claim("w") is None
