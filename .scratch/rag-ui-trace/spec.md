# Live RAG search flow — PRD/TRD

Status: ready-for-agent
Recorded: 2026-11-06
Scope: Backend API, website proxy, and visitor-facing frontend
Delivery: Backend changes in this repository; frontend changes in the website repository

## Problem Statement

Website visitors receive only the final answer to a NASA question. While the
search runs, they cannot see which stage is active, what passages retrieval
found, how rankings changed, or how much model work the question required.

The pipeline already produces much of this information, but the web adapter
discards intermediate retrieval results. Console logs are an unsuitable website
contract: their format is unstructured, detailed RAG logs are suppressed in the
web process, and they include material unrelated to a visitor's search flow.
Stage timings and HTTP-request-specific usage totals also need instrumentation.

## Solution

Show an ordered live search flow beside the existing answer experience. Every
stage has a plain-language explanation, a status, and expandable details. Stage
updates arrive during processing; the full answer appears after generation and
the existing citation reference check. Visitors can inspect retrieved passages,
rankings, reranking reasons, durations, model usage, and estimated costs.

Preserve completed work when a later stage fails. Explain deadlines and lost
connections without claiming that underlying processing has stopped. Keep the
flow in the current page only. The legacy JSON question endpoint and existing
answer text remain compatible.

### Agreed product scope

The user confirmed visitor-facing stage updates; expandable stage results;
durations, model names, calls, tokens, and estimated costs; retained partial
results after failure; manual retries; whole-answer delivery; and no saved
history or page-reload recovery. The user also accepted HTTP-boundary tests with
mocked model calls and a frontend/proxy streaming test.

The transport and field definitions below are engineering decisions that make
those requirements implementable across the two repositories.

## User Stories

1. As a visitor, I want to see all search stages when I submit a question, so
   that I understand the work involved.
2. As a visitor, I want the active stage to update while processing continues,
   so that I can tell the request is progressing.
3. As a visitor, I want a short explanation of each stage, so that I can follow
   the flow without knowing retrieval terminology.
4. As a visitor, I want to inspect the rewritten search query and source filter,
   so that I can understand how my question was interpreted.
5. As a visitor, I want to see which model embeds the query, so that I understand
   the semantic search preparation.
6. As a visitor, I want semantic-search passages and their ranks and scores,
   so that I can inspect semantic matches.
7. As a visitor, I want keyword-search passages and their ranks and scores,
   so that I can inspect keyword matches.
8. As a visitor, I want to inspect the combined ranking and contributing ranks,
   so that I can understand how both searches influence passage selection.
9. As a visitor, I want reranking progress per passage, so that a sequence of
   model requests has visible progress.
10. As a visitor, I want the final reranking scores and relevance reasons, so
    that I can understand the selected passage order.
11. As a visitor, I want to expand a passage to read its text and reference,
    so that I can inspect the context available to answer generation.
12. As a visitor, I want the answer with its existing citations and warnings,
    so that the new experience preserves current answer behavior.
13. As a visitor, I want citation reference checking described accurately,
    so that I do not confuse it with factual verification.
14. As a visitor, I want per-stage and overall durations, so that I can see where
    processing time was spent.
15. As a visitor, I want model names and application-level call counts,
    so that I can understand which stages use models.
16. As a visitor, I want available token usage and estimated costs,
    so that I can understand the resources used by my question.
17. As a visitor, I want incomplete usage and cost to be labeled unknown,
    so that missing data is not presented as free usage.
18. As a visitor, I want completed stages to remain inspectable after failure,
    so that I retain useful information from the attempt.
19. As a visitor, I want to distinguish failure, timeout, and lost connection,
    so that I understand what is known about the outcome.
20. As a visitor, I want a deliberate retry without automatic resubmission,
    so that a connection problem does not silently repeat model work.
21. As a keyboard or screen-reader user, I want accessible stage controls and
    concise progress announcements, so that I can follow the same flow.
