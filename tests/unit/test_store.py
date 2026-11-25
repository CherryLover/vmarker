# 磁盘结构、Markdown 文件、系列
from __future__ import annotations

import json

import pytest

from tests.conftest import add_ai


def write(user, oid, name, text):
    return user.put(f"/api/v1/files/{oid}/{name}", json={"content": text})


def test_layout_on_disk(user, cfg, pid):
    write(user, pid, "文字稿.md", "# 一")
    root = cfg.data_dir / "projects" / pid
    assert json.loads((root / "project.json").read_text())["title"] == "测试片"
    assert (root / "文字稿.md").read_text() == "# 一"
    assert (cfg.data_dir / "vmarker.db").is_file()


@pytest.mark.parametrize(
    "name", ["a.txt", ".hidden.md", "..%2Fx.md", "a%2Fb.md", "%2e%2e.md", "a%5Cb.md", "a%00.md", "a.md%0A"]
)
def test_bad_names(user, pid, name):
    assert write(user, pid, name, "x").status_code in (404, 422)


def test_bad_ids(user):
    for oid in ("..", "p-xyz", "p-0000000000"):
        assert user.get(f"/api/v1/projects/{oid}").status_code == 404


def test_history_and_delete(user, pid):
    write(user, pid, "a.md", "one")
    write(user, pid, "a.md", "two")
    write(user, pid, "a.b.md", "别混进来")
    write(user, pid, "a.b.md", "别混进来2")
    versions = user.get(f"/api/v1/files/{pid}/a.md/history").json()
    assert len(versions) == 1
    v = versions[0]["version"]
    assert user.get(f"/api/v1/files/{pid}/a.md/history/{v}").json()["content"] == "one"
    assert user.get(f"/api/v1/files/{pid}/a.md/history/x..y").status_code == 404
    assert user.delete(f"/api/v1/files/{pid}/a.md").status_code == 204
    assert user.get(f"/api/v1/files/{pid}/a.md").status_code == 404
    assert len(user.get(f"/api/v1/files/{pid}/a.md/history").json()) == 2


def test_series_flow(user, pid):
    sid = user.post(f"/api/v1/projects/{pid}/to-series", json={"name": "系列甲"}).json()["id"]
    assert user.get(f"/api/v1/projects/{pid}").json()["position"] == 1
    assert user.post(f"/api/v1/projects/{pid}/to-series", json={"name": "再来"}).status_code == 422
    p2 = user.post("/api/v1/projects", json={"title": "第二集", "series_id": sid}).json()
    assert p2["position"] == 2
    assert user.put(f"/api/v1/series/{sid}/order", json={"ids": [p2["id"], pid]}).status_code == 204
    assert [e["title"] for e in user.get(f"/api/v1/series/{sid}").json()["episodes"]] == ["第二集", "测试片"]
    assert user.put(f"/api/v1/series/{sid}/order", json={"ids": [pid]}).status_code == 422
    assert user.delete(f"/api/v1/series/{sid}").status_code == 422
    assert user.post("/api/v1/projects", json={"title": "x", "series_id": "s-0000000000"}).status_code == 404


def test_distill(user, fake, pid):
    add_ai(user, fake)
    sid = user.post(f"/api/v1/projects/{pid}/to-series", json={"name": "甲"}).json()["id"]
    assert user.post(f"/api/v1/series/{sid}/distill", json={}).status_code == 422
    write(user, pid, "a.md", "内容")
    assert user.post(f"/api/v1/series/{sid}/distill", json={}).json()["content"] == "可用"


def test_delete_goes_to_trash(user, cfg, pid):
    write(user, pid, "a.md", "x")
    user.post(f"/api/v1/projects/{pid}/confirm")
    assert user.delete(f"/api/v1/projects/{pid}").status_code == 204
    assert user.get(f"/api/v1/projects/{pid}").status_code == 404
    assert list((cfg.data_dir / "trash").glob(f"{pid}-*/a.md"))
    assert user.app.state.tasks.claim("w") is None
