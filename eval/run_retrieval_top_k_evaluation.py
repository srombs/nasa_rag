"""Run retrieval evaluation across several top-K values efficiently."""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import semantic_search  # noqa: E402
from eval.run_bm25_retrieval_evaluation import retrieve_bm25_references  # noqa: E402
from eval.run_faiss_retrieval_evaluation import (  # noqa: E402
    RetrievalMetrics,
    RetrievedReferences,
    chunk_reference,
    evaluate_faiss_retrieval,
    retrieve_faiss_references,
)
from eval.run_retrieval_evaluation import (  # noqa: E402
    EVALUATION_PATH,
    RetrievalEvaluationCase,
    load_evaluation_cases,
)
from model_costs import report_run_costs  # noqa: E402
from models import DocumentChunk, RerankResult  # noqa: E402

DEFAULT_TOP_K_VALUES = (1, 3, 5, 10, 30)
DEFAULT_RRF_TOP_K_VALUES = (1, 3, 5, 10)
DEFAULT_RRF_K = 60
DEFAULT_RRF_CANDIDATE_TOP_K = semantic_search.TOP_K
DEFAULT_RERANKER_TOP_K_VALUES = (1, 3, 5, 10)
DEFAULT_RERANKER_CANDIDATE_TOP_K = 10
RerankedResults = dict[str, list[RerankResult]]


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
    """Run the FAISS top-K evaluation."""
    return _run_top_k_evaluation(
        cases,
        retriever,
        top_k_values,
        retrieve_faiss_references,
        "FAISS",
    )


def run_bm25_top_k_evaluation(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object,
    top_k_values: Sequence[int] = DEFAULT_TOP_K_VALUES,
) -> list[TopKEvaluationResult]:
    """Run the BM25 top-K evaluation."""
    return _run_top_k_evaluation(
        cases,
        retriever,
        top_k_values,
        retrieve_bm25_references,
        "BM25",
    )


def run_both_top_k_evaluation(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object,
    top_k_values: Sequence[int] = DEFAULT_TOP_K_VALUES,
) -> tuple[list[TopKEvaluationResult], list[TopKEvaluationResult]]:
    """Evaluate FAISS and BM25 using one rewritten query per case."""
    unique_top_k_values = _validate_top_k_values(top_k_values)
    faiss_references, bm25_references = retrieve_both_references(
        cases, retriever, top_k=max(unique_top_k_values)
    )
    return (
        _evaluate_top_k_values(cases, faiss_references, unique_top_k_values, "FAISS"),
        _evaluate_top_k_values(cases, bm25_references, unique_top_k_values, "BM25"),
    )