22. As an existing API consumer, I want the JSON endpoint unchanged,
    so that introducing live progress does not break my integration.
23. As a frontend implementer, I want a stable event contract and failure rules,
    so that I can implement the website in its own repository.
24. As an operator, I want request-correlated cost records and sanitized request
    outcomes, so that I can investigate runs without logging visitor passages.

## Implementation Decisions

### 1. Stage model and visitor-visible data

Use these stable stage IDs and this execution order. The existing sequential
pipeline is preserved; this feature does not parallelize retrieval or reranking.

| Order / ID | UI label and purpose | Completion detail fields |
| --- | --- | --- |
| 1. `plan_query` | Plan query: interpret the question for retrieval. | `search_query` string; `source_file_filter` string or null. |
| 2. `embed_query` | Embed query: represent the search query for semantic matching. | `model` string; `dimensions` positive integer. No embedding vector. |
| 3. `semantic_search` | Semantic search: find passages with similar meaning. | `results`: up to 30 semantic ranking records. |
| 4. `keyword_search` | Keyword search: find passages using query terms. | `results`: up to 30 keyword ranking records. |
| 5. `combine_rankings` | Combine rankings: merge semantic and keyword rankings using RRF. | `rrf_k` (60); `results`: up to ten fusion ranking records. |
| 6. `rerank_evidence` | Rerank evidence: evaluate candidate passages against the original question. | `results`: final ordered reranking records; progress fields described below. |
| 7. `generate_answer` | Generate answer: answer the original question using the reranked passages. | `context_references`: ordered array of passage reference strings. |
| 8. `check_citations` | Check citation references: compare answer references with retrieved context. | `outcome`: `valid`, `warning`, or `no_citations`; `checked_references` and `invalid_references`: arrays of strings. |

Every stage also exposes the metrics defined below. The server supplies the
ordered stage IDs on admission; the frontend owns the labels and explanations.
Source filters and the planned query reflect values actually used by retrieval.
An invalid model-created plan fails planning; it is not reported as completed.

There is no second rewrite stage or extra rewrite model call. Document loading,
document embedding, and index preparation happen at server startup and are not
per-question stages. Corpus/index initialization failures retain the existing
readiness behavior.

#### Passage and ranking records

All returned passage records contain `source` (filename), `chunk_index`
(zero-based integer), `reference` (the existing printable citation key), and
`text` (full text of that chunk). UI lists show a compact excerpt and allow the
full chunk to be expanded. Return only fields appropriate to the ranking:

| Ranking | Additional fields |
| --- | --- |
| Semantic | `rank` (one-based integer), `similarity` (finite number). |
| Keyword | `rank` (one-based integer), `bm25_score` (finite number). |
| Fusion | `rank`, `rrf_score` (finite number), `faiss_rank` and `bm25_rank` (one-based integer or null). |
| Reranking | `rank`, `rerank_score` (0–1), `reason` (string), `rrf_score`, `faiss_rank`, `bm25_rank`. |

Arrays retain actual pipeline order, including existing tie behavior. Rank
positions in fusion refer to the full eligible base rankings; a source rank can
exceed the 30 records exposed for inspection. Fusion still uses the full eligible
rankings before selecting candidates. Presentation bounds must not change the
search or answer context. Return native Python numbers as finite JSON numbers;
never serialize vectors or arbitrary object dictionaries.

Treat the reference as passage identity within a run. A retrieved passage is an
evidence candidate, not a guarantee that it is cited or proves the answer. Scores
from different methods are not directly comparable or accuracy percentages.

Reranking emits a progress update after each successfully validated candidate:
`completed` (integer), `total` (integer), and `result` (passage plus rerank score,
reason, and fusion metadata, without a final rank). Progress results are in
evaluation order. Only the completion array establishes final rerank order.
Retain already evaluated candidates if a later candidate fails. Use the actual
candidate count rather than hardcoding ten in the UI.

