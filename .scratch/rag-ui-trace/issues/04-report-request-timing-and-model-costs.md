# 04: Report request-scoped timing and model costs

**What to build:** Let an HTTP consumer inspect the elapsed time, model work,
token usage, and estimated cost of each stage and the overall question, with
usage records correlated to that question rather than a shared process run.

**Blocked by:** 01 — Stream a question's live search stages.

**Status:** resolved

**Specification:** [PRD/TRD](../spec.md), especially timing, model usage, cost
aggregation, and request/worker correlation.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [x] Stage completion/failure events and terminal snapshots expose the defined
  metric fields: monotonic duration, recorded application-level model calls,
  requested models, token-category totals, known estimated USD subtotal,
  unknown-cost call count, cost completeness, and rate dates.
- [x] Stage durations measure the actual observed operations, including provider
  retries; overall duration is measured independently rather than summing
  rounded stage values. Preserve the existing pricing rules rather than changing
  models or token rates as part of this feature.
- [x] Aggregate token categories without double counting cached/cache-write
  input or reasoning output. Use zero for inapplicable categories and null for
  unavailable applicable usage, including incomplete aggregate categories.
  Pure non-model stages have zero calls/tokens/cost and empty model/rate lists.
- [x] Missing usage, unknown rates, and failed requests retain the existing
  unknown-cost semantics. Preserve a known subtotal alongside unknown calls;
  never represent unknown cost as a complete zero-cost estimate.
- [x] Create one usage scope for each admitted web question on both question
  routes. Ledger entries add the HTTP `request_id`, use that UUID as `run_id`,
  and use run name `ask`. Preserve existing ledger fields and CLI/evaluation
  accounting.
- [x] Scope lifetime follows the actual worker, including calls that finish
  after the HTTP observation ends. Exclude startup document embeddings and
  other questions. A timed-out snapshot covers recorded calls so far and cannot
  imply a final bill while processing may continue.
- [x] Derive aggregates from the existing model-call recording boundary without
  rereading the ledger or inferring token counts from text. A ledger write
  failure does not prevent in-memory accounting or search completion. Usage
  recorded before later output-validation failure remains included.
- [x] Return immutable metric snapshots. Late worker activity may continue to
  update its accounting and ledger but cannot mutate a snapshot already sent
  to a consumer. Do not add prompts, passage text, or answers to ledger records.
- [x] Mocked HTTP and temporary-ledger tests verify exact stage/run aggregation,
  missing usage and unknown cost, validation-after-response failure, ledger
  write failure, distinct sequential request scopes, startup exclusion, legacy
  JSON request correlation, and accounting after observation ends.

## Slice boundary

This ticket can proceed independently of 02 after 01 exists. It exposes backend
metrics; formatting and display belong to the separate frontend handoff.
Ticket 05 combines these metrics with complete interruption snapshots and
worker-lifecycle checks.

## Implementation and verification

The model-call recording boundary now accumulates immutable run/stage usage
snapshots in memory. Both HTTP routes bind a distinct `ask` accounting scope
inside the worker and correlate ledger records with the HTTP request UUID.
Streaming stage completion/failure events and terminal snapshots include the
defined timing, model, token, and estimated-cost fields. CLI/evaluation totals
read the same accumulator while retaining their operation summaries and ledger
fields. Pricing rules and rates are unchanged.

Unknown applicable usage remains null, and unpriceable calls remain explicitly
unknown alongside any known subtotal. Provider errors never receive invented
usage. Recorded response usage survives later output-validation failure. Calls
that finish after timeout/disconnect continue accounting under the original
request ID; they cannot mutate already published snapshots. Ledger failures
do not stop in-memory accounting or the search flow.

Offline verification (mocked providers; no paid calls):

- `.venv/bin/python -m pytest -q tests/test_web_stream.py`: **55 passed**,
  including exact stage/run totals, missing categories, unknown rates, provider
  failure, validation failure, unwritable ledger, sequential scopes, startup
  exclusion, legacy correlation, late worker usage after timeout on both routes,
  real loopback disconnect, partial reranking timing/usage, and frozen snapshots.
- `.venv/bin/python -m pytest -q`: **204 passed** after review refactoring.
- Ruff on four changed modules, the streaming tests, and CI verification
  scripts/runtime tests: **passed**.
- mypy with `--follow-imports=silent --ignore-missing-imports --check-untyped-defs`
  on four changed modules and verification scripts: **passed** (9 files).
- `git diff --check`: **passed**.

### Standards

**0 hard violations; 0 remaining actionable smell findings.** Review identified
duplicated overall accounting state. CLI-facing totals now read compatibility
properties backed by the same accumulator as HTTP metrics; the reviewer
confirmed the concern resolved.

### Spec

**0 findings**, including a final audit of the shared-total refactoring.
All ticket 04 acceptance criteria are covered. Complete interruption lifecycle
verification remains ticket 05; the stream remains a development slice until
ticket 06 verifies the full backend contract.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
- 2026-11-09: User confirmed ticket 04 on `implement/rag-ui-trace-ticket-04`
  based on main `6669197`, with the explicit requirement to surface only known
  usage/cost information and never invent values after failure.
- 2026-11-09: Completed after independent standards/spec reviews, their final
  follow-up audits, and 204 passing regression tests.
