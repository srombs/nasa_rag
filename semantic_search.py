"""Starter documents for semantic search experiments."""

from collections.abc import Sequence
import argparse
import logging
from math import sqrt
from pathlib import Path

from embedder import embed_documents, embed_query
from generator import (
    build_chunk_references,
    build_context,
    format_chunk_reference,
    generate_answer,
    validate_answer_citations,
)
from models import BM25SearchResult, DocumentChunk, HybridSearchResult, RerankResult
from retriever import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_SIZE, Retriever

TOP_RESULTS = 10
TOP_K = 30
RRF_TOP_K = 10


# documents = [
#     "Perseverance landed in Jezero Crater on Mars in February 2021.",
#     "The James Webb Space Telescope observes the universe primarily in infrared light.",
#     "Apollo 11 landed the first humans on the Moon in July 1969.",
#     "Cassini studied Saturn, its rings, and its moons before ending its mission in 2017.",
#     "The Curiosity rover landed in Gale Crater on Mars in August 2012.",
#     "The Hubble Space Telescope observes stars, galaxies, and other astronomical objects from orbit around Earth.",
#     "Voyager 1 launched in 1977 and became the first human-made spacecraft to enter interstellar space.",
#     "The Ingenuity helicopter performed the first powered controlled flight on another planet while operating on Mars.",
#     "The Artemis program aims to return humans to the Moon and establish a foundation for future missions to Mars.",
#     "The Parker Solar Probe studies the Sun's outer atmosphere and has traveled closer to the Sun than any previous spacecraft."
# ]

documents = [
    "Perseverance landed in Jezero Crater.",
    "The Mars 2020 rover touched down inside an ancient Martian lake bed.",
    "Jezero is a crater on Mars.",
    "Apollo astronauts landed on the Moon.",
    "NASA landed a spacecraft."
]


def cosine_similarity(vector_a: Sequence[float], vector_b: Sequence[float]) -> float:
    """Calculate cosine similarity between two equally sized vectors."""
    if len(vector_a) != len(vector_b):
        raise ValueError("Vectors must have the same number of dimensions.")

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b, strict=True))
    magnitude_a = sqrt(sum(value * value for value in vector_a))
    magnitude_b = sqrt(sum(value * value for value in vector_b))
    if magnitude_a == 0 or magnitude_b == 0:
        raise ValueError("Cosine similarity is undefined for a zero vector.")
    return dot_product / (magnitude_a * magnitude_b)


def score_document_chunks(
    query_embedding: Sequence[float], document_chunks: Sequence[DocumentChunk]
) -> list[DocumentChunk]:
    """Store each chunk's similarity to the query and return ranked chunks."""
    for document_chunk in document_chunks:
        document_chunk.similarity = cosine_similarity(
            query_embedding, document_chunk.embed
        )
    return sorted(
        document_chunks,
        key=lambda chunk: chunk.similarity if chunk.similarity is not None else -1.0,
        reverse=True,
    )


def print_ranked_chunks(
    document_chunks: Sequence[DocumentChunk], top_k: int = TOP_RESULTS
) -> None:
    """Print the requested number of ranked chunks without their vectors."""
    if top_k < 0:
        raise ValueError("top_k must be at least zero.")

    for chunk in document_chunks[:top_k]:
        print(f"{chunk.similarity:.4f} | {format_chunk_reference(chunk)}")


def print_hybrid_results(results: Sequence[HybridSearchResult]) -> None:
    """Print hybrid scores and source metadata for each ranked result."""
    for result in results:
        chunk = result.document_chunk
        print(
            f"hybrid {result.hybrid_score:.4f} | "
            f"semantic {result.semantic_score:.4f} | "
            f"keyword {result.keyword_score:.4f} | "
            f"{format_chunk_reference(chunk)}"
        )


def print_bm25_results(results: Sequence[BM25SearchResult]) -> None:
    """Print BM25 scores and source metadata for each ranked result."""
    for result in results:
        print(
            f"{result.score:.4f} | {format_chunk_reference(result.chunk)}"
        )


def print_rrf_results(results: Sequence[DocumentChunk]) -> None:
    """Print RRF scores with the source rankings that produced each score."""
    for chunk in results:
        print(
            f"rrf {chunk.rrf_score:.4f} | "
            f"FAISS rank {chunk.faiss_rank} | "
            f"BM25 rank {chunk.bm25_rank} | "
            f"{format_chunk_reference(chunk)}"
        )