Citation outcome `valid` means at least one citation was found and none was
outside retrieved context. `no_citations` is informational, not a new error.
Warnings remain successful answer content. Derive structured citation results
from the existing check rather than parsing its appended warning or introducing
a second validator. The final answer string must stay unchanged.

### 2. Additive HTTP transport

Keep `POST /ask` and its existing JSON success/error shapes unchanged. Add
`POST /ask/stream` with the same strict request object: only a string `question`,
nonblank and at most 1,000 characters. Both endpoints use the same pipeline,
single active-work slot, rate allowance, trusted-proxy identity rules, and
configured overall response deadline.

The website calls its same-origin server proxy. That proxy forwards the request
to the backend streaming route and streams the response to the browser. Its
public route spelling is an FE-repository integration detail; it must be mapped
and documented there without changing this backend contract.

After admission, respond with HTTP 200 and `Content-Type: text/event-stream`
using UTF-8 SSE framing. The browser uses Fetch with POST and incrementally reads
the body. Use `Cache-Control: no-cache, no-transform`, preserve `X-Request-ID`,
avoid a fixed Content-Length, and disable response buffering/transforms on this
route throughout the deployed proxy path. Send a comment heartbeat at least
every 15 seconds while no application event is available. Heartbeats do not
represent stage progress or reset the deadline.

Use one POST connection for one run. There is no separate job-creation call,
polling route, event replay store, or automatic reconnect/resubmission. Native
EventSource is not the client interface for this POST/body contract. SSE defines
the event framing; Fetch provides the request body and streamed consumption.

### 3. Event contract, version 1

Each application event has an SSE `event` field equal to its type, an SSE `id`
equal to its sequence number, and a JSON `data` object with these common fields.
The blank-line SSE delimiter terminates the event. Heartbeat comments have no
JSON envelope or sequence number.

| Field | Type / meaning |
| --- | --- |
| `schema_version` | Integer `1`. |
| `request_id` | Server-generated UUID string; matches the HTTP header and ledger correlation. |
| `sequence` | Integer starting at 1; contiguous and strictly increasing for application events in this run. |
| `type` | Event name from the table below. |
| `timestamp_utc` | UTC ISO 8601 timestamp. |
| `elapsed_ms` | Nonnegative monotonic elapsed time since run admission; milliseconds. |
| `stage_id` | Stable stage ID for a stage event; null for a run event. |
| `data` | Type-specific object defined below. |

| Event | Required `data` fields and meaning |
| --- | --- |
| `run.started` | `stage_ids` (the ordered eight IDs). First event; initializes pending stages. |
| `stage.started` | Empty object. Marks that stage running before its work starts. |
| `stage.progress` | Reranking's `completed`, `total`, and `result` fields. Other stages do not emit synthetic progress. |
| `stage.completed` | `details` (stage completion object defined above) and `metrics` (stage metrics). |
| `stage.failed` | `error` (sanitized code/message) and `metrics` for the failed stage. Emitted only for an actual observed stage failure. |
| `run.completed` | `answer` (the full existing answer string), `metrics` (run metrics), and `stages` (final stage snapshots). Successful terminal event. |
| `run.failed` | `error`, `http_equivalent_status` (integer), `processing_may_continue` (boolean), `metrics`, and `stages`. Failed terminal event. |

`error` contains only `code` and a fixed public `message`, following existing
public error vocabulary. A stage snapshot contains `stage_id`, `status`,
`details` (object or null), `progress` (latest rerank progress or null),
`metrics` (latest available metrics or null), and `error` (object or null).
For incomplete reranking, snapshot `details` preserves `evaluated_results` in
evaluation order, including on failure or timeout; completed reranking uses the
final ordered `results` array. Other incomplete stages have null details unless
a defined result was already produced.

Stage status is one of `pending`, `running`, `completed`, `failed`, `skipped`,
or `unknown`. Normal transitions are pending → running → completed/failed.
After a true failure, subsequent pending stages are skipped. If observation ends
while processing may continue, unfinished stages become unknown in the terminal
snapshot; this does not claim the actual worker has failed or skipped them.

