# API runtime verification and RAM evidence

Ticket 03 verifies the completed single-worker API, including its request
controls. The [operator guide](web-api.md) covers optional web installation,
environment credentials, port, a writable persistent cache, the response
deadline, trusted proxies, and ordinary health/question commands.

## Repeat the offline profile

From the repository root, with compatible persisted caches available:

```sh
uv run --extra web --extra dev --with psutil python scripts/profile_web_runtime.py \
  --cache-dir cache --output /tmp/nasa-rag-runtime.json
```

The script supports macOS and Linux. `psutil` is a transient profiling dependency;
it is not needed by the API or CLI. A pip environment can install `.[web]` and
`psutil`, then use `python scripts/profile_web_runtime.py` with the same arguments.
No real credential is required for this default run. The child receives an
offline placeholder rather than any inherited API key.

The inputs must include `embeds/document_cache_100_20.json` and
`faiss/document_100_20.index`. Preflight compares cached chunk text, filenames,
and chunk indices with all four bundled sources at 100/20. It checks finite,
nonzero vectors and verifies that the exact inner-product index contains those
normalized vectors. Missing, stale, or incompatible caches fail before a server
starts. The script does not build a real embedding cache; that requires a
separately authorized model run. Cache format alone cannot prove embedding
provenance or model identity, so the report records that uncertainty.

The procedure:

1. Copy only the two compatible cache files to a writable temporary directory.
   The source cache stays untouched. The JSON report fingerprints the input
   caches and corpus; it does not estimate RAM from their file sizes.
2. Start one actual Uvicorn/API process on an inherited loopback socket with an
   ephemeral port. Keep the API's current settings and request controls. Use
   empty trusted proxies and disable Uvicorn proxy headers and access logs.
3. Sample that worker's RSS every 0.01 seconds from the separate controller.
   Capture startup, two seconds of loaded idle, one question, and two seconds
   of idle after the question. The question is “What mission launched Hubble?”
4. Substitute only OpenAI HTTP transport, using the actual SDK and unchanged
   planning → query embedding → FAISS/BM25 → fusion → ten reranks → generation
   → citation-check code. The mock query vector has the cached dimension;
   generated text, rankings, latency, and answer quality are not benchmarks.
5. Check `/health` three times, submit `/ask`, and observe graceful lifespan
   shutdown. Require zero model requests at startup and during health checks,
   and unchanged index contents and modification time. Document-embedding
   requests are rejected before any transport, including in live mode.
6. Start a second fresh worker against the same writable cache copy and repeat.
   Both workers therefore test persisted warm caches, not ingestion from an
   empty cache. Cache JSON is still rewritten by the existing loader.
7. Write the report only after both runs succeed. Temporary caches, server logs,
   and isolated model-cost ledgers are cleaned up. Reports contain no keys,
   environment dumps, model prompts, or answer text.

`--idle-seconds`, `--sample-interval`, `--startup-timeout`, and
`--request-timeout` override the defaults (2, 0.01, 60, and 150 seconds).
The server retains `NASA_RAG_RESPONSE_TIMEOUT_SECONDS` (default 120); increasing
the controller's request timeout does not change that server deadline. Any
failed startup, HTTP check, cache reuse check, or forced shutdown fails the run.

## How to interpret the report

- `memory.<phase>.rss_peak_bytes` is the highest sampled RSS in that phase.
  Short spikes between samples may be missed. Means are sample averages over
  the specified window, not long-term traffic averages.
- `startup_os_peak_rss_bytes` is the worker's OS high-water mark at readiness.
  `question_os_lifetime_peak_rss_bytes` is the lifetime maximum after the
  question, including startup. `os_peak_rss_bytes` includes graceful shutdown.
  These high-water marks cannot be reset into independent phase peaks.
- RSS includes the real Python process, native indexes, SDK, and small mock/
  observation overhead. It excludes the controller and test runner. It does
  not reproduce real network/TLS buffers, retries, output sizes, or latency.
  The helper imports OpenAI eagerly to intercept its client; warm-only idle
  can exceed an ordinary worker that has not yet imported its provider SDK.
