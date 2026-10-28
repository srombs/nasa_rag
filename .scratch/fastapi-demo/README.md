# FastAPI demo tickets

Source plan: [FastAPI service plan](../../docs/fastapi-service-plan.md).

| Ticket | Blocked by | Status |
| --- | --- | --- |
| [01: Ask NASA questions through a locally runnable API](issues/01-ask-questions-through-api.md) | None | ready-for-agent |
| [02: Bound demo requests and report operational failures](issues/02-bound-demo-requests.md) | 01 | ready-for-agent |
| [03: Verify the completed demo runtime and measure its RAM](issues/03-verify-runtime-and-memory.md) | 02 (which depends on 01) | ready-for-agent |

Work in order: **01 → 02 → 03**. Each ticket includes its own acceptance criteria and verification. These ticket files are planning artifacts; implementation, live model requests, and deployment require a separate user instruction.
