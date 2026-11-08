# 05: Preserve results through failures and interruptions

**What to build:** Keep completed search-flow results and observed usage useful
when a stage fails, the response deadline expires, or the consumer disconnects.
Make the backend honest about unfinished work and keep resource ownership tied
to the actual search, not the lifetime of its HTTP connection.

**Blocked by:** 03 — Stream reranking progress and citation results;
04 — Report request-scoped timing and model costs.

**Status:** ready-for-agent

**Specification:** [PRD/TRD](../spec.md), especially event state transitions,
terminal snapshots, admission controls, and resource lifecycle.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [ ] An actual observed stage failure emits `stage.failed` followed by exactly
  one `run.failed` with the specified sanitized error and equivalent HTTP
  status. Preserve completed stage details, evaluated rerank candidates, and
  observed metrics; mark subsequent unstarted stages skipped.
- [ ] Distinguish pre-stream JSON errors from failures after HTTP 200 headers.
  Provider and malformed model-output failures retain the existing upstream
  classification; unexpected faults retain the existing internal-error mapping.
  Never leak provider details or tracebacks to event consumers.
- [ ] Enforce the configured overall response deadline without restarting it
  for stages, events, or heartbeats. If the worker remains active, a writable
  stream receives a terminal timeout with `processing_may_continue` true,
  retained completed results, and unknown unfinished stages. Do not claim the
  worker failed, skipped later work, or was cancelled merely because time ran out.
- [ ] After deadline, disconnect, or observation failure, retain the shared
  admission slot until actual worker completion. Other questions on either
  route receive busy responses during that interval. Observe eventual worker
  exceptions, release the slot correctly afterward, and retain the existing
  shutdown wait semantics.
- [ ] Detach a disconnected observer and discard later event emissions without
  blocking the worker or retaining an unbounded event history. Use thread-safe
  delivery, the specified 64-event queue bound, and at most one progress event
  per validated rerank candidate. Queue exhaustion closes observation without
  guaranteeing a terminal event; it must not deadlock the worker.
- [ ] Freeze terminal snapshots and detach their event sinks atomically. Healthy
  connected runs have one terminal event and no application events afterward;
  later model activity cannot mutate earlier results or terminal metric totals.
  Request-scoped accounting and late ledger records continue for the real work.
- [ ] Keep one sanitized operational record per HTTP request with request ID,
  actual transport status, elapsed time, stream outcome, and known failure code.
  Preserve detailed RAG/provider-log suppression and do not log visitor event
  bodies, questions, passages, or raw exceptions.
- [ ] Do not add automatic retries, reconnect/replay, duplicate model runs,
  cancellation claims, job queues, or a separate rate allowance. A manual retry
  remains a fresh ordinarily limited request with a new ID.
- [ ] Deterministic mocked HTTP tests cover failure at different stages,
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
