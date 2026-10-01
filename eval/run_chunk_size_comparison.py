"""Compare retrieval metrics across every labeled chunk-size dataset."""

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eval.run_retrieval_evaluation import (  # noqa: E402
    RetrievalEvaluationCase,
    load_evaluation_cases,
)
from eval.run_retrieval_top_k_evaluation import (  # noqa: E402
    DEFAULT_RERANKER_CANDIDATE_TOP_K,
    DEFAULT_RERANKER_TOP_K_VALUES,
    DEFAULT_RRF_CANDIDATE_TOP_K,
    DEFAULT_RRF_K,
    DEFAULT_RRF_TOP_K_VALUES,
    DEFAULT_TOP_K_VALUES,
    TopKEvaluationResult,
    run_all_top_k_evaluation,
)
from nasa_rag import search as semantic_search  # noqa: E402
from nasa_rag.model_costs import report_run_costs  # noqa: E402
from nasa_rag.retrieval.query_rewriter import QueryRewriter  # noqa: E402

DATASET_DIRECTORY = Path(__file__).resolve().parent / "datasets"
DATASET_NAME = re.compile(r"eval_(?P<chunk_size>\d+)_(?P<overlap_size>\d+)\.json")
METHODS = ("FAISS", "BM25", "RRF", "RERANKER")


@dataclass(frozen=True)
class DatasetSpec:
    """A labeled dataset and its corresponding retriever chunk settings."""

    path: Path
    chunk_size: int
    overlap_size: int

    @property
    def label(self) -> str:
        return f"{self.chunk_size}/{self.overlap_size}"


@dataclass(frozen=True)
class ChunkSizeResult:
    """All top-K scores for one chunk-size dataset."""

    dataset: DatasetSpec
    scores: Mapping[str, Sequence[TopKEvaluationResult]]


def discover_datasets(directory: Path = DATASET_DIRECTORY) -> list[DatasetSpec]:
    """Find datasets named for their chunk size and overlap."""
    datasets = []
    for path in directory.glob("eval_*.json"):
        match = DATASET_NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Invalid evaluation dataset filename: {path.name}")
        datasets.append(
            DatasetSpec(
                path=path,
                chunk_size=int(match["chunk_size"]),
                overlap_size=int(match["overlap_size"]),
            )
        )
    datasets.sort(key=lambda item: (item.chunk_size, item.overlap_size))
    if len(datasets) < 2:
        raise ValueError(
            f"At least two eval_*.json datasets are required in {directory}."
        )
    return datasets


def load_comparable_cases(
    datasets: Sequence[DatasetSpec],
) -> list[tuple[DatasetSpec, list[RetrievalEvaluationCase]]]:
    """Validate that every dataset asks the same answerable questions."""
    loaded = []
    baseline = None
    for dataset in datasets:
        cases = load_evaluation_cases(
            dataset.path, dataset.chunk_size, dataset.overlap_size
        )
        signature = {
            case["id"]: (case["question"], bool(case["relevant_chunks"]))
            for case in cases
        }
        if baseline is None:
            baseline = signature
        elif signature != baseline:
            raise ValueError(
                f"Dataset {dataset.path.name} has different questions or "
                "answerability; chunk-size scores would not be comparable."
            )
        loaded.append((dataset, cases))
    return loaded


def run_chunk_size_comparison(
    datasets: Sequence[tuple[DatasetSpec, list[RetrievalEvaluationCase]]],
    top_k_values: Sequence[int] = DEFAULT_TOP_K_VALUES,
    rrf_top_k_values: Sequence[int] = DEFAULT_RRF_TOP_K_VALUES,
    rrf_k: int = DEFAULT_RRF_K,
    rrf_candidate_top_k: int = DEFAULT_RRF_CANDIDATE_TOP_K,
    reranker_top_k_values: Sequence[int] | None = None,
    reranker_candidate_top_k: int = DEFAULT_RERANKER_CANDIDATE_TOP_K,
) -> list[ChunkSizeResult]:
    """Run the same rewritten questions against each chunk-size corpus."""
    if not datasets:
        raise ValueError("At least one dataset is required.")
    if not top_k_values or not rrf_top_k_values or any(
        top_k <= 0
        for values in (top_k_values, rrf_top_k_values)
        for top_k in values
    ):
        raise ValueError("Top-K values must be nonempty and positive.")
    if reranker_top_k_values is not None and (
        not reranker_top_k_values or any(top_k <= 0 for top_k in reranker_top_k_values)
    ):
        raise ValueError("Reranker top-K values must be nonempty and positive.")
    if rrf_k < 0 or reranker_candidate_top_k <= 0:
        raise ValueError("Invalid RRF or reranker candidate settings.")
    if (
        reranker_top_k_values is not None
        and reranker_candidate_top_k < max(reranker_top_k_values)
    ):
        raise ValueError("Reranker candidate count must cover reranker top-K.")
    largest_result = max(
        max(top_k_values),
        max(rrf_top_k_values),
        reranker_candidate_top_k if reranker_top_k_values is not None else 0,
    )
    if rrf_candidate_top_k < largest_result:
        raise ValueError("RRF candidate count must cover every requested top-K.")
    answerable_cases = [case for case in datasets[0][1] if case["relevant_chunks"]]
    if not answerable_cases:
        raise ValueError("At least one answerable case is required.")
    rewriter = QueryRewriter()
    search_queries = {
        case["id"]: rewriter.rewrite(case["question"])
        for case in answerable_cases
    }
    results = []
    for dataset, cases in datasets:
        print(f"\n=== Chunk size {dataset.label}: {dataset.path.name} ===")
        retriever = semantic_search.load_retriever(
            dataset.chunk_size, dataset.overlap_size
        )
        faiss, bm25, rrf, reranker = run_all_top_k_evaluation(
            cases,
            retriever,
            top_k_values=top_k_values,
            rrf_top_k_values=rrf_top_k_values,
            rrf_k=rrf_k,
            rrf_candidate_top_k=rrf_candidate_top_k,
            reranker_top_k_values=reranker_top_k_values,
            reranker_candidate_top_k=reranker_candidate_top_k,
            search_queries_by_case=search_queries,
        )
        scores = {"FAISS": faiss, "BM25": bm25, "RRF": rrf}
        if reranker is not None:
            scores["RERANKER"] = reranker
        results.append(ChunkSizeResult(dataset, scores))
    return results


