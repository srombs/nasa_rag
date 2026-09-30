"""Evaluate FAISS retrieval against answer-level chunk references."""

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import semantic_search  # noqa: E402
from eval.run_retrieval_evaluation import (  # noqa: E402
    EVALUATION_PATH,
    RetrievalEvaluationCase,
    load_evaluation_cases,
)
from model_costs import report_run_costs  # noqa: E402
from models import DocumentChunk  # noqa: E402

CHUNK_REFERENCE_PATTERN = re.compile(
    r"^\[\s*(?P<source>[^,\]]+)\s*,\s*chunk\s+(?P<chunk_index>\d+)\s*\]$"
)


@dataclass(frozen=True)
class RetrievalMetrics:
    """Aggregate chunk-retrieval metrics for one evaluation run."""

    hit_at_k: float
    recall_at_k: float
    hit_count: int
    answerable_case_count: int

    @property
    def hit_fraction(self) -> str:
        """Return the hit numerator and denominator for terminal reporting."""
        return f"{self.hit_count}/{self.answerable_case_count}"


RetrievedReferences = dict[str, list[str]]


def chunk_reference(chunk: DocumentChunk) -> str:
    """Return the canonical reference used by the retrieval evaluation set."""
    return f"[{chunk.source}, chunk {chunk.chunk_index}]"


def normalize_chunk_reference(reference: str) -> str:
    """Normalize an evaluation reference to the same form as retrieved chunks."""
    match = CHUNK_REFERENCE_PATTERN.fullmatch(reference.strip())
    if match is None:
        raise ValueError(f"Invalid chunk reference: {reference!r}")
    return f"[{match['source'].strip()}, chunk {int(match['chunk_index'])}]"


def hit_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Return 1.0 when at least one relevant chunk appears in the first K."""
    if k <= 0:
        raise ValueError("k must be greater than zero.")

    return float(bool(set(retrieved[:k]).intersection(relevant)))


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Return the fraction of unique relevant chunks found in the first K."""
    if k <= 0:
        raise ValueError("k must be greater than zero.")

    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0

    return len(set(retrieved[:k]).intersection(relevant_set)) / len(relevant_set)


def retrieve_faiss_references(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object,
    top_k: int,
    show_progress: bool = True,
) -> RetrievedReferences:
    """Retrieve the largest required ranking once for each answerable case."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")

    answerable_cases = [case for case in cases if case["relevant_chunks"]]
    if show_progress:
        print(
            f"[FAISS] Retrieving top {top_k} for "
            f"{len(answerable_cases)} answerable cases."
        )

    retrieved_references_by_case = {}
    for position, case in enumerate(answerable_cases, start=1):
        if show_progress:
            print(
                f"[FAISS] {position}/{len(answerable_cases)} | "
                f"{case['id']} | {case['question']}"
            )
        retrieved_references_by_case[case["id"]] = [
            chunk_reference(chunk)
            for chunk in semantic_search.run_embedded_search(
                case["question"], retriever, top_k=top_k
            )
        ]
    return retrieved_references_by_case


def evaluate_faiss_retrieval(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object | None = None,
    top_k: int = semantic_search.TOP_K,
    verbose: bool = True,
    print_summary: bool = True,
    retrieved_references_by_case: Mapping[str, list[str]] | None = None,
) -> RetrievalMetrics:
    """Retrieve with FAISS and return aggregate chunk Hit@K and Recall@K."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")

    if retrieved_references_by_case is None:
        if retriever is None:
            raise ValueError("A retriever is required when rankings are not supplied.")
        retrieved_references_by_case = retrieve_faiss_references(
            cases, retriever, top_k
        )

    return evaluate_retrieved_references(
        cases,
        retrieved_references_by_case,
        top_k=top_k,
        verbose=verbose,
        print_summary=print_summary,
    )


def evaluate_retrieved_references(
    cases: Sequence[RetrievalEvaluationCase],
    retrieved_references_by_case: Mapping[str, list[str]],
    top_k: int,
    verbose: bool = True,
    print_summary: bool = True,
) -> RetrievalMetrics:
    """Evaluate supplied rankings with chunk Hit@K and macro Recall@K.

    Cases with no expected chunks are skipped because ranked retrieval alone
    cannot establish that a question is unanswerable.
    """
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")

    answerable_cases = [case for case in cases if case["relevant_chunks"]]
    if not answerable_cases:
        raise ValueError("At least one case with relevant chunks is required.")

    hit_count = 0
    recall_total = 0.0
    for case in cases:
        expected_references = {
            normalize_chunk_reference(reference)
            for reference in case["relevant_chunks"]
        }
        if not expected_references:
            if verbose:
                print(f"\nID: {case['id']}")
                print(f"Question: {case['question']}")
                print("Result: SKIP (no relevant chunks)")
            continue

        try:
            retrieved_references = retrieved_references_by_case[case["id"]]
        except KeyError as error:
            raise ValueError(
                f"Missing retrieved references for case {case['id']!r}."
            ) from error
        expected_references_list = sorted(expected_references)
        matching_references = expected_references.intersection(retrieved_references)
        hit = hit_at_k(retrieved_references, expected_references_list, top_k)
        recall = recall_at_k(
            retrieved_references, expected_references_list, top_k
        )
        hit_count += int(hit)
        recall_total += recall

        if verbose:
            print(f"\nID: {case['id']}")
            print(f"Question: {case['question']}")
            print(f"Expected chunks: {', '.join(expected_references_list)}")
            print(f"Retrieved chunks: {', '.join(retrieved_references) or 'None'}")
            print(
                "Matching chunks: "
                f"{', '.join(sorted(matching_references)) or 'None'}"
            )
            print(f"Hit@{top_k}: {hit:.1f}")
            print(f"Recall@{top_k}: {recall:.1%}")
            print(f"Result: {'HIT' if hit else 'MISS'}")

    metrics = RetrievalMetrics(
        hit_at_k=hit_count / len(answerable_cases),
        recall_at_k=recall_total / len(answerable_cases),
        hit_count=hit_count,
        answerable_case_count=len(answerable_cases),
    )
    if print_summary:
        print(f"\nChunk Hit@{top_k}: {metrics.hit_fraction}")
        print(f"Mean Chunk Recall@{top_k}: {metrics.recall_at_k:.1%}")
    return metrics


@report_run_costs("faiss_evaluation")
def main() -> None:
    """Load the shared retriever and evaluate FAISS chunk retrieval."""
    parser = argparse.ArgumentParser(
        description="Evaluate FAISS retrieval against eval_100_20 chunk references."
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
        help=f"FAISS results per question (default: {semantic_search.TOP_K}).",
    )
    args = parser.parse_args()

    cases = load_evaluation_cases(
        args.evaluation_file, args.chunk_size, args.overlap_size
    )
    retriever = semantic_search.load_retriever(args.chunk_size, args.overlap_size)
    evaluate_faiss_retrieval(cases, retriever, top_k=args.top_k)


if __name__ == "__main__":
    main()
