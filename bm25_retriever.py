"""BM25 retrieval index construction for document chunks."""

from collections.abc import Sequence

from rank_bm25 import BM25Okapi

from models import BM25SearchResult, DocumentChunk
from tokenizer import tokenize_text


class BM25Retriever:
    """Build a BM25 corpus from every document-chunk word token."""

    def __init__(self) -> None:
        self.document_chunks: list[DocumentChunk] = []
        self.tokenized_documents: list[list[str]] = []
        self.index: BM25Okapi | None = None

    def load(self, document_chunks: Sequence[DocumentChunk]) -> None:
        """Tokenize every chunk word and build the BM25 index."""
        self.document_chunks = list(document_chunks)
        if not self.document_chunks:
            raise ValueError("No document chunks were loaded.")

        self.tokenized_documents = [
            tokenize_text(chunk.text)
            for chunk in self.document_chunks
        ]
        if not any(self.tokenized_documents):
            raise ValueError("No BM25 tokens were created from document chunks.")
        self.index = BM25Okapi(self.tokenized_documents)

    def search(
        self,
        tokenized_query: Sequence[str],
        top_k: int,
        source_file_filter: str | None = None,
    ) -> list[BM25SearchResult]:
        """Score query terms and optionally keep chunks from one source file."""
        if self.index is None:
            raise RuntimeError("Load the BM25 retriever before searching.")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")
        if top_k > len(self.document_chunks):
            raise ValueError("top_k cannot exceed the number of loaded chunks.")
        if source_file_filter is not None and not source_file_filter.strip():
            raise ValueError("Source file filter cannot be empty.")

        scores = self.index.get_scores(tokenized_query)
        ranked_indexes = sorted(
            range(len(scores)), key=lambda index: scores[index], reverse=True
        )
        ranked_chunks = []
        for index in ranked_indexes:
            chunk = self.document_chunks[index]
            if source_file_filter is not None and chunk.source != source_file_filter:
                continue
            ranked_chunks.append(
                BM25SearchResult(score=float(scores[index]), chunk=chunk)
            )
            if len(ranked_chunks) == top_k:
                break
        return ranked_chunks