def print_comparison(results: Sequence[ChunkSizeResult]) -> None:
    """Show each method and K with comparable metrics across chunk sizes."""
    if not results:
        raise ValueError("No chunk-size results to compare.")
    labels = [result.dataset.label for result in results]
    print("\nChunk-size comparison (Hit@K; mean Recall@K)")
    print("Method | K | " + " | ".join(labels))
    print("-" * (13 + sum(len(label) + 3 for label in labels)))
    for method in METHODS:
        if method not in results[0].scores:
            continue
        by_size = [
            {score.top_k: score.metrics for score in result.scores[method]}
            for result in results
        ]
        if any(set(scores) != set(by_size[0]) for scores in by_size[1:]):
            raise ValueError(f"Top-K settings differ for {method} across chunk sizes.")
        for top_k in sorted(by_size[0]):
            cells = [
                f"{scores[top_k].hit_fraction} ({scores[top_k].hit_at_k:.1%}); "
                f"{scores[top_k].recall_at_k:.1%}"
                for scores in by_size
            ]
            print(f"{method} | {top_k} | " + " | ".join(cells))


@report_run_costs("chunk_size_comparison")
def main() -> None:
    """Run every matching dataset and print a side-by-side comparison."""
    parser = argparse.ArgumentParser(
        description="Compare FAISS, BM25, and RRF across chunk-size datasets."
    )
    parser.add_argument(
        "--dataset-dir", type=Path, default=DATASET_DIRECTORY,
        help="Directory of eval_<chunk_size>_<overlap_size>.json files.",
    )
    parser.add_argument(
        "--top-k-values", type=int, nargs="+", default=DEFAULT_TOP_K_VALUES,
    )
    parser.add_argument(
        "--rrf-top-k-values", type=int, nargs="+", default=DEFAULT_RRF_TOP_K_VALUES,
    )
    parser.add_argument(
        "--rrf-k", type=int, default=DEFAULT_RRF_K,
    )
    parser.add_argument(
        "--rrf-candidate-top-k", type=int, default=DEFAULT_RRF_CANDIDATE_TOP_K,
    )
    parser.add_argument(
        "--enable-reranker", action="store_true",
        help="Also compare model reranking across all chunk sizes.",
    )
    parser.add_argument(
        "--reranker-top-k-values", type=int, nargs="+",
        default=DEFAULT_RERANKER_TOP_K_VALUES,
    )
    parser.add_argument(
        "--reranker-candidate-top-k", type=int,
        default=DEFAULT_RERANKER_CANDIDATE_TOP_K,
    )
    args = parser.parse_args()

    datasets = load_comparable_cases(discover_datasets(args.dataset_dir))
    print(
        f"Comparing {len(datasets)} chunk sizes using "
        f"{sum(bool(case['relevant_chunks']) for case in datasets[0][1])} "
        "answerable questions."
    )
    results = run_chunk_size_comparison(
        datasets,
        top_k_values=args.top_k_values,
        rrf_top_k_values=args.rrf_top_k_values,
        rrf_k=args.rrf_k,
        rrf_candidate_top_k=args.rrf_candidate_top_k,
        reranker_top_k_values=(
            args.reranker_top_k_values if args.enable_reranker else None
        ),
        reranker_candidate_top_k=args.reranker_candidate_top_k,
    )
    print_comparison(results)


if __name__ == "__main__":
    main()
