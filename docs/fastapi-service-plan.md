# FastAPI service — high-level implementation scope

Status: initial demo plan recorded, 2026-10-28. No application implementation or deployment is authorized by this document.

This expands item 1 of the portfolio demo plan: expose the existing Python RAG pipeline through a FastAPI service. The user requested sensible defaults for the remaining items because this is a small demo. Preserve the decisions already agreed; use the defaults below instead of continuing an exhaustive design interview. This remains documentation only.

## Established context

- The portfolio demo will be public, with a question box inside the NASA RAG project card.
- The agreed submission limit is 10 per IP address per 10 minutes.
- Answer caching is deferred. Document embeddings and the search-index cache remain part of the design.
- A global daily quota is deferred from the initial demo. The earlier 50-attempt proposal was never confirmed. Retain the agreed per-IP submission limit.
- Railway deployment and the portfolio UI are separate workstreams; this document focuses on the Python API.
- Endpoint capabilities agreed on 2026-10-28: independent questions, the four bundled source documents, and the current full hybrid pipeline. Verify the pipeline description with the user before implementation; no retrieval-setting changes have been approved.
- OpenAI pricing is not a concern for this effort. Keep the existing pipeline; do not add model-cost optimization work. The hosting-cost investigation should focus on Railway resource usage, especially RAM.

## Scope boundary

Clarified by the user on 2026-10-28: this work exposes the existing RAG project through FastAPI. Preserve its retrieval, ranking, generation, insufficient-evidence responses, and citation-validation behavior. Leave existing RAG and CLI source modules unchanged. Add the HTTP adapter, web tests, and the packaging/configuration needed to run the adapter. API request validation, HTTP representation, service lifecycle, and execution/admission controls are in scope. New RAG filtering, evidence thresholds, stricter citation acceptance, automatic regeneration policies, and existing-project refactors are not.

## Small-demo defaults for the remaining API work

These defaults were reviewed with the user after their request to simplify the remaining items. They do not reopen the earlier API/RAG decisions or authorize implementation/deployment.

| Item | Initial default |
| --- | --- |
| Startup and health | Load once during backend startup. Fail startup if required configuration or retriever initialization fails. Add one `GET /health` endpoint that returns 200 once initialized; health requests do not run the pipeline. No separate liveness/readiness subsystem or startup retry manager. |
| Waiting, disconnects, shutdown | Start with a configurable 120-second HTTP response deadline. Do not add automatic pipeline retries or custom cancellation/job recovery. If a visitor disconnects or the response times out, let existing work finish and keep the busy slot occupied until it actually ends. Use normal server shutdown; interrupted work is not resumed after restart. |
| Submission limiting | Keep 10 submissions per IP per 10 minutes with a small in-memory limiter and expired-entry cleanup. Counters reset on restart. No database/Redis, persistent counters, or global daily quota initially. |
| Access boundary | Target a private backend reached through the portfolio's same-origin proxy. No visitor login or separate authentication system. No CORS configuration is needed for that same-origin path. Trust client-IP forwarding only from the configured proxy; verify that forwarding during integration. Proxy/network deployment remains a separate workstream. |
| Installation and configuration | Add a small web adapter and optional FastAPI/Uvicorn dependencies. Use one server worker and environment configuration for credentials, port, cache location, and response deadline. Keep existing RAG/CLI modules unchanged. |
| Logs | Use standard server logs plus request ID, status, and elapsed time. Keep full question/context text and credentials out of routine web logs. No metrics platform, dashboards, distributed tracing, or separate monitoring service. |
| Verification | Add a small set of mocked HTTP tests covering the contract, validation, startup reuse/health, busy/rate-limit responses, deadline/failure handling, and unchanged answer strings. Keep the existing project's tests. Retain the agreed RAM measurement task for Railway pricing. |

These defaults are enough to prepare a small demo. Adjust the response deadline if actual latency measurements justify it. Increased concurrency, durable limits, and other operational machinery can be reconsidered if real use requires them.

## Current code to reuse

The package currently exposes a CLI, with orchestration in `src/nasa_rag/search.py`:

- `RetrievalPlanner.infer()` produces a search query and optional source restriction.
- `Retriever.search_faiss_bm25_rrf_and_rerank()` runs hybrid retrieval, fusion, and reranking. Passing the planner's search query avoids rewriting it again.
- `generate_rag_answer()` builds the context, generates an answer, and checks citation references.
- The corpus has four source files: `hubble.txt`, `iss.txt`, `nasa_overview.txt`, and `space_shuttle.txt`.

