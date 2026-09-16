"""Run FAISS evaluation across several top-K values efficiently."""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import semantic_search  # noqa: E402
from eval.run_faiss_retrieval_evaluation import (  # noqa: E402
    RetrievalMetrics,
    evaluate_faiss_retrieval,
    retrieve_faiss_references,
)
from eval.run_retrieval_evaluation import (  # noqa: E402
    EVALUATION_PATH,
    RetrievalEvaluationCase,
    load_evaluation_cases,
)

DEFAULT_TOP_K_VALUES = (1, 3, 5, 10, 30)


@dataclass(frozen=True)
class TopKEvaluationResult:
    """The aggregate metrics measured for one top-K setting."""

    top_k: int
    metrics: RetrievalMetrics


def run_top_k_evaluation(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object,
    top_k_values: Sequence[int] = DEFAULT_TOP_K_VALUES,
) -> list[TopKEvaluationResult]:
    """Retrieve once at the maximum K, then evaluate every requested K."""
    if not top_k_values:
        raise ValueError("At least one top_k value is required.")
    if any(top_k <= 0 for top_k in top_k_values):
        raise ValueError("All top_k values must be greater than zero.")

    unique_top_k_values = sorted(set(top_k_values))
    retrieved_references = retrieve_faiss_references(
        cases, retriever, top_k=max(unique_top_k_values)
    )
    results = []
    for top_k in unique_top_k_values:
        print(f"[FAISS] Calculating Hit@{top_k} and Recall@{top_k}.")
        results.append(
            TopKEvaluationResult(
                top_k=top_k,
                metrics=evaluate_faiss_retrieval(
                    cases,
                    top_k=top_k,
                    verbose=False,
                    print_summary=False,
                    retrieved_references_by_case=retrieved_references,
                ),
            )
        )
    return results


def print_top_k_results(results: Sequence[TopKEvaluationResult]) -> None:
    """Print an overview table for the measured top-K values."""
    print("top_k | hit_at_k | mean_recall_at_k")
    print("------|----------|-----------------")
    for result in results:
        print(
            f"{result.top_k:5} | {result.metrics.hit_at_k:8.1%} | "
            f"{result.metrics.recall_at_k:.1%}"
        )


def main() -> None:
    """Load FAISS once and evaluate a configurable set of top-K values."""
    parser = argparse.ArgumentParser(
        description="Evaluate FAISS chunk retrieval across several top-K values."
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
        "--top-k-values",
        type=int,
        nargs="+",
        default=DEFAULT_TOP_K_VALUES,
        help=(
            "Top-K values to compare "
            f"(default: {' '.join(map(str, DEFAULT_TOP_K_VALUES))})."
        ),
    )
    args = parser.parse_args()

    cases = load_evaluation_cases(args.evaluation_file)
    retriever = semantic_search.load_retriever(args.chunk_size, args.overlap_size)
    results = run_top_k_evaluation(cases, retriever, args.top_k_values)
    print_top_k_results(results)


if __name__ == "__main__":
    main()
