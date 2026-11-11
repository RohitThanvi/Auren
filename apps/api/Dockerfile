# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ARG UV_VERSION=0.11.32
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir "uv==${UV_VERSION}"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 auren \
    && useradd --system --uid 10001 --gid auren --no-create-home --shell /usr/sbin/nologin auren
WORKDIR /app
COPY --from=builder --chown=auren:auren /app/.venv ./.venv
COPY --chown=auren:auren alembic.ini ./
COPY --chown=auren:auren migrations ./migrations
USER auren
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"]
CMD ["python", "-m", "auren_api"]