The full pipeline currently makes 13 OpenAI calls per question with ten rerank candidates, excluding ingestion and retries. Shared document result objects are mutable. Cached document embeddings are rewritten on warm loads, so the runtime cache path must be writable.

## Current full pipeline — code verification

The combined CLI path in `src/nasa_rag/search.py` currently does the following:

1. `RetrievalPlanner.infer(question)` rewrites the question into a search query and optionally chooses one of the available source files.
2. `Retriever.search_faiss_bm25_rrf_and_rerank(...)` receives that planned query, avoiding another rewrite call.
3. The retriever embeds the planned query for FAISS and tokenizes it for BM25. Both methods produce rankings over the corpus, restricted by the source filter when present.
4. Reciprocal rank fusion combines the full rankings using `rrf_k=60`, then keeps ten candidates by default. The top-30 lists returned for CLI display are separate from the full rankings used for fusion.
5. The reranker scores each of those candidates against the original question, with one sequential model call per candidate, and sorts the results by relevance.
6. `generate_rag_answer(question, reranked_chunks)` builds the context from the reranked chunks, generates the answer, and checks citation references against those chunks. Currently an unrecognized citation appends a warning; this is not a guarantee that every claim is supported.

The plain CLI defaults to semantic search. The full combined-and-generation path requires both `--both-searches` and `--generate-answer`.

Relevant source files to review in the NASA repository:

- `src/nasa_rag/search.py`
- `src/nasa_rag/retrieval/retrieval_planner.py`
- `src/nasa_rag/retrieval/retriever.py`
- `src/nasa_rag/retrieval/reranker.py`
- `src/nasa_rag/generation/generator.py`

Verification here was by reading the code, without running model requests. Source code is the authority if the pipeline changes later.

## Line items to settle

### 1.1 Define the first endpoint's capabilities

Decide whether requests are independent questions or conversational turns, which corpus is available, and which retrieval pipeline the service exposes.

Agreed: independent question answering over the bundled corpus, using the current planning → hybrid retrieval → fusion → reranking → generation pipeline. Review the verified sequence above before implementation. Cost/latency tuning is a later decision, rather than an approved change to this pipeline.

### 1.2 Define the HTTP contract

Specify the API's route, accepted question format, HTTP validation boundaries, response representation, and request identifier. Pass through the pipeline's existing answers and warnings without imposing new RAG policies.

Agreed on 2026-10-28:

- The initial request contains only a question. Model choice, retrieval settings, and corpus access are controlled by the service for now.
- Return one complete JSON response when processing finishes. The initial version does not stream responses or progress events.
- Return a minimal success object with `request_id` and `answer`. Set `answer` to the existing pipeline string unchanged, including inline citation references and any existing warning. A separate source/excerpt array is deferred.
- Require a nonblank question of at most 1,000 characters and reject unsupported request fields instead of silently ignoring them.
- Use an unversioned `POST /ask` endpoint as the demo default. The portfolio's external path mapping is separate. This changes API versioning only, not the earlier public-demo access decision.
- Use HTTP statuses 422 for request validation, 429 for submission/quota limits, 503 for busy/not-ready service, 502 for upstream provider failures, 504 for response deadlines, and 500 for unexpected server faults. Normal pipeline answer content and citation warnings are not HTTP errors. Public failures omit stack traces and secrets.
- Return HTTP failures as `request_id` plus an `error` object containing a machine-readable `code` and public `message`, with the agreed status code.

Agreed initial request shape:

```json
{ "question": "What powers the ISS?" }
```

Agreed initial success response shape:

```json
{
  "request_id": "<server-generated request identifier>",
  "answer": "<existing pipeline answer string, unchanged>"
}
```

The response can be extended in the future. Do not add structured source records or full excerpts to the initial payload.

Verified existing output:

- `generate_answer()` returns the model's answer as one string.
- `generate_rag_answer()` returns that string after the existing citation check, including any appended warning. Source references such as `[iss.txt, chunk 2]` appear inline in the answer text.
- Full source excerpts and a structured source list are not automatically included in that returned string. They exist separately as context chunk metadata (`source`, `chunk_index`, `text`).
- CLI planning/search/ranking printouts are separate diagnostics, not part of the answer return value.
- Existing tests cover unchanged valid/absent citations, an appended invalid-citation warning, and the string return value of `generate_rag_answer()`.

