# 04: Report request-scoped timing and model costs

**What to build:** Let an HTTP consumer inspect the elapsed time, model work,
token usage, and estimated cost of each stage and the overall question, with
usage records correlated to that question rather than a shared process run.

**Blocked by:** 01 — Stream a question's live search stages.

**Status:** ready-for-agent

**Specification:** [PRD/TRD](../spec.md), especially timing, model usage, cost
aggregation, and request/worker correlation.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [ ] Stage completion/failure events and terminal snapshots expose the defined
  metric fields: monotonic duration, recorded application-level model calls,
  requested models, token-category totals, known estimated USD subtotal,
  unknown-cost call count, cost completeness, and rate dates.
- [ ] Stage durations measure the actual observed operations, including provider
  retries; overall duration is measured independently rather than summing
  rounded stage values. Preserve the existing pricing rules rather than changing
  models or token rates as part of this feature.
- [ ] Aggregate token categories without double counting cached/cache-write
  input or reasoning output. Use zero for inapplicable categories and null for
  unavailable applicable usage, including incomplete aggregate categories.
  Pure non-model stages have zero calls/tokens/cost and empty model/rate lists.
- [ ] Missing usage, unknown rates, and failed requests retain the existing
  unknown-cost semantics. Preserve a known subtotal alongside unknown calls;
  never represent unknown cost as a complete zero-cost estimate.
- [ ] Create one usage scope for each admitted web question on both question
  routes. Ledger entries add the HTTP `request_id`, use that UUID as `run_id`,
  and use run name `ask`. Preserve existing ledger fields and CLI/evaluation
  accounting.
- [ ] Scope lifetime follows the actual worker, including calls that finish
  after the HTTP observation ends. Exclude startup document embeddings and
  other questions. A timed-out snapshot covers recorded calls so far and cannot
  imply a final bill while processing may continue.
- [ ] Derive aggregates from the existing model-call recording boundary without
  rereading the ledger or inferring token counts from text. A ledger write
  failure does not prevent in-memory accounting or search completion. Usage
  recorded before later output-validation failure remains included.
- [ ] Return immutable metric snapshots. Late worker activity may continue to
  update its accounting and ledger but cannot mutate a snapshot already sent
  to a consumer. Do not add prompts, passage text, or answers to ledger records.
- [ ] Mocked HTTP and temporary-ledger tests verify exact stage/run aggregation,
  missing usage and unknown cost, validation-after-response failure, ledger
  write failure, distinct sequential request scopes, startup exclusion, legacy
  JSON request correlation, and accounting after observation ends.

## Slice boundary

This ticket can proceed independently of 02 after 01 exists. It exposes backend
metrics; formatting and display belong to the separate frontend handoff.
Ticket 05 combines these metrics with complete interruption snapshots and
worker-lifecycle checks.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
