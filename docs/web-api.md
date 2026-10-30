# Local question API

The optional FastAPI adapter exposes the existing full hybrid pipeline.
Install and run it from the repository root:

```sh
uv sync --extra web
export NASA_RAG_CACHE_DIR="$PWD/cache"
export PORT=8000
export NASA_RAG_RESPONSE_TIMEOUT_SECONDS=120
export NASA_RAG_TRUSTED_PROXIES=''
uv run --extra web uvicorn nasa_rag.web:app --host 127.0.0.1 --port "$PORT" \
  --workers 1 --no-proxy-headers --no-access-log
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
Every HTTP response also includes `X-Request-ID`, matching the JSON request ID
when present. Client-supplied request IDs are ignored.
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
the processing slot. The slot follows actual pipeline work if a request handler
is canceled, the client disconnects, or its response deadline expires. No question
queue is maintained. Normal shutdown waits for that work to finish; process
termination does not recover it on restart.

## Submission limits and deadlines

Each client IP may submit ten `POST /ask` requests in a rolling ten-minute window.
The eleventh receives 429. Invalid submissions, busy requests, timeouts, and
failures consume the allowance; over-limit attempts do not extend the window.
Separate addresses have separate allowances. Health checks do not consume them.
Expired timestamps and empty address entries are removed on subsequent
submissions. Counters live only in the worker's memory and reset on restart;
there is no database, Redis service, or global daily quota.

`NASA_RAG_RESPONSE_TIMEOUT_SECONDS` sets the pipeline response deadline (default
120 seconds); it must be a positive finite number or startup fails. A deadline
produces 504 with a request ID. This ends the HTTP wait; underlying processing
may continue, with the service returning `busy` until that call actually finishes.
The adapter does not retry or claim cancellation. Existing model-client retries
are unchanged. A disconnected or canceled request is recorded with status 499;
the disconnected visitor cannot receive that response.

## Proxy trust and access boundary

Local development binds to loopback and leaves `NASA_RAG_TRUSTED_PROXIES` empty,
so forwarded headers cannot change the rate-limit identity. Keep
`--no-proxy-headers` in the launch command: the adapter owns forwarding trust,
and Uvicorn must pass the original connection address through unchanged. See
[Uvicorn's proxy settings](https://uvicorn.dev/settings/#http).

The intended hosted path is browser → portfolio same-origin proxy → private API.
Configure `NASA_RAG_TRUSTED_PROXIES` with a comma-separated list of the connecting
proxy's IP addresses or narrowly scoped CIDR networks before starting the API.
The adapter uses Uvicorn's proxy middleware to honor `X-Forwarded-For` only from
those connections. It walks a proxy chain from the right, selecting the first
untrusted address, so a visitor cannot override its identity by prepending a
forged address. Untrusted connections' forwarding headers are ignored.

The proxy must overwrite forwarding headers with the observed visitor address,
or append that address correctly; every intermediate trusted hop must do the
same. Do not trust arbitrary visitor networks or use `*`. Restrict backend network
access to the proxy, and verify distinct visitor addresses and forged-header
handling during integration. The same-origin path needs no CORS configuration
or visitor login. This ticket does not deploy the proxy, configure networking,
or add authentication.

## Errors and logs

All HTTP failures use the illustrated `request_id` / `error.code` /
`error.message` JSON envelope, with fixed public messages:

| HTTP status | Error code | Meaning |
| --- | --- | --- |
| 422 | `invalid_request` | Invalid JSON or question payload |
| 429 | `rate_limited` | Submission allowance exhausted |
| 503 | `not_ready` / `busy` | Pipeline unavailable or still running |
| 502 | `upstream_error` | Provider connection/status or model-response failure |
| 504 | `response_timeout` | Response deadline exceeded |
| 500 | `internal_error` | Unexpected server fault |
| 404 / 405 | `http_error` | Unknown route / unsupported method |

Existing answers, insufficient-evidence text, and citation warnings remain
successful answer content. Provider error details, credentials, and tracebacks
are omitted from public failures.

Standard `nasa_rag.web` INFO logs record one entry per HTTP request, for example:

```text
request_id=<UUID> status=504 elapsed_ms=120001.23
```

Match the response ID to that entry for operational correlation. Routine web
logging omits bodies, questions, context, headers, raw URLs, and credentials.
During the web lifespan, logging configuration silences existing RAG loggers
(including their prompt-bearing INFO logs and exception tracebacks) and provider
HTTP library logs. Original RAG/CLI modules are unchanged; logger configuration
is restored when the app shuts down. Keep `--no-access-log` to avoid a second
Uvicorn access log containing raw request URLs.

See [runtime verification and measured RAM evidence](web-runtime-verification.md)
for a repeatable offline server/profile command, persisted-cache restart checks,
the provisional local memory report, and rough Railway hosting costs with
explicit resource assumptions and plan minimums.
Real model benchmarks, portfolio/proxy integration, and deployment require
separate authorization.

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

For the ticket 02 demo alone, including busy/recovery, rate-limit expiry, deadline
request-ID correlation, and disconnect/cancellation behavior:

```sh
uv run --extra web --extra dev python -m pytest -q tests/test_web.py \
  -k 'busy or rate_limit or configured_proxy or deadline or disconnected or response_ids'
```

These tests use controlled events, an injected limiter clock, and a 0.02-second
deadline. They do not wait 120 seconds or make paid requests.
