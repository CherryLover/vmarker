# ============================================================================
#  providers —— OpenAI 格式的 AI 供应商：加密存储、模型列表、测试、流式对话
#
#  Claude / Gemini / DeepSeek / OpenAI 都走各自的 OpenAI 兼容地址。
#  Key 用 Fernet 加密落库，从不返回给前端，也不出现在错误信息里。
# ============================================================================
from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.db import DB, now_iso

TIMEOUT = httpx.Timeout(30, read=300)
PUBLIC = "id, name, base_url, model, is_default, test_ok, test_detail, tested_at"


class LLMError(Exception):
    pass


class Providers:
    def __init__(self, db: DB, secret_key: str, http: httpx.AsyncClient):
        self.db, self.http = db, http
        digest = hashlib.sha256(("vmarker/providers/" + secret_key).encode()).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(digest))

    # ---------------------------------------------------------------- 存取
    def list(self) -> list[dict]:
        return self.db.all(f"SELECT {PUBLIC} FROM providers ORDER BY is_default DESC, id")

    def get(self, pid: int | None) -> dict:
        row = (
            self.db.one("SELECT * FROM providers WHERE id = ?", pid)
            if pid
            else self.db.one("SELECT * FROM providers ORDER BY is_default DESC, id LIMIT 1")
        )
        if not row:
            raise LLMError("还没有配置 AI，请先到「设置 → AI 模型」添加")
        try:
            row["api_key"] = self.fernet.decrypt(row["api_key"]).decode()
        except InvalidToken:
            raise LLMError("AI Key 无法解密（VM_SECRET_KEY 换过），请重新填写") from None
        return row

    def save(self, pid: int | None, name: str, base_url: str, model: str, api_key: str) -> int:
        url = base_url.strip().rstrip("/")
        if urlparse(url).scheme not in ("http", "https"):
            raise LLMError("Base URL 必须以 http:// 或 https:// 开头")
        old = self.get(pid) if pid else None
        # 换了地址必须重填 Key：不能把旧 Key 发给新主机
        if old and not api_key and old["base_url"] != url:
            raise LLMError("修改 Base URL 时需要重新填写 API Key")
        key = api_key.strip() or (old["api_key"] if old else "")
        if not key:
            raise LLMError("请填写 API Key")
        blob = self.fernet.encrypt(key.encode())
        if old:
            self.db.run(
                "UPDATE providers SET name = ?, base_url = ?, model = ?, api_key = ?, test_ok = NULL, "
                "test_detail = NULL, tested_at = NULL WHERE id = ?", name, url, model, blob, pid,
            )  # fmt: skip
            return pid
        first = not self.db.one("SELECT 1 AS x FROM providers")
        return self.db.run(
            "INSERT INTO providers (name, base_url, model, api_key, is_default, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            name, url, model, blob, int(first), now_iso(),
        )  # fmt: skip

    def set_default(self, pid: int) -> None:
        self.db.run("UPDATE providers SET is_default = (id = ?)", pid)

    def delete(self, pid: int) -> None:
        self.db.run("DELETE FROM providers WHERE id = ?", pid)

    # ---------------------------------------------------------------- 上游
    async def models(self, base_url: str, api_key: str) -> list[str]:
        """拉取最新模型列表。Anthropic 的 /models 只认 x-api-key，Bearer 被拒时换头再试。"""
        url = base_url.strip().rstrip("/") + "/models"
        headers = (
            {"Authorization": f"Bearer {api_key}"},
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
        for h in headers:
            r = await self._send("GET", url, h, params={})
            if r.status_code == 200:
                return _model_ids(r)
        raise LLMError(_explain(r))

    async def _send(self, method: str, url: str, headers: dict, **kw) -> httpx.Response:
        try:
            return await self.http.request(method, url, headers=headers, timeout=30, **kw)
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise LLMError(f"连不上上游：{type(e).__name__}") from None

    async def test(self, pid: int) -> dict:
        """真实对话一次：验证地址、Key、模型三者都可用。"""
        p, start, text = self.get(pid), time.monotonic(), ""
        try:
            async for piece in self.stream(
                p, p["model"], [{"role": "user", "content": "只回复两个字：可用"}]
            ):
                text += piece
            ok, detail = bool(text.strip()), text.strip()[:200] or "上游返回了空内容"
        except LLMError as e:
            ok, detail = False, str(e)
        ms = int((time.monotonic() - start) * 1000)
        self.db.run(
            "UPDATE providers SET test_ok = ?, test_detail = ?, tested_at = ? WHERE id = ?",
            int(ok), detail, now_iso(), pid,
        )  # fmt: skip
        return {"ok": ok, "detail": detail, "model": p["model"], "ms": ms}

    async def stream(self, p: dict, model: str, messages: list[dict]) -> AsyncIterator[str]:
        body = {"model": model, "messages": messages, "stream": True}
        headers = {"Authorization": f"Bearer {p['api_key']}"}
        try:
            async with self.http.stream(
                "POST", p["base_url"] + "/chat/completions", json=body, headers=headers, timeout=TIMEOUT
            ) as r:
                if r.status_code != 200:
                    await r.aread()
                    raise LLMError(_explain(r))
                async for piece in _pieces(r):
                    yield piece
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise LLMError(f"和上游的连接中断：{type(e).__name__}") from None


# -------------------------------------------------------------------- 解析
async def _pieces(r: httpx.Response) -> AsyncIterator[str]:
    """SSE → 文本片段。没有收到 finish_reason / [DONE] 就断开，视为不完整。"""
    done = False
    async for line in r.aiter_lines():
        data = line[5:].strip() if line.startswith("data:") else ""
        if data == "[DONE]":
            done = True
            break
        chunk = _json(data)
        if chunk.get("error"):
            raise LLMError(f"上游报错：{str(chunk['error'])[:300]}")
        for choice in (chunk.get("choices") or [])[:1]:
            if text := (choice.get("delta") or {}).get("content"):
                yield text
            reason = choice.get("finish_reason")
            done = done or bool(reason)
            if reason == "length":
                raise LLMError("回复达到模型的长度上限，被截断了")
    if not done:
        raise LLMError("上游提前断开，回复不完整")


def _json(data: str) -> dict:
    try:
        obj = json.loads(data)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _model_ids(r: httpx.Response) -> list[str]:
    try:
        rows = r.json()["data"]
        # 有发布时间的按最新在前；没有的按名字倒序，版本号大的靠前
        rows.sort(key=lambda m: (str(m.get("created") or m.get("created_at") or ""), m["id"]), reverse=True)
        return [m["id"].removeprefix("models/") for m in rows]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise LLMError("上游没有返回 OpenAI 格式的模型列表，请手动填写模型名") from None


def _explain(r: httpx.Response) -> str:
    body = _json(r.text)
    err = body.get("error", body)
    msg = err.get("message") if isinstance(err, dict) else str(err)
    return f"上游返回 HTTP {r.status_code}：{(msg or r.text or '无内容')[:300]}"
