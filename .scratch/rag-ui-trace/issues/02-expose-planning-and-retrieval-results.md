# 02: Expose planning and retrieval results

**What to build:** Let an HTTP consumer inspect how a question was interpreted
and which passages semantic search, keyword search, and fusion selected. Return
the actual pipeline's structured results with the live stage events.

**Blocked by:** 01 — Stream a question's live search stages.

**Status:** resolved

**Specification:** [PRD/TRD](../spec.md), especially stage completion details and
passage/ranking records.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [x] Planning completion exposes the actual `search_query` and optional
  `source_file_filter` used by retrieval. Invalid model-created plans fail the
  planning stage rather than being reported as successful plans.
- [x] Embedding completion exposes the requested embedding model and actual
  vector dimensions, without returning embedding vectors or raw provider
  response objects.
- [x] Semantic and keyword completion events expose their actual ordered result
  lists, bounded to 30 each under the agreed web defaults, with source filename,
  zero-based chunk index, printable reference, full chunk text, one-based rank,
  and the method's native score fields.
- [x] Fusion completion exposes the actual RRF constant and up to ten selected
  candidates with fusion score, final fusion rank, and contributing FAISS/BM25
  ranks. Source ranks can exceed the exposed base-list lengths.
- [x] Fusion still uses the full eligible rankings. Inspection bounds and
  serialization do not alter filtering, ranking ties, candidate selection, or
  the passages later supplied to reranking and generation.
- [x] Serialize explicit allowed fields with finite JSON numbers. Snapshot
  results when published so subsequent mutation of shared chunk objects cannot
  change prior events or retained stage details.
- [x] Completed stage snapshots in terminal events agree with their live detail
  events. Previously completed retrieval results survive a later controlled
  pipeline failure using the lifecycle established in 01.
- [x] Mocked HTTP tests cover source restrictions, exact native scores/ranks and
  passage references, full-ranking fusion versus bounded inspection lists,
  immutable snapshots, and absence of vectors or unintended provider fields.
  Tests verify existing retrieval results and model-call counts stay unchanged.

## Slice boundary

Expose retrieved passages as candidates, without claiming that every returned
passage is cited or proves the answer. UI expansion, excerpt presentation, and
score labels belong to the separate frontend handoff. Ticket 03 extends these
same passage records for reranking and generation context.

## Answer

Implemented planning, embedding, semantic-search, keyword-search, and fusion
completion details through the existing observation seam. `StageDetails` uses
explicit field serializers and immutable finite JSON snapshots; the same
snapshots feed live events and retained terminal stage details. Invalid provider
plans, including missing/extra fields, fail planning before retrieval starts.

Retrieval still uses the full eligible rankings and the original selection/tie
behavior. HTTP tests demonstrate 30-item inspection bounds with selected fusion
candidates whose source ranks reach 40, unchanged reranking/generation inputs,
unchanged model calls and answers, source restrictions, native scores, field
exclusion, rejection of nonfinite scores, and retained snapshots after shared
chunk mutation or later failure. See the updated
[development-slice API documentation](../../../docs/web-api.md#live-search-stages-development-slice).

Verification (mocked providers; no paid calls):

- `.venv/bin/python -m pytest -q tests/test_web_stream.py`: **32 passed**.
- `.venv/bin/python -m pytest -q`: **181 passed**.
- Ruff formatting and lint on changed Python files: **passed**.
- mypy on all six changed source modules, with the existing
  `--follow-imports=silent --ignore-missing-imports --check-untyped-defs` flags:
  **passed**; `git diff --check`: **passed**.

Standards review: **0 hard violations; 0 actionable smell findings**. The changes
follow tracker/domain conventions; HTTP fault injection keeps real retrieval
calculations intact, and snapshot serializers centralize the public fields.

Spec review: **0 findings**. All ticket 02 requirements are covered. Later
tickets' reranking/citation details, usage, and complete interruption contract
remain deferred; the full frontend contract stays gated on ticket 06.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
- 2026-11-09: User approved implementation on
  `implement/rag-ui-trace-ticket-02`, based on main `60671a3`. Tests use the
  agreed public HTTP boundary with mocked providers and temporary corpus/cache.
- 2026-11-09: Completed after standards/spec reviews and 181 passing tests.
  Ticket 03 is now unblocked.
