"""Retrieval interfaces and the FAISS-backed implementation."""

from abc import ABC, abstractmethod
from pathlib import Path

import faiss
import numpy as np

from embedder import embed_query
from file_loader import CACHE_FILE_NAME, load_and_embed_directory
from models import DocumentChunk
from vector_store import create_query_matrix, load_or_create_index


DEFAULT_CHUNK_SIZE = 100
DEFAULT_OVERLAP_SIZE = 20


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
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap_size: int = DEFAULT_OVERLAP_SIZE,
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

    def _cache_path(self, file_name: str) -> Path:
        """Return a cache path unique to non-default chunking settings."""
        if (
            self.chunk_size == DEFAULT_CHUNK_SIZE
            and self.overlap_size == DEFAULT_OVERLAP_SIZE
        ):
            return self.cache_directory / file_name

        cache_file = Path(file_name)
        suffix = f"_{self.chunk_size}_{self.overlap_size}"
        return self.cache_directory / f"{cache_file.stem}{suffix}{cache_file.suffix}"

    def load(self) -> None:
        """Load cached documents and create or load their FAISS index."""
        self.document_chunks = load_and_embed_directory(
            self.data_directory,
            chunk_size=self.chunk_size,
            overlap_size=self.overlap_size,
            cache_path=self._cache_path(CACHE_FILE_NAME),
        )
        matrix = np.array(
            [chunk.embed for chunk in self.document_chunks], dtype=np.float32
        )
        self.index = load_or_create_index(
            matrix, self._cache_path("document.index")
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
