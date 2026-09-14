"""Generic retrieval orchestration for documents, tokens, and FAISS."""

from pathlib import Path

from bm25_retriever import BM25Retriever
from embedder import embed_query
from faiss_retriever import FaissRetriever
from file_loader import CACHE_FILE_NAME, load_and_embed_directory
from models import BM25SearchResult, DocumentChunk, HybridSearchResult, TokenizedChunk
from tokenizer import (
    score_tokenized_chunks,
    tokenize_chunks,
    tokenize_text,
    tokenize_text_set,
)
from vector_store import VectorStoreError


DEFAULT_CHUNK_SIZE = 100
DEFAULT_OVERLAP_SIZE = 20


class RetrievalError(RuntimeError):
    """Raised when a loaded retriever cannot complete a search."""


class Retriever:
    """Load documents and prepare token, FAISS, and BM25 retrieval."""

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
        self.tokenized_chunks: list[TokenizedChunk] = []
        self.faiss_retriever = FaissRetriever(self._cache_path("document.index"))
        self.bm25_retriever = BM25Retriever()

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
        """Load documents, tokenize text, and prepare FAISS and BM25 retrieval."""
        try:
            self.document_chunks = load_and_embed_directory(
                self.data_directory,
                chunk_size=self.chunk_size,
                overlap_size=self.overlap_size,
                cache_path=self._cache_path(CACHE_FILE_NAME),
            )
            if not self.document_chunks:
                raise ValueError("No document chunks were loaded.")
            self.tokenized_chunks = tokenize_chunks(self.document_chunks)
            self.faiss_retriever.load(self.document_chunks)
            self.bm25_retriever.load(self.document_chunks)
        except (ValueError, VectorStoreError):
            raise
        except Exception as error:
            raise RetrievalError("Unable to load the retriever.") from error

    def search(self, query: str, top_k: int) -> list[DocumentChunk]:
        """Embed a query and delegate its vector search to FAISS."""
        if not query:
            raise ValueError("Query text cannot be empty.")

        try:
            return self.faiss_retriever.search(embed_query(query), top_k)
        except ValueError:
            raise
        except Exception as error:
            raise RetrievalError("Unable to search the FAISS index.") from error

    def search_keywords(self, query: str, top_k: int) -> list[DocumentChunk]:
        """Rank loaded chunks by normalized keyword overlap with a query."""
        if not query:
            raise ValueError("Query text cannot be empty.")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")
        if top_k > len(self.tokenized_chunks):
            raise ValueError("top_k cannot exceed the number of loaded chunks.")

        tokenized_query = tokenize_text_set(query)
        ranked_tokens = score_tokenized_chunks(
            tokenized_query, self.tokenized_chunks
        )
        chunk_by_reference = {
            (chunk.source, chunk.chunk_index): chunk for chunk in self.document_chunks
        }
        ranked_chunks = []
        for tokenized_chunk, score in ranked_tokens[:top_k]:
            chunk = chunk_by_reference[
                (tokenized_chunk.source, tokenized_chunk.chunk_index)
            ]
            chunk.similarity = score
            ranked_chunks.append(chunk)
        return ranked_chunks

    def search_bm25(self, query: str, top_k: int) -> list[BM25SearchResult]:
        """Tokenize a query and delegate scoring to the BM25 retriever."""
        if not query:
            raise ValueError("Query text cannot be empty.")

        try:
            return self.bm25_retriever.search(tokenize_text(query), top_k)
        except ValueError:
            raise
        except Exception as error:
            raise RetrievalError("Unable to search the BM25 index.") from error

    def search_hybrid(
        self,
        query: str,
        top_k: int,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[HybridSearchResult]:
        """Rank chunks using weighted semantic and keyword-overlap scores."""
        _, hybrid_results = self.search_semantic_and_hybrid(
            query,
            top_k=top_k,
            semantic_weight=semantic_weight,
            keyword_weight=keyword_weight,
        )
        return hybrid_results

    def search_semantic_and_hybrid(
        self,
        query: str,
        top_k: int,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> tuple[list[DocumentChunk], list[HybridSearchResult]]:
        """Return FAISS and hybrid rankings using one embedded query."""
        if not query:
            raise ValueError("Query text cannot be empty.")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")
        if top_k > len(self.document_chunks):
            raise ValueError("top_k cannot exceed the number of loaded chunks.")
        if semantic_weight < 0 or keyword_weight < 0:
            raise ValueError("Hybrid search weights cannot be negative.")

        semantic_results = self.faiss_retriever.search(
            embed_query(query), top_k=len(self.document_chunks)
        )
        semantic_scores = {
            (chunk.source, chunk.chunk_index): chunk.similarity
            for chunk in semantic_results
        }
        keyword_scores = {
            (chunk.source, chunk.chunk_index): score
            for chunk, score in score_tokenized_chunks(
                tokenize_text_set(query), self.tokenized_chunks
            )
        }
        hybrid_results = []
        for chunk in self.document_chunks:
            reference = (chunk.source, chunk.chunk_index)
            semantic_score = semantic_scores[reference]
            keyword_score = keyword_scores[reference]
            hybrid_score = (
                semantic_weight * semantic_score + keyword_weight * keyword_score
            )
            hybrid_results.append(
                HybridSearchResult(
                    document_chunk=chunk,
                    semantic_score=semantic_score,
                    keyword_score=keyword_score,
                    hybrid_score=hybrid_score,
                )
            )

        return semantic_results[:top_k], sorted(
            hybrid_results,
            key=lambda result: result.hybrid_score,
            reverse=True,
        )[:top_k]
