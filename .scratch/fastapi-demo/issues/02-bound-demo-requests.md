# 02: Bound demo requests and report operational failures

**What to build:** Visitors receive predictable rate-limit, busy, timeout, and failure responses while the single-worker API stays responsive. An operator can correlate each response with a concise server log entry.

**Blocked by:** 01: Ask NASA questions through a locally runnable API.

**Status:** resolved

## Acceptance criteria

- [x] The API applies the agreed limit of 10 submissions per client IP per 10 minutes. Over-limit requests receive 429; distinct client addresses have separate allowances.
- [x] Rate counters live in memory, expired entries are cleaned up, and counters reset on restart. This feature adds neither a database/Redis dependency nor a global daily quota.
- [x] Client-IP forwarding is trusted only from configured proxy connections. An untrusted caller cannot change its rate-limit identity by supplying a forwarded-IP header. The intended private-backend/same-origin-proxy arrangement and local development configuration are documented without deploying the proxy or adding visitor authentication.
- [x] A configurable response deadline defaults to 120 seconds. Exceeding it produces 504 with a request ID, without claiming the underlying pipeline was canceled or issuing an automatic retry.
- [x] A timeout or client disconnect does not free the processing slot while the original pipeline call is still running. Further questions remain busy (503) until that work actually finishes; subsequent requests can run afterward. No unlimited queue, job recovery, or changes to core model-client retry behavior are added.
- [x] Failures consistently use a JSON object containing `request_id` and `error`, where `error` contains `code` and `message`. Request validation uses 422, rate limiting 429, busy/not-ready service 503, upstream provider failures 502, response deadlines 504, and unexpected server faults 500.
- [x] Existing answer text and citation warnings remain successful answer content. Public errors do not expose stack traces or credentials.
- [x] Standard web logs record request ID, HTTP status, and elapsed time. Routine logging excludes question/context text and credentials; existing prompt-bearing RAG INFO logs are suppressed by web-layer logging configuration, without editing their original modules.
- [x] Mocked HTTP tests verify rate-limit boundaries/expiry, proxy identity handling, timeout followed by busy/recovery, disconnect handling, error mapping, and absence of sensitive contents from public errors/routine logs. Waiting in tests uses controlled events or short configured deadlines rather than real 120-second delays.

## Demo path

Keep one mocked question running while a second receives a busy response; then complete the first and submit another successfully. Demonstrate an over-limit response and a timeout with matching request IDs in the logs.

## Scope

Use the existing full hybrid pipeline and its current settings. Preserve existing RAG and CLI source modules and behavior. This ticket concerns the new web adapter, its installation/configuration, and its own verification. Creating this ticket does not authorize execution, model requests, or deployment. Portfolio UI, proxy deployment, streaming, answer caching, richer source responses, user-controlled settings, and changes to RAG answer/citation policy remain outside this feature.

## Answer

Implemented request controls in `src/nasa_rag/web.py`: rolling in-memory IP
allowances with expiry cleanup, configured proxy trust, a configurable 120-second
default response deadline, and one occupied processing slot until actual work
finishes after timeout, disconnect, or handler cancellation. Every response has
a generated `X-Request-ID`, shared with its JSON envelope and concise request log.
Provider and internal failures receive distinct public errors without exception
details. Web lifespan logging configuration suppresses prompt-bearing RAG and
provider logs and restores logger configuration on shutdown.

See [operator setup and the mocked demo](../../../docs/web-api.md) for environment
settings, the required one-worker launch flags, proxy integration requirements,
error codes, and the repeatable demo command. The optional Uvicorn minimum is
0.31 to support CIDR proxy configuration. Existing RAG and CLI modules are
unchanged.

Verification:

- `uv run --extra web --extra dev python -m pytest -q`: **129 passed**, including
  **47 HTTP cases**, with mocked pipeline/provider calls only.
- `uv run --extra web --extra dev ruff check src/nasa_rag/web.py tests/test_web.py`:
  **passed**; `git diff --check`: **passed**.
- `uv run --extra web --extra dev --with mypy mypy --follow-imports=silent src/nasa_rag/web.py`:
  **passed**. Mypy is used transiently, with no new runtime dependency.
- Standards review: **0 findings**. Spec review: **2 findings fixed**, then
  **0 remaining findings**. Regression tests reproduce the task-reference race
  and wrapped-local-fault misclassification before their fixes.

## Comments

2026-10-28: Implemented ticket 02 on `implement/fastapi-ticket-02`, based on
`main` at `eb023b6`. No live model requests, portfolio/proxy deployment, or runtime
RAM measurements were performed. Ticket 03 remains separate and is now unblocked.
