# 03: Verify the completed demo runtime and measure its RAM

**What to build:** A developer can repeatably run the completed API with its configured cache and environment, verify cache reuse after restart, and inspect measured RAM evidence for Railway capacity and pricing decisions.

**Blocked by:** 02: Bound demo requests and report operational failures (which depends on 01). Measurements must represent the completed demo API, including its request controls.

**Status:** ready-for-agent

## Acceptance criteria

- [ ] Operator instructions cover optional web installation, the one-worker launch command, required credentials, port, writable cache location, response deadline, trusted-proxy configuration, and a local health/question smoke check. Credentials are supplied through the environment rather than recorded in documentation.
- [ ] Starting the API twice with compatible persisted document/index caches reuses those caches. Verification shows that a warm restart does not make new document-embedding requests; ordinary health checks also make no model requests. Cache initialization still has a writable location.
- [ ] A documented, repeatable profiling procedure records startup peak, loaded idle memory, and representative-question peak for the single-process API, along with measurement environment, corpus/retrieval settings, cache state, and whether question processing used the real pipeline or a mock.
- [ ] Record actual process RSS and service/container memory when available. Clearly separate local/provisional measurements from deployed observations. A missing or unapproved live measurement is reported as pending, never represented as measured or replaced by file-size estimates.
- [ ] A real representative-question benchmark is run only when separately authorized. It preserves the current pipeline and settings; OpenAI price estimation and model-cost tuning are not required.
- [ ] The resulting RAM-cost estimate uses the current published Railway RAM rate with its check date and distinguishes recurring average/idle memory from peak capacity headroom. CPU, storage, egress, plan allowances, and unrelated services are not silently treated as part of the measured RAM cost.
- [ ] The existing test suite and the mocked API suite pass for the completed runtime. Verification records the commands and results without introducing a large benchmark/monitoring system.
- [ ] Runtime verification does not provision or deploy Railway resources, modify the portfolio, or alter existing RAG/CLI modules. Those remain separate workstreams.

## Demo path

Use the documented commands to start the API, check health, make a mocked request, restart against the same compatible cache, and inspect the recorded memory report. A live pipeline run or deployment requires its own user instruction.

## Scope

Use the existing full hybrid pipeline and its current settings. Preserve existing RAG and CLI source modules and behavior. This ticket concerns the new web adapter, its installation/configuration, and its own verification. Creating this ticket does not authorize execution, model requests, or deployment. Portfolio UI, proxy deployment, streaming, answer caching, richer source responses, user-controlled settings, and changes to RAG answer/citation policy remain outside this feature.
