# 03: Verify the completed demo runtime and measure its RAM

**What to build:** A developer can repeatably run the completed API with its configured cache and environment, verify cache reuse after restart, and inspect measured RAM evidence for Railway capacity and pricing decisions.

**Blocked by:** 02: Bound demo requests and report operational failures (which depends on 01). Measurements must represent the completed demo API, including its request controls.

**Status:** resolved

## Acceptance criteria

- [x] Operator instructions cover optional web installation, the one-worker launch command, required credentials, port, writable cache location, response deadline, trusted-proxy configuration, and a local health/question smoke check. Credentials are supplied through the environment rather than recorded in documentation.
- [x] Starting the API twice with compatible persisted document/index caches reuses those caches. Verification shows that a warm restart does not make new document-embedding requests; ordinary health checks also make no model requests. Cache initialization still has a writable location.
- [x] A documented, repeatable profiling procedure records startup peak, loaded idle memory, and representative-question peak for the single-process API, along with measurement environment, corpus/retrieval settings, cache state, and whether question processing used the real pipeline or a mock.
- [x] Record actual process RSS and service/container memory when available. Clearly separate local/provisional measurements from deployed observations. A missing or unapproved live measurement is reported as pending, never represented as measured or replaced by file-size estimates.
- [x] A real representative-question benchmark is run only when separately authorized. It preserves the current pipeline and settings; OpenAI price estimation and model-cost tuning are not required.
- [x] The resulting RAM-cost estimate uses the current published Railway RAM rate with its check date and distinguishes recurring average/idle memory from peak capacity headroom. CPU, storage, egress, plan allowances, and unrelated services are not silently treated as part of the measured RAM cost.
- [x] The existing test suite and the mocked API suite pass for the completed runtime. Verification records the commands and results without introducing a large benchmark/monitoring system.
- [x] Runtime verification does not provision or deploy Railway resources, modify the portfolio, or alter existing RAG/CLI modules. Those remain separate workstreams.

## Demo path

Use the documented commands to start the API, check health, make a mocked request, restart against the same compatible cache, and inspect the recorded memory report. A live pipeline run or deployment requires its own user instruction.

## Scope

Use the existing full hybrid pipeline and its current settings. Preserve existing RAG and CLI source modules and behavior. This ticket concerns the new web adapter, its installation/configuration, and its own verification. Creating this ticket does not authorize execution, model requests, or deployment. Portfolio UI, proxy deployment, streaming, answer caching, richer source responses, user-controlled settings, and changes to RAG answer/citation policy remain outside this feature.


## Answer

Added the standalone profiler in `scripts/profile_web_runtime.py` and its private
worker/provider helper. Both starts use the actual single-worker API and the
unchanged full pipeline, with OpenAI HTTP transport mocked by default. Source
caches are validated and copied to a writable temporary directory. Fresh-worker
restart verification observes zero startup/health model calls and an untouched
FAISS index; document-embedding requests are rejected before transport.

See [runtime procedure and RAM-only estimate](../../../docs/web-runtime-verification.md)
and [raw local process measurements](../../../docs/web-runtime-memory-local.json).
The final macOS run used 737 chunks with 1,536-dimensional supplied embeddings:
startup OS peaks 258.41/258.52 MiB, loaded idle 258.43/258.55 MiB, question sampled
peaks 280.72/280.83 MiB, and lifetime OS peaks 280.73/280.84 MiB. Each worker
exercised 13 mocked question requests. Linux/container, real-provider question,
and deployed Railway observations remain explicitly pending. The RAM-only
illustration uses Railway's published container rate checked 2026-10-30 UTC;
peak capacity headroom is separate from short-window average-memory cost.

Verification:

- `uv run --extra web --extra dev --with psutil python -m pytest -q`:
  **132 passed**, including 47 API cases and three profiling cases.
- `uv run --extra web --extra dev ruff check scripts tests/test_web_runtime.py src/nasa_rag/web.py tests/test_web.py`:
  **passed**.
- `uv run --extra web --extra dev --with psutil --with mypy mypy --follow-imports=silent --ignore-missing-imports --check-untyped-defs scripts/profile_web_runtime.py scripts/runtime_mock_provider.py src/nasa_rag/web.py`:
  **passed**, three source files.
- `uv run --extra web --extra dev --with psutil python scripts/profile_web_runtime.py --cache-dir cache --output docs/web-runtime-memory-local.json`:
  **passed**, two distinct server processes, only mocked provider requests.
- `git diff --check`: **passed**.
- Standards review: **0 findings**. Spec review: **1 finding fixed**, then
  **0 remaining findings**. An unavailable cgroup counter previously truncated
  RSS sampling; a regression reproduced one sample before the fix and verifies
  continued RSS observation afterward. Optional counters now fail to null;
  actual RSS reader failures fail the profile explicitly.

## Comments

2026-10-29 Pacific: Implemented on `implement/fastapi-ticket-03`, based on `main`
at `8b4efd2`. No existing RAG/CLI modules were edited, no live model requests
were made, and no Railway, proxy, or portfolio resources were deployed. This
resolution completes the authorized provisional verification; pending live and
deployed observations require separate instructions, as the acceptance criteria
permit.