def run_all_top_k_evaluation(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object,
    top_k_values: Sequence[int] = DEFAULT_TOP_K_VALUES,
    rrf_top_k_values: Sequence[int] = DEFAULT_RRF_TOP_K_VALUES,
    rrf_k: int = DEFAULT_RRF_K,
    rrf_candidate_top_k: int = DEFAULT_RRF_CANDIDATE_TOP_K,
    reranker_top_k_values: Sequence[int] | None = None,
    reranker_candidate_top_k: int = DEFAULT_RERANKER_CANDIDATE_TOP_K,
) -> tuple[
    list[TopKEvaluationResult],
    list[TopKEvaluationResult],
    list[TopKEvaluationResult],
    list[TopKEvaluationResult] | None,
]:
    """Evaluate FAISS, BM25, RRF, and optionally model reranking."""
    unique_top_k_values = _validate_top_k_values(top_k_values)
    unique_rrf_top_k_values = _validate_top_k_values(rrf_top_k_values)
    unique_reranker_top_k_values = (
        _validate_top_k_values(reranker_top_k_values)
        if reranker_top_k_values is not None
        else None
    )
    if rrf_k < 0:
        raise ValueError("rrf_k cannot be negative.")
    if reranker_candidate_top_k <= 0:
        raise ValueError("reranker_candidate_top_k must be greater than zero.")
    largest_rrf_result = max(
        max(unique_rrf_top_k_values),
        reranker_candidate_top_k if unique_reranker_top_k_values is not None else 0,
    )
    if rrf_candidate_top_k < max(
        max(unique_top_k_values), largest_rrf_result
    ):
        raise ValueError("rrf_candidate_top_k must cover every requested top_k.")

    faiss_references, bm25_references = retrieve_both_references(
        cases, retriever, top_k=rrf_candidate_top_k
    )
    rrf_references = {
        case_id: fuse_rrf_references(
            faiss_references[case_id],
            bm25_references[case_id],
            top_k=largest_rrf_result,
            rrf_k=rrf_k,
        )
        for case_id in faiss_references
    }
    print_retrieval_misses(
        cases,
        rrf_references,
        faiss_references,
        bm25_references,
        top_k=max(unique_rrf_top_k_values),
        search_name="RRF",
    )
    reranker_output = (
        rerank_rrf_references(
            cases,
            retriever,
            rrf_references,
            top_k=reranker_candidate_top_k,
        )
        if unique_reranker_top_k_values is not None
        else None
    )
    reranker_references, reranked_results_by_case = (
        reranker_output if reranker_output is not None else (None, None)
    )
    if reranker_references is not None and reranked_results_by_case is not None:
        print_reranker_misses(
            cases,
            rrf_references,
            reranked_results_by_case,
            rrf_hit_k=reranker_candidate_top_k,
        )
    return (
        _evaluate_top_k_values(cases, faiss_references, unique_top_k_values, "FAISS"),
        _evaluate_top_k_values(cases, bm25_references, unique_top_k_values, "BM25"),
        _evaluate_top_k_values(cases, rrf_references, unique_rrf_top_k_values, "RRF"),
        _evaluate_top_k_values(
            cases,
            reranker_references,
            unique_reranker_top_k_values,
            "RERANKER",
        )
        if reranker_references is not None and unique_reranker_top_k_values is not None
        else None,
    )


def fuse_rrf_references(
    faiss_references: Sequence[str],
    bm25_references: Sequence[str],
    top_k: int,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[str]:
    """Fuse two ranked reference lists with reciprocal rank fusion."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")
    if rrf_k < 0:
        raise ValueError("rrf_k cannot be negative.")

    scores = {}
    for ranked_references in (faiss_references, bm25_references):
        for rank, reference in enumerate(ranked_references, start=1):
            scores[reference] = scores.get(reference, 0.0) + 1 / (rrf_k + rank)
    return sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]


def rerank_rrf_references(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object,
    rrf_references_by_case: RetrievedReferences,
    top_k: int,
) -> tuple[RetrievedReferences, RerankedResults]:
    """Use the model reranker to reorder the top RRF candidates per question."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")

    chunk_by_reference: dict[str, DocumentChunk] = {
        chunk_reference(chunk): chunk for chunk in retriever.document_chunks
    }
    answerable_cases = [case for case in cases if case["relevant_chunks"]]
    print(
        f"[RERANKER] Reranking top {top_k} RRF candidates for "
        f"{len(answerable_cases)} answerable cases."
    )
    reranked_references = {}
    reranked_results_by_case = {}
    for position, case in enumerate(answerable_cases, start=1):
        print(
            f"[RERANKER] {position}/{len(answerable_cases)} | "
            f"{case['id']} | {case['question']}"
        )
        try:
            rrf_chunks = [
                chunk_by_reference[reference]
                for reference in rrf_references_by_case[case["id"]][:top_k]
            ]
        except KeyError as error:
            raise ValueError(
                f"Missing RRF chunk reference for case {case['id']!r}."
            ) from error
        reranked_results = retriever.rerank_rrf_results(case["question"], rrf_chunks)
        reranked_results_by_case[case["id"]] = reranked_results
        reranked_references[case["id"]] = [
            chunk_reference(result.chunk) for result in reranked_results
        ]
    return reranked_references, reranked_results_by_case


