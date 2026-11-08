# 01: Stream a question's live search stages

**What to build:** Let an HTTP consumer submit one question and observe the real
eight-stage search flow while it runs, followed by the existing full answer.
Deliver the first usable backend streaming path without changing the legacy JSON
question endpoint or adding model work.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

**Specification:** [PRD/TRD](../spec.md), especially stage order, additive HTTP
transport, event contract, and shared admission controls.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [ ] Add `POST /ask/stream` with the existing strict question request: only a
  nonblank string `question` of at most 1,000 characters. Legacy `POST /ask`
  and health responses, errors, and answer strings remain compatible.
- [ ] Both question routes share the single active-work slot, submission
  allowance, trusted-proxy identity rules, and configured response deadline.
  Reject invalid, not-ready, busy, and rate-limited requests before committing
  streaming headers, with the existing JSON error envelope and HTTP statuses.
- [ ] Accepted streams use SSE framing, UTF-8 `text/event-stream`, the specified
  cache-control behavior, and `X-Request-ID`. All application events have the
  version-1 envelope, matching request ID, contiguous sequence, and actual
  timestamp/monotonic elapsed time. Heartbeat comments are sent during idle
  periods at the specified interval and do not reset the deadline.
- [ ] Emit `run.started` and actual start/completion events for planning,
  embedding, semantic search, keyword search, fusion, reranking, generation,
  and the citation reference check. Stage starts precede their operations;
  completions follow successful validation. Do not synthesize progress or
  include server-startup ingestion as question stages.
- [ ] Preserve the existing pipeline and return values for unobserved callers.
  Introduce the smallest optional observation seam needed for actual stage
  boundaries. Reuse the planner's query without a second rewrite, and preserve
  existing ranking order, model calls, and answer content.
- [ ] Keep synchronous work off the event loop and bridge worker events safely.
  Establish bounded, detachable observation and keep track of actual worker
  completion; introducing the route must not allow concurrent searches after
  the HTTP consumer stops waiting. Ticket 05 completes the detailed failure
  snapshots and interruption cases.
- [ ] End successful observation with exactly one `run.completed` containing the
  unchanged answer after citation checking. Keep provider/model exceptions
  sanitized; report observed in-stream failures with a terminal `run.failed`
  rather than trying to replace already-sent HTTP status headers.
- [ ] A real loopback HTTP test with a deterministically blocked mocked provider
  receives a stage event before releasing the provider, then receives the final
  answer. A fully buffered response test alone does not satisfy live delivery.
- [ ] Focused mocked HTTP tests verify admission, stage order, request IDs,
  framing, terminal behavior, heartbeat delivery, no extra model calls, and
  legacy JSON compatibility. Do not use paid models or sleep-only timing proofs.

## Slice boundary

This slice establishes live lifecycle delivery. Ticket 02 completes planning and
retrieval detail payloads, 03 adds per-candidate reranking and structured citation
results, and 04 completes model-usage metrics. Do not fill unfinished fields with
fabricated values or present this intermediate implementation as the complete
version-1 frontend contract. Each later slice extends this same real pipeline.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
