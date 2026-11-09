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

For the installed application in a Linux container, see [the Docker guide](docker.md).
For private hosting and the operator checklist, see [Railway dashboard deployment](railway-deployment.md).

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

## Live search stages (development slice)

`POST /ask/stream` accepts the same strict question body as `/ask`. This is an
incremental backend implementation of the [live search flow](../.scratch/rag-ui-trace/spec.md),
for development only until ticket 06 verifies the complete frontend contract.
It currently delivers stage lifecycles, planning/retrieval details, and the final
answer. `metrics` contains only measured `duration_ms`. Reranking progress,
structured citation results, usage/cost fields, and complete interruption
handling arrive in tickets 03–05; their completion `details` remain empty.
Missing fields are not fabricated values or claims of zero model usage.

The first five `stage.completed` events include these `data.details` fields:

| Stage | Details |
| --- | --- |
| `plan_query` | Actual `search_query` and `source_file_filter` (filename or null). Invalid provider plans fail this stage. |
| `embed_query` | Requested `model` and validated vector `dimensions`. |
| `semantic_search` | `results`: up to 30 passages with one-based `rank` and native `similarity`. |
| `keyword_search` | `results`: up to 30 passages with one-based `rank` and native `bm25_score`. |
| `combine_rankings` | Actual `rrf_k` (60) and up to ten `results` with `rank`, `rrf_score`, `faiss_rank`, and `bm25_rank`. |

Each passage includes `source` (filename), zero-based `chunk_index`, printable
`reference` (for example `[hubble.txt, chunk 0]`), and full chunk `text`. Scores
are finite JSON numbers. Arrays preserve actual ranking and tie order. Fusion
uses the full eligible base rankings before truncating inspection lists, so its
source ranks can exceed 30. Retrieval results are candidates; selection does
not establish that a passage is cited or proves an answer. Scores from different
methods are not directly comparable or accuracy percentages.

Details are frozen when their stage completes. The same snapshots appear in
terminal `data.stages`, including completed retrieval stages retained after a
later pipeline failure. Serialization uses explicit allowed fields; embedding
vectors and raw provider objects are excluded.

With live model calls authorized, inspect incremental delivery using:

```sh
curl --no-buffer --fail-with-body "http://127.0.0.1:$PORT/ask/stream" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What mission launched Hubble?"}'
```

Accepted requests return HTTP 200, UTF-8 `text/event-stream`,
`Cache-Control: no-cache, no-transform`, and `X-Request-ID`, without a fixed
content length. Each application event uses `event: <type>`, `id: <sequence>`,
and JSON `data: <envelope>`, followed by a blank line. The envelope contains
`schema_version` (1), `request_id`, contiguous `sequence` starting at 1, `type`,
UTC `timestamp_utc`, monotonic `elapsed_ms`, `stage_id` (null for run events),
and a type-specific `data` object. Idle periods send `: heartbeat` comments at
least every 15 seconds; these do not consume sequence numbers or reset deadlines.

`run.started` supplies the ordered `stage_ids`. Each operation emits
`stage.started` before its work and `stage.completed` after successful return
and its existing validation: planning, embedding, semantic search, keyword
search, fusion, reranking, generation, and the citation reference check.
`run.completed` delivers the unchanged full `answer` after citation checking.
Answer tokens are not streamed. There is exactly one terminal event on a healthy
connection. A failure emits sanitized `stage.failed` and `run.failed` events;
`run.failed` includes the existing public error, `http_equivalent_status`, and
`processing_may_continue`. Deadlines emit a terminal failure without inventing
a stage failure. HTTP status remains 200 once streaming headers were sent.

Both routes share the work slot, IP allowance, proxy trust, and admission errors.
Invalid, unavailable, busy, and over-limit submissions receive the usual JSON
errors before SSE headers. After a timeout or disconnect, the actual worker
keeps its slot until it finishes. Observation is detachable, with a 64-event
queue bound; overflow closes observation rather than blocking model work.
EOF without a terminal event means interruption. There is no replay, automatic
resubmission, or claim that closing the stream cancels processing.

Stream request logs retain the actual HTTP status and add `stream_outcome`
(`completed`, `failed`, `timeout`, or `disconnected`) and `failure_code` when
known. HTTP 200 alone does not establish successful observation. Questions,
event bodies, and raw exceptions are omitted from operational logs.

The focused offline streaming tests include a real loopback TCP connection with
a deterministically blocked mocked provider. They receive an active stage and
heartbeat before releasing generation, then receive the unchanged final answer:

```sh
uv run --extra web --extra dev python -m pytest -q tests/test_web_stream.py
```

This is backend evidence only. Website proxy buffering, runtime timeouts, and
browser delivery still need verification in the frontend repository.

## Submission limits and deadlines

Each client IP may submit ten requests across `POST /ask` and `POST /ask/stream`
in a rolling ten-minute window.
The eleventh receives 429. Invalid submissions, busy requests, timeouts, and
failures consume the allowance; over-limit attempts do not extend the window.
Separate addresses have separate allowances. Health checks do not consume them.
Expired timestamps and empty address entries are removed on subsequent
submissions. Counters live only in the worker's memory and reset on restart;
there is no database, Redis service, or global daily quota.

`NASA_RAG_RESPONSE_TIMEOUT_SECONDS` sets the pipeline response deadline (default
120 seconds); it must be a positive finite number or startup fails. A deadline
produces 504 with a request ID for `/ask`, or a `run.failed` event after
streaming admission. This ends the HTTP wait; underlying processing
may continue, with the service returning `busy` until that call actually finishes.
The adapter does not retry or claim cancellation. Existing model-client retries
are unchanged. A disconnected or canceled JSON request is recorded with status 499;
the disconnected visitor cannot receive that response. Admitted streams retain
HTTP 200 and record `stream_outcome=disconnected`.

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
HTTP library logs. Existing CLI logging behavior is preserved; logger
configuration is restored when the app shuts down. Keep `--no-access-log` to avoid
a second Uvicorn access log containing raw request URLs.

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
