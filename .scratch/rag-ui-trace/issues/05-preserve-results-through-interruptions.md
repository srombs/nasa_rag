# 05: Preserve results through failures and interruptions

**What to build:** Keep completed search-flow results and observed usage useful
when a stage fails, the response deadline expires, or the consumer disconnects.
Make the backend honest about unfinished work and keep resource ownership tied
to the actual search, not the lifetime of its HTTP connection.

**Blocked by:** 03 — Stream reranking progress and citation results;
04 — Report request-scoped timing and model costs.

**Status:** resolved

**Specification:** [PRD/TRD](../spec.md), especially event state transitions,
terminal snapshots, admission controls, and resource lifecycle.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [x] An actual observed stage failure emits `stage.failed` followed by exactly
  one `run.failed` with the specified sanitized error and equivalent HTTP
  status. Preserve completed stage details, evaluated rerank candidates, and
  observed metrics; mark subsequent unstarted stages skipped.
- [x] Distinguish pre-stream JSON errors from failures after HTTP 200 headers.
  Provider and malformed model-output failures retain the existing upstream
  classification; unexpected faults retain the existing internal-error mapping.
  Never leak provider details or tracebacks to event consumers.
- [x] Enforce the configured overall response deadline without restarting it
  for stages, events, or heartbeats. If the worker remains active, a writable
  stream receives a terminal timeout with `processing_may_continue` true,
  retained completed results, and unknown unfinished stages. Do not claim the
  worker failed, skipped later work, or was cancelled merely because time ran out.
- [x] After deadline, disconnect, or observation failure, retain the shared
  admission slot until actual worker completion. Other questions on either
  route receive busy responses during that interval. Observe eventual worker
  exceptions, release the slot correctly afterward, and retain the existing
  shutdown wait semantics.
- [x] Detach a disconnected observer and discard later event emissions without
  blocking the worker or retaining an unbounded event history. Use thread-safe
  delivery, the specified 64-event queue bound, and at most one progress event
  per validated rerank candidate. Queue exhaustion closes observation without
  guaranteeing a terminal event; it must not deadlock the worker.
- [x] Freeze terminal snapshots and detach their event sinks atomically. Healthy
  connected runs have one terminal event and no application events afterward;
  later model activity cannot mutate earlier results or terminal metric totals.
  Request-scoped accounting and late ledger records continue for the real work.
- [x] Keep one sanitized operational record per HTTP request with request ID,
  actual transport status, elapsed time, stream outcome, and known failure code.
  Preserve detailed RAG/provider-log suppression and do not log visitor event
  bodies, questions, passages, or raw exceptions.
- [x] Do not add automatic retries, reconnect/replay, duplicate model runs,
  cancellation claims, job queues, or a separate rate allowance. A manual retry
  remains a fresh ordinarily limited request with a new ID.
- [x] Deterministic mocked HTTP tests cover failure at different stages,
  partially completed reranking, deadline while a provider is blocked,
  disconnect/cancellation, slow or absent consumers, completion/deadline races,
  immutable terminal snapshots, late cost records, slot recovery on both routes,
  sanitized request logs, and shutdown with active work.

## Slice boundary

This ticket needs 03's partial candidate results and 04's scoped metrics to
validate complete failure snapshots and accounting after observation ends.
Browser interruption presentation and manual-retry controls remain frontend
work; this ticket provides the server behavior they consume.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
- 2026-11-09: User confirmed implementation after reviewing the ticket and
  feature overview. Claimed on `implement/rag-ui-trace-ticket-05`; lifecycle
  tests use the approved public HTTP/ASGI boundary with mocked providers.
- 2026-11-09: Resolved after implementation, offline verification, and separate
  standards/spec reviews. Ticket 06 is now unblocked; the complete version-1
  contract remains development-only until that ticket passes.

## Implementation and verification

Observed stage failure now publishes its stage and terminal run snapshots under
one lock. A subsequent deadline cannot replace that known failure with a
timeout. A completed run likewise remains successful if terminal delivery
crosses the deadline. Actual worker ownership still includes cleanup.

Event JSON/UTF-8 encoding errors detach observation instead of aborting or
restarting the pipeline. JSON errors record their known public failure code;
failed terminal delivery and queue exhaustion retain already observed failure
codes while reporting disconnection. Detached workers discard later emissions
without remapping late exceptions for an absent observer.

The existing queue, usage scope, worker task, and shutdown ownership remain in
place. New public HTTP/ASGI checks exercise exact 64-event buffering limits for
both absent and slow consumers, terminal delivery failure, cancellation,
encoding failure, deadline ordering, late provider exceptions, frozen
snapshots, request-correlated late ledger records, shared-slot recovery, and
shutdown waiting for real work. Existing provider/loopback checks retain
coverage for partial reranking, model-output classification, live delivery,
and unchanged legacy responses. All model work is mocked.

Verification:

- `uv run --extra web --extra dev --extra profile python -m pytest -q`:
  **222 passed**.
- `uv run --extra web --extra dev python -m pytest -q tests/test_web_lifecycle.py`:
  **18 passed**, including after the final recovery-test synchronization change.
- Ruff on changed Python modules/tests and CI verification scripts/runtime
  tests: **passed**.
- mypy with `--follow-imports=silent --ignore-missing-imports --check-untyped-defs`
  on both changed modules and verification scripts: **passed** (7 files).
- HTML scenario/filter controls, clipboard fallback, local links, and unique
  IDs checked with an offline JavaScript harness. Visual pages now show the
  implemented ticket and next backend step.
- `git diff --check`: **passed**.

### Standards

**0 findings.** No documented-standard breaches or actionable baseline smells.
Review identified an assumption that one loop turn synchronized worker
completion; the final test observes eventual admission with bounded public HTTP
requests instead. Worker ownership remains tied to the actual application task.

### Spec

**0 findings.** No missing requirements or unrequested scope creep. The review
confirmed failure/deadline distinctions, atomic terminal freezing, observer
detachment, exact queue-bound checks, accounting, slot recovery, and shutdown
coverage. Frontend/proxy work and final protocol fixtures remain separate.
