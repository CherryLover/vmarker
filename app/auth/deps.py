# ============================================================================
#  deps —— 请求级身份判定
#
#    owner             只认浏览器会话：确认、审片、设置
#    allow("plan")     会话，或带该权限的 API Key
#    allow()           会话，或任意有效的 API Key（只读）
# ============================================================================
from __future__ import annotations

from fastapi import HTTPException, Request

from app.auth import keys


def owner(request: Request) -> dict:
    user = request.session.get("user")
    row = request.app.state.db.one("SELECT sub FROM owner") if user else None
    if not row or row["sub"] != user["sub"]:
        raise HTTPException(401, "请先通过 Pocket ID 登录")
    return user


def bearer(db, header: str | None) -> dict | None:
    scheme, _, key = (header or "").partition(" ")
    return keys.verify(db, key.strip()) if scheme.lower() == "bearer" else None


def allow(scope: str | None = None):
    def check(request: Request) -> dict:
        header = request.headers.get("authorization")
        if not header:
            return owner(request)
        row = bearer(request.app.state.db, header)
        if not row:
            raise HTTPException(401, "API Key 无效或已吊销")
        if scope and scope not in row["scopes"]:
            raise HTTPException(403, f"这个 API Key 没有 {scope} 权限")
        return row

    return check