def print_reranker_misses(
    cases: Sequence[RetrievalEvaluationCase],
    rrf_references_by_case: RetrievedReferences,
    reranked_results_by_case: RerankedResults,
    rrf_hit_k: int,
) -> None:
    """Print failures where RRF hit but reranking missed at rank one."""
    if rrf_hit_k <= 0:
        raise ValueError("rrf_hit_k must be greater than zero.")

    misses = []
    for case in cases:
        if not case["relevant_chunks"]:
            continue
        expected_references = set(case["relevant_chunks"])
        rrf_references = rrf_references_by_case[case["id"]][:rrf_hit_k]
        reranked_results = reranked_results_by_case[case["id"]]
        reranked_references = [
            chunk_reference(result.chunk) for result in reranked_results
        ]
        rrf_hit = bool(expected_references.intersection(rrf_references))
        reranker_hit_at_one = bool(
            expected_references.intersection(reranked_references[:1])
        )
        if rrf_hit and not reranker_hit_at_one:
            misses.append((case, rrf_references, reranked_results))

    print(
        f"\n[RERANKER] Misses at Hit@1 where RRF Hit@{rrf_hit_k} succeeds: "
        f"{len(misses)}"
    )
    for case, rrf_references, reranked_results in misses:
        rrf_ranks = {
            reference: rank
            for rank, reference in enumerate(rrf_references, start=1)
        }
        reranked_references = [
            chunk_reference(result.chunk) for result in reranked_results
        ]
        rerank_ranks = {
            reference: rank
            for rank, reference in enumerate(reranked_references, start=1)
        }
        print(f"ID: {case['id']}")
        print(f"Question: {case['question']}")
        print(f"Expected chunks: {', '.join(case['relevant_chunks'])}")
        print("RRF:")
        for rank, reference in enumerate(rrf_references, start=1):
            print(f"  {rank} | {reference}")
        print("Reranked:")
        for rank, result in enumerate(reranked_results, start=1):
            print(
                f"  {rank} | score {result.score:.2f} | {result.reason} | "
                f"{chunk_reference(result.chunk)}"
            )
        print("Expected chunk ranks:")
        for reference in case["relevant_chunks"]:
            print(
                f"  {reference}: RRF rank "
                f"{rrf_ranks.get(reference, 'not in top ' + str(rrf_hit_k))} "
                f"-> Rerank rank {rerank_ranks.get(reference, 'not returned')}"
            )


def print_retrieval_misses(
    cases: Sequence[RetrievalEvaluationCase],
    retrieved_references_by_case: RetrievedReferences,
    faiss_references_by_case: RetrievedReferences,
    bm25_references_by_case: RetrievedReferences,
    top_k: int,
    search_name: str,
) -> None:
    """Print answerable cases with no relevant chunk in the first K results."""
    misses = []
    for case in cases:
        if not case["relevant_chunks"]:
            continue
        retrieved_references = retrieved_references_by_case[case["id"]][:top_k]
        expected_references = set(case["relevant_chunks"])
        if not set(retrieved_references).intersection(expected_references):
            misses.append((case, retrieved_references))

    print(f"\n[{search_name}] Misses at K={top_k}: {len(misses)}")
    for case, retrieved_references in misses:
        faiss_ranks = {
            reference: rank
            for rank, reference in enumerate(
                faiss_references_by_case[case["id"]], start=1
            )
        }
        bm25_ranks = {
            reference: rank
            for rank, reference in enumerate(
                bm25_references_by_case[case["id"]], start=1
            )
        }
        print(f"ID: {case['id']}")
        print(f"Question: {case['question']}")
        print(f"Expected chunks: {', '.join(case['relevant_chunks'])}")
        print(f"Retrieved chunks: {', '.join(retrieved_references) or 'None'}")
        print("RRF chunks with base ranks:")
        for rrf_rank, reference in enumerate(retrieved_references, start=1):
            print(
                f"  RRF rank {rrf_rank} | "
                f"FAISS rank {faiss_ranks.get(reference, 'not in candidates')} | "
                f"BM25 rank {bm25_ranks.get(reference, 'not in candidates')} | "
                f"{reference}"
            )
        print("Expected chunks with base ranks:")
        for reference in case["relevant_chunks"]:
            print(
                f"  FAISS rank {faiss_ranks.get(reference, 'not in candidates')} | "
                f"BM25 rank {bm25_ranks.get(reference, 'not in candidates')} | "
                f"{reference}"
            )


