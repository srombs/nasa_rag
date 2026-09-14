"""Model-based reranking for reciprocal-rank-fusion candidates."""

from collections.abc import Sequence
import json
import logging
from typing import Any

from models import DocumentChunk, RerankResult


RERANK_MODEL = "gpt-5.6-luna"
RERANK_INSTRUCTIONS = """You are evaluating whether a passage contains evidence
needed to answer a question.

Score the passage from 0.0 to 1.0. The score does not have to be exactly the numbers below.

1.0 = directly answers the question
0.7 = strong supporting evidence
0.4 = related topic but incomplete
0.1 = weakly related
0.0 = irrelevant

Judge whether the passage answers the specific relationship
or fact asked in the question.

Do not reward a passage merely because it contains the same keywords.

Judge relevance only against the level of specificity requested
by the question. Do not require a more specific answer than the
question asks for.

A passage should receive a high score if it directly contains
enough information to answer the question, even if additional
details could exist elsewhere."""


RERANK_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "rerank_result",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["score", "reason"],
        "additionalProperties": False,
    },
}
LOGGER = logging.getLogger(__name__)


class RerankingError(RuntimeError):
    """Raised when a model reranking request cannot be completed."""


class Reranker:
    """Rerank RRF candidates with one model request per query-chunk pair."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def rerank(
        self, query: str, rrf_results: Sequence[DocumentChunk]
    ) -> list[RerankResult]:
        """Score every RRF chunk against the query and return model rankings."""
        if not query.strip():
            raise ValueError("Query text cannot be empty.")

        results = [self._rerank_chunk(query, chunk) for chunk in rrf_results]
        return sorted(
            results,
            key=lambda result: (
                result.score,
                result.chunk.rrf_score if result.chunk.rrf_score is not None else 0.0,
            ),
            reverse=True,
        )

    def _rerank_chunk(self, query: str, chunk: DocumentChunk) -> RerankResult:
        """Ask the model to score one query-chunk pair."""
        input_text = f"Query:\n{query}\n\nChunk:\n{chunk.text}"
        LOGGER.info(
            "Sending reranking request to %s for %s, chunk %s with input:\n%s",
            RERANK_MODEL,
            chunk.source,
            chunk.chunk_index,
            input_text,
        )
        try:
            response = self._get_client().responses.create(
                model=RERANK_MODEL,
                instructions=RERANK_INSTRUCTIONS,
                input=input_text,
                text={"format": RERANK_RESPONSE_FORMAT},
            )
            payload = json.loads(response.output_text)
            score, reason = self._validate_response(payload)
            LOGGER.info(
                "Received reranking response from %s for %s, chunk %s.",
                RERANK_MODEL,
                chunk.source,
                chunk.chunk_index,
            )
            return RerankResult(chunk=chunk, score=score, reason=reason)
        except RerankingError:
            raise
        except Exception as error:
            LOGGER.exception(
                "Failed to rerank %s, chunk %s with %s.",
                chunk.source,
                chunk.chunk_index,
                RERANK_MODEL,
            )
            raise RerankingError("Unable to rerank a retrieved chunk.") from error

    def _get_client(self) -> Any:
        """Create and retain the API client only when reranking is requested."""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    @staticmethod
    def _validate_response(payload: object) -> tuple[float, str]:
        """Validate the model's structured reranking result."""
        if not isinstance(payload, dict):
            raise RerankingError("The reranking API returned invalid JSON.")

        score = payload.get("score")
        reason = payload.get("reason")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RerankingError("The reranking API returned an invalid score.")
        if not 0 <= score <= 1:
            raise RerankingError("The reranking API score must be between 0 and 1.")
        if not isinstance(reason, str) or not reason.strip():
            raise RerankingError("The reranking API returned an invalid reason.")
        return float(score), reason.strip()
