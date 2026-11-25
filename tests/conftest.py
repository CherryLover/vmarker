# conftest —— 假上游、指向它的配置、已登录的客户端
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app
from tests.fakes import free_port, serve
from tests.fakes import upstream as F

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000


@pytest.fixture(scope="session")
def ref():
    ref: dict = {}
    port = free_port()
    ref["url"] = f"http://127.0.0.1:{port}"
    server = serve(F.build(ref), port)
    yield ref
    server.should_exit = True


@pytest.fixture
def fake(ref) -> str:
    ref.pop("user", None)
    ref["seen"].clear()
    return ref["url"]


def make_cfg(fake: str, data: Path, base_url: str = "http://testserver") -> Config:
    return Config(base_url, f"{fake}/oidc", F.CLIENT_ID, F.CLIENT_SECRET, "test-secret-key-0123456789", data)


@pytest.fixture
def cfg(fake, tmp_path) -> Config:
    return make_cfg(fake, tmp_path / "data")


@pytest.fixture
def anon(cfg):
    with TestClient(create_app(cfg)) as c:
        yield c


def login(client: TestClient) -> httpx.Response:
    r = client.get("/auth/login", follow_redirects=False)
    cb = urlparse(httpx.get(r.headers["location"], follow_redirects=False).headers["location"])
    return client.get(f"{cb.path}?{cb.query}", follow_redirects=False)


@pytest.fixture
def user(anon):
    assert login(anon).headers["location"] == "/"
    return anon


@pytest.fixture
def pid(user):
    return user.post("/api/v1/projects", json={"title": "测试片", "brief": "讲清楚一件事"}).json()["id"]


def make_key(user, *scopes) -> dict:
    key = user.post("/api/v1/keys", json={"name": "t", "scopes": list(scopes)}).json()["key"]
    return {"Authorization": f"Bearer {key}"}


def add_ai(user, fake, model="echo", key=F.GOOD_KEY, path="/v1"):
    body = {"name": "fake", "base_url": fake + path, "model": model, "api_key": key}
    return user.post("/api/v1/providers", json=body)
