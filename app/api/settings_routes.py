# ============================================================================
#  settings_routes —— 身份、AI 供应商、API Key（只认浏览器会话）
# ============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import keys
from app.auth.deps import owner
from app.core.providers import Providers

router = APIRouter(prefix="/api/v1", dependencies=[Depends(owner)])


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    base_url: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = ""


class ModelsIn(BaseModel):
    base_url: str
    api_key: str


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scopes: list[str] = []


class ScopesIn(BaseModel):
    scopes: list[str] = []


def _p(request: Request) -> Providers:
    return request.app.state.providers


@router.get("/me")
async def me(request: Request, user: dict = Depends(owner)):
    return {"name": user["name"], "email": user["email"], "base_url": request.app.state.cfg.base_url}


# ---------------------------------------------------------------- AI 供应商
@router.get("/providers")
async def list_providers(request: Request):
    return _p(request).list()


@router.post("/providers", status_code=201)
async def add_provider(body: ProviderIn, request: Request):
    pid = _p(request).save(None, body.name, body.base_url, body.model, body.api_key)
    return {"id": pid, "test": await _p(request).test(pid)}


@router.put("/providers/{pid}")
async def edit_provider(pid: int, body: ProviderIn, request: Request):
    _p(request).save(pid, body.name, body.base_url, body.model, body.api_key)
    return {"id": pid, "test": await _p(request).test(pid)}


@router.delete("/providers/{pid}", status_code=204)
async def delete_provider(pid: int, request: Request):
    _p(request).delete(pid)


@router.post("/providers/{pid}/default", status_code=204)
async def default_provider(pid: int, request: Request):
    _p(request).set_default(pid)


@router.post("/providers/{pid}/test")
async def test_provider(pid: int, request: Request):
    return await _p(request).test(pid)


@router.get("/providers/{pid}/models")
async def provider_models(pid: int, request: Request):
    p = _p(request).get(pid)
    return await _p(request).models(p["base_url"], p["api_key"])


@router.post("/providers/models")
async def probe_models(body: ModelsIn, request: Request):
    """还没保存时，用表单里的地址和 Key 拉模型列表。"""
    return await _p(request).models(body.base_url, body.api_key.strip())


# ---------------------------------------------------------------- API Key
@router.get("/keys")
async def list_keys(request: Request):
    return keys.list_all(request.app.state.db)


@router.post("/keys", status_code=201)
async def create_key(body: KeyIn, request: Request):
    return keys.create(request.app.state.db, body.name.strip() or "未命名", body.scopes)


@router.put("/keys/{kid}")
async def edit_key(kid: int, body: ScopesIn, request: Request):
    if not keys.set_scopes(request.app.state.db, kid, body.scopes):
        raise HTTPException(404, "Key 不存在或已吊销")
    return {"id": kid}


@router.delete("/keys/{kid}", status_code=204)
async def revoke_key(kid: int, request: Request):
    if not keys.revoke(request.app.state.db, kid):
        raise HTTPException(404, "Key 不存在或已吊销")
