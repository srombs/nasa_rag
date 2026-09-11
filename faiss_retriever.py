"""FAISS-specific retrieval over already loaded document chunks."""

from collections.abc import Sequence
from pathlib import Path

import faiss
import numpy as np

from models import DocumentChunk
from vector_store import create_query_matrix, load_or_create_index, validate_index


class FaissRetriever:
    """Load and search a FAISS index for supplied document chunks."""

    def __init__(self, cache_path: str | Path) -> None:
        self.cache_path = Path(cache_path)
        self.document_chunks: list[DocumentChunk] = []
        self.index: faiss.IndexFlatIP | None = None

    def load(self, document_chunks: Sequence[DocumentChunk]) -> None:
        """Create or load the FAISS index for document chunk embeddings."""
        self.document_chunks = list(document_chunks)
        if not self.document_chunks:
            raise ValueError("No document chunks were loaded.")

        matrix = np.array(
            [chunk.embed for chunk in self.document_chunks], dtype=np.float32
        )
        index = load_or_create_index(matrix, self.cache_path)
        validate_index(index, self.document_chunks)
        self.index = index

    def search(
        self, query_embedding: Sequence[float], top_k: int
    ) -> list[DocumentChunk]:
        """Search a query embedding and return its top document chunks."""
        if self.index is None:
            raise RuntimeError("Load the FAISS retriever before searching.")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")
        if top_k > self.index.ntotal:
            raise ValueError("top_k cannot exceed the number of indexed chunks.")

        query_matrix = create_query_matrix(query_embedding)
        if query_matrix.shape[1] != self.index.d:
            raise ValueError(
                "Query embedding dimension does not match the FAISS index."
            )

        scores, chunk_indexes = self.index.search(query_matrix, top_k)
        ranked_chunks = []
        for score, chunk_index in zip(scores[0], chunk_indexes[0], strict=True):
            chunk = self.document_chunks[int(chunk_index)]
            chunk.similarity = float(score)
            ranked_chunks.append(chunk)
        return ranked_chunks
