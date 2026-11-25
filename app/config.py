# ============================================================================
#  config —— 进程级配置，全部来自环境变量
#
#  只放「登录之前就必须知道」的东西；AI 供应商属于业务配置，在页面里设置。
#  data_dir 是唯一的可写目录：数据库、Markdown、JSON、视频、上传临时文件都在里面。
# ============================================================================
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("VM_OIDC_ISSUER", "VM_OIDC_CLIENT_ID", "VM_OIDC_CLIENT_SECRET", "VM_SECRET_KEY")


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载：已存在的环境变量优先。"""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, eq, value = line.strip().partition("=")
        if eq and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Config:
    base_url: str
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    secret_key: str
    data_dir: Path
    lease_minutes: int = 60
    max_video_mb: int = 2048

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @classmethod
    def from_env(cls) -> Config:
        _load_dotenv(Path(os.environ.get("VM_ENV_FILE", ".env")))
        env = os.environ
        missing = [k for k in REQUIRED if not env.get(k)]
        if missing:
            raise RuntimeError(f"缺少环境变量: {', '.join(missing)}（见 .env.example）")
        return cls(
            base_url=env.get("VM_BASE_URL", "http://localhost:8710").rstrip("/"),
            oidc_issuer=env["VM_OIDC_ISSUER"].rstrip("/"),
            oidc_client_id=env["VM_OIDC_CLIENT_ID"],
            oidc_client_secret=env["VM_OIDC_CLIENT_SECRET"],
            secret_key=env["VM_SECRET_KEY"],
            data_dir=Path(env.get("VM_DATA_DIR", "./data")),
            lease_minutes=int(env.get("VM_LEASE_MINUTES", "60")),
            max_video_mb=int(env.get("VM_MAX_VIDEO_MB", "2048")),
        )
