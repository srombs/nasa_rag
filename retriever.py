"""Retrieval interfaces and the FAISS-backed implementation."""

from abc import ABC, abstractmethod
from pathlib import Path

import faiss
import numpy as np

from embedder import embed_query
from file_loader import CACHE_FILE_NAME, load_and_embed_directory
from models import DocumentChunk
from vector_store import create_query_matrix, load_or_create_index


class Retriever(ABC):
    """Interface for loading documents and retrieving relevant chunks."""

    @abstractmethod
    def load(self) -> None:
        """Load the documents and prepare the retriever for search."""

    @abstractmethod
    def search(self, query: str, top_k: int) -> list[DocumentChunk]:
        """Return the top matching document chunks for a query."""


class FaissRetriever(Retriever):
    """Retriever backed by a cached FAISS inner-product index."""

    def __init__(
        self,
        data_directory: str | Path,
        chunk_size: int = 100,
        overlap_size: int = 20,
        cache_directory: str | Path | None = None,
    ) -> None:
        self.data_directory = Path(data_directory)
        self.chunk_size = chunk_size
        self.overlap_size = overlap_size
        self.cache_directory = (
            Path(cache_directory)
            if cache_directory is not None
            else self.data_directory.parent / "cache"
        )
        self.document_chunks: list[DocumentChunk] = []
        self.index: faiss.IndexFlatIP | None = None

    def load(self) -> None:
        """Load cached documents and create or load their FAISS index."""
        self.document_chunks = load_and_embed_directory(
            self.data_directory,
            chunk_size=self.chunk_size,
            overlap_size=self.overlap_size,
            cache_path=self.cache_directory / CACHE_FILE_NAME,
        )
        matrix = np.array(
            [chunk.embed for chunk in self.document_chunks], dtype=np.float32
        )
        self.index = load_or_create_index(
            matrix, self.cache_directory / "document.index"
        )

    def search(self, query: str, top_k: int) -> list[DocumentChunk]:
        """Search the normalized query embedding and return matching chunks."""
        if self.index is None:
            raise RuntimeError("Load the retriever before searching.")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")
        if top_k > self.index.ntotal:
            raise ValueError("top_k cannot exceed the number of indexed chunks.")

        query_matrix = create_query_matrix(embed_query(query))
        scores, chunk_indexes = self.index.search(query_matrix, top_k)
        ranked_chunks = []
        for score, chunk_index in zip(scores[0], chunk_indexes[0], strict=True):
            chunk = self.document_chunks[int(chunk_index)]
            chunk.similarity = float(score)
            ranked_chunks.append(chunk)
        return ranked_chunks
