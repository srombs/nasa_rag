"""Compare chunk-size datasets without making live model requests."""

import json
import sys
from types import SimpleNamespace

import pytest

from eval import run_chunk_size_comparison as comparison
from eval.run_faiss_retrieval_evaluation import RetrievalMetrics
from eval.run_retrieval_top_k_evaluation import (
    TopKEvaluationResult,
    retrieve_both_references,
)


def test_existing_datasets_are_aligned_and_sorted():
    datasets = comparison.discover_datasets()
    loaded = comparison.load_comparable_cases(datasets)

    assert {dataset.label for dataset in datasets} >= {
        "50/10", "100/20", "200/50"
    }
    assert datasets == sorted(
        datasets, key=lambda item: (item.chunk_size, item.overlap_size)
    )
    assert all(len(cases) == 25 for _, cases in loaded)
    assert all(sum(bool(case["relevant_chunks"]) for case in cases) == 23
               for _, cases in loaded)


def test_mismatched_questions_are_rejected_before_evaluation(tmp_path):
    source = comparison.DATASET_DIRECTORY / "eval_100_20.json"
    dataset = json.loads(source.read_text(encoding="utf-8"))
    first = tmp_path / "eval_100_20.json"
    second = tmp_path / "eval_200_50.json"
    first.write_text(json.dumps(dataset), encoding="utf-8")
    dataset["metadata"] = {"chunk_size": 200, "overlap_size": 50}
    dataset["cases"][0]["question"] = "A different question"
    second.write_text(json.dumps(dataset), encoding="utf-8")

    with pytest.raises(ValueError, match="not be comparable"):
        comparison.load_comparable_cases(comparison.discover_datasets(tmp_path))


def test_one_rewrite_is_reused_for_every_chunk_size(monkeypatch, capsys):
    loaded = comparison.load_comparable_cases(comparison.discover_datasets())
    rewritten = []
    seen = []

    class FakeRewriter:
        def rewrite(self, question):
            rewritten.append(question)
            return f"search: {question}"

    def fake_evaluation(cases, retriever, **kwargs):
        seen.append((retriever, kwargs["search_queries_by_case"]))
        score = TopKEvaluationResult(
            1,
            RetrievalMetrics(1 / 23, 0.25, 1, 23),
        )
        return [score], [score], [score], None

    monkeypatch.setattr(comparison, "QueryRewriter", FakeRewriter)
    monkeypatch.setattr(
        comparison.semantic_search,
        "load_retriever",
        lambda chunk_size, overlap_size: (chunk_size, overlap_size),
    )
    monkeypatch.setattr(comparison, "run_all_top_k_evaluation", fake_evaluation)

    results = comparison.run_chunk_size_comparison(loaded, top_k_values=[1])
    comparison.print_comparison(results)
    output = capsys.readouterr().out

    assert len(rewritten) == sum(bool(case["relevant_chunks"]) for case in loaded[0][1])
    assert [retriever for retriever, _ in seen] == [
        (dataset.chunk_size, dataset.overlap_size) for dataset, _ in loaded
    ]
    assert all(seen[0][1] is search_queries for _, search_queries in seen)
    assert " | ".join(dataset.label for dataset, _ in loaded) in output
    assert "FAISS | 1 | 1/23 (4.3%); 25.0%" in output


def test_shared_queries_skip_per_corpus_rewriting(monkeypatch):
    case = {
        "id": "case",
        "question": "Original?",
        "relevant_chunks": ["[iss.txt, chunk 0]"],
    }
    retriever = SimpleNamespace(
        rewrite_query=lambda _question: pytest.fail("Question was rewritten twice")
    )
    received = []
    def capture_query(_question, _retriever, **kwargs):
        received.append(kwargs["search_query"])
        return []

    monkeypatch.setattr(
        comparison.semantic_search, "run_embedded_search", capture_query
    )
    monkeypatch.setattr(comparison.semantic_search, "run_bm25_search", capture_query)

    retrieve_both_references(
        [case], retriever, top_k=1, search_queries_by_case={"case": "Shared query"}
    )
    assert received == ["Shared query", "Shared query"]


def test_invalid_top_k_rejected_before_model_calls(monkeypatch):
    loaded = comparison.load_comparable_cases(comparison.discover_datasets())
    monkeypatch.setattr(
        comparison,
        "QueryRewriter",
        lambda: pytest.fail("Invalid settings triggered a model call"),
    )

    with pytest.raises(ValueError, match="RRF candidate count"):
        comparison.run_chunk_size_comparison(
            loaded, top_k_values=[31], rrf_candidate_top_k=30
        )


def test_help_does_not_print_zero_cost_summary(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run_chunk_size_comparison.py", "--help"])
    with pytest.raises(SystemExit) as error:
        comparison.main()
    assert error.value.code == 0
    assert "Model costs" not in capsys.readouterr().out
