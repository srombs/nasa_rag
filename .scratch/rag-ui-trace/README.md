# Live RAG search flow: backend tickets

Recorded: 2026-11-08

These tickets implement the NASA RAG backend portion of the
[PRD/TRD](spec.md). Website proxy, stream-reader, UI, and browser-test work stays
in the separate [frontend handoff](frontend-handoff.md) for the website repo.
No frontend implementation or deployment is required to complete these tickets.

Each implementation ticket delivers behavior verifiable through the backend's
public HTTP/event boundary and includes its own focused mocked-provider checks.
The tickets are incremental: complete payloads, usage accounting, and lifecycle
handling are developed across the slices. Treat incomplete intermediate stream
implementations as development-only. Do not claim the full version-1 contract
is ready for frontend integration until ticket 06 passes; never invent usage
or stage results to fill unfinished fields.

## Tickets and dependencies

| Ticket | What it delivers | Blocked by | Status |
| --- | --- | --- | --- |
| [01: Stream a question's live search stages](issues/01-stream-live-search-stages.md) | Real stage lifecycle events and the final answer over the additive streaming endpoint. | None | resolved |
| [02: Expose planning and retrieval results](issues/02-expose-planning-and-retrieval-results.md) | Inspectable query plan, embedding summary, passages, native rankings, and fusion metadata. | 01 | resolved |
| [03: Stream reranking progress and citation results](issues/03-stream-reranking-and-citation-results.md) | Per-candidate progress, final reranking, context references, and citation-reference outcomes. | 02 | resolved |
| [04: Report request-scoped timing and model costs](issues/04-report-request-timing-and-model-costs.md) | Accurate stage/run metrics and request-correlated usage records. | 01 | resolved |
| [05: Preserve results through failures and interruptions](issues/05-preserve-results-through-interruptions.md) | Complete partial-result, deadline, disconnect, buffering, and worker-lifecycle behavior. | 03, 04 | resolved |
| [06: Verify and document the backend stream contract](issues/06-verify-and-document-stream-contract.md) | Final backend integration evidence, reusable protocol fixtures, and current API documentation. | 05 | resolved |

## Working order

Start with 01. After it completes, 02 and 04 can proceed independently. Ticket 03
extends the passage/ranking payloads delivered by 02. Ticket 05 needs 03's partial
reranking results and 04's request-scoped metrics to verify complete failure
snapshots and accounting after observation ends. Ticket 06 verifies all earlier
work through its dependency on 05.

`ready-for-agent` means a ticket is specified, not that its blockers are done.
Only start a ticket once every listed blocker has actually completed. Maintain
status and acceptance checkboxes as work proceeds.

## Backend completion and frontend handoff

Backend completion means the final contract passes real incremental HTTP checks
with mocked model calls and the existing regression checks. It does not prove
that a browser receives live updates through the deployed website proxy.

Ticket 06 verified backend version 1 on 2026-11-09: 230 mocked regressions
passed, including 81 focused stream/contract/lifecycle checks. The
[implemented contract](../../docs/web-stream-contract.md),
[public fixtures](../../docs/fixtures/search-stream-v1/README.md), and
[verification record](../../docs/web-stream-verification.md) are ready to
transfer with the specification and frontend handoff to the website repo. Proxy
streaming verification, timeline presentation, accessibility, and browser tests
remain frontend acceptance work. The legacy JSON endpoint remains available.

## Comments

- 2026-11-08: User clarified that these tickets concern only the NASA RAG
  backend, with FE work kept in its separate handoff, and requested one Markdown
  file per implementation ticket.