If a separate source/excerpt array is added later, serialize existing context metadata rather than modify the RAG pipeline. Describe such records as retrieved context rather than a claim that every passage is cited by or proves the answer. The supported fields and any UI use will be designed as part of that future change.

Q5 and Q6 introduced proposals beyond the requested API wrapper and were not approved:

- Do not introduce cited-only source filtering as part of this work.
- Do not withhold a pipeline answer or turn a citation warning into an HTTP error.

`generate_rag_answer()` already returns a string after applying `validate_answer_citations()`. Return that answer string unchanged, including any warning it appends for unknown citations. Preserve existing insufficient-evidence answers as normal pipeline output. Do not add a second citation validator or a new answerability classifier. Citation-reference validation is not a factual verification of every claim in an answer.

Future options requested by the user:

- Explore end-user control over settings beyond the question. Which options are exposed, their allowed values, and their cost implications remain to be designed; these controls are not part of the first version.
- Add streamed processing/progress states later. Decide during that work whether to also stream answer tokens; progress events and answer-token streaming are separate choices.
- Revisit a separate source/excerpt array when the UI needs it. The initial response remains `request_id` plus the unchanged answer string.

Use `POST /ask` as the default route spelling. The minimal success envelope, machine-readable error shape, and HTTP status distinctions are agreed; the version prefix was declined.

Q10–Q12 discussion status:

10. Agreed: the JSON error envelope described above.
11. Agreed after clarification: initialize the existing retriever once per backend process start. This means starting the Python API service on Railway, not loading a page in a visitor's browser. The user prefers keeping it running if hosting cost is acceptable; hosting sleep/always-on configuration remains a separate deployment decision.
12. Agreed: admit one active pipeline request initially, returning 503 for concurrent submissions instead of maintaining an unlimited queue. Revisit the concurrency limit in the future if needed. A single service process/worker is proposed to enforce this initial limit; execute synchronous work outside the event loop so the web server remains responsive.

### 1.3 Connect the HTTP layer to the existing pipeline

Define a small adapter that calls the existing Python functions in the established sequence and returns their existing outputs as HTTP data. Keep this integration in the new web layer; do not extract or rewrite existing CLI, retrieval, or generation modules.

Demo default: call the existing pipeline functions directly from an adapter, with no parsing of printed CLI output and no duplicate query-rewriting call.

### 1.4 Define startup, readiness, and resource ownership

Specify how the application creates clients, loads the retriever, locates the corpus/cache, becomes ready, and shuts down. Decide what happens when configuration is missing or initialization fails.

Agreed: load the existing retriever once per backend process start and reuse it across subsequent questions. Demo defaults: an explicit writable cache location, fail startup if initialization fails, and one health endpoint that reports success only after initialization. No embedding calls during package import or image build.

Startup terminology for Q11:

- **Page load:** a visitor opens the portfolio. This does not initialize the Python retriever or submit a question.
- **Backend process start:** the Python API starts after deployment, restart, or another hosting lifecycle event. Load the existing retriever and compatible cached document/index data once at this point, then keep that retriever in memory while the process runs.
- **Question submission:** the web handler uses the initialized retriever to run the existing pipeline for that question. The service does not continuously generate answers while idle.
- **Hosting lifecycle:** whether Railway keeps the process running or allows idle sleeping remains a separate deployment decision. Any new process start must initialize its in-memory resources again. Persistent document caches can be reused; do not equate reloading them into memory with re-embedding an unchanged compatible corpus.

Hosting cost reference, checked 2026-10-28:

- Railway lists ordinary service RAM at $10 per GB-month, CPU at $20 per vCPU-month, volume storage at $0.15 per GB-month, and network egress at $0.05 per GB. These are usage rates, not a fixed price for the API.
- Hobby is $5/month including $5 of resource usage. That allowance is shared across the account's resources; it is not a separate $5 charge for each service.
- Holding 0.25, 0.5, or 1 GB of RAM throughout a month would therefore cost approximately $2.50, $5, or $10 in RAM alone. CPU, storage, and egress are additional usage components.
- A provisional always-on hosting budget for a lightly used demo is $5–$15/month, assuming roughly 0.25–1 GB of actual RAM use and modest CPU/network usage. This is a planning scenario, not a measured estimate for this application; actual loaded-process memory and CPU have not been profiled.
- OpenAI requests and any other Railway applications are separate considerations. Keeping this API idle does not continuously issue model requests.
- Verify current rates and measure the deployed service before committing to a firm operating budget. Hosting settings, spending limits, and deployment are not authorized by this cost note.

