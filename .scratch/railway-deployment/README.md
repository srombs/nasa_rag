# Railway deployment tickets

Source: [Railway deployment specification](spec.md).

Planning recorded 2026-10-30; ticket 01 packaging is implemented. These are local
Markdown tickets, not GitHub issues. Creating them does not authorize code
changes, publishing, live model calls, or deployment.

| Ticket | Blocked by | Status |
| --- | --- | --- |
| [01: Package the API for Docker](issues/01-package-api-for-docker.md) | None | resolved; Linux image verification pending 02 |
| [02: Verify Linux containers and add CI](issues/02-verify-container-and-add-ci.md) | 01 | ready-for-agent |
| [03: Document Railway dashboard deployment](issues/03-document-dashboard-deployment.md) | 01, 02 | ready-for-agent |
| [04: Deploy the private service through Railway's dashboard](issues/04-deploy-through-dashboard.md) | 02, 03; implementation available on GitHub | ready-for-human |

Work in order: **01 → 02 → 03 → 04**. The status labels identify who can perform
the work once dependencies are met; they do not mean a blocked ticket can start.
Ticket 01 packaging is implemented on `implement/railway-ticket-01`; ticket 02
is next. Tickets 01–03 prepare the
repository; ticket 04 is the user's Railway dashboard work.

## Current state

- The existing FastAPI adapter, request controls, and provisional local runtime
  verification are complete. See the [resolved API tickets](../fastapi-demo/README.md).
- The Docker/Railway requirements and this ticket breakdown are written.
- Ticket 01 provides Docker packaging, build-context exclusions, an environment
  example, and [local Docker instructions](../../docs/docker.md). Existing tests
  and clean local production-install checks pass. Actual Linux image verification
  is deferred to ticket 02 because no Docker engine is available here.
- The deployment CI workflow and full Railway dashboard guide remain unimplemented.
- No Railway account has been connected and no service has been deployed by this
  workstream. Linux/container and deployed verification remain pending.
- Optional Railway infrastructure-as-code capture is deferred. The initial
  workflow uses the dashboard and Dockerfile detection. Website UI and proxy
  integration remain separate work.

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
