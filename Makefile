# 常用命令：make dev / make lan / make test / make ci / make hooks
.PHONY: dev lan test e2e ci hooks setup

setup:            ## 安装依赖和测试浏览器，启用 git hooks
	uv sync
	uv run playwright install chromium
	git config core.hooksPath .githooks

dev:              ## 本机开发（自动重载）
	uv run uvicorn app.main:create_app --factory --reload --port 8710

lan:              ## 局域网可访问（VM_BASE_URL 要设成局域网地址）
	uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8710

test:             ## 接口测试
	uv run pytest tests/unit -q -p no:warnings

e2e:              ## 浏览器端到端测试
	uv run pytest tests/e2e -q -p no:warnings

ci:               ## 完整本地 CI（push 前自动执行）
	./scripts/ci.sh

hooks:
	git config core.hooksPath .githooks
