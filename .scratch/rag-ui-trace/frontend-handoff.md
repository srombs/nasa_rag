# Frontend handoff: live RAG search flow

Recorded: 2026-11-06
Companion document: [Combined PRD/TRD](spec.md)

Copy this document and `spec.md` into the frontend repository together. The
combined specification is the authoritative version-1 contract; this document
identifies FE work and the integration checks required there. Backend streaming
is proposed by that specification and is not implemented by these documents.

## Visitor experience

After a visitor submits a NASA question, show a compact live timeline with eight
expandable stages:

1. Plan query.
2. Embed query.
3. Semantic search.
4. Keyword search.
5. Combine rankings.
6. Rerank evidence.
7. Generate answer.
8. Check citation references.

Rows explain the step, show its status, and expose available results on
expansion. Details include the rewritten query/source restriction, retrieved
passages and native scores/ranks, fusion ranks, reranking reasons, model usage,
stage durations, and estimated costs. During reranking, show actual progress
such as "4 of 10 passages evaluated". The full answer appears once the run
completes; answer-token streaming is outside this version.

The citation reference check compares references with retrieved context. Do not
label it factual verification. Retrieved passages are evidence candidates, not
a guarantee that the answer cites or proves a claim from each one.

## Backend contract to consume

- Additive backend route: `POST /ask/stream` through the website's same-origin
  server proxy. Keep the existing JSON `/ask` path available.
- Request: the existing object containing only `question`, a nonblank string
  of at most 1,000 characters.
- Accepted response: HTTP 200, `text/event-stream`, UTF-8, `X-Request-ID`.
- Rejected requests: the existing non-200 JSON request/error envelope.
- Events: `run.started`, `stage.started`, `stage.progress`, `stage.completed`,
  `stage.failed`, `run.completed`, and `run.failed`.
- Every application event includes schema version 1, request ID, sequence,
  type, UTC timestamp, elapsed milliseconds, stage ID or null, and type-specific
  data. Heartbeats are SSE comments.
- Stable stage IDs, payload fields, passage records, metrics, state rules, and
  error semantics are defined under Implementation Decisions in the combined
  specification. Do not invent FE-specific versions of those fields.
- Success is the `run.completed` event with the final unchanged answer;
  HTTP 200 or end-of-stream alone is insufficient.
- `run.failed` is terminal even though the HTTP transport already has status
  200. It carries a sanitized error, equivalent HTTP status, partial snapshots,
  metrics, and whether backend processing may continue.

## Stream reader and proxy

Use Fetch with POST and incrementally read the response body. Parse SSE events
across arbitrary network chunks, including split multibyte UTF-8 characters,
multiple events per read, partial events, CRLF/LF delimiters, and comment
heartbeats. Respect the shared version/sequence rules. Do not use a whole-body
JSON/text reader or an automatically reconnecting EventSource connection.

The server proxy must pass chunks promptly, preserve request IDs and JSON
admission errors, disable buffering/caching and delaying transformations, and
preserve existing visitor-address trust and backend access controls. It must
support the configured backend response deadline plus terminal-delivery margin.
Forward downstream disconnects where supported. Do not automatically retry a
POST or start a fallback JSON search after admission.

Before implementation, locate and verify in the FE repository:

- The current NASA question form, answer renderer, and error/retry UI.
- The actual same-origin proxy route and backend mapping.
- The proxy/runtime's streaming, buffering, compression, timeout, and disconnect
  behavior across the deployed path.
- Existing browser tests and safe Markdown/text rendering.

Those files and hosting facts have not been inspected in the backend repository.

## State and presentation

- Build all stage rows from `run.started` and render actual event progression.
  Do not simulate work or hide fast completed stages.
- Preserve expansion state while results update; keep passage lists compact and
  allow full chunk text to be read on expansion.
- Label each ranking method and its own score. Do not present scores as answer
  accuracy percentages or compare unlike scores on one numeric scale.
- Distinguish pending, running, completed, failed, skipped, and unknown states
  using text as well as appearance. A locally interrupted connection cannot
  establish that unfinished backend work failed or stopped.
- Use authoritative server metrics; an optional local active-stage timer is
  only a running display. Label costs as estimates, show unknown data explicitly,
  and distinguish a known cost subtotal from an incomplete total.
- Preserve the existing answer rendering, citations, insufficient-evidence
  answers, and appended citation warnings. Escape passage/query/reason content
  or use the existing safe renderer.
- Make expansions keyboard-accessible, announce stage changes concisely, and
  support narrow screens and reduced motion.

## Failure, retry, and retention

Preserve received results when a later stage fails. A true failure marks that
stage failed and later work skipped. A deadline can leave actual processing
running; explain that completed data is retained while unfinished status and
final cost remain unknown. EOF without a terminal event, malformed protocol,
or a lost connection shows an interrupted flow with retained received results.

Disable duplicate submission during the active observation. Offer a manual
retry after failure/interruption; a busy response remains visible and does not
trigger polling or automatic resubmission. Starting the new attempt replaces the
previous attempt's flow and gets a new backend request ID. Until that explicit
action, retain the previous attempt's details.

State exists only in the current page. Navigation/reload discards it. There is
no saved history, browser-storage persistence, event replay, or automatic
reconnect. Aborting the browser reader does not guarantee cancellation of model
work.

## FE acceptance checks

1. Through the real proxy path, an intentionally delayed test stream displays
   a stage before its terminal answer. Verify this incrementally, not by looking
   only at the completed response body.
2. The reader handles split/combined frames, split UTF-8, line endings,
   heartbeats, unknown additive fields/events, malformed protocol, unsupported
   version, and EOF without a terminal event.
3. All eight stages, expanded details, reranking progress, native rankings,
   passage text, durations, unknown usage/cost, and citation outcomes render.
4. Pre-stream JSON rejection, in-stream model failure, timeout with continued
   processing, and lost connection retain the correct UI state and partial data.
5. No failure path silently creates another search. A manual retry handles busy
   responses and uses a fresh request ID.
6. Accessible controls, safe content rendering, narrow-screen layout, and the
   existing answer/citation presentation continue to work.
7. Navigation/reload clears flow state, and restoring the legacy JSON UI remains
   a viable frontend rollback.

Use shared protocol fixtures delivered with backend implementation. Enable the
new UI after additive backend deployment and a successful incremental delivery
check through the deployed proxy. A buffering or too-short-lived proxy must be
resolved before claiming live progress is shipped.
