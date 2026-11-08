# 02: Expose planning and retrieval results

**What to build:** Let an HTTP consumer inspect how a question was interpreted
and which passages semantic search, keyword search, and fusion selected. Return
the actual pipeline's structured results with the live stage events.

**Blocked by:** 01 — Stream a question's live search stages.

**Status:** ready-for-agent

**Specification:** [PRD/TRD](../spec.md), especially stage completion details and
passage/ranking records.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [ ] Planning completion exposes the actual `search_query` and optional
  `source_file_filter` used by retrieval. Invalid model-created plans fail the
  planning stage rather than being reported as successful plans.
- [ ] Embedding completion exposes the requested embedding model and actual
  vector dimensions, without returning embedding vectors or raw provider
  response objects.
- [ ] Semantic and keyword completion events expose their actual ordered result
  lists, bounded to 30 each under the agreed web defaults, with source filename,
  zero-based chunk index, printable reference, full chunk text, one-based rank,
  and the method's native score fields.
- [ ] Fusion completion exposes the actual RRF constant and up to ten selected
  candidates with fusion score, final fusion rank, and contributing FAISS/BM25
  ranks. Source ranks can exceed the exposed base-list lengths.
- [ ] Fusion still uses the full eligible rankings. Inspection bounds and
  serialization do not alter filtering, ranking ties, candidate selection, or
  the passages later supplied to reranking and generation.
- [ ] Serialize explicit allowed fields with finite JSON numbers. Snapshot
  results when published so subsequent mutation of shared chunk objects cannot
  change prior events or retained stage details.
- [ ] Completed stage snapshots in terminal events agree with their live detail
  events. Previously completed retrieval results survive a later controlled
  pipeline failure using the lifecycle established in 01.
- [ ] Mocked HTTP tests cover source restrictions, exact native scores/ranks and
  passage references, full-ranking fusion versus bounded inspection lists,
  immutable snapshots, and absence of vectors or unintended provider fields.
  Tests verify existing retrieval results and model-call counts stay unchanged.

## Slice boundary

Expose retrieved passages as candidates, without claiming that every returned
passage is cited or proves the answer. UI expansion, excerpt presentation, and
score labels belong to the separate frontend handoff. Ticket 03 extends these
same passage records for reranking and generation context.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
