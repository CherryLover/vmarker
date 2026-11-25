# ============================================================================
#  task_routes —— 制作任务与视频
#
#  确认 / 审片 / 取消 / 重试只认会话；上传只认 produce 权限 + 本次领取的 claim。
#  播放与下载走 FileResponse：自带 Range，浏览器原生 <video> 可拖动。
# ============================================================================
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.deps import allow, owner
from app.core.tasks import Tasks

router = APIRouter(prefix="/api/v1")
OWNER = Depends(owner)


class RejectIn(BaseModel):
    feedback: str


def _t(request: Request) -> Tasks:
    return request.app.state.tasks


# ---------------------------------------------------------------- 人
@router.post("/projects/{pid}/confirm", status_code=201, dependencies=[OWNER])
async def confirm(pid: str, request: Request):
    return {"task_id": _t(request).confirm(pid)}


@router.post("/tasks/{tid}/approve", status_code=204, dependencies=[OWNER])
async def approve(tid: int, request: Request):
    _t(request).approve(tid)


@router.post("/tasks/{tid}/reject", status_code=201, dependencies=[OWNER])
async def reject(tid: int, body: RejectIn, request: Request):
    return {"task_id": _t(request).reject(tid, body.feedback)}


@router.post("/tasks/{tid}/retry", status_code=201, dependencies=[OWNER])
async def retry(tid: int, request: Request):
    return {"task_id": _t(request).retry(tid)}


@router.post("/tasks/{tid}/cancel", status_code=204, dependencies=[OWNER])
async def cancel(tid: int, request: Request):
    _t(request).cancel(tid)


# ---------------------------------------------------------------- 上传（原始字节流：curl -T video.mp4）
async def _receive(request: Request, tmp, limit: int) -> None:
    size, head = 0, b""
    with tmp.open("wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"视频超过上限 {limit // 1048576} MB")
            head = head if len(head) >= 12 else (head + chunk)[:12]
            f.write(chunk)
    if head[4:8] != b"ftyp":
        raise HTTPException(422, "不是有效的 MP4 文件")


@router.put("/tasks/{tid}/video", status_code=201, dependencies=[Depends(allow("produce"))])
async def upload(tid: int, request: Request, x_claim: str = Header()):
    _t(request).check(tid, x_claim)
    state = request.app.state
    tmp = state.store.root / "tmp" / f"{secrets.token_hex(8)}.part"
    try:
        await _receive(request, tmp, state.cfg.max_video_mb * 1048576)
        return _t(request).add_video(tid, x_claim, tmp)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- 播放 / 下载 / 删除
@router.get("/videos/{vid}", dependencies=[Depends(allow())])
async def video(vid: int, request: Request, download: bool = False):
    row, path = _t(request).video_path(vid)
    title = request.app.state.store.get(row["project_id"])["title"].replace("/", "-")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{title}-v{row['version']}.mp4",
        content_disposition_type="attachment" if download else "inline",
        headers={"Cache-Control": "private, no-cache"},
    )


@router.delete("/videos/{vid}", status_code=204, dependencies=[OWNER])
async def delete_video(vid: int, request: Request):
    _t(request).delete_video(vid)