def retrieve_both_references(
    cases: Sequence[RetrievalEvaluationCase], retriever: object, top_k: int
) -> tuple[RetrievedReferences, RetrievedReferences]:
    """Rewrite once per question, then retrieve FAISS and BM25 rankings."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")

    answerable_cases = [case for case in cases if case["relevant_chunks"]]
    print(
        f"[RETRIEVAL] Rewriting once, then retrieving top {top_k} with FAISS "
        f"and BM25 for {len(answerable_cases)} answerable cases."
    )
    faiss_references = {}
    bm25_references = {}
    for position, case in enumerate(answerable_cases, start=1):
        print(
            f"[RETRIEVAL] {position}/{len(answerable_cases)} | "
            f"{case['id']} | {case['question']}"
        )
        search_query = retriever.rewrite_query(case["question"])
        faiss_references[case["id"]] = [
            chunk_reference(chunk)
            for chunk in semantic_search.run_embedded_search(
                case["question"], retriever, top_k=top_k, search_query=search_query
            )
        ]
        bm25_references[case["id"]] = [
            chunk_reference(result.chunk)
            for result in semantic_search.run_bm25_search(
                case["question"], retriever, top_k=top_k, search_query=search_query
            )
        ]
    return faiss_references, bm25_references


def _run_top_k_evaluation(
    cases: Sequence[RetrievalEvaluationCase],
    retriever: object,
    top_k_values: Sequence[int],
    retrieve_references,
    search_name: str,
) -> list[TopKEvaluationResult]:
    """Retrieve once at the maximum K, then evaluate every requested K."""
    unique_top_k_values = _validate_top_k_values(top_k_values)
    retrieved_references = retrieve_references(
        cases, retriever, top_k=max(unique_top_k_values)
    )
    return _evaluate_top_k_values(
        cases, retrieved_references, unique_top_k_values, search_name
    )


def _validate_top_k_values(top_k_values: Sequence[int]) -> list[int]:
    """Validate and normalize the requested top-K values."""
    if not top_k_values:
        raise ValueError("At least one top_k value is required.")
    if any(top_k <= 0 for top_k in top_k_values):
        raise ValueError("All top_k values must be greater than zero.")
    return sorted(set(top_k_values))


def _evaluate_top_k_values(
    cases: Sequence[RetrievalEvaluationCase],
    retrieved_references: RetrievedReferences,
    top_k_values: Sequence[int],
    search_name: str,
) -> list[TopKEvaluationResult]:
    """Evaluate one method's already-retrieved rankings at each requested K."""
    results = []
    for top_k in top_k_values:
        print(f"[{search_name}] Calculating Hit@{top_k} and Recall@{top_k}.")
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


def print_top_k_results(
    results: Sequence[TopKEvaluationResult], search_name: str
) -> None:
    """Print an overview table for the measured top-K values."""
    print(f"\n{search_name} results")
    print("top_k | hit_at_k        | mean_recall_at_k")
    print("------|-----------------|-----------------")
    for result in results:
        print(
            f"{result.top_k:5} | {result.metrics.hit_fraction:>5} "
            f"({result.metrics.hit_at_k:.1%}) | "
            f"{result.metrics.recall_at_k:.1%}"
        )


