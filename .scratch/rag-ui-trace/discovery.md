# RAG website search flow discovery

Recorded 2026-11-06. This preserves discovery and user decisions; the
implementation-ready PRD/TRD is [spec.md](spec.md).

## Confirmed product decisions

- The feature is visitor-facing and should show each step in the flow of a RAG
  search.
- Stages update live while the search runs.
- The PRD/TRD covers both backend output and website behavior. The frontend work
  will be taken to the frontend repository by the user.
- Show the eight actual per-question stages, with a compact live timeline and
  expandable inputs/results relevant to each stage.
- Show reranking progress per passage, such as four of ten evaluated.
- Include stage durations, model names, model-call counts, token usage, and
  estimated cost, with unknown usage/cost represented honestly.
- Preserve completed results on failure and support manual retry when available.
  Explain when a deadline can leave backend work running.
- Deliver the full answer after generation and the existing citation reference
  check; answer-token streaming is outside this version.
- Keep search flow details in the current page only; no saved history or reload
  recovery.
- Validate through the existing HTTP application boundary with mocked model
  calls, plus a frontend test through its proxy. Prove early stage delivery,
  partial-result retention, and unchanged legacy `/ask` behavior.

## Current behavior and available data

- The web API returns only a request ID and the existing answer string.
- Each question runs retrieval planning, query embedding, FAISS retrieval, BM25
  retrieval, reciprocal rank fusion, model reranking, answer generation, and the
  existing citation-reference check.
- The retrieval plan already contains the rewritten query and optional source
  filter. There is no separate query-rewriting call in the planned web pipeline.
- Retrieval already produces chunk references and text, FAISS and BM25 scores,
  fusion scores and source ranks, and reranking scores and reasons. The web
  adapter discards the intermediate results.
- Default base result lists contain up to 30 chunks; ten fused candidates are
  reranked with one model call per candidate.
- Document loading, document embedding, and index preparation occur during
  server startup, rather than once per visitor question.
- The model ledger records usage and estimated costs, but HTTP requests do not
  have individual cost scopes or correlation with the request ID.
- Detailed pipeline/provider logs are suppressed in the web process. The web
  request log includes request ID, status, and overall elapsed time.
- Live events, stage timing, partial results on failure, and structured
  citation-check outcomes need new capture/instrumentation.
- The current citation check only identifies references outside retrieved
  chunks. It does not verify factual accuracy or require citations.
- The website/proxy implementation is outside this repository. Its actual
  transport behavior must be checked in the frontend repository before
  implementation there.

## Engineering decisions captured in the specification

The specification selects an additive POST streaming endpoint, SSE framing read
with Fetch, request-scoped telemetry, and shared admission controls. These are
engineering decisions supporting the agreed behavior, rather than claims that
the user selected a specific wire format.

## Sources

- [Search CLI and logging reference](../../docs/search-cli.md)
- [Existing web API contract](../../docs/web-api.md)
- [Original API scope and deferred progress feature](../../docs/fastapi-service-plan.md)
- [Web pipeline and request lifecycle](../../src/nasa_rag/web.py)
- [Retrieval orchestration](../../src/nasa_rag/retrieval/retriever.py)
- [Shared retrieval data](../../src/nasa_rag/models.py)
- [Cost ledger and run scopes](../../src/nasa_rag/model_costs.py)

## Comments

- 2026-11-06: User confirmed visitor-facing search steps, live stage updates, and
  a combined backend/frontend specification with frontend work handed to its
  own repository. No implementation requested in this discovery phase.
- 2026-11-06: User answered "yes to all" for stage details, metrics, partial
  failures, whole-answer delivery, and current-page-only retention.
- 2026-11-06: User accepted the proposed HTTP/proxy acceptance checks with
  "looks good". Product discovery is complete for this specification.
