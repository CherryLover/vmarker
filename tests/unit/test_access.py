# 登录、所有者唯一、API Key 权限边界、凭证不外泄
from __future__ import annotations

from tests.conftest import add_ai, login, make_key
from tests.fakes import upstream as F


def test_signed_out(anon):
    for p in ("/", "/settings", "/p/p-0000000000"):
        assert anon.get(p, follow_redirects=False).headers["location"] == "/login"
    for p in ("me", "projects", "providers", "keys", "videos/1"):
        assert anon.get(f"/api/v1/{p}").status_code == 401
    assert anon.get("/healthz").json() == {"ok": True}
    assert anon.post("/mcp", json={}).status_code == 401


def test_only_first_account_is_owner(user, ref):
    user.post("/auth/logout")
    ref["user"] = {"sub": "intruder", "name": "x"}
    assert login(user).status_code == 403
    assert user.get("/api/v1/me").status_code == 401


def test_session_of_non_owner_lands_on_login_without_loop(user):
    user.app.state.db.run("UPDATE owner SET sub = 'someone-else'")
    assert user.get("/", follow_redirects=False).headers["location"] == "/login"
    assert user.get("/login", follow_redirects=False).status_code == 200


def test_forged_callback(anon):
    assert anon.get("/auth/callback?code=x&state=y").status_code == 400


def test_key_scopes(user, pid):
    read, plan, produce = make_key(user), make_key(user, "plan"), make_key(user, "produce")
    user.post("/auth/logout")
    f = f"/api/v1/files/{pid}/a.md"
    assert user.get("/api/v1/projects", headers=read).status_code == 200
    assert user.put(f, json={"content": "x"}, headers=read).status_code == 403
    assert user.put(f, json={"content": "x"}, headers=produce).status_code == 403
    assert user.put(f, json={"content": "x"}, headers=plan).status_code == 200
    # 人的动作：任何 Key 都不行
    for h in (read, plan, produce):
        for p in (
            f"projects/{pid}/confirm",
            "tasks/1/approve",
            "keys",
            "providers",
            f"projects/{pid}/conversations",
        ):
            assert user.post(f"/api/v1/{p}", json={}, headers=h).status_code == 401, p
        assert user.delete(f"/api/v1/projects/{pid}", headers=h).status_code == 401


def test_admin_key_is_owner(user, pid):
    h = make_key(user, "produce")
    kid = user.get("/api/v1/keys").json()[0]["id"]
    assert user.put(f"/api/v1/keys/{kid}", json={"scopes": ["produce", "admin"]}).status_code == 200
    user.post("/auth/logout")
    assert user.get("/api/v1/me", headers=h).status_code == 200
    assert user.put(f"/api/v1/files/{pid}/a.md", json={"content": "x"}, headers=h).status_code == 200
    assert user.post(f"/api/v1/projects/{pid}/confirm", headers=h).status_code == 201
    # 收回 admin 后立即失效
    assert user.put(f"/api/v1/keys/{kid}", json={"scopes": ["produce"]}, headers=h).status_code == 200
    assert user.get("/api/v1/keys", headers=h).status_code == 401
    assert user.put("/api/v1/keys/999", json={"scopes": []}).status_code == 401  # 已登出


def test_revoked_key(user):
    h = make_key(user)
    kid = user.get("/api/v1/keys").json()[0]["id"]
    assert user.delete(f"/api/v1/keys/{kid}").status_code == 204
    assert user.get("/api/v1/projects", headers=h).status_code == 401


def test_provider_lifecycle(user, fake):
    r = add_ai(user, fake).json()
    assert r["test"]["ok"] and r["test"]["detail"] == "可用"
    assert user.get(f"/api/v1/providers/{r['id']}/models").json() == ["echo", "files", "xss"]  # 最新在前
    listed = user.get("/api/v1/providers").text
    assert F.GOOD_KEY not in listed and "api_key" not in listed
    blob = user.app.state.db.one("SELECT api_key FROM providers")["api_key"]
    assert F.GOOD_KEY.encode() not in blob


def test_provider_failures_are_reported(user, fake):
    bad = add_ai(user, fake, key="wrong").json()["test"]
    assert not bad["ok"] and "401" in bad["detail"] and "wrong" not in bad["detail"]
    assert "no such model" in add_ai(user, fake, model="nope").json()["test"]["detail"]
    assert "连" in add_ai(user, "http://127.0.0.1:1").json()["test"]["detail"]
    assert add_ai(user, "ftp://x").status_code == 502


def test_changing_base_url_requires_key_again(user, fake):
    pid = add_ai(user, fake).json()["id"]
    body = {"name": "n", "base_url": "http://evil.test/v1", "model": "echo"}
    assert user.put(f"/api/v1/providers/{pid}", json=body).status_code == 502
    body["base_url"] = fake + "/v1/"
    assert user.put(f"/api/v1/providers/{pid}", json=body).json()["test"]["ok"]


def test_models_falls_back_to_x_api_key(user, fake):
    r = user.post("/api/v1/providers/models", json={"base_url": fake + "/anthropic", "api_key": F.GOOD_KEY})
    assert r.json() == ["claude-x"]
