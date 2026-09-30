"""Keep test model-cost events out of the normal local ledger."""

import pytest


@pytest.fixture(autouse=True)
def isolate_model_cost_log(monkeypatch, tmp_path):
    monkeypatch.setenv("NASA_RAG_COST_LOG_PATH", str(tmp_path / "model_costs.jsonl"))
