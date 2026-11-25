# ============================================================================
#  chat —— 项目对话：拼上下文 → 流式生成 → 落库 → 把回复里的文件写盘
#
#  AI 用 <file name="文字稿.md">…</file> 交付文件，不依赖各家实现不一的函数调用。
#  生成在后台任务里跑：浏览器断线不影响保存，回来能看到完整回复。
# ============================================================================
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

from app.core.providers import LLMError, Providers
from app.core.store import SERIES_DOC, Missing, Store, StoreError
from app.db import DB, now_iso

FILE_TAG = re.compile(r'^<file name="([^"\n]+)">[ \t]*\n(.*?)\n?^</file>[ \t]*$', re.S | re.M)
CONTEXT_FILE_LIMIT = 60_000

RULES = """你是视频策划搭档，帮用户把一支视频从想法梳理到可以直接开工。用中文，直接、具体。
职责：明确受众和一句话目标、收窄范围、写旁白文案、描述每句对应的画面、列出要核实的事实和要准备的素材。
信息不够时先问最关键的一两个问题，不要编造事实。

【写文件】用户要求整理、保存、修改文件时，用下面的格式输出完整文件内容，平台会自动保存并覆盖同名文件：
<file name="文字稿.md">
# 标题
完整内容
</file>
规则：<file> 和 </file> 必须各自独占一行；文件名以 .md 结尾；每次都输出完整内容，不能省略或写「其余不变」；没有要求时不要输出文件。
建议的文件：规划.md（受众、目标、章节、时长）、文字稿.md（按章节，用「旁白 | 画面」两列表格）、准备清单.md（待核实事实、素材）。
制作端只会拿到文件，看不到对话，所以需要的信息都要写进文件。"""


def extract_files(text: str) -> list[tuple[str, str]]:
    return [(m[1].strip(), m[2].rstrip() + "\n") for m in FILE_TAG.finditer(text)]


def build_system(store: Store, pid: str) -> str:
    p = store.get(pid)
    parts = [RULES, f"【当前视频】标题：{p['title']}\n需求：{p['brief'] or '（未填写）'}"]
    if p["series_id"]:
        parts.append(_series_context(store, p))
    budget = CONTEXT_FILE_LIMIT
    for f in store.files(pid):
        text = store.read_file(pid, f["name"])
        shown = text[:budget]
        budget -= len(shown)
        cut = "\n（过长，后面省略；不要覆盖这个文件）" if len(shown) < len(text) else ""
        parts.append(f"【已有文件 {f['name']}】\n{shown}{cut}")
    return "\n\n".join(parts)


def _series_context(store: Store, p: dict) -> str:
    s = store.get(p["series_id"])
    eps = [
        f"{e['position']}. {e['title']}：{e['brief'][:200]}"
        for e in store.episodes(s["id"])
        if e["id"] != p["id"]
    ]
    try:
        doc = store.read_file(s["id"], SERIES_DOC)
    except Missing:
        doc = "（还没有设定）"
    return f"【所属系列】{s['name']}，本集是第 {p['position']} 集\n{doc}\n【系列其他集】\n" + (
        "\n".join(eps) or "无"
    )


@dataclass
class Run:
    """一次生成。listeners 里的每个队列对应一个正在看的浏览器。"""

    text: str = ""
    end: dict | None = None
    listeners: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None

    def emit(self, event: dict) -> None:
        for q in self.listeners:
            q.put_nowait(event)


