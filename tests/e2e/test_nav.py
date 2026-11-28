# 导航：URL 即状态（标签、打开的文件）、后退语义、原地刷新不留历史、手机底部导航
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.test_flow import app  # noqa: F401  复用同一个起服务的 fixture

FILE = "文字稿.md"


@pytest.fixture
def seeded(page: Page, app):  # noqa: F811
    url = app.state.test_url
    page.set_default_timeout(10000)
    page.goto(url)
    page.get_by_role("link", name="用 Pocket ID 登录").click()
    expect(page.get_by_role("heading", name="视频")).to_be_visible()
    rq = page.request
    sid = rq.post(f"{url}/api/v1/series", data={"name": "入门系列", "description": ""}).json()["id"]
    pid = rq.post(f"{url}/api/v1/projects", data={"title": "第一集", "brief": "", "series_id": sid}).json()[
        "id"
    ]
    rq.put(f"{url}/api/v1/files/{pid}/{FILE}", data={"content": "# 稿子\n"})
    return url, sid, pid


def path(page: Page) -> str:
    return re.sub(r"^https?://[^/]+", "", page.url)


def test_url_is_state(page: Page, seeded):
    url, sid, pid = seeded
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # 系列 → 集：主导航归到「系列」，面包屑能回到系列
    page.goto(f"{url}/s/{sid}")
    page.get_by_role("link", name="第一集").click()
    expect(page.get_by_role("heading", name="第一集")).to_be_visible()
    expect(page.locator('[data-nav="/series"]')).to_have_attribute("aria-current", "page")
    expect(page.locator("#crumbs")).to_contain_text("入门系列")
    assert page.title() == "第一集 · vmarker"

    # 开文件进 URL；后退回到列表而不是离开项目；刷新停在原处
    page.get_by_role("link", name=f"📄 {FILE}").click()
    expect(page.locator(".side h1")).to_have_text("稿子")
    assert path(page) == f"/p/{pid}/files/%E6%96%87%E5%AD%97%E7%A8%BF.md"
    page.reload()
    expect(page.locator(".side h1")).to_have_text("稿子")
    page.get_by_role("button", name="返回").click()
    expect(page.get_by_role("link", name=f"📄 {FILE}")).to_be_visible()
    assert path(page) == f"/p/{pid}"  # 真后退：回到打开文件之前的地址

    # 换标签原地替换：后退直接回系列页
    page.get_by_role("tab", name="制作").click()
    assert path(page) == f"/p/{pid}/make"
    expect(page.get_by_role("button", name="确认文案，提交制作")).to_be_visible()
    page.go_back()
    expect(page.get_by_role("heading", name="入门系列")).to_be_visible()

    # 原地刷新（编辑保存）不新增历史：后退一步就离开系列页
    page.get_by_role("link", name="系列", exact=True).first.click()
    page.get_by_role("link", name="入门系列").click()
    page.get_by_role("button", name="编辑").click()
    page.get_by_label("名称").fill("入门系列改")
    page.get_by_role("button", name="保存").click()
    expect(page.get_by_role("heading", name="入门系列改")).to_be_visible()
    page.go_back()
    expect(page).to_have_url(f"{url}/series")
    assert errors == []


def test_phone_layout(browser: Browser, page: Page, seeded):
    url, _, pid = seeded
    phone = browser.new_context(
        storage_state=page.context.storage_state(), viewport={"width": 390, "height": 844}, is_mobile=True
    )
    m = phone.new_page()
    m.goto(f"{url}/p/{pid}")

    # 底部导航固定在屏幕底；没任务时先看对话，文件 / 制作藏起来
    nav = m.get_by_role("navigation", name="主导航")
    expect(nav).to_be_visible()
    box = nav.bounding_box()
    assert box and box["y"] + box["height"] >= 844 - 1
    expect(m.locator('[data-pane="chat"]')).to_be_visible()
    expect(m.locator(".side")).to_be_hidden()
    expect(m.locator("#crumbs a:visible")).to_have_text("入门系列")  # 窄屏只留上一级当返回

    m.get_by_role("tab", name="文件").click()
    expect(m.locator('[data-pane="chat"]')).to_be_hidden()
    expect(m.get_by_role("link", name=f"📄 {FILE}")).to_be_visible()
    assert m.evaluate("document.documentElement.scrollWidth") <= 390  # 不出现横向滚动
    phone.close()
