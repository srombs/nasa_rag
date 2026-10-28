# 01: Ask NASA questions through a locally runnable API

**What to build:** A developer can install the optional web dependencies, start one API worker, check its health, and submit an independent question to receive the existing pipeline's final answer unchanged in JSON.

**Blocked by:** None (can start immediately).

**Status:** resolved

## Acceptance criteria

- [x] The optional web installation provides a documented, working server launch command with configurable port and writable document/index-cache location; existing CLI installation and invocation remain usable.
- [x] Starting the API initializes the existing retriever once per process, before serving questions. Missing required configuration or failed initialization causes startup to fail with an operational error. Importing the web adapter alone does not initialize the retriever or call models.
- [x] `GET /health` succeeds once initialization is complete and never runs retrieval, generation, or a model request.
- [x] `POST /ask` accepts a JSON object containing only a nonblank question of at most 1,000 characters. Wrong types, blank/oversized questions, and unsupported fields receive 422 with a request ID and a public machine-readable error.
- [x] An accepted question follows the existing retrieval planning, hybrid search, fusion, reranking, generation, and citation-check sequence with the current settings. The planned search query is reused rather than rewritten a second time; CLI printouts are not parsed to obtain the result.
- [x] A successful response contains only `request_id` and `answer`. The answer exactly matches the existing pipeline result, including inline citations, insufficient-evidence text, and any existing appended warning. No new source filtering, extra source array, or citation rejection is introduced.
- [x] Only one pipeline call is active in the worker at a time; another concurrent question receives 503. Health checks remain responsive while synchronous pipeline work runs, and the processing slot is released after normal completion or failure.
- [x] Mocked HTTP tests exercise successful pass-through (including an existing warning), invalid input, startup reuse/failure, health behavior, and simultaneous requests. Existing project tests continue to pass without changing existing RAG/CLI modules.

## Demo path

Start the local service, observe a healthy response, submit a question, and inspect the unchanged answer inside the minimal JSON response. Automated demonstrations use a mocked pipeline so they are repeatable without paid requests.

## Scope

Use the existing full hybrid pipeline and its current settings. Preserve existing RAG and CLI source modules and behavior. This ticket concerns the new web adapter, its installation/configuration, and its own verification. Creating this ticket does not authorize execution, model requests, or deployment. Portfolio UI, proxy deployment, streaming, answer caching, richer source responses, user-controlled settings, and changes to RAG answer/citation policy remain outside this feature.


## Answer

Implemented the optional adapter in `src/nasa_rag/web.py`, with startup-only
retriever loading, required environment configuration, strict HTTP validation,
unchanged full-pipeline answer strings, responsive health checks, and one active
pipeline task per worker. Existing RAG and CLI modules are unchanged. See
[local API setup and usage](../../../docs/web-api.md).

Verification:

- `uv run --extra web --extra dev python -m pytest -q`: **107 passed**
  (82 existing tests and 25 HTTP cases), using mocked model requests only.
- `uv run --extra web --extra dev ruff check src/nasa_rag/web.py tests/test_web.py`:
  **passed**; `git diff --check`: **passed**.
- After `uv sync` removes optional web/dev packages,
  `uv run --with pytest python -m pytest -q`: **82 passed, 1 skipped**.
  `uv run nasa-rag --help` still works without web dependencies.
- Optional installation resolves FastAPI/Uvicorn successfully; Uvicorn launch
  options and the documented ASGI target were verified without live model calls.

## Comments

2026-10-28: Implemented ticket 01 only on `implement/fastapi-ticket-01`, based on
`integration/fastapi-ticket-01`. Live pipeline execution and deployment were not
performed. Rate limits, deadlines, proxy trust, full operational error mapping,
and request logs remain ticket 02; runtime/RAM measurements remain ticket 03.