@report_run_costs("top_k_evaluation")
def main() -> None:
    """Load retrieval once and evaluate a configurable set of top-K values."""
    parser = argparse.ArgumentParser(
        description="Evaluate retrieval methods across several top-K values."
    )
    parser.add_argument(
        "--evaluation-file",
        type=Path,
        default=EVALUATION_PATH,
        help=f"Evaluation JSON path (default: {EVALUATION_PATH.name}).",
    )
    parser.add_argument(
        "--search-method",
        choices=("faiss", "bm25", "both", "rrf", "all"),
        default="all",
        help="Retrieval method to evaluate (default: all).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=semantic_search.DEFAULT_CHUNK_SIZE,
        help=f"Words per chunk (default: {semantic_search.DEFAULT_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--rrf-top-k-values",
        type=int,
        nargs="+",
        default=DEFAULT_RRF_TOP_K_VALUES,
        help=(
            "RRF top-K values to compare "
            f"(default: {' '.join(map(str, DEFAULT_RRF_TOP_K_VALUES))})."
        ),
    )
    parser.add_argument(
        "--rrf-k",
        type=int,
        default=DEFAULT_RRF_K,
        help=f"RRF rank constant (default: {DEFAULT_RRF_K}).",
    )
    parser.add_argument(
        "--rrf-candidate-top-k",
        type=int,
        default=DEFAULT_RRF_CANDIDATE_TOP_K,
        help=(
            "FAISS and BM25 candidates supplied to RRF "
            f"(default: {DEFAULT_RRF_CANDIDATE_TOP_K})."
        ),
    )
    parser.add_argument(
        "--enable-reranker",
        action="store_true",
        help="Rerank RRF candidates with model calls (disabled by default).",
    )
    parser.add_argument(
        "--reranker-top-k-values",
        type=int,
        nargs="+",
        default=DEFAULT_RERANKER_TOP_K_VALUES,
        help=(
            "Reranker top-K values to compare "
            f"(default: {' '.join(map(str, DEFAULT_RERANKER_TOP_K_VALUES))})."
        ),
    )
    parser.add_argument(
        "--reranker-candidate-top-k",
        type=int,
        default=DEFAULT_RERANKER_CANDIDATE_TOP_K,
        help=(
            "RRF candidates sent to the reranker per question "
            f"(default: {DEFAULT_RERANKER_CANDIDATE_TOP_K})."
        ),
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

    cases = load_evaluation_cases(
        args.evaluation_file, args.chunk_size, args.overlap_size
    )
    retriever = semantic_search.load_retriever(args.chunk_size, args.overlap_size)
    if args.enable_reranker and args.search_method not in ("all", "rrf"):
        parser.error("--enable-reranker requires --search-method rrf or all.")
    if args.search_method == "all":
        faiss_results, bm25_results, rrf_results, reranker_results = (
            run_all_top_k_evaluation(
            cases,
            retriever,
            args.top_k_values,
            args.rrf_top_k_values,
            args.rrf_k,
            args.rrf_candidate_top_k,
            args.reranker_top_k_values if args.enable_reranker else None,
            args.reranker_candidate_top_k,
            )
        )
        print_top_k_results(faiss_results, "FAISS")
        print_top_k_results(bm25_results, "BM25")
        print_top_k_results(rrf_results, "RRF")
        if reranker_results is not None:
            print_top_k_results(reranker_results, "RERANKER")
    elif args.search_method == "both":
        faiss_results, bm25_results = run_both_top_k_evaluation(
            cases, retriever, args.top_k_values
        )
        print_top_k_results(faiss_results, "FAISS")
        print_top_k_results(bm25_results, "BM25")
    elif args.search_method == "faiss":
        print_top_k_results(
            run_top_k_evaluation(cases, retriever, args.top_k_values), "FAISS"
        )
    elif args.search_method == "bm25":
        print_top_k_results(
            run_bm25_top_k_evaluation(cases, retriever, args.top_k_values), "BM25"
        )
    elif args.search_method == "rrf":
        _, _, rrf_results, reranker_results = run_all_top_k_evaluation(
            cases,
            retriever,
            args.top_k_values,
            args.rrf_top_k_values,
            args.rrf_k,
            args.rrf_candidate_top_k,
            args.reranker_top_k_values if args.enable_reranker else None,
            args.reranker_candidate_top_k,
        )
        print_top_k_results(rrf_results, "RRF")
        if reranker_results is not None:
            print_top_k_results(reranker_results, "RERANKER")


if __name__ == "__main__":
    main()
