# 用官方 MCP 客户端连真实服务，走完制作闭环
from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from app.main import create_app
from tests.conftest import MP4, login, make_cfg, make_key
from tests.fakes import free_port, serve


@pytest.fixture
def live(fake, tmp_path):
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    server = serve(create_app(make_cfg(fake, tmp_path / "data", url)), port)
    with httpx.Client(base_url=url) as c:
        login(c)
        yield c
    server.should_exit = True


def mcp(live, headers, fn):
    async def go():
        async with (
            create_mcp_http_client(headers=headers) as http,
            streamable_http_client(
                f"{live.base_url}/mcp".replace("//mcp", "/mcp"), http_client=http
            ) as streams,
            ClientSession(streams[0], streams[1]) as s,
        ):
            await s.initialize()

            async def call(tool, /, **args):
                r = await s.call_tool(tool, args)
                text = r.content[0].text
                return text if r.is_error else json.loads(text)

            return await fn(s, call)

    # Playwright 的同步模式会占用主线程的事件循环，所以在单独的线程里跑
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, go()).result()


def test_tools_have_no_self_approval(live):
    async def fn(s, call):
        return {t.name for t in (await s.list_tools()).tools}

    assert mcp(live, make_key(live), fn) == {
        "claim_task", "report_progress", "submit_video", "fail_task",
        "list_projects", "get_project", "create_project", "save_file",
    }  # fmt: skip


def test_produce_loop(live):
    h = make_key(live, "plan", "produce")

    async def plan(s, call):
        assert (await call("claim_task"))["task"] is None
        p = await call("create_project", title="MCP 片", brief="b")
        assert "文件名" in await call("save_file", project_id=p["id"], name="../x.md", content="x")
        await call("save_file", project_id=p["id"], name="文字稿.md", content="正文")
        return p["id"]

    pid = mcp(live, h, plan)
    assert live.post(f"/api/v1/projects/{pid}/confirm").status_code == 201

    async def make(s, call):
        got = await call("claim_task")
        t = got["task"]
        ids = {"task_id": t["task_id"], "claim": t["claim"]}
        assert t["files"] == {"文字稿.md": "正文"}
        assert (await call("report_progress", **ids, text="渲染 50%"))["lease_until"]
        assert "还没有上传" in await call("submit_video", **ids, note="n")
        r = await asyncio.to_thread(
            httpx.put, got["upload_url"], content=MP4, headers={**h, "X-Claim": t["claim"]}
        )
        assert r.status_code == 201
        assert (await call("submit_video", **ids, note="初版"))["status"] == "review"
        assert "失效" in await call("fail_task", **ids, error="晚了")

    mcp(live, h, make)
    assert live.get(f"/api/v1/projects/{pid}").json()["status"] == "review"


def test_scope_enforced(live):
    async def fn(s, call):
        return await call("claim_task"), await call("create_project", title="x", brief="")

    for msg in mcp(live, make_key(live), fn):
        assert "没有" in msg and "权限" in msg


def test_rejects_session_cookie_and_foreign_host(live):
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert live.post("/mcp", json=body).status_code == 401  # 有会话 cookie 也不行
    bad = {**make_key(live), "Host": "evil.test", "Accept": "application/json, text/event-stream"}
    assert live.post("/mcp", json=body, headers=bad).status_code >= 400
