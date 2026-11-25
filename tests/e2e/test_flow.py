# 真浏览器走完整条链路：登录 → 配 AI 并测试 → 建片 → 对话写文件 → 转系列 → 确认 → 制作 → 审片 → 播放下载
from __future__ import annotations

import shutil
import subprocess

import httpx
import pytest
from playwright.sync_api import Page, expect

from app.main import create_app
from tests.conftest import MP4, make_cfg
from tests.fakes import free_port, serve
from tests.fakes import upstream as F


@pytest.fixture
def app(fake, tmp_path):
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    application = create_app(make_cfg(fake, tmp_path / "data", url))
    server = serve(application, port)
    application.state.test_url = url
    yield application
    server.should_exit = True


@pytest.fixture
def mp4(tmp_path) -> bytes:
    """有 ffmpeg 就用能播放的真视频（VP9 in MP4：无头 Chromium 不带 H.264 解码器）。"""
    if not shutil.which("ffmpeg"):
        return MP4
    out = tmp_path / "x.mp4"
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=d=2:s=320x180",
        "-c:v",
        "libvpx-vp9",
        "-movflags",
        "+faststart",
    ]
    subprocess.run([*cmd, str(out)], check=True)
    return out.read_bytes()


def send(page: Page, text: str, model: str, reply: str):
    page.get_by_label("模型").select_option(model)
    page.get_by_label("消息").fill(text)
    page.get_by_role("button", name="发送").click()
    expect(page.locator(".msg.assistant").last).to_contain_text(reply)


def test_whole_loop(page: Page, app, fake, mp4):
    url, errors = app.state.test_url, []
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    page.goto(url)
    page.get_by_role("link", name="用 Pocket ID 登录").click()
    expect(page.get_by_role("heading", name="视频")).to_be_visible()

    # ---- 配 AI：拉模型列表、选最新、真实测试
    page.get_by_role("link", name="设置").click()
    page.get_by_role("button", name="添加 AI").click()
    page.get_by_label("名称").fill("假上游")
    page.get_by_label("Base URL").fill(f"{fake}/v1")
    page.get_by_label("API Key").fill(F.GOOD_KEY)
    page.get_by_role("button", name="获取最新模型").click()
    page.get_by_label("从列表选择模型").select_option("echo")
    page.get_by_role("button", name="保存并测试").click()
    expect(page.locator(".chip.ok", has_text="可用")).to_be_visible()
    page.get_by_role("button", name="测试", exact=True).click()
    expect(page.get_by_role("status").last).to_contain_text("可用")

    # ---- 建片、对话、写文件、历史保留
    page.get_by_role("link", name="视频", exact=True).click()
    page.get_by_role("button", name="新建视频").click()
    page.get_by_label("标题").fill("第一支片")
    page.get_by_label("想做什么").fill("讲清楚 Matter")
    page.get_by_role("button", name="创建").click()
    expect(page.get_by_role("heading", name="第一支片")).to_be_visible()
    send(page, "你好", "echo", "可用")
    send(page, "整理成文件", "files", "已写入：文字稿.md")
    page.get_by_role("button", name="📄 文字稿.md").click()
    expect(page.locator(".side table")).to_contain_text("片头")
    page.get_by_role("button", name="编辑", exact=True).last.click()
    page.get_by_label("文件内容").fill("# 我改过\n")
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.locator(".side h1")).to_have_text("我改过")
    send(page, "试试注入", "xss", "<img src=x")
    assert page.evaluate("window.pwned") is None and page.locator(".msg a").count() == 0
    page.reload()
    expect(page.locator(".msg.user").first).to_have_text("你好")
    expect(page.locator(".msg")).to_have_count(6)

    # ---- 转系列、加一集
    page.get_by_role("button", name="转成系列").click()
    page.get_by_role("button", name="创建系列").click()
    expect(page.get_by_text("第 1 集")).to_be_visible()
    page.get_by_role("button", name="新增一集").click()
    page.get_by_label("标题").fill("第二支片")
    page.get_by_role("button", name="创建").click()
    expect(page.get_by_text("第 2 集")).to_be_visible()
    page.go_back()
    page.get_by_role("button", name="下移").first.click()
    expect(page.locator("a.card h2").first).to_have_text("第二支片")
    page.get_by_role("link", name="第一支片").click()

    # ---- 确认 → 制作端领取、上传、交付
    page.get_by_role("tab", name="制作").click()
    page.get_by_role("button", name="确认文案，提交制作").click()
    expect(page.locator("[data-status]")).to_have_text("等待制作")
    key = httpx_key(page, url)
    for note in ("初版", "改了片头"):
        produce(app, url, key, mp4, note)
        expect(page.locator("[data-status]")).to_have_text("待审片", timeout=20000)
        if note == "初版":
            page.get_by_role("button", name="打回").click()
            page.get_by_label("要改什么").fill("片头太长")
            page.get_by_role("button", name="打回").last.click()
            expect(page.locator("[data-status]")).to_have_text("等待制作")

    # ---- 播放、下载、通过
    if mp4 is not MP4:
        page.wait_for_function("document.querySelector('video').duration > 1")
    with page.expect_download() as d:
        page.get_by_role("link", name="下载").first.click()
    assert d.value.suggested_filename == "第一支片-v2.mp4"
    page.get_by_role("button", name="通过").click()
    expect(page.locator("[data-status]")).to_have_text("已完成")
    assert errors == []


def httpx_key(page: Page, url: str) -> str:
    body = {"name": "端到端", "scopes": ["produce"]}
    return page.request.post(f"{url}/api/v1/keys", data=body).json()["key"]


def produce(app, url: str, key: str, mp4: bytes, note: str):
    t = app.state.tasks.claim("e2e")
    headers = {"Authorization": f"Bearer {key}", "X-Claim": t["claim"]}
    r = httpx.put(f"{url}/api/v1/tasks/{t['task_id']}/video", content=mp4, headers=headers)
    assert r.status_code == 201
    app.state.tasks.submit(t["task_id"], t["claim"], note)