On a healthy connection there is exactly one terminal event, and no application
events follow it. Snapshots agree with earlier events and do not replace live
delivery. Each started stage emits its start before executing the operation;
completion follows successful operation and output validation. Each successful
stage completes before the next begins. A successfully delivered terminal event
is required for the browser to consider the run complete.

Publish the answer only in `run.completed`, after citation checking. Do not emit
raw generation output as an earlier answer or stream answer tokens. Unknown
additive fields are ignored by clients; unknown event types within version 1
are ignored after checking the common envelope and sequence. Invalid framing,
invalid required fields, gaps/conflicting sequences, or an unsupported schema
version end observation with an explicit connection/protocol error. No automatic
retry is allowed. Clients must not assume a network read contains one full event.

### 4. Timing, model usage, and cost

Stage and run metric objects use the following fields:

| Field | Meaning |
| --- | --- |
| `duration_ms` | Nonnegative monotonic duration. On failure, time observed so far. Run time is not a sum of rounded stage durations. |
| `model_calls` | Application-level calls completed with a response or exception and recorded by the model wrapper. Provider-internal retries are not separate calls. |
| `models` | Unique requested model names used in recorded calls. |
| `tokens` | Object containing `input_tokens`, `cached_input_tokens`, `cache_write_tokens`, `output_tokens`, and `reasoning_tokens`; each a nonnegative integer or null. |
| `known_cost_usd` | Decimal string: sum of priceable calls under the configured rates. |
| `unknown_cost_calls` | Number of recorded calls with unpriceable usage or unknown rates. |
| `cost_complete` | True exactly when all recorded calls have priceable usage. |
| `price_dates` | Unique rate-date strings used for those estimates. |

Use zero for token categories that do not apply to a call. Use null for missing
applicable usage. An aggregate category is null if any recorded applicable call
has missing usage; otherwise sum it. Categories already contained in another
category must not be counted twice: reasoning tokens are included in output,
and cached/cache-write tokens are parts of input.

Pure retrieval/fusion/check stages report zero model calls, zero tokens, zero
known cost, complete cost, and empty model/rate-date arrays. Do not infer token
usage from text length. Keep the existing rules for missing usage, rates, and
API failures. Known costs are estimates, not billing assertions. Display the
known subtotal plus an unknown-cost indicator when incomplete, never a false
complete total or a zero-dollar approximation caused by coarse rounding.

An in-flight provider call is not yet recorded. On timeout, metrics are an
observed snapshot and cannot imply final totals even if `cost_complete` is true
for the calls already recorded. The run failure's `processing_may_continue`
governs that distinction. Do not count a pending call as known free work.

Create one request-scoped usage accumulator for each accepted web question,
including legacy JSON questions. Correlate ledger records by adding
`request_id`; use the same UUID as that web run's `run_id` and use run name `ask`.
The scope must follow worker execution, including work that finishes after the
HTTP observer times out or disconnects. Exclude server-startup embeddings and
other questions. Preserve CLI/evaluation accounting and existing ledger fields.
Read usage from the existing model-call instrumentation rather than rereading
the ledger. Ledger-write failure must not prevent in-memory metrics or search.

### 5. Failures, admission controls, and resource lifecycle

Validate the request and reserve the shared work slot before committing the
stream response. Pre-stream failures retain the existing JSON error envelope
and HTTP status: invalid question 422, allowance exhausted 429, not ready/busy
503, and unexpected admission failure 500. There are no run events for a request
that is not admitted. Rate-limit accounting follows existing behavior and is
shared across both routes: ten submissions per client IP per ten-minute window,
including invalid/busy attempts; do not grant separate allowances per route.

After HTTP 200 headers have been sent, a failure is reported in the event stream,
not by changing the HTTP status. Existing error codes map to
`http_equivalent_status`: `upstream_error` 502, `internal_error` 500, and
`response_timeout` 504. Model-output validation failures retain the current
upstream-failure classification. An actual stage failure emits `stage.failed`
and then `run.failed`, preserving prior results and marking later stages skipped.

