# ============================================================================
#  假上游：/oidc/* 假 Pocket ID（自动同意）；/v1/* 假的 OpenAI 格式接口
#  模型名决定行为：echo 正常、files 写文件、cut 截断、slow 慢速、broken 报错
# ============================================================================
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

CLIENT_ID, CLIENT_SECRET = "test-client", "test-secret"
GOOD_KEY = "good-key"
USER = {"sub": "user-1", "email": "owner@acme.test", "name": "Acme Owner"}
_OIDC_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FILES = '好的。\n<file name="文字稿.md">\n# 测试稿\n\n| 旁白 | 画面 |\n|---|---|\n| 你好 | 片头 |\n</file>\n<file name="../坏.md">\nx\n</file>\n'
REPLIES = {
    "echo": "可用",
    "files": FILES.split('<file name="../')[0],
    "evil": FILES,
    "cut": '<file name="半.md">\n没写完',
    "slow": "慢" * 40,
    "xss": "<img src=x onerror=window.pwned=1> [x](javascript:alert(1))",
}


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign_jwt(claims: dict) -> str:
    seg = (
        b64(json.dumps({"alg": "RS256", "typ": "JWT", "kid": "k1"}).encode())
        + "."
        + b64(json.dumps(claims).encode())
    )
    return seg + "." + b64(_OIDC_KEY.sign(seg.encode(), padding.PKCS1v15(), hashes.SHA256()))


def build(ref: dict) -> FastAPI:
    app = FastAPI()
    codes: dict = {}
    ref["seen"] = []

    def base() -> str:
        return ref["url"]

    @app.get("/oidc/.well-known/openid-configuration")
    async def discovery():
        b = base()
        return {
            "issuer": f"{b}/oidc",
            "authorization_endpoint": f"{b}/oidc/authorize",
            "token_endpoint": f"{b}/oidc/token",
            "jwks_uri": f"{b}/oidc/jwks",
            "userinfo_endpoint": f"{b}/oidc/userinfo",
            "id_token_signing_alg_values_supported": ["RS256"],
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "code_challenge_methods_supported": ["S256"],
        }

    @app.get("/oidc/jwks")
    async def jwks():
        pub = _OIDC_KEY.public_key().public_numbers()
        to = lambda n: b64(n.to_bytes((n.bit_length() + 7) // 8, "big"))  # noqa: E731
        return {
            "keys": [
                {"kty": "RSA", "kid": "k1", "alg": "RS256", "use": "sig", "n": to(pub.n), "e": to(pub.e)}
            ]
        }

    @app.get("/oidc/authorize")
    async def authorize(request: Request):
        q = request.query_params
        if q.get("client_id") != CLIENT_ID or q.get("code_challenge_method") != "S256":
            raise HTTPException(400, "bad client or missing PKCE")
        code = secrets.token_urlsafe(16)
        codes[code] = {
            "nonce": q.get("nonce"),
            "challenge": q.get("code_challenge"),
            "redirect": q["redirect_uri"],
        }
        return RedirectResponse(f"{q['redirect_uri']}?{urlencode({'code': code, 'state': q['state']})}")

    @app.post("/oidc/token")
    async def token(request: Request):
        form = await request.form()
        auth = request.headers.get("authorization", "")
        cid, csec = form.get("client_id"), form.get("client_secret")
        if auth.startswith("Basic "):
            cid, _, csec = base64.b64decode(auth[6:]).decode().partition(":")
        if (cid, csec) != (CLIENT_ID, CLIENT_SECRET):
            return JSONResponse({"error": "invalid_client"}, 401)
        c = codes.pop(form.get("code"), None)
        verifier = form.get("code_verifier", "")
        if not c or b64(hashlib.sha256(verifier.encode()).digest()) != c["challenge"]:
            return JSONResponse({"error": "invalid_grant"}, 400)
        now = int(time.time())
        idt = sign_jwt(
            {
                "iss": f"{base()}/oidc",
                "aud": CLIENT_ID,
                "iat": now,
                "exp": now + 600,
                "nonce": c["nonce"],
                **ref.get("user", USER),
            }
        )
        return {
            "access_token": "at-" + secrets.token_hex(8),
            "token_type": "Bearer",
            "expires_in": 600,
            "id_token": idt,
        }

    @app.get("/oidc/userinfo")
    async def userinfo():
        return USER

    # ------------------------------------------------------------ OpenAI 格式
    def auth(request: Request):
        if request.headers.get("authorization") != f"Bearer {GOOD_KEY}":
            raise HTTPException(401, "bad key")

    @app.get("/v1/models")
    async def models(request: Request):
        auth(request)
        ages = {"xss": 1, "echo": 9, "files": 5}
        return {"data": [{"id": m, "created": t} for m, t in ages.items()]}

    @app.get("/anthropic/models")
    async def anthropic_models(request: Request):
        if request.headers.get("x-api-key") != GOOD_KEY:
            raise HTTPException(401, "Invalid bearer token")
        return {"data": [{"id": "claude-x", "created_at": "2026-01-01"}]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        auth(request)
        body = await request.json()
        ref["seen"].append(body)
        model = body["model"]
        if model not in REPLIES:
            return JSONResponse({"error": {"message": "no such model"}}, 404)

        async def gen():
            for ch in REPLIES[model]:
                await asyncio.sleep(0.05 if model == "slow" else 0)
                yield "data: " + json.dumps({"choices": [{"delta": {"content": ch}}]}) + "\n\n"
            reason = "length" if model == "cut" else "stop"
            yield "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": reason}]}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app
