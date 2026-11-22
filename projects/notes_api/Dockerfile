# syntax=docker/dockerfile:1
# The Notes API image (API and worker). Stage "build" installs the locked dependencies with uv
# into /app/.venv; stage "runtime" copies only that environment and the migrations, and runs
# as an unprivileged user. Build: docker build -t notes-api .
ARG PYTHON_VERSION=3.15

FROM ghcr.io/astral-sh/uv:0.13.5 AS uv


FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# 1. Dependencies only: this layer is reused until uv.lock or pyproject.toml change.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
# 2. The project itself, installed as a regular package (no link back to /app/src).
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM python:${PYTHON_VERSION}-slim AS runtime
# Debian security fixes published after the base image was built (CI fails on fixable
# HIGH/CRITICAL findings), and no pip: the app runs from /app/.venv and installs nothing,
# while the base image's pip vendors its own urllib3, msgpack and setuptools copies.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --root-user-action=ignore pip
RUN groupadd --system --gid 10001 notes \
    && useradd --system --uid 10001 --gid notes --no-create-home --shell /usr/sbin/nologin notes \
    && install -d -o notes -g notes /tmp/prometheus
WORKDIR /app
COPY --from=build --chown=notes:notes /app/.venv /app/.venv
COPY --chown=notes:notes alembic.ini ./
COPY --chown=notes:notes alembic ./alembic
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_CONCURRENCY=2 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus \
    NOTES_ENVIRONMENT=production
USER notes
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
# Uvicorn reads WEB_CONCURRENCY (worker processes) and FORWARDED_ALLOW_IPS (trusted proxies).
CMD ["uvicorn", "notes_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "20"]
