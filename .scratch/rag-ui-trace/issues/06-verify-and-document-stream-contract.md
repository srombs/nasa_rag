# 06: Verify and document the backend stream contract

**What to build:** Deliver an implementation-backed version-1 API contract that
the website team can consume, with repeatable evidence that events arrive live,
failure snapshots are correct, and the existing NASA RAG interfaces still work.

**Blocked by:** 05 — Preserve results through failures and interruptions
(which depends on the preceding payload and metrics tickets).

**Status:** ready-for-agent

**Specification:** [PRD/TRD](../spec.md), especially Testing Decisions and the
frontend handoff boundary.

**Scope:** NASA RAG backend verification, reusable protocol fixtures, and API
documentation. Website changes, browser tests, and deployment are separate.

## Acceptance criteria

- [ ] Verify the complete version-1 event contract through a real loopback HTTP
  connection using mocked providers: all eight stages, actual detail fields,
  rerank progress, metrics, ordered sequences, request correlation, and exactly
  one successful terminal answer. Prove early event delivery while later model
  work is blocked; a collected final response alone is insufficient evidence.
- [ ] Verify partial failure, timeout with continuing work, disconnect, observer
  detachment, bounded buffering, late usage accounting, and eventual slot
  recovery across both question routes. Retain focused tests from earlier
  tickets; broaden checks where integration exposes a genuine remaining risk.
- [ ] Provide reusable public protocol fixtures covering success, rerank
  progress, citation warning/no-citation outcomes, unknown usage/cost,
  pre-stream JSON rejection, actual stage failure, and timeout with unfinished
  work. Fixtures have no credentials or real visitor content and are checked
  against actual server serialization so the frontend need not invent messages.
- [ ] Document the implemented request, response headers, schema version,
  envelope, stage IDs, detail/metric fields, state transitions, heartbeat,
  framing, terminal events, admission errors, and equivalent failure statuses.
  Document the distinction between cost completeness for recorded calls and
  unfinished overall work.
- [ ] Document incremental consumption, shared allowance/worker limits,
  response deadlines, continued work after observation ends, and the lack of
  automatic replay/resubmission. Explain that an HTTP 200 or EOF alone does not
  establish successful stream completion.
- [ ] Document the required proxy behavior for the separate FE implementation:
  immediate forwarding, no response buffering/delaying transformations,
  preserved request IDs/errors and visitor trust, sufficient lifetime, and
  downstream-disconnect handling. Identify the browser-through-deployed-proxy
  check as outstanding frontend acceptance work, not a completed backend test.
- [ ] Keep legacy JSON requests, health, CLI/library callers, evaluations,
  retrieval results, citation behavior, and pricing behavior compatible. Run
  appropriate existing regressions and required repository checks using mocked
  providers; no paid model calls are required for backend verification.
- [ ] Package the implemented contract references and reusable fixtures with
  the separate frontend handoff. State the additive-backend-first rollout and
  legacy-JSON rollback path without performing deployment or frontend changes.
  Do not introduce an automatic JSON fallback that repeats an admitted search.
- [ ] The delivered backend contract has no invented result/usage placeholders
  from intermediate tickets. Record reproducible verification commands and
  results, with any remaining environment-specific FE checks clearly separated.

## Slice boundary

This is the backend readiness check, not proof that the website UI is shipped.
Frontend proxy, reader, timeline, accessibility, and browser acceptance tests are
owned by the separate frontend handoff. No source/frontend deployment is part
of this ticket.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
