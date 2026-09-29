"""Evaluate BM25 retrieval against answer-level chunk references."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import semantic_search  # noqa: E402
from eval.run_faiss_retrieval_evaluation import (  # noqa: E402
    RetrievalMetrics,
    RetrievedReferences,
    chunk_reference,
    evaluate_retrieved_references,
)
from eval.run_retrieval_evaluation import (  # noqa: E402
    EVALUATION_PATH,
    RetrievalEvaluationCase,
    load_evaluation_cases,
)


def retrieve_bm25_references(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object,
    top_k: int,
    show_progress: bool = True,
) -> RetrievedReferences:
    """Retrieve the largest required BM25 ranking once per answerable case."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")

    answerable_cases = [case for case in cases if case["relevant_chunks"]]
    if show_progress:
        print(
            f"[BM25] Retrieving top {top_k} for "
            f"{len(answerable_cases)} answerable cases."
        )

    retrieved_references_by_case = {}
    for position, case in enumerate(answerable_cases, start=1):
        if show_progress:
            print(
                f"[BM25] {position}/{len(answerable_cases)} | "
                f"{case['id']} | {case['question']}"
            )
        retrieved_references_by_case[case["id"]] = [
            chunk_reference(result.chunk)
            for result in semantic_search.run_bm25_search(
                case["question"], retriever, top_k=top_k
            )
        ]
    return retrieved_references_by_case


def evaluate_bm25_retrieval(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object | None = None,
    top_k: int = semantic_search.TOP_K,
    verbose: bool = True,
    print_summary: bool = True,
    retrieved_references_by_case: RetrievedReferences | None = None,
) -> RetrievalMetrics:
    """Retrieve with BM25 and return aggregate chunk Hit@K and Recall@K."""
    if retrieved_references_by_case is None:
        if retriever is None:
            raise ValueError("A retriever is required when rankings are not supplied.")
        retrieved_references_by_case = retrieve_bm25_references(
            cases, retriever, top_k
        )

    return evaluate_retrieved_references(
        cases,
        retrieved_references_by_case,
        top_k=top_k,
        verbose=verbose,
        print_summary=print_summary,
    )


def main() -> None:
    """Load the shared retriever and evaluate BM25 chunk retrieval."""
    parser = argparse.ArgumentParser(
        description="Evaluate BM25 retrieval against eval_100_20 chunk references."
    )
    parser.add_argument(
        "--evaluation-file",
        type=Path,
        default=EVALUATION_PATH,
        help=f"Evaluation JSON path (default: {EVALUATION_PATH.name}).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=semantic_search.DEFAULT_CHUNK_SIZE,
        help=f"Words per chunk (default: {semantic_search.DEFAULT_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--overlap-size",
        type=int,
        default=semantic_search.DEFAULT_OVERLAP_SIZE,
        help=(
            "Overlapping words per chunk "
            f"(default: {semantic_search.DEFAULT_OVERLAP_SIZE})."
        ),
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=semantic_search.TOP_K,
        help=f"BM25 results per question (default: {semantic_search.TOP_K}).",
    )
    args = parser.parse_args()

    cases = load_evaluation_cases(
        args.evaluation_file, args.chunk_size, args.overlap_size
    )
    retriever = semantic_search.load_retriever(args.chunk_size, args.overlap_size)
    evaluate_bm25_retrieval(cases, retriever, top_k=args.top_k)


if __name__ == "__main__":
    main()
