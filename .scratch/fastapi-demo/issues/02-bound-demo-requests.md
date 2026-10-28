# 02: Bound demo requests and report operational failures

**What to build:** Visitors receive predictable rate-limit, busy, timeout, and failure responses while the single-worker API stays responsive. An operator can correlate each response with a concise server log entry.

**Blocked by:** 01: Ask NASA questions through a locally runnable API.

**Status:** ready-for-agent

## Acceptance criteria

- [ ] The API applies the agreed limit of 10 submissions per client IP per 10 minutes. Over-limit requests receive 429; distinct client addresses have separate allowances.
- [ ] Rate counters live in memory, expired entries are cleaned up, and counters reset on restart. This feature adds neither a database/Redis dependency nor a global daily quota.
- [ ] Client-IP forwarding is trusted only from configured proxy connections. An untrusted caller cannot change its rate-limit identity by supplying a forwarded-IP header. The intended private-backend/same-origin-proxy arrangement and local development configuration are documented without deploying the proxy or adding visitor authentication.
- [ ] A configurable response deadline defaults to 120 seconds. Exceeding it produces 504 with a request ID, without claiming the underlying pipeline was canceled or issuing an automatic retry.
- [ ] A timeout or client disconnect does not free the processing slot while the original pipeline call is still running. Further questions remain busy (503) until that work actually finishes; subsequent requests can run afterward. No unlimited queue, job recovery, or changes to core model-client retry behavior are added.
- [ ] Failures consistently use a JSON object containing `request_id` and `error`, where `error` contains `code` and `message`. Request validation uses 422, rate limiting 429, busy/not-ready service 503, upstream provider failures 502, response deadlines 504, and unexpected server faults 500.
- [ ] Existing answer text and citation warnings remain successful answer content. Public errors do not expose stack traces or credentials.
- [ ] Standard web logs record request ID, HTTP status, and elapsed time. Routine logging excludes question/context text and credentials; existing prompt-bearing RAG INFO logs are suppressed by web-layer logging configuration, without editing their original modules.
- [ ] Mocked HTTP tests verify rate-limit boundaries/expiry, proxy identity handling, timeout followed by busy/recovery, disconnect handling, error mapping, and absence of sensitive contents from public errors/routine logs. Waiting in tests uses controlled events or short configured deadlines rather than real 120-second delays.

## Demo path

Keep one mocked question running while a second receives a busy response; then complete the first and submit another successfully. Demonstrate an over-limit response and a timeout with matching request IDs in the logs.

## Scope

Use the existing full hybrid pipeline and its current settings. Preserve existing RAG and CLI source modules and behavior. This ticket concerns the new web adapter, its installation/configuration, and its own verification. Creating this ticket does not authorize execution, model requests, or deployment. Portfolio UI, proxy deployment, streaming, answer caching, richer source responses, user-controlled settings, and changes to RAG answer/citation policy remain outside this feature.
