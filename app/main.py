# ============================================================================
#  main —— 装配：配置 → 存储 → AI / 任务 → 路由 → MCP → 页面
# ============================================================================
from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route

from app.api import chat_routes, mcp_server, project_routes, settings_routes, task_routes
from app.auth import oidc
from app.auth.deps import owner
from app.config import Config
from app.core.chat import Chat
from app.core.providers import LLMError, Providers
from app.core.store import Missing, Store, StoreError
from app.core.tasks import Conflict, Tasks
from app.db import DB

WEB = Path(__file__).parent / "web"
PAGES = ("/", "/series", "/settings", "/p/{oid}", "/s/{oid}", "/settings/{section}")
ERRORS = {StoreError: 422, Missing: 404, Conflict: 409, LLMError: 502}
CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https:"
)


# ---------------------------------------------------------------- 静态资源版本化
#  HTML 不缓存，静态资源带内容哈希永久缓存：避开 CDN 给 JS/CSS 补的浏览器缓存。
def asset_version() -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in WEB.rglob("*") if p.is_file()):
        h.update(f.relative_to(WEB).as_posix().encode() + f.read_bytes())
    return h.hexdigest()[:12]


class CachedStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


def html_page(name: str, ver: str) -> HTMLResponse:
    text = (WEB / name).read_text(encoding="utf-8").replace('="/static/', f'="/static/{ver}/')
    imports = f'<script type="importmap">{{"imports": {{"/static/": "/static/{ver}/"}}}}</script>'
    text = text.replace("</head>", f"{imports}\n</head>", 1)
    return HTMLResponse(text, headers={"Cache-Control": "no-store", "Content-Security-Policy": CSP})


# ---------------------------------------------------------------- 装配
def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp_inner.router.lifespan_context(mcp_inner):
            yield
        await app.state.chat.close()
        await app.state.http.aclose()

    app = FastAPI(
        title="vmarker",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    s = app.state
    s.cfg = cfg
    s.db = DB(cfg.data_dir / "vmarker.db")
    s.store = Store(cfg.data_dir)
    s.http = httpx.AsyncClient(headers={"User-Agent": "vmarker/1.0"})
    s.providers = Providers(s.db, cfg.secret_key, s.http)
    s.chat = Chat(s.db, s.store, s.providers)
    s.tasks = Tasks(s.db, s.store, cfg.lease_minutes)
    s.oauth = oidc.make_oauth(cfg)
    s.asset_version = ver = asset_version()

    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.secret_key,
        session_cookie="vm_session",
        max_age=14 * 86400,
        same_site="lax",
        https_only=cfg.secure_cookies,
    )
    for m in (oidc, settings_routes, project_routes, chat_routes, task_routes):
        app.include_router(m.router)
    s.app = app  # MCP 的 call_api 在进程内转发到 REST
    mcp_app, mcp_inner = mcp_server.asgi(mcp_server.build(s), s)
    app.router.routes.append(Route("/mcp", endpoint=_Asgi(mcp_app)))
    app.mount(f"/static/{ver}", CachedStatic(directory=WEB), name="assets")
    _errors(app)
    _pages(app, ver)
    return app


class _Asgi:
    """Route 只把类实例当作原生 ASGI 应用；函数会被当成 request→response 端点。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


def _errors(app: FastAPI) -> None:
    for exc, code in ERRORS.items():

        async def handler(_: Request, e: Exception, code: int = code):
            return JSONResponse({"detail": str(e)}, status_code=code)

        app.add_exception_handler(exc, handler)


def _signed_in(request: Request) -> bool:
    try:
        return bool(owner(request))
    except HTTPException:
        return False


def _pages(app: FastAPI, ver: str) -> None:
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    @app.get("/login", include_in_schema=False)
    async def login_page(request: Request):
        return RedirectResponse("/") if _signed_in(request) else html_page("login.html", ver)

    async def page(request: Request):
        return html_page("index.html", ver) if _signed_in(request) else RedirectResponse("/login")

    for p in PAGES:
        app.add_api_route(p, page, include_in_schema=False)