References: [Railway resource pricing](https://docs.railway.com/pricing), [plan allowances](https://docs.railway.com/pricing/plans).

Required measurement before settling the Railway hosting budget:

- Profile the intended single-process service with the current corpus and existing pipeline settings loaded.
- Record steady-state idle memory after initialization, peak memory during startup, and peak memory during representative question processing. Record both process RSS and deployed service/container memory when available; local measurements are provisional until checked against the deployment.
- Use steady-state/representative average memory to estimate recurring always-on RAM cost at Railway's current published rates. Use startup/request peaks separately to choose sufficient memory headroom.
- Record the measurement environment and results alongside the hosting estimate, replacing the provisional $5–$15 range with evidence once measured.
- This is a future measurement task. No benchmark, paid model request, implementation, or deployment is being run as part of writing this plan. OpenAI price estimation is not required.

### 1.5 Bound execution and admission

Define how requests interact with the shared retriever, submission limits, daily quota, deadlines, retries, disconnects, and busy responses.

Agreed: one active pipeline request initially, without an unlimited queue; concurrent submissions receive 503. Future option: revisit this limit if demand requires it. The existing project stays unchanged during this API work, so increased concurrency will need a separate compatibility review.

Demo default: one service process/worker, with synchronous pipeline work outside the event loop. Do not release its processing slot while underlying work is still running. A web-response timeout must not be mistaken for cancellation of the underlying synchronous pipeline. Do not add pipeline retries or change core model-client behavior as part of HTTP handling. Apply the in-memory per-IP limit; omit the unconfirmed daily quota and persistent counters from the initial demo. See the small-demo defaults for the HTTP waiting deadline and disconnect behavior.

### 1.6 Define installation and runtime configuration

Specify web dependencies, a runnable service entry point, environment-based configuration, and which settings callers can control.

Demo defaults: optional FastAPI/Uvicorn web dependencies, one server worker, and server-held credentials. Use environment configuration for the port, cache location, and 120-second response deadline. Keep the existing model/retrieval settings unchanged. Exact environment-variable names and module layout are routine implementation details.

### 1.7 Define failure handling and operational visibility

Specify HTTP responses for invalid input, unavailable/busy service, provider failures, and deadlines. Define request IDs and usage/latency records without exposing secrets or internal tracebacks. Existing pipeline answers about insufficient evidence and embedded citation warnings remain answer content rather than new HTTP failure categories.

Demo defaults: stable machine-readable errors and metadata-focused web logging. Configure logging at the web application boundary so existing prompt/context-bearing RAG INFO logs are not enabled in production. Leave the existing project's logging statements unchanged.

### 1.8 Define the verification boundary

Specify tests for the HTTP contract, orchestration, startup reuse, cache reuse, admission rules, failures, and cancellation behavior. Verify the minimal JSON envelope and unchanged pass-through of pipeline answer strings, including existing citation warnings. Structured source/excerpt response tests belong to the deferred payload extension. Preserve existing CLI/retrieval tests without introducing stricter RAG-quality policies.

Demo defaults: automated tests mock paid model calls. A small, explicitly authorized live benchmark later verifies the adapter's model access, response latency, and deployment compatibility. Measure loaded/idle, startup-peak, and request-peak RAM for Railway pricing and capacity planning as described in 1.4. OpenAI price estimation and RAG-quality/pipeline tuning are not required by this API-layer work.

## Discussion order

The high-level capabilities in 1.1 and the initial API contract are agreed. The remaining operational choices use the small-demo defaults above. No further exhaustive question rounds are needed before preparing the adapter implementation. A user review of the recorded pipeline is still welcome; existing RAG code and behavior remain unchanged regardless. Implementation and deployment still require a separate user request.

## Deferred work

Portfolio component implementation, Caddy routing, Railway provisioning/deployment, answer caching, and changes to RAG answer/evidence policy are outside this item's implementation scope. Their integration requirements should inform the API contract, but they are not deliverables of this document. Streaming, richer source responses, user-selectable settings, increased concurrency, global daily quotas, and persistent/distributed request counters remain future options.
