# Public search stream fixtures, version 1

These UTF-8 files are backend-produced wire examples for the separate frontend
reader and UI. They contain synthetic questions, passages, reasons and answers,
without credentials or real visitor content. No provider calls are needed to
read or use them. The real retrieval/generation/citation pipeline runs with
mocked provider responses when producing/checking them.

| File | Expected use |
| --- | --- |
| [success.sse](success.sse) | All eight stages, four rerank progress events in evaluation order, different final rerank order, known metrics, valid citations, one terminal answer. |
| [citation-warning.sse](citation-warning.sse) | Successful answer with the existing appended citation warning and structured invalid references. |
| [no-citations.sse](no-citations.sse) | Successful uncited answer; informational `no_citations` outcome. |
| [unknown-usage.sse](unknown-usage.sse) | Null applicable usage, unknown-cost calls and incomplete cost; zero known subtotal does not mean free work. |
| [stage-failure.sse](stage-failure.sse) | Actual malformed second rerank result: one validated candidate retained, `stage.failed`, terminal 502 equivalent, later stages skipped. |
| [timeout-unfinished.sse](timeout-unfinished.sse) | Second rerank call blocked: partial results, unknown unfinished stages, terminal 504 equivalent, continuing work. Recorded cost is complete while overall work is unfinished. |
| [pre-stream-rejection.http.json](pre-stream-rejection.http.json) | HTTP status, selected response headers and body for JSON validation rejection on either question route. Never parse as SSE. |

Every `.sse` response has HTTP 200, `Content-Type: text/event-stream;
charset=utf-8`, `Cache-Control: no-cache, no-transform`, and `X-Request-ID`
matching the envelopes, without a fixed content length. The full
[contract](../../web-stream-contract.md) defines envelope/event fields and
failure rules; [API tables](../../web-api.md#live-search-flow-stream) define
stage details and metrics.

Only volatile values are normalized: `request_id` is
`00000000-0000-4000-8000-000000000001`, `timestamp_utc` is
`2026-11-09T00:00:00+00:00`, and `elapsed_ms`/`duration_ms` are `0.0`.
Zero durations here are test normalization, not runtime measurements. No result,
usage, cost, error, state, sequence, or model-name fields are filled in or
invented. Shared fixture IDs do not imply replay or stable IDs across real runs.

The fixtures preserve server LF framing and JSON field order. A frontend test
can split their bytes at arbitrary positions (including within `Ω`), combine
frames into one read, or transform LF to CRLF to exercise its reader. Inject
SSE comment heartbeats (`: heartbeat\n\n`), unknown additive fields/events,
unsupported versions, malformed required data, sequence conflicts/gaps, and
truncated EOF in reader tests. Those are deliberate FE test transformations,
not additional claims about backend output. An EOF cut before a terminal is
interruption. No test should trigger automatic retries or repeat paid work.

Normal checks compare every normalized frame against actual server
serialization. The success fixture is consumed incrementally over loopback TCP
while generation is blocked; timeout also uses real loopback HTTP. Other
outcomes use the public HTTP adapter via TestClient. Existing lifecycle tests
cover exact queue bounds, transport loss, detachment and late worker behavior.

```sh
uv sync --locked --extra web --extra dev --extra profile
uv run --no-sync python -m pytest -q tests/test_stream_contract.py
```

After an intentional contract/provider-example change, regenerate explicitly,
review the resulting fixture diff, then rerun without the update flag:

```sh
uv run --no-sync python -m pytest -q tests/test_stream_contract.py --update-stream-fixtures
uv run --no-sync python -m pytest -q tests/test_stream_contract.py
```

Loopback socket access is required. These checks make no paid model calls.
CI's existing full pytest job includes them without the update flag, so drift
fails verification. Backend results do not replace the outstanding
browser-through-deployed-proxy check in the
[frontend handoff](../../../.scratch/rag-ui-trace/frontend-handoff.md).
