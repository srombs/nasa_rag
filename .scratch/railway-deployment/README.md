# Railway deployment tickets

Source: [Railway deployment specification](spec.md).

Planning recorded 2026-10-30; ticket 01 packaging is implemented. These are local
Markdown tickets, not GitHub issues. Creating them does not authorize code
changes, publishing, live model calls, or deployment.

| Ticket | Blocked by | Status |
| --- | --- | --- |
| [01: Package the API for Docker](issues/01-package-api-for-docker.md) | None | resolved; Linux image verified by 02 |
| [02: Verify Linux containers and add CI](issues/02-verify-container-and-add-ci.md) | 01 | resolved |
| [03: Document Railway dashboard deployment](issues/03-document-dashboard-deployment.md) | 01, 02 | resolved; triage ready-for-agent |
| [04: Deploy the private service through Railway's dashboard](issues/04-deploy-through-dashboard.md) | 02, 03; implementation available on GitHub | ready-for-human |

Work in order: **01 → 02 → 03 → 04**. The status labels identify who can perform
the work once dependencies are met; they do not mean a blocked ticket can start.
Tickets 01–03 are implemented; ticket 04 is next after the implementation is
published with matching CI evidence. Ticket 04 is the user's Railway dashboard work, including verification
of the deployment the user reports already exists.

## Current state

- The existing FastAPI adapter, request controls, and provisional local runtime
  verification are complete. See the [resolved API tickets](../fastapi-demo/README.md).
- The Docker/Railway requirements and this ticket breakdown are written.
- Ticket 01 provides Docker packaging, build-context exclusions, an environment
  example, and [local Docker instructions](../../docs/docker.md). Existing tests
  and clean local production-install checks pass. Ticket 02 completed the actual
  Linux image verification on GitHub's runner.
- Ticket 02's [container checks and CI workflow](../../docs/container-verification.md)
  are implemented on `implement/railway-ticket-02` in [PR #5](https://github.com/srombs/nasa_rag/pull/5).
  Local tests and hosted Linux image/runtime verification pass. Linux process and
  container memory are recorded with synthetic-fixture/probe limits. The full
  [Railway dashboard guide](../../docs/railway-deployment.md) is delivered by ticket 03.
- The user reports an existing Railway deployment. This workstream has not
  inspected or changed its configuration. Hosted verification remains pending.
- Optional Railway infrastructure-as-code capture is deferred. The initial
  workflow uses the dashboard and Dockerfile detection. Website UI and proxy
  integration remain separate work.
- Ticket 03 provides the [dashboard guide](../../docs/railway-deployment.md),
  private health/cache commands, recovery steps, and ticket 04 operator checklist.
  Its completion is recorded separately from its configured triage role. Current
  platform guidance and offline snippets are verified; publication and all hosted
  observations remain pending.

## Comments

2026-10-30: Created the ticket breakdown at the user's request. Implementation
and dashboard deployment have not started. The source spec and tickets are
local working-tree changes until committed and pushed.

2026-10-30: Confirmed Markdown as the configured tracker and reviewed the existing
four-ticket breakdown with the to-tickets workflow. Normalized the ticket headers
and outcome descriptions; retained ticket numbers, scope, dependencies, and human
ownership of dashboard deployment. No duplicate tickets or external issues were
created. Detailed configuration locations remain in the source specification.

2026-10-30: User authorized ticket 01 implementation and branch creation. Packaging
is delivered on `implement/railway-ticket-01`; [the ticket's verification record](issues/01-package-api-for-docker.md#answer)
distinguishes passing local checks from pending Linux image checks. Ticket 02
is the next task. No commit, push, live model request, or deployment was performed.

2026-11-03: Ticket 02 implemented and resolved in PR #5. Hosted workflow run
41704044621 passes 132 tests and the actual Linux build/import/runtime/cache
checks. Both review axes report no actionable findings. No live model requests,
Railway changes, or deployment were performed. Ticket 03 is unblocked.

2026-11-03: Ticket 03 completed on `implement/railway-ticket-03`, based on updated
`main` at `7922466`. Documentation links, offline snippets, 132 tests, Ruff, and
mypy pass. The guide was checked against official Railway documentation. Ticket
04 remains ready-for-human, pending publication/CI and the user's dashboard work.
