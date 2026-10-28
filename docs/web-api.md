# Local question API

Ticket 01 adds an optional FastAPI adapter for the existing full hybrid pipeline.
Install and run it from the repository root:

```sh
uv sync --extra web
export NASA_RAG_CACHE_DIR="$PWD/cache"
export PORT=8000
uv run --extra web uvicorn nasa_rag.web:app --host 127.0.0.1 --port "$PORT" --workers 1
```

Supply `OPENAI_API_KEY` through the environment before starting the server; keep
its value out of source files. Both `OPENAI_API_KEY` and `NASA_RAG_CACHE_DIR` are
required. Set `PORT` to choose a different listening port. Pip installations can
use `pip install '.[web]'` followed by the same `uvicorn` command without `uv run`.
The base installation and `nasa-rag` CLI remain available without the web extra.

The cache directory must be writable and may be an absolute path to a persistent
volume. The adapter uses the four bundled documents, current chunk size/overlap
(100/20), top 30 display rankings, ten fused/reranked candidates, and RRF constant
60. It initializes one retriever during startup and reuses it for questions.
Initialization fails if configuration, document loading, or cache/index loading
fails. Importing `nasa_rag.web` alone does not load the retriever or call models.
Cold startup can request document embeddings; questions run the existing model
pipeline. Live smoke checks therefore require authorization for model calls.

After startup, check readiness without invoking any model:

```sh
curl --fail "http://127.0.0.1:$PORT/health"
```

This returns `{"status":"ok"}`. With live calls authorized, submit an independent
question:

```sh
curl --fail-with-body "http://127.0.0.1:$PORT/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What mission launched Hubble?"}'
```

A successful response contains only `request_id` (a generated UUID) and `answer`.
The answer is the existing pipeline string, including inline citations,
insufficient-evidence text, and any appended citation warning. Retrieval planning
chooses the search query and optional source restriction; the adapter reuses that
query for hybrid retrieval and generates from the reranked chunks.

The request must be a JSON object containing only a string `question`, with at
least one non-whitespace character and a maximum length of 1,000 characters.
Validation errors use HTTP 422 with this public envelope:

```json
{
  "request_id": "<generated UUID>",
  "error": {
    "code": "invalid_request",
    "message": "Provide only a nonblank question of at most 1,000 characters."
  }
}
```

Run exactly one worker. It accepts one pipeline call at a time, returns 503 with
error code `busy` for concurrent questions, and keeps `/health` responsive by
running synchronous pipeline work in a thread. A completed or failed call frees
the processing slot; a pipeline failure currently returns a generic 500 error.
The slot follows actual pipeline work if a request handler is canceled, and
normal shutdown waits for that work to finish.

Ticket 02 adds submission limits, response deadlines, proxy trust configuration,
full operational error mapping, and request logging. Ticket 03 adds completed
runtime verification and RAM measurements. This adapter is currently a local
development service; those tickets and deployment remain separate work.

Run the repeatable mocked HTTP demonstration and the existing suite without
model calls:

```sh
uv run --extra web --extra dev python -m pytest -q
uv run --extra web --extra dev ruff check src/nasa_rag/web.py tests/test_web.py
```

The HTTP tests substitute the pipeline for lifecycle/concurrency cases and mock
only the OpenAI provider for full pipeline/citation checks. They write document
and FAISS caches into test temporary directories. Without the web extra, the
optional HTTP tests are skipped and the existing suite remains runnable.
