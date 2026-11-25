#!/usr/bin/env bash
# ============================================================================
#  本地 CI：push 之前必须全绿。GitHub Actions 跑的是同一个脚本。
#    1. 防泄密：仓库是公开的，任何真实凭证都不能进 git
#    2. ruff lint + 格式
#    3. pytest：接口测试 + Playwright 浏览器端到端测试
#    4. Docker 镜像能构建（本机有 docker 且未设置 SKIP_DOCKER 时）
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "防泄密扫描"
PATTERN='BEGIN (RSA |EC )?PRIVATE KEY|sk-[A-Za-z0-9_-]{30,}|AIza[0-9A-Za-z_-]{30,}|vmk_[A-Za-z0-9_-]{30,}'
if git grep --untracked -I -n -E "$PATTERN" -- ':!scripts/ci.sh'; then
  echo "发现疑似凭证，拒绝继续。" >&2; exit 1
fi
if git ls-files --cached --others --exclude-standard | grep -E '(^|/)\.env$|\.db$'; then
  echo "发现不应提交的文件。" >&2; exit 1
fi

step "ruff"
uv run ruff check .
uv run ruff format --check .

step "pytest（含浏览器端到端）"
uv run pytest -q -p no:warnings

if [[ -z "${SKIP_DOCKER:-}" ]] && command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  step "docker build"
  docker build -q -t vmarker:ci . >/dev/null
else
  step "跳过 docker build（Docker 未运行或设置了 SKIP_DOCKER）"
fi

printf '\n\033[1;32m本地 CI 通过\033[0m\n'
