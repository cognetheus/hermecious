# syntax=docker/dockerfile:1
# Image for both the API (`python -m app`) and the worker (`python -m app.workers`).

FROM python:3.13.17-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.7.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/api
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13.17-slim-bookworm
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv/api
COPY app ./app
USER app
EXPOSE 8000
CMD ["python", "-m", "app"]