def print_rerank_results(results: Sequence[RerankResult]) -> None:
    """Print model-reranked chunks with their score and relevance reason."""
    for result in results:
        print(
            f"rerank {result.score:.4f} | "
            f"{format_chunk_reference(result.chunk)} | {result.reason}"
        )


def compare_query_to_documents(
    query_embedding: Sequence[float],
    document_embeddings: Sequence[Sequence[float]],
    document_texts: Sequence[str] = documents,
) -> list[tuple[str, float]]:
    """Score every document, then print the three best matches."""
    if len(document_embeddings) != len(document_texts):
        raise ValueError("Each document must have exactly one embedding.")

    results = [
        (document, cosine_similarity(query_embedding, embedding))
        for document, embedding in zip(document_texts, document_embeddings, strict=True)
    ]
    results.sort(key=lambda result: result[1], reverse=True)
    for document, score in results[:TOP_RESULTS]:
        print(f"{score:.4f}  {document}")
    return results


def search(query: str) -> list[tuple[str, float]]:
    """Embed a query, score it against the documents, and print the results."""
    document_chunks = embed_documents(documents, source="sample_documents")
    ranked_chunks = score_document_chunks(embed_query(query), document_chunks)
    print_ranked_chunks(ranked_chunks)
    return [(chunk.text, chunk.similarity) for chunk in ranked_chunks]


def load_retriever(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_size: int = DEFAULT_OVERLAP_SIZE,
) -> Retriever:
    """Load the document retriever used by command-line and evaluation searches."""
    data_directory = Path(__file__).with_name("data")
    retriever = Retriever(
        data_directory, chunk_size=chunk_size, overlap_size=overlap_size
    )
    retriever.load()
    return retriever


def run_embedded_search(
    query: str,
    retriever: Retriever,
    top_k: int = TOP_K,
    source_file_filter: str | None = None,
) -> list[DocumentChunk]:
    """Run one query through FAISS with an optional source file filter."""
    return retriever.search(
        query, top_k=top_k, source_file_filter=source_file_filter
    )


def run_keyword_search(
    query: str, retriever: Retriever, top_k: int = TOP_K
) -> list[DocumentChunk]:
    """Run one query through the token-overlap retriever."""
    return retriever.search_keywords(query, top_k=top_k)


def run_bm25_search(
    query: str,
    retriever: Retriever,
    top_k: int = TOP_K,
    source_file_filter: str | None = None,
) -> list[BM25SearchResult]:
    """Run one query through BM25, optionally restricted to one source file."""
    return retriever.search_bm25(
        query, top_k=top_k, source_file_filter=source_file_filter
    )


def run_both_searches(
    query: str,
    retriever: Retriever,
    top_k: int = TOP_K,
    rrf_top_k: int = RRF_TOP_K,
    source_file_filter: str | None = None,
) -> tuple[
    list[DocumentChunk],
    list[BM25SearchResult],
    list[DocumentChunk],
    list[RerankResult],
    str,
]:
    """Return the rewritten query and all combined retrieval rankings."""
    return retriever.search_faiss_bm25_rrf_and_rerank(
        query,
        top_k=top_k,
        rrf_top_k=rrf_top_k,
        source_file_filter=source_file_filter,
    )


