"""Cost accounting tests use synthetic OpenAI usage; they never call the API."""

import json
import sys
from decimal import Decimal
from types import SimpleNamespace

import pytest

import generator
import model_costs


def _records(monkeypatch, tmp_path):
    path = tmp_path / "model_costs.jsonl"
    monkeypatch.setenv(model_costs.LOG_PATH_ENV, str(path))
    return path


def test_response_costs_include_cache_reads_writes_and_output(
    monkeypatch, tmp_path, capsys
):
    path = _records(monkeypatch, tmp_path)
    usage = SimpleNamespace(
        input_tokens=1200,
        output_tokens=100,
        input_tokens_details=SimpleNamespace(cached_tokens=500, cache_write_tokens=200),
        output_tokens_details=SimpleNamespace(reasoning_tokens=25),
    )
    response = SimpleNamespace(model="gpt-5.6-luna", usage=usage)

    @model_costs.report_run_costs("test_eval")
    def run():
        return model_costs.call_model(
            "rerank", "responses", "gpt-5.6-luna", lambda **_kwargs: response
        )

    assert run() is response
    record = json.loads(path.read_text().strip())
    # (500 * .20 + 500 * .02 + 200 * .25 + 100 * 1.20) / 1M
    assert Decimal(record["estimated_cost_usd"]) == Decimal("0.00028")
    assert record["tokens"]["reasoning_tokens"] == 25
    assert record["rates_usd_per_million"]["cache_write"] == "0.25"
    assert "rerank: 1 call(s), known ~$0.00028000" in capsys.readouterr().out


def test_embedding_cost_uses_prompt_tokens(monkeypatch, tmp_path):
    path = _records(monkeypatch, tmp_path)
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1000, total_tokens=1000),
        model="text-embedding-3-small",
    )
    model_costs.call_model(
        "document_embedding", "embeddings", "text-embedding-3-small",
        lambda **_kwargs: response,
    )
    record = json.loads(path.read_text().strip())
    assert Decimal(record["estimated_cost_usd"]) == Decimal("0.00002")


def test_missing_usage_and_failed_request_have_unknown_cost(monkeypatch, tmp_path):
    path = _records(monkeypatch, tmp_path)
    model_costs.call_model(
        "query_rewrite", "responses", "gpt-5.6-luna",
        lambda **_kwargs: SimpleNamespace(output_text="fake"),
    )

    def fail(**_kwargs):
        raise RuntimeError("API failure")

    with pytest.raises(RuntimeError, match="API failure"):
        model_costs.call_model("rerank", "responses", "gpt-5.6-luna", fail)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["estimated_cost_usd"] for record in records] == [None, None]
    assert records[1]["status"] == "error"
    assert records[1]["error_type"] == "RuntimeError"


def test_large_context_uses_model_multiplier():
    usage = SimpleNamespace(
        input_tokens=272_001,
        output_tokens=100,
        input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=0),
    )
    _, cost = model_costs._estimate_cost("responses", "gpt-5.6-luna", usage)
    assert cost == (
        Decimal(272_001) * Decimal("0.40") + Decimal(100) * Decimal("1.80")
    ) / Decimal(1_000_000)


def test_generation_records_usage_before_output_validation(monkeypatch, tmp_path):
    path = _records(monkeypatch, tmp_path)
    response = SimpleNamespace(
        output_text="   ",
        model="gpt-5.6-luna",
        usage=SimpleNamespace(
            input_tokens=50,
            output_tokens=10,
            input_tokens_details=SimpleNamespace(
                cached_tokens=0, cache_write_tokens=0
            ),
        ),
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_: response))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda: client))

    with pytest.raises(generator.GenerationError, match="empty answer"):
        generator.generate_answer("NASA context", "What is NASA?")

    record = json.loads(path.read_text().strip())
    assert record["operation"] == "answer_generation"
    assert Decimal(record["estimated_cost_usd"]) > 0