The configured response deadline starts at admission and does not restart per
stage, progress event, or heartbeat. On deadline, send `run.failed` if writable,
with `response_timeout`, `processing_may_continue` true when the worker still
runs, completed-stage results, and unknown status for unfinished stages. Do not
manufacture a stage failure or claim cancellation of synchronous work. Close the
HTTP observation; retain the admission slot until the real worker finishes.

On browser/proxy disconnect, retain only the completed results already received
by the browser. It displays an interrupted flow and unknown unfinished stages.
The worker may continue and must retain its slot and usage scope. Stop retaining
or queueing events for the detached observer; discard later events. Observe the
eventual task exception and release the slot when actual work ends. Stream
cleanup must not cancel or lose track of the worker. Server shutdown retains
the existing wait-for-active-work semantics.

The synchronous pipeline remains off the event loop. Bridge events from the
worker with thread-safe delivery; do not mutate an async queue directly from
the worker thread. Bound a run's queued application events to 64, with at most
one progress event per evaluated candidate. Heartbeats are generated by the
stream consumer and are not queued. Never let an absent/slow consumer block the
worker indefinitely; if the bound is exhausted, detach observation and close the
stream, letting the client treat missing terminal delivery as interruption.
On terminal observation, atomically freeze the terminal snapshot and detach its
event sink; later worker activity must not mutate that snapshot or emit more
events to it. Use immutable serialized snapshots so later chunk mutations do not
alter already published events. There is no durable trace store.

Keep one sanitized operational request log per HTTP request. For admitted
streams, retain the actual transport status and add `stream_outcome`
(`completed`, `failed`, `timeout`, or `disconnected`) and `failure_code` when
known. Keep request ID and elapsed milliseconds. HTTP 200 alone does not mean
the stream succeeded. Preserve prompt/context/provider-log suppression. Event
bodies, visitor questions, passage text, and raw exceptions are not added to
operational logs or the cost ledger.

### 6. Frontend and proxy responsibilities

Show all eight stages after `run.started`. Each row has an accessible expandable
control, a plain-language label, a short explanation, and textual status. Use
pending, running, completed, failed, skipped, and unavailable/unknown states;
status must not rely on color alone. Preserve the visitor's expansion choices
during updates. Announce stage changes concisely without repeatedly reading all
passages. Support keyboard interaction, narrow screens, and reduced motion.

Start progress when actual events arrive. A local running timer may update the
display, but server metrics are authoritative. Do not invent completed steps,
percentages for stages with no counts, or fixed delays to animate fast stages.
Keep rapid completed stages inspectable even if several arrive in one read.

Expanded rows present their defined details and metrics. Label ranks and scores
by retrieval method. Treat passages, rewritten queries, model reasons, and
answers as untrusted display content; use escaped text or the website's safe
Markdown rendering. Do not insert returned strings as executable HTML. Keep
the existing answer presentation and inline citations; display citation warnings
without converting the run into a failure.

The Fetch reader incrementally decodes UTF-8 and parses SSE frames across
arbitrary read boundaries, including split multibyte characters, combined
events, CRLF/LF line endings, and heartbeat comments. Check HTTP status and
content type before parsing. Non-200 JSON admission errors use the existing
error UI. Stop reading after the terminal event. EOF without a terminal event,
transport errors, and malformed protocol data preserve received results but
show interruption rather than success.

Disable duplicate submission while the current run is observed. After a terminal
failure or interruption, offer manual retry; if the backend is still busy, show
its 503 response without a retry loop. A retry is a fresh submission with a new
request ID and normal rate accounting. Retain the previous attempt's details
until the visitor explicitly starts the new attempt, then replace them. Reload
or leaving the page discards local state; no local/session storage, cross-tab
history, replay, or reconnect is introduced.

