#!/usr/bin/env bash
# 服务器上更新：拉公开镜像 → 重建容器 → 健康检查
set -euo pipefail
cd "$(dirname "$0")"
export DOCKER_CONFIG="$PWD/.docker"   # 匿名拉取，不受本机其他 ghcr 登录影响
mkdir -p "$DOCKER_CONFIG" data
chown 10001 data                      # 容器以 uid 10001 运行
docker compose pull -q
docker compose up -d --remove-orphans
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8710/healthz >/dev/null 2>&1 && { echo "vmarker 已就绪"; exit 0; }
  sleep 1
done
docker compose logs --tail 50
exit 1
