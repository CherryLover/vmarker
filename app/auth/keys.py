# ============================================================================
#  keys —— API Key：明文只在创建时返回一次，库里只存 SHA-256
#
#  权限：read 人人都有；plan 可建项目、写文件；produce 可领任务、传视频；
#  admin 等同所有者：全部接口（确认、审片、设置、Key 管理），并隐含 plan + produce。
#  没有 admin 的 Key 碰不到人的动作。
# ============================================================================
from __future__ import annotations

import hashlib
import secrets

from app.db import DB, now_iso

PREFIX = "vmk_"
SCOPES = ("plan", "produce", "admin")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(db: DB, name: str, scopes: list[str]) -> dict:
    key = PREFIX + secrets.token_urlsafe(32)
    kid = db.run(
        "INSERT INTO api_keys (name, prefix, key_hash, scopes, created_at) VALUES (?, ?, ?, ?, ?)",
        name, key[:10], _hash(key), _pack(scopes), now_iso(),
    )  # fmt: skip
    return {"id": kid, "key": key}


def list_all(db: DB) -> list[dict]:
    return db.all(
        "SELECT id, name, prefix, scopes, created_at, last_used_at, revoked_at FROM api_keys "
        "ORDER BY revoked_at IS NOT NULL, id DESC"
    )


def _pack(scopes: list[str]) -> str:
    return ",".join(s for s in SCOPES if s in scopes)


def set_scopes(db: DB, kid: int, scopes: list[str]) -> bool:
    sql = "UPDATE api_keys SET scopes = ? WHERE id = ? AND revoked_at IS NULL"
    return db.changed(sql, _pack(scopes), kid) > 0


def revoke(db: DB, kid: int) -> bool:
    return (
        db.changed("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", now_iso(), kid)
        > 0
    )


def verify(db: DB, key: str) -> dict | None:
    row = db.one(
        "SELECT id, name, scopes FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", _hash(key)
    )
    if row:
        db.run("UPDATE api_keys SET last_used_at = ? WHERE id = ?", now_iso(), row["id"])
        row["scopes"] = set(row["scopes"].split(","))
        if "admin" in row["scopes"]:
            row["scopes"] |= {"plan", "produce"}
    return row