The proxy must forward the POST body without changing question content, preserve
request IDs and pre-stream JSON errors, and pass stream chunks promptly without
calling a whole-body JSON/text reader. Disable buffering/caching and prevent
compression or other transformations that delay event delivery. Preserve the
existing trusted visitor-address handling and backend access boundary. Forward
downstream disconnects where supported; the backend remains robust if the proxy
does not propagate them promptly.

Verify the actual website runtime and every deployed proxy hop support streaming
for at least the backend response deadline plus terminal-delivery margin. A
shorter upstream/platform timeout or buffered proxy is an integration blocker,
not evidence that the backend stage events work end to end. Do not weaken the
backend deadline or access boundary to work around an unverified proxy.

### 7. Module boundaries and delivery

The shared search pipeline owns stage boundaries and typed public detail
snapshots. Retrieval and reranking expose actual intermediate results/progress;
generation and citation checking expose their existing results. Optional
observation must preserve existing return values and behavior for CLI, library,
evaluation, and legacy web callers. Do not duplicate ranking logic in the HTTP
adapter or scrape console output.

The web adapter owns admission, request correlation, live transport, worker
observation, public failure mapping, and the streaming response. Cost accounting
owns per-call usage and request aggregates. Keep the public event serializer an
explicit allowlist; it must not expose embedding vectors or arbitrary model
response objects. Do not add model requests solely for explaining stages.

The frontend repository owns the public proxy route, incremental stream reader,
timeline rendering, error/retry experience, and browser integration tests. Deliver
shared version-1 protocol examples/fixtures with backend implementation so both
repositories validate the same messages. Additive fields remain compatible;
breaking field/type/semantic changes require a new schema version coordinated
across repositories.

Deploy the additive backend capability first, then verify proxy delivery and
enable the frontend flow. Legacy JSON clients remain usable. Frontend rollback
can restore the existing `/ask` experience without a backend rollback. Do not
automatically fall back to a second JSON model run after an admitted stream fails.

## Testing Decisions

The main acceptance seam is the existing HTTP application boundary with mocked
model providers and temporary cache/ledger state. Exercise public responses,
events, passage data, usage, and lifecycle behavior rather than private helper
call order. Reuse existing web tests' pipeline substitution and provider fakes,
request-control tests, and cost tests' temporary ledger fixtures.

The streaming visibility check uses a real loopback HTTP connection with a
deterministically blocked mocked provider: receive stage events while generation
is still blocked, then release it and receive the answer. A test client that
buffers the complete response cannot establish this requirement. Avoid paid
models and timing assertions based only on arbitrary sleeps.

| Acceptance check | Required observable result |
| --- | --- |
| Happy path | Eight stages in actual order; plan reused; all stage details match mocked pipeline results; exactly one terminal answer. |
| Live delivery | `run.started` and an active stage reach the HTTP consumer before the blocked provider finishes. |
| Reranking | One progress event per validated candidate, actual total, final sorted ranking, and retained successful candidates on later failure. |
| Retrieval fidelity | Native scores/ranks/references/text preserved; full-ranking fusion unaffected by bounded inspection arrays; no vectors or extra model calls. |
| Answer fidelity | Final string matches legacy behavior, including insufficient-evidence content and appended citation warnings. |
| Citation outcomes | Valid, unknown-reference warning, and no-citation answers produce the defined structured outcome without factual-verification claims. |
| Usage | Per-stage/run totals agree with mocked responses and request-correlated ledger records; missing data stays unknown; no cross-request/startup leakage. |
| Usage failure | A response followed by output-validation failure retains recorded usage; ledger write failure does not prevent in-memory metrics. |
| Partial failure | Completed stage data retained; failed stage marked; later stages skipped; sanitized terminal error with correct equivalent status. |
| Admission | Invalid input, shared allowance, not-ready/busy status, trusted-proxy identity, and header/body request-ID agreement work on both routes. |
| Deadline | Terminal timeout while worker blocked; unfinished states unknown; slot remains busy until actual worker completes. |
| Disconnect/slow consumer | No automatic resubmit; observer detaches without deadlock/unbounded buffering; task exception observed and eventual slot release. |
| Observability | One sanitized HTTP log with actual status and stream outcome; no new prompt/context/error-detail leakage. |
| Regression | Existing `/ask`, health, CLI, evaluation, retrieval, and cost behavior remains intact under relevant existing checks. |
| FE parser | Split UTF-8/frames, combined frames, CRLF/LF, comments, unknown additive fields/events, invalid schema/sequence, JSON admission errors, and early EOF behave correctly. |
| FE presentation | Live rows, expandable details, native score labels, usage unknowns, retained partial results, manual retry, and accessible controls work. |
| Deployed proxy path | A delayed mocked/test stream reaches the browser through the actual proxy before its terminal event; buffering and deadline settings verified. |

