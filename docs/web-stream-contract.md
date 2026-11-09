# Search stream API, version 1

This is the implemented backend contract for `POST /ask/stream`. The
[API guide](web-api.md) defines setup, stage detail and metric fields, trusted
proxy configuration, and the legacy JSON API. The
[public fixtures](fixtures/search-stream-v1/README.md) are checked against
server responses by [offline verification](web-stream-verification.md).

## Request and admission

Send `Content-Type: application/json` with exactly
`{"question":"What mission launched Hubble?"}`. `question` must be a strict
string, nonblank, at most 1,000 characters; extra fields are rejected. The
pipeline receives the original question. There is one POST connection per run.

Both `/ask` and `/ask/stream` share one active worker and ten submissions per
visitor IP per rolling ten minutes. Invalid, busy, failed and timed-out attempts
consume allowance. Over-limit attempts do not extend the window. Allowance is
process-local and resets on restart; run one server worker. `/health` consumes
neither allowance nor model calls. Visitor identity follows the trusted-proxy
rules in the API guide.

Before admission, failures are non-200 `application/json` with
`{"request_id":"<UUID>","error":{"code":"<code>","message":"<fixed public message>"}}`.
The ID matches `X-Request-ID`. Do not send this body to the SSE parser.

| Status | Code | Meaning |
| --- | --- | --- |
| 422 | `invalid_request` | Invalid JSON, type, question length, or extra fields. |
| 429 | `rate_limited` | Shared submission allowance exhausted. |
| 503 | `not_ready`, `busy` | Pipeline unavailable or actual work still running. |

Legacy `/ask` still returns `{request_id, answer}` on success. Failures during
its work use 502 `upstream_error`, 500 `internal_error`, or 504
`response_timeout`. A disconnected JSON request is recorded as 499
`client_disconnected`; the departed client cannot receive it.

## Headers, framing, and envelope

An admitted stream returns HTTP 200 with:

```text
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-transform
X-Request-ID: <server-generated UUID>
```

There is no fixed `Content-Length`. Each UTF-8 application frame has this form,
terminated by a blank line (LF on the backend):

```text
event: run.started
id: 1
data: {"schema_version":1,"request_id":"<UUID>","sequence":1,"type":"run.started","timestamp_utc":"<UTC ISO 8601>","elapsed_ms":0.1,"stage_id":null,"data":{"stage_ids":["plan_query","embed_query","semantic_search","keyword_search","combine_rankings","rerank_evidence","generate_answer","check_citations"]}}

```

| Envelope field | Required type and meaning |
| --- | --- |
| `schema_version` | Integer `1`. |
| `request_id` | UUID string matching the response header and usage ledger. |
| `sequence` | Contiguous increasing integer starting at 1 for this run; equals SSE `id`. |
| `type` | Event name string; equals SSE `event`. |
| `timestamp_utc` | UTC ISO 8601 string. |
| `elapsed_ms` | Nonnegative monotonic number of milliseconds since admission. |
| `stage_id` | Stage ID string on stage events, null on run events. |
| `data` | Event-specific object. |

When idle, the server emits `: heartbeat\n\n` at least every 15 seconds.
Comments have no envelope or sequence and do not indicate stage progress or
extend the response deadline.

## Event data and stage state

| Event | Required `data` fields |
| --- | --- |
| `run.started` | `stage_ids`: the ordered eight strings above. First event; initialize pending stages. |
| `stage.started` | Empty object. The stage is running before its operation executes. |
| `stage.progress` | Reranking only: integer `completed`, integer `total`, object `result`. |
| `stage.completed` | `details`: completion object; `metrics`: stage metric object. |
| `stage.failed` | `error`: fixed public code/message; `metrics`: observed stage metrics. Only an actual stage failure emits this. |
| `run.completed` | `answer`: full unchanged string; `metrics`: run metrics; `stages`: final snapshot array. Successful terminal. |
| `run.failed` | `error`, integer `http_equivalent_status`, boolean `processing_may_continue`, `metrics`, `stages`. Failed terminal. |

