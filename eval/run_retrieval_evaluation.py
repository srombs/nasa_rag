"""Load and inspect answer-level retrieval evaluation cases."""

import argparse
import json
from pathlib import Path
from typing import TypedDict

EVALUATION_PATH = Path(__file__).with_name("eval_v1.json")


class RetrievalEvaluationCase(TypedDict):
    """One answer-level retrieval evaluation case."""

    id: str
    question: str
    expected_answer: str | None
    relevant_chunks: list[str]
    difficulty: str
    category: str
    expected_source_filter: str | None


def load_evaluation_cases(
    path: str | Path = EVALUATION_PATH,
) -> list[RetrievalEvaluationCase]:
    """Load and validate the retrieval cases stored in ``eval_v1.json``."""
    evaluation_path = Path(path)
    try:
        cases = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid retrieval evaluation JSON: {evaluation_path}"
        ) from error

    if not isinstance(cases, list):
        raise ValueError("Retrieval evaluation cases must be a JSON list.")

    required_fields = {
        "id",
        "question",
        "expected_answer",
        "relevant_chunks",
        "difficulty",
        "category",
        "expected_source_filter",
    }
    case_ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != required_fields:
            raise ValueError(
                "Each retrieval evaluation case must contain the required fields."
            )
        if not isinstance(case["id"], str) or not case["id"].strip():
            raise ValueError("Retrieval evaluation case IDs must be nonempty strings.")
        if case["id"] in case_ids:
            raise ValueError(f"Duplicate retrieval evaluation case ID: {case['id']}")
        if not isinstance(case["question"], str) or not case["question"].strip():
            raise ValueError("Retrieval evaluation questions must be nonempty strings.")
        if case["expected_answer"] is not None and not isinstance(
            case["expected_answer"], str
        ):
            raise ValueError("Expected answers must be strings or null.")
        if not isinstance(case["relevant_chunks"], list) or not all(
            isinstance(chunk, str) for chunk in case["relevant_chunks"]
        ):
            raise ValueError("Relevant chunks must be a string array.")
        if not isinstance(case["difficulty"], str) or not isinstance(
            case["category"], str
        ):
            raise ValueError("Difficulty and category must be strings.")
        if case["expected_source_filter"] is not None and not isinstance(
            case["expected_source_filter"], str
        ):
            raise ValueError("Expected source filters must be strings or null.")
        case_ids.add(case["id"])

    return cases


def print_evaluation_cases(cases: list[RetrievalEvaluationCase]) -> None:
    """Print the loaded evaluation cases without running retrieval yet."""
    for case in cases:
        print(f"\nID: {case['id']}")
        print(f"Question: {case['question']}")
        print(f"Expected answer: {case['expected_answer']}")
        print(f"Relevant chunks: {', '.join(case['relevant_chunks']) or 'None'}")
        print(f"Expected source filter: {case['expected_source_filter']}")


def main() -> None:
    """Load the retrieval-evaluation data and print its cases for inspection."""
    parser = argparse.ArgumentParser(
        description="Load answer-level retrieval evaluation cases."
    )
    parser.add_argument(
        "--evaluation-file",
        type=Path,
        default=EVALUATION_PATH,
        help=f"Evaluation JSON path (default: {EVALUATION_PATH.name}).",
    )
    args = parser.parse_args()

    cases = load_evaluation_cases(args.evaluation_file)
    print(
        f"Loaded {len(cases)} retrieval evaluation cases from "
        f"{args.evaluation_file}."
    )
    print_evaluation_cases(cases)


if __name__ == "__main__":
    main()
