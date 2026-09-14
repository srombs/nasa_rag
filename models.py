"""Shared data objects for the retrieval pipeline."""

from dataclasses import dataclass


@dataclass
class DocumentChunk:
    """A text chunk, its source metadata, and its embedding vector."""

    source: str
    chunk_index: int
    text: str
    embed: list[float]
    similarity: float | None = None
    rrf_score: float | None = None
    faiss_rank: int | None = None
    bm25_rank: int | None = None

    def to_cache_record(self) -> dict[str, str | int | list[float]]:
        """Return the persistent fields used by the document cache."""
        return {
            "source": self.source,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "embed": self.embed,
        }

    @classmethod
    def from_cache_record(cls, record: dict[str, object]) -> "DocumentChunk":
        """Re-create a chunk object from a persisted cache record."""
        try:
            source = record["source"]
            chunk_index = record["chunk_index"]
            text = record["text"]
            embed = record["embed"]
        except KeyError as error:
            message = f"Document cache record is missing {error.args[0]!r}."
            raise ValueError(message) from error

        if not isinstance(source, str) or not isinstance(chunk_index, int):
            raise ValueError("Document cache record has invalid source or chunk_index.")
        if not isinstance(text, str) or not isinstance(embed, list):
            raise ValueError("Document cache record has invalid text or embed values.")
        if not all(isinstance(value, (int, float)) for value in embed):
            raise ValueError("Document cache embedding must contain only numbers.")

        return cls(source, chunk_index, text, [float(value) for value in embed])


@dataclass
class TokenizedChunk:
    """A document chunk's source metadata and normalized token set."""

    source: str
    chunk_index: int
    tokens: set[str]


@dataclass
class HybridSearchResult:
    """A document chunk and each score used to rank it in hybrid search."""

    document_chunk: DocumentChunk
    semantic_score: float
    keyword_score: float
    hybrid_score: float


@dataclass
class BM25SearchResult:
    """A document chunk and its BM25 relevance score."""

    score: float
    chunk: DocumentChunk


@dataclass
class RerankResult:
    """A reranked chunk, its reranking score, and scoring explanation."""

    chunk: DocumentChunk
    score: float
    reason: str