Stage order is sequential: plan query, embed query, semantic search, keyword
search, combine rankings, rerank evidence, generate answer, check citation
references. Startup corpus loading/embedding/indexing is outside this flow.
The [stage detail and metric tables](web-api.md#live-search-flow-stream) define
the exact fields and ranking records for each stage. Semantic/keyword inspection
lists contain up to 30 passages; fusion and reranking contain up to ten. Full
eligible rankings still participate in fusion. Passage `reference` is its
identity within a run. Native scores are not comparable across methods.

Rerank progress follows evaluation order, after each validated candidate, with
the actual candidate count. Its result contains passage fields, `rerank_score`,
`reason`, `rrf_score`, `faiss_rank`, and `bm25_rank`, without a final `rank`.
Only the completion `results` array defines the final ranking. Generation
completion exposes `context_references`; the answer is published only in
`run.completed`, after the citation reference check. No answer tokens or raw
generation output are sent earlier. Citation outcomes `valid`, `warning`, and
`no_citations` all permit successful completion; none establishes factual truth.

Each terminal `stages` element contains:

| Field | Type |
| --- | --- |
| `stage_id` | Stable stage ID string, in execution order. |
| `status` | `pending`, `running`, `completed`, `failed`, `skipped`, or `unknown`. |
| `details` | Stage result object or null. Incomplete reranking preserves `evaluated_results` in evaluation order; completed reranking uses `results`. |
| `progress` | Latest rerank progress object or null. |
| `metrics` | Latest available metric object or null for unstarted work. |
| `error` | Object containing only string `code` and fixed public string `message`, or null. |

Normal transitions are pending → running → completed/failed. A true stage
failure marks later pending stages skipped and preserves prior results. An
observation deadline marks unfinished stages unknown rather than manufacturing
a stage failure. Snapshots preserve earlier events and are frozen at terminal
publication. Healthy connected runs deliver exactly one terminal event with no
application events afterward.

After admission, equivalent statuses are carried inside `run.failed` while
HTTP remains 200: 502 `upstream_error` for provider/malformed-output failure,
500 `internal_error` for unexpected faults, and 504 `response_timeout` for a
deadline. Errors use the same fixed vocabulary as JSON failures. A known stage
failure is not replaced by a later timeout; completed success remains success
if terminal delivery crosses the deadline.

## Metrics and work lifetime

Stage/run metrics contain numeric `duration_ms`, integer `model_calls`, sorted
string arrays `models` and `price_dates`, `tokens`, decimal-string
`known_cost_usd`, integer `unknown_cost_calls`, and boolean `cost_complete`.
Token categories are `input_tokens`, `cached_input_tokens`, `cache_write_tokens`,
`output_tokens`, and `reasoning_tokens`, each a nonnegative integer or null.
Missing applicable counts remain null; inapplicable categories are zero. Input
already includes cached/cache-write tokens; output already includes reasoning.

Calls are application-level completed responses/exceptions; provider retries
remain part of one call. Usage is recorded before output validation; in-flight
calls have not yet been recorded. `cost_complete` describes priceability of
**recorded calls**, not completion of all work. A timeout fixture deliberately
has `cost_complete: true` with `processing_may_continue: true`. Later calls can
add cost under the same request ID after observation ends. A zero known
subtotal with unknown-cost calls is not free usage. No model tokens are inferred
from text. Estimates use the existing pricing behavior and are not billing totals.

The deadline is `NASA_RAG_RESPONSE_TIMEOUT_SECONDS` (default 120), measured once
from admission, including provider retries. Events and heartbeats do not reset
it. Timeout ends observation, with `processing_may_continue` reflecting whether
work is still active at that point. Disconnect, reader abort, queue exhaustion,
or serialization failure can end observation without a terminal event. The
64-event buffer detaches on overflow rather than blocking the worker. Later
events are discarded; worker accounting and ledger recording continue. Actual
work retains the shared slot until it ends, including cleanup. Shutdown waits
for that work. Closing a connection does not establish cancellation.

## Incremental consumption and proxy requirements

Use Fetch POST with an incremental body reader and streaming UTF-8 decoding.
Validate status/content type before parsing. Retain partial frames across reads:
UTF-8 characters and SSE lines can split anywhere, and one read can contain
multiple frames. Accept LF/CRLF framing, ignore heartbeat comments, and validate
the envelope, sequence, request correlation, and required fields.

Ignore additive fields and unknown event types within version 1 after validating
the common envelope and sequence. Unsupported versions, malformed required data,
gaps/conflicting sequences, transport loss, or EOF without a terminal event
end observation as an explicit protocol/connection error. Preserve received
results and mark unfinished work unknown. HTTP 200 and EOF alone cannot prove
success: require `run.completed`. `run.failed` is a terminal failure.

There is no replay, job lookup, polling, automatic reconnect/resubmission, or
automatic JSON fallback that repeats an admitted search. A deliberate retry is
a new question attempt with a new request ID and normal allowance. It can
receive busy while the previous worker continues.

The website proxy must immediately forward request/body chunks, preserve
`X-Request-ID` and non-200 JSON errors, and disable caching, response buffering,
compression, or transformations that delay delivery. Preserve the existing
visitor-address trust and private backend access boundary. Every deployed hop
must support the backend deadline plus terminal-delivery margin. Forward
downstream disconnects where supported; this ends observation without promising
worker cancellation. No proxy should retry an admitted POST.

The browser-through-deployed-proxy incremental check remains **outstanding FE
acceptance work**. Backend loopback tests do not establish deployed streaming.
The [frontend handoff](../.scratch/rag-ui-trace/frontend-handoff.md) lists the
reader, presentation, accessibility, rollout, and rollback acceptance work.
