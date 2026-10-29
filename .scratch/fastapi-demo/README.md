# FastAPI demo tickets

Source plan: [FastAPI service plan](../../docs/fastapi-service-plan.md).

| Ticket | Blocked by | Status |
| --- | --- | --- |
| [01: Ask NASA questions through a locally runnable API](issues/01-ask-questions-through-api.md) | None | resolved |
| [02: Bound demo requests and report operational failures](issues/02-bound-demo-requests.md) | 01 | resolved |
| [03: Verify the completed demo runtime and measure its RAM](issues/03-verify-runtime-and-memory.md) | 02 (which depends on 01) | ready-for-agent |

Work in order: **01 → 02 → 03**. Each ticket includes its own acceptance criteria and verification. These ticket files are planning artifacts; implementation, live model requests, and deployment require a separate user instruction.


## Decisions so far

- Ticket 01 is resolved: the local API exposes the unchanged full hybrid pipeline
  with startup reuse, validation, and one active question per worker. See its
  [implementation and verification](issues/01-ask-questions-through-api.md#answer)
  and the [API usage guide](../../docs/web-api.md).
- Ticket 02 is resolved: the API bounds submissions and HTTP waiting, preserves
  its processing slot through disconnects/timeouts, and provides safe errors and
  request logs. See its [implementation and verification](issues/02-bound-demo-requests.md#answer).
  Ticket 03 remains open and is now unblocked.
