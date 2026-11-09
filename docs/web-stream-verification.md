# Backend stream verification

Recorded: 2026-11-09. Scope: ticket 06, version-1 backend contract readiness.
Providers are mocked; no paid model calls, deployment, or website changes occur.

## Reproduce

From the repository root, install the locked optional dependencies and run:

```sh
uv sync --locked --extra web --extra dev --extra profile
uv run --no-sync python -m pytest -q tests/test_stream_contract.py tests/test_web_stream.py tests/test_web_lifecycle.py
uv run --no-sync ruff check scripts tests/test_web_runtime.py tests/conftest.py tests/stream_support.py tests/test_stream_contract.py tests/test_web_stream.py
uv run --no-sync mypy --follow-imports=silent --ignore-missing-imports --check-untyped-defs scripts tests/conftest.py tests/stream_support.py tests/test_stream_contract.py
uv run --no-sync python -m pytest -q
git diff --check
```

Run with permission to bind loopback sockets. Each test uses temporary caches
and ledgers, controlled provider gates, and synthetic data. The verification
run used the equivalent `.venv/bin/python`, `.venv/bin/ruff`, and
`.venv/bin/mypy` commands against the installed environment. Fixture checks
run without `--update-stream-fixtures`; normal runs fail if examples drift.
Explicit regeneration instructions live beside the fixtures.

## Evidence

| Boundary | Repeatable evidence |
| --- | --- |
| Complete live HTTP contract | `test_complete_contract_arrives_live_over_loopback` receives 18 application events through a real TCP connection before releasing blocked generation: admission, the first six completed stages, four rerank progress events, and generation start. Health stays responsive and both question routes return busy. After release it consumes through EOF, checks all eight stages, native detail fields, final rerank/context order, metrics, UUID/header correlation, contiguous sequences, timestamps, snapshots, and exactly one terminal answer. |
| Fixture agreement | `test_public_outcome_fixtures_match_server`, `test_pre_stream_json_rejection_fixture`, success and timeout tests compare all normalized serialized frames/JSON to the committed public examples. Known values are real pipeline results from mocked providers; only identity/time vary. |
| Partial timeout and late work | `test_timeout_fixture_freezes_partial_work_while_late_usage_and_slots_recover` blocks the second rerank provider call over loopback HTTP. The timeout retains one validated candidate and completed retrieval stages, marks unfinished stages unknown, counts only three recorded calls, and reports continuing work. Both routes stay busy until release, then both admit new work. The old snapshot remains unchanged; seven eventual call records retain the original run/request ID. |
| Real failure and citation behavior | Outcome fixtures cover malformed rerank output after one successful candidate, a sanitized 502 equivalent, skipped later stages, citation warning text, no-citation success, valid citations, and unknown usage/cost. Existing stream tests retain full-ranking fusion, original question/answer preservation, validated model outputs, usage/pricing, and all three citation outcomes. |
| Early progress and heartbeat | Existing loopback tests receive a candidate before a later candidate finishes and receive an active stage plus heartbeat while generation is blocked. These are incremental observations, not collected-body timing claims. |
| Detachment and buffering | Existing HTTP/ASGI lifecycle tests deterministically exercise disconnect/cancellation, slow/absent consumers on either side of the exact 64-event queue bound, failed terminal delivery, serialization/encoding failure, terminal/deadline ordering, late provider exceptions/accounting, recovery on both routes, and shutdown waiting for work. ASGI backpressure checks supplement TCP checks without relying on OS send-buffer size. |
| Compatibility | The full suite includes legacy JSON/health behavior, both-route admission/trust/deadline/disconnect handling, CLI/library callers, evaluation runners, retrieval/reranking, citation validation/warnings, pricing, and mocked runtime profiling. Production pipeline code and rates are unchanged by ticket 06. |

The [public fixture directory](fixtures/search-stream-v1/README.md) includes six
SSE examples and one JSON rejection, with generation/check commands. The
[implemented API contract](web-stream-contract.md) and
[API detail/metric tables](web-api.md#live-search-flow-stream) accompany the
[frontend handoff](../.scratch/rag-ui-trace/frontend-handoff.md).

## Results

- Focused stream/contract/lifecycle checks: **81 passed**.
- Full mocked regression suite: **230 passed** (37.56 seconds).
- Ruff on new/changed tests plus the CI verification scripts/runtime test: passed.
- mypy on new support/contract tests, conftest, and CI scripts: passed, 8 files.
- Local documentation links, Python formatting, and complete diff whitespace checks: passed.
- Separate code reviews: Standards **0 findings**; Spec **0 findings**.

The final review is recorded in
[ticket 06](../.scratch/rag-ui-trace/issues/06-verify-and-document-stream-contract.md).

## Frontend acceptance still outstanding

Loopback HTTP proves backend incremental delivery. It does not verify the
website's actual hosting runtime or any deployed proxy hop. The FE team must
still check immediate forwarding, absent buffering/delaying transformations,
preserved IDs/JSON errors/visitor trust, sufficient response lifetime, and
downstream-disconnect behavior through the deployed proxy to the browser.
Reader chunk/UTF-8/framing handling, timeline presentation, safe rendering,
accessibility, and manual-retry behavior remain FE acceptance work.

Roll out the additive backend before enabling that UI. Keep legacy JSON for
future submissions and rollback; never automatically repeat an admitted search
as a JSON fallback. The handoff packages these references and fixtures without
performing deployment or modifying the frontend repository.
