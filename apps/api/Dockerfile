# syntax=docker/dockerfile:1
# Default (last) stage: the API (`python -m app`) and worker (`python -m app.workers`).
# The `test` stage adds dev dependencies and tests for scripts/test-integration.sh.

FROM python:3.13.17-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.7.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/api
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM build AS build-dev
RUN uv sync --locked --no-install-project

FROM python:3.13.17-slim-bookworm AS test
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build-dev /opt/venv /opt/venv
WORKDIR /srv/api
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests
USER app
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/integration"]

FROM python:3.13.17-slim-bookworm
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv/api
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
USER app
EXPOSE 8000
CMD ["python", "-m", "app"]