def run_hybrid_search(
    query: str,
    retriever: Retriever,
    top_k: int = TOP_K,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> list[HybridSearchResult]:
    """Run weighted semantic and keyword retrieval for one query."""
    return retriever.search_hybrid(
        query,
        top_k=top_k,
        semantic_weight=semantic_weight,
        keyword_weight=keyword_weight,
    )


def run_semantic_and_hybrid_search(
    query: str,
    retriever: Retriever,
    top_k: int = TOP_K,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> tuple[list[DocumentChunk], list[HybridSearchResult]]:
    """Return FAISS and hybrid rankings using a single query embedding."""
    return retriever.search_semantic_and_hybrid(
        query,
        top_k=top_k,
        semantic_weight=semantic_weight,
        keyword_weight=keyword_weight,
    )


def generate_rag_answer(question: str, results: Sequence[DocumentChunk]) -> str:
    """Build retrieved context and generate an answer to a question."""
    answer = generate_answer(build_context(results), question)
    return validate_answer_citations(answer, build_chunk_references(results))


def main() -> None:
    """Run a semantic search from the command line."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Search the NASA text documents semantically."
    )
    parser.add_argument("query", help="The question or search phrase to embed.")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Words per chunk (default: {DEFAULT_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--overlap-size",
        type=int,
        default=DEFAULT_OVERLAP_SIZE,
        help=f"Overlapping words per chunk (default: {DEFAULT_OVERLAP_SIZE}).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=TOP_K,
        help=f"Number of chunks to return (default: {TOP_K}).",
    )
    parser.add_argument(
        "--generate-answer",
        action="store_true",
        help="Generate a context-grounded answer after retrieval.",
    )
    search_mode = parser.add_mutually_exclusive_group()
    search_mode.add_argument(
        "--keyword-search",
        action="store_true",
        help="Rank chunks by keyword overlap instead of embedding similarity.",
    )
    search_mode.add_argument(
        "--bm25-search",
        action="store_true",
        help="Rank chunks with BM25 scores without embedding the query.",
    )
    parser.add_argument(
        "--source-file",
        help="Restrict FAISS and BM25 results to this source file, such as iss.txt.",
    )
    search_mode.add_argument(
        "--both-searches",
        action="store_true",
        help="Print FAISS, BM25, and reciprocal-rank-fusion rankings.",
    )
    search_mode.add_argument(
        "--hybrid-search",
        action="store_true",
        help="Rank chunks with weighted FAISS and keyword-overlap scores.",
    )
    parser.add_argument(
        "--semantic-weight",
        type=float,
        default=0.7,
        help="FAISS score weight for hybrid search (default: 0.7).",
    )
    parser.add_argument(
        "--keyword-weight",
        type=float,
        default=0.3,
        help="Keyword score weight for hybrid search (default: 0.3).",
    )
    args = parser.parse_args()
    if args.source_file and (args.keyword_search or args.hybrid_search):
        parser.error("--source-file is not supported with keyword or hybrid search.")

    retriever = load_retriever(args.chunk_size, args.overlap_size)
    if args.both_searches:
        (
            ranked_chunks,
            bm25_results,
            rrf_results,
            rerank_results,
            rewritten_query,
        ) = (
            run_both_searches(
                args.query,
                retriever,
                top_k=args.top_k,
                source_file_filter=args.source_file,
            )
        )
        print(f"Original query:\n{args.query}")
        print(f"\nRewritten query:\n{rewritten_query}")
        print("\nFAISS results:")
        print_ranked_chunks(ranked_chunks, top_k=args.top_k)
        print("\nBM25 results:")
        print_bm25_results(bm25_results)
        print("\nRRF results:")
        print_rrf_results(rrf_results)
        print("\nReranked results:")
        print_rerank_results(rerank_results)
        ranked_chunks = [result.chunk for result in rerank_results]
    else:
        print(f"Question: {args.query}")
    if not args.both_searches and args.keyword_search:
        ranked_chunks = run_keyword_search(args.query, retriever, top_k=args.top_k)
        print_ranked_chunks(ranked_chunks, top_k=args.top_k)
    elif not args.both_searches and args.bm25_search:
        bm25_results = run_bm25_search(
            args.query,
            retriever,
            top_k=args.top_k,
            source_file_filter=args.source_file,
        )
        print_bm25_results(bm25_results)
        ranked_chunks = [result.chunk for result in bm25_results]
    elif not args.both_searches and args.hybrid_search:
        semantic_results, hybrid_results = run_semantic_and_hybrid_search(
            args.query,
            retriever,
            top_k=args.top_k,
            semantic_weight=args.semantic_weight,
            keyword_weight=args.keyword_weight,
        )
        print("\nFAISS results:")
        print_ranked_chunks(semantic_results, top_k=args.top_k)
        print("\nHybrid results:")
        print_hybrid_results(hybrid_results)
        ranked_chunks = [result.document_chunk for result in hybrid_results]
    elif not args.both_searches:
        ranked_chunks = run_embedded_search(
            args.query,
            retriever,
            top_k=args.top_k,
            source_file_filter=args.source_file,
        )
        print_ranked_chunks(ranked_chunks, top_k=args.top_k)
    if args.generate_answer:
        print(f"\nAnswer: {generate_rag_answer(args.query, ranked_chunks)}")


if __name__ == "__main__":
    main()