- On Linux with a readable cgroup v2, each phase also records actual
  `memory.current` sample mean/peak and `memory.peak`. The latter is a cgroup
  lifetime maximum and may predate this run; the script never resets it.
  Cgroup accounting includes page cache and all processes in that cgroup,
  potentially the controller and unrelated workloads. Inspect the recorded
  cgroup path and isolate the service before treating this as service usage.
  Unavailable counter reads do not interrupt RSS sampling. `cgroup_samples`
  shows successful counter reads; counter means use only those observations.
  Cgroup v1, unavailable counters, and macOS have no container observation;
  null means unavailable, not zero. Linux/container execution is still pending.
  See the [kernel's cgroup memory interface](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory).
- The OS `ru_maxrss` unit is normalized to bytes (macOS bytes; Linux KiB).
  RSS is process memory, not a Railway invoice metric. See the
  [psutil memory reference](https://psutil.readthedocs.io/en/latest/#psutil.Process.memory_info)
  and [Python resource reference](https://docs.python.org/3/library/resource.html#resource.getrusage).

## Recorded local observation

Raw evidence: [web-runtime-memory-local.json](web-runtime-memory-local.json).
Recorded 2026-10-30 UTC (2026-10-29 Pacific), macOS 26.5.2 x86_64, Python 3.13.7.
The report records exact library versions and corpus/cache fingerprints. Both
runs used the bundled four documents, 737 chunks, 1,536-dimensional supplied
embeddings, chunk/overlap 100/20, top K 30, ten fused/reranked candidates, and RRF
constant 60. Both started from the same compatible persisted cache copy.

| Process RSS, MiB | First start | Restart |
| --- | ---: | ---: |
| Startup peak, OS high-water mark | 258.41 | 258.52 |
| Loaded idle, sample mean | 258.43 | 258.55 |
| Question phase, sampled peak | 280.72 | 280.83 |
| Idle after question, sample mean | 280.72 | 280.83 |
| Entire run, OS high-water mark | 280.73 | 280.84 |

Each run recorded **zero startup requests, zero health model requests, and
13 mocked question requests**: one plan, one query embedding, ten reranks, and
one answer. Both reused their index without a rewrite. These are actual worker
RSS observations with mocked provider HTTP, not synthetic-cache file estimates.
The two-second idle windows and one question per process do not establish
steady-state behavior or a maximum under extended traffic.

Real provider-question benchmark: **pending separate authorization**.
Linux/container memory, deployed Railway metrics, and traffic-weighted average:
**pending; not measured**. No Railway resources were provisioned or deployed.

## Provisional Railway RAM-only estimate

Checked 2026-10-30 UTC (2026-10-29 Pacific): Railway publishes container RAM at
**$10 per GB-month** ($0.000231 per GB-minute). See
[Railway resource usage pricing](https://docs.railway.com/pricing/plans#resource-usage-pricing).
This is the container rate, not Railway's separate VM rate.

An illustrative full-month estimate is:

```text
RAM cost = average resident bytes / 1,000,000,000 × $10
```

Using decimal GB explicitly, the measured loaded idle windows imply
about **$2.71/month**. The retained idle after a question implies
about **$2.94/month**. These calculations assume continuously resident memory at
those short-window means. They are not a measured monthly average or invoice
prediction; service/container accounting and traffic must replace local RSS.
The cited pricing page labels GB without defining its byte conversion; using
GiB instead would give about $2.74 for retained idle. Confirm billed
units against deployed usage before treating the estimate as exact.

For capacity review, the largest observed OS peak was about **281 MiB**.
A **512 MiB limit is a candidate to validate**, giving about 231 MiB above that
local observation. It is not a verified production minimum. Retained memory,
container page cache, real requests, repeated traffic, and startup variance need
headroom. A peak limit is not the average-memory input to the cost calculation.

These are RAM-only figures. CPU, persistent cache storage, egress, subscription
minimums/included usage, and unrelated services are excluded and must be
considered separately for a total bill.

## Separately authorized live follow-up

After explicit authorization, supply `OPENAI_API_KEY` through the environment
and repeat the command with `--live` and a new output path. This performs
**two real questions**, one per worker, normally 26 question-model requests
before existing provider retries. It still requires compatible caches and
rejects new document-embedding requests. It preserves the pipeline/settings;
no model-price estimation or tuning is needed. The report remains provisional
until matched with actual deployment observations.

## Automated verification

```sh
uv run --extra web --extra dev --with psutil python -m pytest -q tests/test_web_runtime.py
uv run --extra web --extra dev --with psutil python -m pytest -q
uv run --extra web --extra dev ruff check scripts tests/test_web_runtime.py src/nasa_rag/web.py tests/test_web.py
uv run --extra web --extra dev --with psutil --with mypy mypy --follow-imports=silent --ignore-missing-imports --check-untyped-defs scripts/profile_web_runtime.py scripts/runtime_mock_provider.py src/nasa_rag/web.py
git diff --check
```

The command test creates a small synthetic embedding fixture (four dimensions)
to verify offline execution, distinct processes, cache reuse, HTTP smoke checks,
positive measured memory, and credential omission. Its figures are never used
for capacity/cost estimates. Without optional web/profiling dependencies the
corresponding tests skip; the base CLI installation remains unchanged.

Final verification: **132 tests passed** (including 47 API and three profiling
cases); the listed Ruff and mypy commands passed, and `git diff --check` passed.
Standards review found no issues. Spec review found one optional-counter/RSS
sampling defect, reproduced by a failing regression and fixed; both review
passes then reported no remaining findings.
