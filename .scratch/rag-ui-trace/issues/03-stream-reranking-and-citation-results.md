# 03: Stream reranking progress and citation results

**What to build:** Let an HTTP consumer follow evaluation of each candidate
passage, inspect the final evidence order and relevance reasons, and understand
the citation reference check that precedes the unchanged answer.

**Blocked by:** 02 — Expose planning and retrieval results.

**Status:** ready-for-agent

**Specification:** [PRD/TRD](../spec.md), especially reranking progress, passage
records, generation details, and citation-reference outcomes.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [ ] After each candidate has a successfully validated reranking response,
  emit one `stage.progress` with actual `completed` and `total` counts and that
  candidate's passage, score, reason, and fusion metadata. Do not hardcode ten
  when the actual candidate set is smaller.
- [ ] Progress results preserve evaluation order and do not claim a final rank.
  Reranking completion exposes the actual final sorted results with native
  rerank score, reason, final rank, and contributing fusion metadata, retaining
  existing tie behavior and one model call per evaluated candidate.
- [ ] Retain validated candidate results as `evaluated_results` in incomplete
  stage snapshots when a later evaluation fails or observation ends. Ticket 05
  verifies their preservation across complete deadline/disconnect scenarios.
- [ ] Generation completion exposes the ordered context references actually
  supplied from the reranked passages. Generation still uses the original
  visitor question and the existing instructions; it adds no explanatory call.
- [ ] Citation-check completion exposes `valid`, `warning`, or `no_citations`,
  plus checked and invalid reference arrays, using the existing citation-check
  logic rather than parsing warning text or adding another validator.
- [ ] Preserve the exact final answer, inline citations, insufficient-evidence
  content, and any appended warning. A warning or an answer without citations
  remains successful answer content. Do not present reference matching as
  factual verification or add an answerability classifier.
- [ ] Publish answer text only in the successful terminal event after citation
  checking. Do not expose an earlier raw answer or introduce answer-token
  streaming.
- [ ] Mocked HTTP tests verify progressive delivery while a later candidate is
  blocked, actual progress totals, final sorting, retained candidate results on
  failure, context-reference order, all three citation outcomes, exact answer
  preservation, and unchanged model-call counts.

## Slice boundary

This ticket adds backend data and progressive delivery only. Frontend passage
cards, reranking counters, citation messages, and answer presentation remain in
the separate handoff. Its partial results are prerequisites for the complete
failure snapshots in 05.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
