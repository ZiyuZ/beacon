FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first to maximise layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# README.md is referenced as `readme = "README.md"` in pyproject.toml and
# read by uv_build at install time, so it must exist in the build context.
# LICENSE is included to keep PyPI metadata complete.
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    BEACON_SQLITE_PATH=/app/data/beacon.db

EXPOSE 8000
VOLUME ["/app/data"]

CMD ["uvicorn", "beacon.main:app", "--host", "0.0.0.0", "--port", "8000"]
