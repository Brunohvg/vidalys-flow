FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /uvx /bin/

WORKDIR /app

FROM base AS production-dependencies
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM base AS test
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --group dev --no-install-project
COPY . .

FROM production-dependencies AS runtime

RUN groupadd --system --gid 10001 vidalys \
    && useradd --system --uid 10001 --gid vidalys --home-dir /app --shell /usr/sbin/nologin vidalys

COPY --chown=vidalys:vidalys manage.py ./
COPY --chown=vidalys:vidalys apps ./apps
COPY --chown=vidalys:vidalys config ./config
COPY --chown=vidalys:vidalys templates ./templates
COPY --chown=vidalys:vidalys static ./static

RUN SECRET_KEY=build-only-not-a-runtime-secret \
    DATABASE_URL=postgresql://build:build@localhost:5432/build \
    CELERY_BROKER_URL=redis://localhost:6379/0 \
    REDIS_CACHE_URL=redis://localhost:6379/1 \
    VIDALYS_DEMO_MODE=1 \
    .venv/bin/python manage.py collectstatic --noinput

USER vidalys

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD [".venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live/', timeout=3)"]

CMD [".venv/bin/gunicorn", "config.wsgi:application", "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--timeout=60", "--access-logfile=-", "--error-logfile=-"]
