# 01: Stream a question's live search stages

**What to build:** Let an HTTP consumer submit one question and observe the real
eight-stage search flow while it runs, followed by the existing full answer.
Deliver the first usable backend streaming path without changing the legacy JSON
question endpoint or adding model work.

**Blocked by:** None (can start immediately).

**Status:** resolved

**Specification:** [PRD/TRD](../spec.md), especially stage order, additive HTTP
transport, event contract, and shared admission controls.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [x] Add `POST /ask/stream` with the existing strict question request: only a
  nonblank string `question` of at most 1,000 characters. Legacy `POST /ask`
  and health responses, errors, and answer strings remain compatible.
- [x] Both question routes share the single active-work slot, submission
  allowance, trusted-proxy identity rules, and configured response deadline.
  Reject invalid, not-ready, busy, and rate-limited requests before committing
  streaming headers, with the existing JSON error envelope and HTTP statuses.
- [x] Accepted streams use SSE framing, UTF-8 `text/event-stream`, the specified
  cache-control behavior, and `X-Request-ID`. All application events have the
  version-1 envelope, matching request ID, contiguous sequence, and actual
  timestamp/monotonic elapsed time. Heartbeat comments are sent during idle
  periods at the specified interval and do not reset the deadline.
- [x] Emit `run.started` and actual start/completion events for planning,
  embedding, semantic search, keyword search, fusion, reranking, generation,
  and the citation reference check. Stage starts precede their operations;
  completions follow successful validation. Do not synthesize progress or
  include server-startup ingestion as question stages.
- [x] Preserve the existing pipeline and return values for unobserved callers.
  Introduce the smallest optional observation seam needed for actual stage
  boundaries. Reuse the planner's query without a second rewrite, and preserve
  existing ranking order, model calls, and answer content.
- [x] Keep synchronous work off the event loop and bridge worker events safely.
  Establish bounded, detachable observation and keep track of actual worker
  completion; introducing the route must not allow concurrent searches after
  the HTTP consumer stops waiting. Ticket 05 completes the detailed failure
  snapshots and interruption cases.
- [x] End successful observation with exactly one `run.completed` containing the
  unchanged answer after citation checking. Keep provider/model exceptions
  sanitized; report observed in-stream failures with a terminal `run.failed`
  rather than trying to replace already-sent HTTP status headers.
- [x] A real loopback HTTP test with a deterministically blocked mocked provider
  receives a stage event before releasing the provider, then receives the final
  answer. A fully buffered response test alone does not satisfy live delivery.
- [x] Focused mocked HTTP tests verify admission, stage order, request IDs,
  framing, terminal behavior, heartbeat delivery, no extra model calls, and
  legacy JSON compatibility. Do not use paid models or sleep-only timing proofs.

## Slice boundary

This slice establishes live lifecycle delivery. Ticket 02 completes planning and
retrieval detail payloads, 03 adds per-candidate reranking and structured citation
results, and 04 completes model-usage metrics. Do not fill unfinished fields with
fabricated values or present this intermediate implementation as the complete
version-1 frontend contract. Each later slice extends this same real pipeline.

## Answer

Implemented `POST /ask/stream` with real lifecycle observation of all eight
stages, shared admission controls, SSE envelopes/heartbeats, measured durations,
sanitized terminal failures, and bounded detachable observation. The actual
worker retains its slot after observation ends. Existing `/ask` answers and
pipeline ranking/model calls are preserved. See
[development-slice API documentation](../../../docs/web-api.md#live-search-stages-development-slice).

Completion `details` are empty objects and `metrics` contains only measured
`duration_ms` in this slice. Tickets 02–04 add the remaining payloads and usage;
05 completes detailed interruption snapshots and failure cases. The full
version-1 frontend contract remains development-only through ticket 06.

Verification (mocked providers only):

- `.venv/bin/python -m pytest -q` (after installing the locked web/dev/profile
  environment with `uv run --locked --extra web --extra dev --extra profile`):
  **162 passed**, including an actual loopback TCP stream received while
  generation was held by a test event, then released for final-answer delivery.
- Focused HTTP checks cover strict admission, shared IP allowances/proxy trust,
  stage order, framing/IDs, heartbeat delivery, provider-output validation,
  sanitized failures, response deadlines, cancellation/disconnect, slot ownership,
  unchanged answers, and no additional model calls.
- Ruff checks on all changed Python files: **passed**.
- mypy on `search_flow.py`, `web_stream.py`, `web.py`, and
  `retrieval/faiss_retriever.py`, with existing
  `--follow-imports=silent --ignore-missing-imports --check-untyped-defs` flags:
  **passed**; `git diff --check`: **passed**.

Standards review: **0 hard violations, 0 remaining optional smells**.
Spec review: **0 remaining findings**. Review caught vector validation completing
outside the embedding boundary; fixed by preparing the vector within that stage
and reusing its normalized matrix in FAISS. Four regressions cover empty,
wrong-dimension, non-finite, and zero vectors while preserving legacy errors.
The optional snapshot-typing suggestion was also addressed with `StageSnapshot`.

One affected-suite run exceeded an existing two-second busy-recovery test wait;
the isolated cases and final full suite passed without changing its threshold.

No paid calls, deployment, or frontend changes were performed.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.

- 2026-11-08: User approved implementation on `implement/rag-ui-trace-ticket-01`
  after updating from main `c69f02b`. Using the specified mocked HTTP boundary,
  including real loopback delivery with a blocked provider.
- 2026-11-08: Completed ticket 01 after standards/spec reviews and 162 passing
  tests. Tickets 02 and 04 are unblocked; complete frontend integration remains
  gated on ticket 06.
