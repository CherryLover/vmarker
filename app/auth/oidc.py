# ============================================================================
#  oidc —— Pocket ID 单点登录（授权码 + PKCE），唯一的登录方式
#
#  这是单人平台：第一个登录的账号成为所有者，之后其他账号一律拒绝。
# ============================================================================
from __future__ import annotations

from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Config
from app.db import now_iso

router = APIRouter(include_in_schema=False)


def make_oauth(cfg: Config) -> OAuth:
    oauth = OAuth()
    oauth.register(
        "pocketid",
        client_id=cfg.oidc_client_id,
        client_secret=cfg.oidc_client_secret,
        server_metadata_url=f"{cfg.oidc_issuer}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )
    return oauth


def _refuse(msg: str, code: int) -> HTMLResponse:
    return HTMLResponse(
        f"<meta charset='utf-8'><p>{msg}<a href='/login'>返回登录页</a></p>", status_code=code
    )


@router.get("/auth/login")
async def login(request: Request):
    cfg: Config = request.app.state.cfg
    # 会话 cookie 绑定主机名：从别的地址进来先跳到 VM_BASE_URL，否则回调时 state 对不上
    if request.url.netloc != urlparse(cfg.base_url).netloc:
        return RedirectResponse(f"{cfg.base_url}/auth/login")
    return await request.app.state.oauth.pocketid.authorize_redirect(request, f"{cfg.base_url}/auth/callback")


@router.get("/auth/callback")
async def callback(request: Request):
    try:
        token = await request.app.state.oauth.pocketid.authorize_access_token(request)
    except OAuthError:
        return _refuse("登录失败，请重试。", 400)
    info = token.get("userinfo") or {}
    name = info.get("name") or info.get("preferred_username") or info.get("email")
    user = {"sub": info["sub"], "email": info.get("email"), "name": name}
    db = request.app.state.db
    db.run(
        "INSERT OR IGNORE INTO owner VALUES (1, ?, ?, ?, ?)", user["sub"], user["email"], name, now_iso()
    )  # 抢先登录者为所有者
    if db.one("SELECT sub FROM owner")["sub"] != user["sub"]:
        return _refuse("这个平台只允许所有者登录。", 403)
    request.session.clear()
    request.session["user"] = user
    return RedirectResponse("/")


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login?out=1", status_code=303)
