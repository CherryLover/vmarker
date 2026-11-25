# 对话：流式、历史保留、写文件、异常路径、断线续看
from __future__ import annotations

import json
import time

import pytest

from tests.conftest import add_ai


@pytest.fixture
def cid(user, fake, pid):
    add_ai(user, fake)
    return user.post(f"/api/v1/projects/{pid}/conversations").json()["id"]


def send(user, cid, model, text="你好"):
    r = user.post(f"/api/v1/conversations/{cid}/messages", json={"text": text, "model": model})
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.split("\n") if line.startswith("data: ")]


def test_stream_and_history(user, cid, ref, pid):
    events = send(user, cid, "echo")
    assert "".join(e.get("text", "") for e in events) == "可用" and events[-1]["type"] == "done"
    send(user, cid, "echo", "第二句")
    c = user.get(f"/api/v1/conversations/{cid}").json()
    assert [m["role"] for m in c["messages"]] == ["user", "assistant"] * 2 and c["title"] == "你好"
    sent = ref["seen"][-1]["messages"]
    assert sent[0]["role"] == "system" and "讲清楚一件事" in sent[0]["content"]
    assert [m["content"] for m in sent[1:]] == ["你好", "可用", "第二句"]


def test_ai_writes_files_and_sees_them(user, cid, ref, pid):
    assert send(user, cid, "files")[-1] == {"type": "done", "error": None, "files": ["文字稿.md"]}
    assert user.get(f"/api/v1/files/{pid}/文字稿.md").json()["content"].startswith("# 测试稿")
    send(user, cid, "echo")
    assert "# 测试稿" in ref["seen"][-1]["messages"][0]["content"]


def test_series_context(user, cid, ref, pid):
    sid = user.post(f"/api/v1/projects/{pid}/to-series", json={"name": "系列甲"}).json()["id"]
    user.put(f"/api/v1/files/{sid}/设定.md", json={"content": "语气：轻松"})
    user.post("/api/v1/projects", json={"title": "第二集", "series_id": sid})
    send(user, cid, "echo")
    system = ref["seen"][-1]["messages"][0]["content"]
    assert "系列甲" in system and "语气：轻松" in system and "第二集" in system


def test_unsafe_or_truncated_files_are_not_written(user, cid, pid):
    end = send(user, cid, "evil")[-1]
    assert end["files"] == ["文字稿.md"] and "没有保存" in end["error"]
    end = send(user, cid, "cut")[-1]
    assert end["files"] == [] and "截断" in end["error"]
    assert [f["name"] for f in user.get(f"/api/v1/projects/{pid}").json()["files"]] == ["文字稿.md"]


def test_upstream_error_is_kept_in_history(user, cid):
    assert "no such model" in send(user, cid, "broken")[-1]["error"]
    assert "no such model" in user.get(f"/api/v1/conversations/{cid}").json()["messages"][-1]["error"]


def test_no_provider(user, pid):
    cid = user.post(f"/api/v1/projects/{pid}/conversations").json()["id"]
    r = user.post(f"/api/v1/conversations/{cid}/messages", json={"text": "x"})
    assert r.status_code == 502 and "设置" in r.json()["detail"]


def test_generation_survives_disconnect_and_can_be_stopped(user, cid):
    async def go():
        return user.app.state.chat.start(cid, "x", None, "slow")

    run = user.portal.call(go)  # 没有任何浏览器在听
    time.sleep(0.5)
    assert user.get(f"/api/v1/conversations/{cid}").json()["running"]
    body = {"text": "y", "model": "echo"}
    assert user.post(f"/api/v1/conversations/{cid}/messages", json=body).status_code == 422
    assert user.post(f"/api/v1/conversations/{cid}/stop").status_code == 204
    last = user.get(f"/api/v1/conversations/{cid}").json()
    assert not last["running"] and last["messages"][-1]["error"] == "已停止生成" and run.text


def test_attach_receives_full_reply(user, cid):
    async def go():
        user.app.state.chat.start(cid, "x", None, "slow")

    user.portal.call(go)
    r = user.get(f"/api/v1/conversations/{cid}/stream")
    text = "".join(json.loads(x[6:]).get("text", "") for x in r.text.split("\n") if x.startswith("data: "))
    assert text == "慢" * 40
    assert user.get(f"/api/v1/conversations/{cid}/stream").status_code == 404


def test_delete_conversation_keeps_files(user, cid, pid):
    send(user, cid, "files")
    assert user.delete(f"/api/v1/conversations/{cid}").status_code == 204
    assert user.get(f"/api/v1/projects/{pid}/conversations").json() == []
    assert user.get(f"/api/v1/files/{pid}/文字稿.md").status_code == 200