class Chat:
    def __init__(self, db: DB, store: Store, providers: Providers):
        self.db, self.store, self.providers = db, store, providers
        self.runs: dict[int, Run] = {}

    # ---------------------------------------------------------------- 历史
    def conversations(self, pid: str) -> list[dict]:
        self.store.get(pid)
        return self.db.all(
            "SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC, id DESC", pid
        )

    def create(self, pid: str) -> dict:
        self.store.get(pid)
        cid = self.db.run(
            "INSERT INTO conversations (project_id, title, created_at, updated_at) VALUES (?, '新对话', ?, ?)",
            pid, now_iso(), now_iso(),
        )  # fmt: skip
        return self.get(cid)

    def get(self, cid: int) -> dict:
        row = self.db.one("SELECT * FROM conversations WHERE id = ?", cid)
        if not row:
            raise Missing("对话不存在")
        return row

    def messages(self, cid: int) -> list[dict]:
        self.get(cid)
        rows = self.db.all("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", cid)
        return [{**r, "files": json.loads(r["files"])} for r in rows]

    def delete(self, cid: int) -> None:
        if cid in self.runs:
            raise StoreError("正在生成，先停止再删除")
        self.db.run("DELETE FROM conversations WHERE id = ?", cid)

    # ---------------------------------------------------------------- 生成
    def start(self, cid: int, text: str, provider_id: int | None, model: str) -> Run:
        conv = self.get(cid)
        if cid in self.runs:
            raise StoreError("上一条还在生成")
        provider = self.providers.get(provider_id)
        self._add(cid, "user", text)
        if conv["title"] == "新对话":
            self.db.run("UPDATE conversations SET title = ? WHERE id = ?", text[:30], cid)
        run = self.runs[cid] = Run()
        run.task = asyncio.create_task(self._generate(run, conv, provider, model or provider["model"]))
        return run

    def _add(self, cid: int, role: str, content: str, model=None, error=None, files=()) -> None:
        self.db.run(
            "INSERT INTO messages (conversation_id, role, content, model, error, files, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            cid, role, content, model, error, json.dumps(list(files), ensure_ascii=False), now_iso(),
        )  # fmt: skip
        self.db.run("UPDATE conversations SET updated_at = ? WHERE id = ?", now_iso(), cid)

    async def _generate(self, run: Run, conv: dict, provider: dict, model: str) -> None:
        cid, error, files = conv["id"], None, []
        try:
            async for piece in self.providers.stream(provider, model, self._context(conv)):
                run.text += piece
                run.emit({"type": "delta", "text": piece})
            files, error = self._save_files(conv["project_id"], run.text)
        except LLMError as e:
            error = str(e)
        except asyncio.CancelledError:
            error = "已停止生成"
        except Exception as e:  # 后台任务没人 await：任何意外都要落到对话里，不能静默
            error = f"内部错误：{type(e).__name__}"
        finally:
            self._add(cid, "assistant", run.text, model, error, files)
            self.runs.pop(cid, None)
            run.end = {"type": "done", "error": error, "files": files}
            run.emit(run.end)

    def _context(self, conv: dict) -> list[dict]:
        rows = [m for m in self.messages(conv["id"]) if m["content"].strip()]
        system = {"role": "system", "content": build_system(self.store, conv["project_id"])}
        return [system, *({"role": m["role"], "content": m["content"]} for m in rows)]

    def _save_files(self, pid: str, text: str) -> tuple[list[str], str | None]:
        saved = []
        for name, content in extract_files(text):
            try:
                self.store.write_file(pid, name, content)
                saved.append(name)
            except StoreError as e:
                return saved, f"文件 {name} 没有保存：{e}"
        if text.count("<file name=") > len(saved):
            return saved, "有文件没写完整，没有保存；可以让 AI 重新输出"
        return saved, None

    async def stop(self, cid: int) -> None:
        run = self.runs.get(cid)
        if run and run.task:
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
            self.runs.pop(cid, None)  # 还没开始就被取消时，协程体不会执行到清理

    async def close(self) -> None:
        for cid in list(self.runs):
            await self.stop(cid)

    async def events(self, run: Run):
        """给浏览器的 SSE。每 15 秒心跳，避免推理模型首字太慢被 CDN 断开。"""
        q: asyncio.Queue = asyncio.Queue()
        run.listeners.add(q)
        if run.text:
            q.put_nowait({"type": "delta", "text": run.text})
        if run.end:  # 订阅之前就已经结束
            q.put_nowait(run.end)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), 15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "done":
                    return
        finally:
            run.listeners.discard(q)

    # ---------------------------------------------------------------- 系列设定提炼
    async def distill(self, sid: str, provider_id: int | None, model: str) -> str:
        eps = self.store.episodes(sid)
        docs = [
            f"【{e['title']} / {f['name']}】\n{self.store.read_file(e['id'], f['name'])}"
            for e in eps[:3]
            for f in self.store.files(e["id"])
        ]
        if not docs:
            raise StoreError("系列里的视频还没有文件，没有内容可提炼")
        ask = (
            f"从下面的视频文件提炼系列「{self.store.get(sid)['name']}」的设定，供后续每集沿用。"
            "只输出 Markdown，包含：受众、语气、声音与语速、每集骨架、画面风格、不讲什么、片头片尾约定。"
            "材料里没有的写「待定」，不要编造。\n\n"
        )
        content = ask + "\n\n".join(docs)[:CONTEXT_FILE_LIMIT]
        p = self.providers.get(provider_id)
        stream = self.providers.stream(p, model or p["model"], [{"role": "user", "content": content}])
        return "".join([piece async for piece in stream])
