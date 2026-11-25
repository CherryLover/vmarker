# ============================================================================
#  vmarker 镜像：只有代码，没有数据。所有可写内容都在挂载的 /data
# ============================================================================
FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/CherryLover/vmarker" \
      org.opencontainers.image.description="Video planning and production platform"

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" VM_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app

RUN useradd --system --uid 10001 vmarker
USER vmarker
EXPOSE 8710
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8710/healthz', timeout=4)"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8710", "--proxy-headers", "--forwarded-allow-ips", "*"]
