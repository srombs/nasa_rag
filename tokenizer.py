"""Tokenization helpers for retrieved document chunks."""

from collections.abc import Sequence
import re

from models import DocumentChunk, TokenizedChunk


TOKEN_PATTERN = re.compile(r"\b\w+\b")


def tokenize_text(text: str) -> set[str]:
    """Return lowercase word tokens from text, with duplicates removed."""
    return set(TOKEN_PATTERN.findall(text.lower()))


def tokenize_chunks(chunks: Sequence[DocumentChunk]) -> list[TokenizedChunk]:
    """Create token-set objects for every supplied document chunk."""
    return [
        TokenizedChunk(
            source=chunk.source,
            chunk_index=chunk.chunk_index,
            tokens=tokenize_text(chunk.text),
        )
        for chunk in chunks
    ]


def keyword_score(query_tokens: set[str], chunk_tokens: set[str]) -> float:
    """Return the fraction of query tokens that occur in a chunk."""
    if not query_tokens:
        return 0.0
    return len(query_tokens & chunk_tokens) / len(query_tokens)


def score_tokenized_chunks(
    query_tokens: set[str], chunks: Sequence[TokenizedChunk]
) -> list[tuple[TokenizedChunk, float]]:
    """Rank tokenized chunks by how much of the query they contain."""
    return sorted(
        ((chunk, keyword_score(query_tokens, chunk.tokens)) for chunk in chunks),
        key=lambda result: result[1],
        reverse=True,
    )
