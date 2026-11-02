FROM python:3.13.18-slim-bookworm AS build

# Match the repository's local uv version; the runtime does not need uv.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY data/ ./data/
RUN uv sync --locked --extra web --no-dev --no-editable --no-cache

FROM python:3.13.18-slim-bookworm AS runtime

# FAISS uses OpenMP on Linux.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    NASA_RAG_CACHE_DIR=/data/cache \
    NASA_RAG_COST_LOG_PATH=/data/logs/model_costs.jsonl \
    NASA_RAG_RESPONSE_TIMEOUT_SECONDS=120 \
    NASA_RAG_TRUSTED_PROXIES=""

WORKDIR /app
# A non-editable install contains the application and bundled documents.
COPY --from=build /app/.venv /app/.venv

EXPOSE 8000
# exec forwards container shutdown signals directly to the one server worker.
CMD ["sh", "-c", "exec uvicorn nasa_rag.web:app --host 0.0.0.0 --port \"$PORT\" --workers 1 --no-proxy-headers --no-access-log"]
