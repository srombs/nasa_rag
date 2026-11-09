# 06: Verify and document the backend stream contract

**What to build:** Deliver an implementation-backed version-1 API contract that
the website team can consume, with repeatable evidence that events arrive live,
failure snapshots are correct, and the existing NASA RAG interfaces still work.

**Blocked by:** 05 — Preserve results through failures and interruptions
(which depends on the preceding payload and metrics tickets).

**Status:** resolved

**Specification:** [PRD/TRD](../spec.md), especially Testing Decisions and the
frontend handoff boundary.

**Scope:** NASA RAG backend verification, reusable protocol fixtures, and API
documentation. Website changes, browser tests, and deployment are separate.

## Acceptance criteria

- [x] Verify the complete version-1 event contract through a real loopback HTTP
  connection using mocked providers: all eight stages, actual detail fields,
  rerank progress, metrics, ordered sequences, request correlation, and exactly
  one successful terminal answer. Prove early event delivery while later model
  work is blocked; a collected final response alone is insufficient evidence.
- [x] Verify partial failure, timeout with continuing work, disconnect, observer
  detachment, bounded buffering, late usage accounting, and eventual slot
  recovery across both question routes. Retain focused tests from earlier
  tickets; broaden checks where integration exposes a genuine remaining risk.
- [x] Provide reusable public protocol fixtures covering success, rerank
  progress, citation warning/no-citation outcomes, unknown usage/cost,
  pre-stream JSON rejection, actual stage failure, and timeout with unfinished
  work. Fixtures have no credentials or real visitor content and are checked
  against actual server serialization so the frontend need not invent messages.
- [x] Document the implemented request, response headers, schema version,
  envelope, stage IDs, detail/metric fields, state transitions, heartbeat,
  framing, terminal events, admission errors, and equivalent failure statuses.
  Document the distinction between cost completeness for recorded calls and
  unfinished overall work.
- [x] Document incremental consumption, shared allowance/worker limits,
  response deadlines, continued work after observation ends, and the lack of
  automatic replay/resubmission. Explain that an HTTP 200 or EOF alone does not
  establish successful stream completion.
- [x] Document the required proxy behavior for the separate FE implementation:
  immediate forwarding, no response buffering/delaying transformations,
  preserved request IDs/errors and visitor trust, sufficient lifetime, and
  downstream-disconnect handling. Identify the browser-through-deployed-proxy
  check as outstanding frontend acceptance work, not a completed backend test.
- [x] Keep legacy JSON requests, health, CLI/library callers, evaluations,
  retrieval results, citation behavior, and pricing behavior compatible. Run
  appropriate existing regressions and required repository checks using mocked
  providers; no paid model calls are required for backend verification.
- [x] Package the implemented contract references and reusable fixtures with
  the separate frontend handoff. State the additive-backend-first rollout and
  legacy-JSON rollback path without performing deployment or frontend changes.
  Do not introduce an automatic JSON fallback that repeats an admitted search.
- [x] The delivered backend contract has no invented result/usage placeholders
  from intermediate tickets. Record reproducible verification commands and
  results, with any remaining environment-specific FE checks clearly separated.

## Slice boundary

This is the backend readiness check, not proof that the website UI is shipped.
Frontend proxy, reader, timeline, accessibility, and browser acceptance tests are
owned by the separate frontend handoff. No source/frontend deployment is part
of this ticket.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
- 2026-11-09: Claimed through the implement skill on the current branch,
  `implement/rag-ui-trace-ticket-05`. Using the specification's approved
  HTTP-boundary seam with mocked providers; deployment and FE work stay separate.

- 2026-11-09: Resolved after 230 mocked regressions, live loopback/fixture
  verification, documentation checks, and separate standards/spec reviews.
  Backend version 1 is ready for the separate FE integration; deployed proxy,
  browser, accessibility, and rollout checks remain with that handoff.

## Implementation and verification

Delivered the [implemented version-1 contract](../../../docs/web-stream-contract.md),
[public protocol fixtures](../../../docs/fixtures/search-stream-v1/README.md), and
[reproducible verification record](../../../docs/web-stream-verification.md).
Updated the API guide, root README, and frontend handoff with the current
contract references, exact fixture package, additive-backend-first rollout,
legacy-JSON rollback, and outstanding deployed-proxy/browser acceptance work.

New HTTP tests consume all eight stages over real loopback TCP, receive the
first 18 application events before releasing blocked generation, check real
payloads/metrics/correlation/sequences, and observe exactly one terminal
answer. The timeout fixture check retains partial reranking, freezes the old
snapshot, verifies late usage under the original request ID, and observes
shared-slot recovery on both routes. Existing focused lifecycle tests remain.
Shared provider/cache/loopback helpers now support both suites.

Six SSE fixtures and one pre-stream JSON rejection are compared against server
serialization. They use synthetic content and normalize only request identity
and timing, with explicit regeneration instructions. A narrowly scoped Git
attribute preserves SSE's required final blank-line delimiter. No production
pipeline, pricing, frontend source, or deployment changes were needed.

Verification (installed environment; equivalent locked `uv` commands appear
in the verification record):

- `.venv/bin/python -m pytest -q tests/test_stream_contract.py tests/test_web_stream.py tests/test_web_lifecycle.py`:
  **81 passed**.
- `.venv/bin/python -m pytest -q`: **230 passed**, no paid model calls.
- `.venv/bin/ruff check scripts tests/test_web_runtime.py tests/conftest.py tests/stream_support.py tests/test_stream_contract.py tests/test_web_stream.py`:
  **passed**.
- `.venv/bin/mypy --follow-imports=silent --ignore-missing-imports --check-untyped-defs scripts tests/conftest.py tests/stream_support.py tests/test_stream_contract.py`:
  **passed**, 8 files.
- Ruff formatting checks on changed/new Python tests: **passed**.
- Local links in six changed/new entry documents: **passed**.
- `git diff bcce92d38c91d2ab399228f2eb96b197a9706e5c...HEAD --check`:
  **passed**, including the complete committed fixture package.

### Standards

**0 findings.** No documented standards violations or actionable baseline
smells. Tracker artifact/comment conventions, glossary terminology, the FE
acceptance boundary, and shared test support were reviewed. Tooling-enforced
concerns were excluded; supplied passing verification results were accepted
without rerunning checks.

### Spec

**0 findings.** No missing/partial requirements, unrequested scope, or incorrect
implementation found. The review confirmed all required fixture scenarios,
early loopback delivery, details/metrics, timeout/late accounting/recovery,
unchanged focused lifecycle coverage, and the explicitly outstanding deployed
proxy/browser checks.

Review totals: Standards **0** (no worst issue); Spec **0** (no worst issue).
