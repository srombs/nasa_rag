"""OpenAI embedding operations."""

from collections.abc import Sequence
import logging

import numpy as np

from models import DocumentChunk


EMBEDDING_MODEL = "text-embedding-3-small"
LOGGER = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when an embedding request cannot be completed."""


def embed_texts(
    texts: Sequence[str], source: str | None = None
) -> np.ndarray:
    """Return a float32 embedding matrix with one row per supplied text."""
    input_texts = list(texts)
    if not input_texts:
        return np.empty((0, 0), dtype=np.float32)

    source_label = source if source is not None else "unnamed source"
    try:
        from openai import OpenAI

        LOGGER.info(
            "Sending %d text chunks from %s to the embedding API.",
            len(input_texts),
            source_label,
        )
        response = OpenAI().embeddings.create(
            model=EMBEDDING_MODEL,
            input=input_texts,
        )
        embeddings = [
            item.embedding for item in sorted(response.data, key=lambda item: item.index)
        ]
        return np.array(embeddings, dtype=np.float32)
    except Exception as error:
        LOGGER.exception("Failed to embed text chunks from %s.", source_label)
        raise EmbeddingError("Unable to embed text chunks.") from error


def embed_documents(texts: Sequence[str], source: str) -> list[DocumentChunk]:
    """Embed text strings and store each returned vector with its chunk data."""
    text_list = list(texts)
    embeddings = embed_texts(text_list, source=source)
    return [
        DocumentChunk(source, index, text, embedding.tolist())
        for index, (text, embedding) in enumerate(
            zip(text_list, embeddings, strict=True)
        )
    ]


def embed_query(query: str) -> list[float]:
    """Embed one search query."""
    if not query:
        raise ValueError("Query text cannot be empty.")

    try:
        from openai import OpenAI

        response = OpenAI().embeddings.create(
            model=EMBEDDING_MODEL,
            input=query,
        )
        return response.data[0].embedding
    except Exception as error:
        LOGGER.exception("Failed to embed query.")
        raise EmbeddingError("Unable to embed the query.") from error
