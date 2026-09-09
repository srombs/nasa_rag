"""Run the semantic-search pipeline against the evaluation questions."""

import argparse
import json
from pathlib import Path
import sys
from typing import TypedDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = Path(__file__).with_name("test_questions_harder.json")
sys.path.insert(0, str(PROJECT_ROOT))

import semantic_search  # noqa: E402


class EvaluationQuestion(TypedDict):
    """One question and its acceptable source files."""

    question: str
    expected_sources: list[str]


def load_questions(path: str | Path = QUESTIONS_PATH) -> list[EvaluationQuestion]:
    """Load question and expected-source records from the evaluation JSON file."""
    questions = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(questions, list):
        raise ValueError("Evaluation questions must be a JSON list.")
    if not all(
        isinstance(question, dict)
        and isinstance(question.get("question"), str)
        and isinstance(question.get("expected_sources"), list)
        and all(isinstance(source, str) for source in question["expected_sources"])
        for question in questions
    ):
        raise ValueError(
            "Each evaluation record needs a question and expected_sources array."
        )
    return questions


def evaluate_questions(
    questions: list[EvaluationQuestion],
    retriever,
    top_k: int = semantic_search.TOP_K,
    verbose: bool = True,
    show_misses_only: bool = False,
    print_summary: bool = True,
) -> float:
    """Print retrieval results and return source-level recall at ``top_k``."""
    if not questions:
        raise ValueError("At least one evaluation question is required.")

    hits = 0
    for question_record in questions:
        question = question_record["question"]
        expected_sources = question_record["expected_sources"]
        ranked_chunks = semantic_search.run_search(question, retriever, top_k=top_k)
        retrieved_sources = {chunk.source for chunk in ranked_chunks}
        hit = bool(retrieved_sources.intersection(expected_sources))
        hits += hit

        if verbose and (not show_misses_only or not hit):
            print(f"\nQuestion: {question}")
            print(f"Expected sources: {', '.join(expected_sources)}")
            semantic_search.print_ranked_chunks(ranked_chunks, top_k=top_k)
            print(f"Retrieved sources: {', '.join(sorted(retrieved_sources))}")
            print(f"Result: {'HIT' if hit else 'MISS'}")

    recall = hits / len(questions)
    if print_summary:
        print(f"\nRecall@{top_k}: {hits}/{len(questions)} ({recall:.1%})")
    return recall


def main() -> None:
    """Search every evaluation question with one shared loaded retriever."""
    parser = argparse.ArgumentParser(
        description="Evaluate semantic search against expected source files."
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
        help=(
            "Number of chunks to evaluate per question "
            f"(default: {semantic_search.TOP_K})."
        ),
    )
    args = parser.parse_args()
    questions = load_questions()
    retriever = semantic_search.load_retriever(args.chunk_size, args.overlap_size)
    evaluate_questions(questions, retriever, top_k=args.top_k)


if __name__ == "__main__":
    main()
