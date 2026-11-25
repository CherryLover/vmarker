# ============================================================================
#  project_routes —— 项目、系列、Markdown 文件
#
#  读：会话或任意 API Key；写：会话或带 plan 权限的 Key；删除：只认会话。
# ============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth.deps import allow, owner
from app.core.store import Store

router = APIRouter(prefix="/api/v1")
READ, PLAN, OWNER = Depends(allow()), Depends(allow("plan")), Depends(owner)


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    brief: str = Field("", max_length=5000)
    series_id: str | None = None


class SeriesIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=5000)


class FileIn(BaseModel):
    content: str


class OrderIn(BaseModel):
    ids: list[str]


class ModelIn(BaseModel):
    provider_id: int | None = None
    model: str = ""


def _s(request: Request) -> Store:
    return request.app.state.store


def _row(request: Request, p: dict) -> dict:
    return {**p, "status": request.app.state.tasks.status(p["id"])}


# ---------------------------------------------------------------- 项目
@router.get("/projects", dependencies=[READ])
async def list_projects(request: Request):
    return [_row(request, p) for p in _s(request).projects()]


@router.post("/projects", status_code=201, dependencies=[PLAN])
async def create_project(body: ProjectIn, request: Request):
    return _row(request, _s(request).create_project(body.title, body.brief, body.series_id))


@router.get("/projects/{pid}", dependencies=[READ])
async def get_project(pid: str, request: Request):
    store, tasks = _s(request), request.app.state.tasks
    p = store.get(pid)
    series = store.get(p["series_id"]) if p["series_id"] else None
    return {
        **_row(request, p),
        "series": series,
        "files": store.files(pid),
        "tasks": tasks.of_project(pid),
        "videos": tasks.videos(pid),
    }


@router.put("/projects/{pid}", dependencies=[PLAN])
async def edit_project(pid: str, body: ProjectIn, request: Request):
    _s(request).set_series(pid, body.series_id)
    return _row(request, _s(request).update(pid, title=body.title, brief=body.brief))


@router.delete("/projects/{pid}", status_code=204, dependencies=[OWNER])
async def delete_project(pid: str, request: Request):
    _s(request).get(pid)
    for t in request.app.state.tasks.of_project(pid):
        if t["status"] in ("queued", "working"):
            request.app.state.tasks.cancel(t["id"])
    _s(request).trash(pid)


@router.post("/projects/{pid}/to-series", status_code=201, dependencies=[PLAN])
async def to_series(pid: str, body: SeriesIn, request: Request):
    return _s(request).to_series(pid, body.name)


# ---------------------------------------------------------------- 系列
@router.get("/series", dependencies=[READ])
async def list_series(request: Request):
    return [{**s, "count": len(_s(request).episodes(s["id"]))} for s in _s(request).series()]


@router.post("/series", status_code=201, dependencies=[PLAN])
async def create_series(body: SeriesIn, request: Request):
    return _s(request).create_series(body.name, body.description)


@router.get("/series/{sid}", dependencies=[READ])
async def get_series(sid: str, request: Request):
    s = _s(request)
    return {**s.get(sid), "files": s.files(sid), "episodes": [_row(request, p) for p in s.episodes(sid)]}


@router.put("/series/{sid}", dependencies=[PLAN])
async def edit_series(sid: str, body: SeriesIn, request: Request):
    return _s(request).update(sid, name=body.name, description=body.description)


@router.put("/series/{sid}/order", status_code=204, dependencies=[PLAN])
async def order_series(sid: str, body: OrderIn, request: Request):
    _s(request).reorder(sid, body.ids)


@router.delete("/series/{sid}", status_code=204, dependencies=[OWNER])
async def delete_series(sid: str, request: Request):
    _s(request).trash(sid)


@router.post("/series/{sid}/distill", dependencies=[OWNER])
async def distill(sid: str, body: ModelIn, request: Request):
    return {"content": await request.app.state.chat.distill(sid, body.provider_id, body.model)}


# ---------------------------------------------------------------- 文件（项目和系列通用）
@router.get("/files/{oid}/{name}", dependencies=[READ])
async def read_file(oid: str, name: str, request: Request):
    return {"name": name, "content": _s(request).read_file(oid, name)}


@router.put("/files/{oid}/{name}", dependencies=[PLAN])
async def write_file(oid: str, name: str, body: FileIn, request: Request):
    _s(request).write_file(oid, name, body.content)
    return {"name": name}


@router.delete("/files/{oid}/{name}", status_code=204, dependencies=[OWNER])
async def delete_file(oid: str, name: str, request: Request):
    _s(request).delete_file(oid, name)


@router.get("/files/{oid}/{name}/history", dependencies=[READ])
async def file_history(oid: str, name: str, request: Request):
    return _s(request).history(oid, name)


@router.get("/files/{oid}/{name}/history/{version}", dependencies=[READ])
async def file_version(oid: str, name: str, version: str, request: Request):
    return {"name": name, "content": _s(request).read_history(oid, name, version)}
