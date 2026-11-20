# Two stages: install with uv, then copy only the virtual environment and the
# code into a small runtime image that runs as a non-root user.

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

# Dependencies first, so this layer is cached until the lock file changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY README.md alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --locked --no-dev


FROM python:3.13-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build --chown=app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000

# Apply migrations, load the demo data into an empty database, then serve.
# The host may set PORT (Render does).
CMD ["sh", "-c", "alembic upgrade head && python -m invoice_api.seed --if-empty && uvicorn invoice_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
