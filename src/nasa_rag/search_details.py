"""Explicit public search details, frozen as finite JSON at the stage boundary."""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from .generation.generator import CitationCheck, format_chunk_reference
from .models import BM25SearchResult, DocumentChunk, RerankResult, RetrievalPlan


def _passage(chunk: DocumentChunk) -> dict:
    return {
        "source": chunk.source,
        "chunk_index": chunk.chunk_index,
        "reference": format_chunk_reference(chunk),
        "text": chunk.text,
    }


def _score(value: float | None) -> float:
    if value is None:
        raise ValueError("A completed ranking must have a score.")
    return float(value)


def _reranked_passage(result: RerankResult) -> dict:
    return {
        **_passage(result.chunk),
        "rerank_score": float(result.score),
        "reason": result.reason,
        "rrf_score": _score(result.chunk.rrf_score),
        "faiss_rank": result.chunk.faiss_rank,
        "bm25_rank": result.chunk.bm25_rank,
    }


@dataclass(frozen=True)
class StageDetails:
    """An immutable snapshot; each public read returns independent JSON values."""

    _json: str = "{}"

    @classmethod
    def _capture(cls, fields: dict) -> "StageDetails":
        return cls(json.dumps(fields, ensure_ascii=False, allow_nan=False))

    def public(self) -> dict:
        return json.loads(self._json)

    @classmethod
    def candidate(cls, result: RerankResult) -> "StageDetails":
        return cls._capture(_reranked_passage(result))

    def append_evaluated(self, result: "StageDetails") -> "StageDetails":
        return self._capture(
            {
                "evaluated_results": [
                    *self.public().get("evaluated_results", []),
                    result.public(),
                ]
            }
        )

    @classmethod
    def reranking(cls, results: Sequence[RerankResult]) -> "StageDetails":
        return cls._capture(
            {
                "results": [
                    {**_reranked_passage(result), "rank": rank}
                    for rank, result in enumerate(results, 1)
                ]
            }
        )

    @classmethod
    def generation(cls, context_references: Sequence[str]) -> "StageDetails":
        return cls._capture({"context_references": list(context_references)})

    @classmethod
    def citations(cls, check: CitationCheck) -> "StageDetails":
        return cls._capture(
            {
                "outcome": check.outcome,
                "checked_references": list(check.checked_references),
                "invalid_references": list(check.invalid_references),
            }
        )

    @classmethod
    def plan(cls, plan: RetrievalPlan) -> "StageDetails":
        return cls._capture(
            {
                "search_query": plan.search_query,
                "source_file_filter": plan.source_file_filter,
            }
        )

    @classmethod
    def embedding(cls, model: str, dimensions: int) -> "StageDetails":
        return cls._capture({"model": model, "dimensions": dimensions})

    @classmethod
    def semantic(cls, chunks: Sequence[DocumentChunk]) -> "StageDetails":
        return cls._capture(
            {
                "results": [
                    {
                        **_passage(chunk),
                        "rank": rank,
                        "similarity": _score(chunk.similarity),
                    }
                    for rank, chunk in enumerate(chunks, 1)
                ]
            }
        )

    @classmethod
    def keyword(cls, results: Sequence[BM25SearchResult]) -> "StageDetails":
        return cls._capture(
            {
                "results": [
                    {
                        **_passage(result.chunk),
                        "rank": rank,
                        "bm25_score": float(result.score),
                    }
                    for rank, result in enumerate(results, 1)
                ]
            }
        )

    @classmethod
    def fusion(cls, chunks: Sequence[DocumentChunk], rrf_k: int) -> "StageDetails":
        return cls._capture(
            {
                "rrf_k": rrf_k,
                "results": [
                    {
                        **_passage(chunk),
                        "rank": rank,
                        "rrf_score": _score(chunk.rrf_score),
                        "faiss_rank": chunk.faiss_rank,
                        "bm25_rank": chunk.bm25_rank,
                    }
                    for rank, chunk in enumerate(chunks, 1)
                ],
            }
        )
