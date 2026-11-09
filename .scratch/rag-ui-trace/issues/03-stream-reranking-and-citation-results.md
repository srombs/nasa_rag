# 03: Stream reranking progress and citation results

**What to build:** Let an HTTP consumer follow evaluation of each candidate
passage, inspect the final evidence order and relevance reasons, and understand
the citation reference check that precedes the unchanged answer.

**Blocked by:** 02 — Expose planning and retrieval results.

**Status:** resolved

**Specification:** [PRD/TRD](../spec.md), especially reranking progress, passage
records, generation details, and citation-reference outcomes.

**Scope:** NASA RAG backend only. Frontend implementation is a separate handoff.

## Acceptance criteria

- [x] After each candidate has a successfully validated reranking response,
  emit one `stage.progress` with actual `completed` and `total` counts and that
  candidate's passage, score, reason, and fusion metadata. Do not hardcode ten
  when the actual candidate set is smaller.
- [x] Progress results preserve evaluation order and do not claim a final rank.
  Reranking completion exposes the actual final sorted results with native
  rerank score, reason, final rank, and contributing fusion metadata, retaining
  existing tie behavior and one model call per evaluated candidate.
- [x] Retain validated candidate results as `evaluated_results` in incomplete
  stage snapshots when a later evaluation fails or observation ends. Ticket 05
  verifies their preservation across complete deadline/disconnect scenarios.
- [x] Generation completion exposes the ordered context references actually
  supplied from the reranked passages. Generation still uses the original
  visitor question and the existing instructions; it adds no explanatory call.
- [x] Citation-check completion exposes `valid`, `warning`, or `no_citations`,
  plus checked and invalid reference arrays, using the existing citation-check
  logic rather than parsing warning text or adding another validator.
- [x] Preserve the exact final answer, inline citations, insufficient-evidence
  content, and any appended warning. A warning or an answer without citations
  remains successful answer content. Do not present reference matching as
  factual verification or add an answerability classifier.
- [x] Publish answer text only in the successful terminal event after citation
  checking. Do not expose an earlier raw answer or introduce answer-token
  streaming.
- [x] Mocked HTTP tests verify progressive delivery while a later candidate is
  blocked, actual progress totals, final sorting, retained candidate results on
  failure, context-reference order, all three citation outcomes, exact answer
  preservation, and unchanged model-call counts.

## Slice boundary

This ticket adds backend data and progressive delivery only. Frontend passage
cards, reranking counters, citation messages, and answer presentation remain in
the separate handoff. Its partial results are prerequisites for the complete
failure snapshots in 05.

## Implementation and verification

Validated candidate results now publish immutable progress snapshots in evaluation
order, with actual totals and no final rank. Reranking completion exposes the
existing sorted results with final ranks. Failed or interrupted observations
retain prior candidates in `evaluated_results`. Generation completion identifies
the supplied context in order. A shared citation reference check supplies both
structured outcomes and the existing appended warning without a second parser
or model call. Answer text remains exclusive to terminal success.

Offline verification (mocked providers; no paid calls):

- `.venv/bin/python -m pytest -q tests/test_web_stream.py`: **39 passed**,
  including real loopback progressive delivery with a later candidate blocked.
- `.venv/bin/python -m pytest -q`: **188 passed**.
- Ruff on the changed modules/tests and CI verification scripts: **passed**
  with the four existing E501 findings in generator/reranker excluded. They
  concern unchanged prompt strings and context formatting.
- mypy with `--follow-imports=silent --ignore-missing-imports --check-untyped-defs`
  on six changed modules plus verification scripts: **passed** (11 files).
  Checking `search.py` additionally reports five existing errors; a
  `--shadow-file` check of main `3620bf0` reproduces the same errors in untouched
  search helpers. No new type errors were found.
- `git diff --check`: **passed**.

Standards review: **0 hard violations; 0 actionable smell findings**.
Spec review: **0 findings**. All ticket 03 acceptance criteria are covered.
Usage/cost accounting, complete interruption lifecycle checks, and final stream
contract verification remain in tickets 04–06. API documentation continues to
identify this as a development slice until ticket 06 completes.

## Comments

- 2026-11-08: Published from the approved backend-only ticket breakdown.
- 2026-11-09: User confirmed ticket 03 and authorized implementation on
  `implement/rag-ui-trace-ticket-03`, based on main `3620bf0`. Tests use the
  approved HTTP boundary with mocked providers and temporary corpus/cache,
  including real loopback delivery while a later candidate is blocked.
- 2026-11-09: Completed after standards/spec reviews and 188 passing tests.