## Out of Scope

- Answer-token streaming or changing answer content, prompts, models, retrieval
  parameters, ranking logic, citation policy, or pipeline concurrency.
- Raw console/provider-log feeds, prompt dumps, embedding vectors, stack traces,
  or provider-response objects in visitor output.
- New user settings, authentication, accounts, source-document downloads, or
  a new factual-verification/answerability classifier.
- Saved searches, durable trace storage, event replay, reload recovery,
  automatic reconnect/resubmission, job queues, or cancellation guarantees.
- Streaming server-startup ingestion/index preparation as visitor search stages.
- Changes to cloud infrastructure or frontend deployment in this specification
  task. Implementation is separate from this documentation deliverable.

## Further Notes

### Frontend handoff and remaining environment verification

Take this spec and the [frontend handoff](frontend-handoff.md) to the website
repository together. The handoff summarizes FE work; this specification is the
source of truth for contract fields and semantics. Discovery is retained in
[the decision record](discovery.md).

The FE repository has not been inspected for this task. Before frontend
implementation, identify the actual question UI, same-origin proxy route,
runtime streaming support, timeout/buffering controls, and existing browser-test
setup. These are environment facts to verify there, not unmade product choices.
Backend completion alone does not establish browser-visible streaming.

### Current implementation references

- [CLI/logging inventory](../../docs/search-cli.md)
- [Existing API contract and controls](../../docs/web-api.md)
- [Original API scope and deferred progress work](../../docs/fastapi-service-plan.md)
- [Search orchestration](../../src/nasa_rag/search.py)
- [Retrieval orchestration](../../src/nasa_rag/retrieval/retriever.py)
- [Reranking](../../src/nasa_rag/retrieval/reranker.py)
- [Generation and citation check](../../src/nasa_rag/generation/generator.py)
- [Model usage ledger](../../src/nasa_rag/model_costs.py)
- [Web adapter](../../src/nasa_rag/web.py)
- [HTTP contract tests](../../tests/test_web.py)
- [Model cost tests](../../tests/test_model_costs.py)

### Primary transport references

Checked 2026-11-06. SSE framing, UTF-8 decoding, named events, blank-line dispatch,
and comment heartbeats follow the
[HTML event-stream specification](https://html.spec.whatwg.org/multipage/server-sent-events.html).
The POST client and incremental response reading use the
[Fetch API](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch#streaming_the_response_body).
The backend can stream an iterator/generator through
[Starlette StreamingResponse](https://starlette.dev/responses/#streamingresponse).
The event names, schema, lifecycle, and proxy requirements above are this
feature's engineering contract, rather than requirements imposed by SSE.

## Comments

- 2026-11-06: User confirmed visitor-facing search stages, live updates, and
  combined backend/frontend requirements, with FE implementation transferred to
  the FE repository.
- 2026-11-06: User accepted all five detail decisions: expandable stage output,
  timing/usage/cost, preserved partial results, whole-answer delivery, and
  current-page-only state.
- 2026-11-06: User accepted the proposed HTTP/proxy acceptance-test boundaries.
