"""Evaluate recall across multiple chunking and retrieval settings."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import semantic_search  # noqa: E402
from run_evaluation import evaluate_questions, load_questions  # noqa: E402


CHUNKING_CONFIGURATIONS = [(50, 10), (100, 20), (200, 50)]
TOP_K_VALUES = range(1, 6)


def main() -> None:
    """Print source-level recall for every chunking and top-k combination."""
    questions = load_questions()
    results = []

    for chunk_size, overlap_size in CHUNKING_CONFIGURATIONS:
        retriever = semantic_search.load_retriever(chunk_size, overlap_size)
        for top_k in TOP_K_VALUES:
            print(f"\nMisses: chunk_size={chunk_size}, overlap_size={overlap_size}, top_k={top_k}")
            recall = evaluate_questions(
                questions,
                retriever,
                top_k=top_k,
                verbose=True,
                show_misses_only=True,
                print_summary=False,
            )
            results.append((chunk_size, overlap_size, top_k, recall))

    print("\nchunk_size | overlap_size | top_k | recall")
    print("-----------|--------------|-------|-------")
    for chunk_size, overlap_size, top_k, recall in results:
        print(f"{chunk_size:10} | {overlap_size:12} | {top_k:5} | {recall:.1%}")


if __name__ == "__main__":
    main()
