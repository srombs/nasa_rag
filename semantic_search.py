"""Search the NASA document corpus from the command line or Python."""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from generator import (
    build_chunk_references,
    build_context,
    format_chunk_reference,
    generate_answer,
    validate_answer_citations,
)
from model_costs import report_run_costs
from models import BM25SearchResult, DocumentChunk, RerankResult
from retrieval_planner import RetrievalPlanner
from retriever import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_SIZE, Retriever

TOP_RESULTS = 10
TOP_K = 30
RRF_TOP_K = 10


def print_ranked_chunks(
    document_chunks: Sequence[DocumentChunk], top_k: int = TOP_RESULTS
) -> None:
    """Print the requested number of ranked chunks without their vectors."""
    if top_k < 0:
        raise ValueError("top_k must be at least zero.")

    for chunk in document_chunks[:top_k]:
        print(f"{chunk.similarity:.4f} | {format_chunk_reference(chunk)}")


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


def search(query: str) -> list[tuple[str, float]]:
    """Search the NASA corpus and return text with its FAISS score."""
    ranked_chunks = run_embedded_search(query, load_retriever(), top_k=TOP_RESULTS)
    print_ranked_chunks(ranked_chunks)
    return [(chunk.text, chunk.similarity) for chunk in ranked_chunks]


def load_retriever(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_size: int = DEFAULT_OVERLAP_SIZE,
) -> Retriever:
    """Load the document retriever used by command-line and evaluation searches."""
    module_directory = Path(__file__).resolve().parent
    data_directory = module_directory / "data"
    cache_directory = (
        None
        if (module_directory / "pyproject.toml").is_file()
        else Path.home() / ".cache" / "nasa_rag"
    )
    retriever = Retriever(
        data_directory,
        chunk_size=chunk_size,
        overlap_size=overlap_size,
        cache_directory=cache_directory,
    )
    retriever.load()
    return retriever


def run_embedded_search(
    query: str,
    retriever: Retriever,
    top_k: int = TOP_K,
    source_file_filter: str | None = None,
    search_query: str | None = None,
) -> list[DocumentChunk]:
    """Run one query through FAISS with an optional pre-rewritten query."""
    search_arguments = {
        "top_k": top_k,
        "source_file_filter": source_file_filter,
    }
    if search_query is not None:
        search_arguments["search_query"] = search_query
    return retriever.search(query, **search_arguments)


def run_bm25_search(
    query: str,
    retriever: Retriever,
    top_k: int = TOP_K,
    source_file_filter: str | None = None,
    search_query: str | None = None,
) -> list[BM25SearchResult]:
    """Run one query through BM25 with an optional pre-rewritten query."""
    search_arguments = {
        "top_k": top_k,
        "source_file_filter": source_file_filter,
    }
    if search_query is not None:
        search_arguments["search_query"] = search_query
    return retriever.search_bm25(query, **search_arguments)


def run_both_searches(
    query: str,
    retriever: Retriever,
    top_k: int = TOP_K,
    rrf_top_k: int = RRF_TOP_K,
    source_file_filter: str | None = None,
    search_query: str | None = None,
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
        search_query=search_query,
    )


def generate_rag_answer(question: str, results: Sequence[DocumentChunk]) -> str:
    """Build retrieved context and generate an answer to a question."""
    answer = generate_answer(build_context(results), question)
    return validate_answer_citations(answer, build_chunk_references(results))


@report_run_costs("search")
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
    args = parser.parse_args()

    retriever = load_retriever(args.chunk_size, args.overlap_size)
    if args.both_searches:
        retrieval_plan = RetrievalPlanner().infer(args.query)
        retriever.validate_source_file_filter(retrieval_plan.source_file_filter)
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
                source_file_filter=(
                    args.source_file or retrieval_plan.source_file_filter
                ),
                search_query=retrieval_plan.search_query,
            )
        )
        print(f"Original query:\n{args.query}")
        print(f"\nRetrieval plan:\n{retrieval_plan}")
        print(f"\nRewritten query:\n{rewritten_query}")
        print(
            "\nSource file filter:\n"
            f"{args.source_file or retrieval_plan.source_file_filter or 'None'}"
        )
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
    if not args.both_searches and args.bm25_search:
        bm25_results = run_bm25_search(
            args.query,
            retriever,
            top_k=args.top_k,
            source_file_filter=args.source_file,
        )
        print_bm25_results(bm25_results)
        ranked_chunks = [result.chunk for result in bm25_results]
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
