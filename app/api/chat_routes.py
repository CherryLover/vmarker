# ============================================================================
#  chat_routes —— 项目对话（只认浏览器会话：会花 AI 供应商的钱）
# ============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.deps import owner
from app.core.chat import Chat
from app.core.store import Missing

router = APIRouter(prefix="/api/v1", dependencies=[Depends(owner)])


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    provider_id: int | None = None
    model: str = ""


def _c(request: Request) -> Chat:
    return request.app.state.chat


def _sse(request: Request, run) -> StreamingResponse:
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(_c(request).events(run), media_type="text/event-stream", headers=headers)


@router.get("/projects/{pid}/conversations")
async def list_conversations(pid: str, request: Request):
    return _c(request).conversations(pid)


@router.post("/projects/{pid}/conversations", status_code=201)
async def create_conversation(pid: str, request: Request):
    return _c(request).create(pid)


@router.get("/conversations/{cid}")
async def get_conversation(cid: int, request: Request):
    return {**_c(request).get(cid), "messages": _c(request).messages(cid), "running": cid in _c(request).runs}


@router.delete("/conversations/{cid}", status_code=204)
async def delete_conversation(cid: int, request: Request):
    _c(request).delete(cid)


@router.post("/conversations/{cid}/messages")
async def send(cid: int, body: SendIn, request: Request):
    return _sse(request, _c(request).start(cid, body.text, body.provider_id, body.model))


@router.get("/conversations/{cid}/stream")
async def attach(cid: int, request: Request):
    """刷新页面后接着看还在生成的回复。"""
    run = _c(request).runs.get(cid)
    if not run:
        raise Missing("没有正在生成的回复")
    return _sse(request, run)


@router.post("/conversations/{cid}/stop", status_code=204)
async def stop(cid: int, request: Request):
    await _c(request).stop(cid)
