"""Live search flow through HTTP, with providers replaced and no paid calls."""

import json
from datetime import datetime
from decimal import Decimal
from threading import Event
from types import SimpleNamespace
from uuid import UUID

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from stream_support import loopback  # noqa: E402

from nasa_rag import web  # noqa: E402

STAGES = [
    "plan_query",
    "embed_query",
    "semantic_search",
    "keyword_search",
    "combine_rankings",
    "rerank_evidence",
    "generate_answer",
    "check_citations",
]
GENERATED = "A claim. [unknown.txt, chunk 999]"
ANSWER = (
    GENERATED + "\n\n[Validation warning: citations not in retrieved chunks: "
    "[unknown.txt, chunk 999]]"
)


def test_stage_and_request_metrics_match_recorded_usage_and_request_ledger(
    metered_provider, tmp_path
):
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
        legacy = client.post("/ask", json={"question": "Hubble?"})
        second = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    total = flow[-1]["data"]["metrics"]
    assert total["model_calls"] == 13
    assert total["models"] == ["gpt-5.6-luna", "text-embedding-3-small"]
    assert total["tokens"] == {
        "input_tokens": 15400,
        "cached_input_tokens": 6000,
        "cache_write_tokens": 2400,
        "output_tokens": 1200,
        "reasoning_tokens": 300,
    }
    assert Decimal(total["known_cost_usd"]) == Decimal("0.00338")
    assert total["unknown_cost_calls"] == 0
    assert total["cost_complete"] is True
    assert total["price_dates"] == ["2026-09-29"]
    assert total["duration_ms"] >= 0
    assert events(second)[-1]["data"]["metrics"]["model_calls"] == 13
    assert set(legacy.json()) == {"request_id", "answer"}

    stages = {
        e["stage_id"]: e["data"]["metrics"]
        for e in flow
        if e["type"] == "stage.completed"
    }
    for snapshot in flow[-1]["data"]["stages"]:
        assert snapshot["metrics"] == stages[snapshot["stage_id"]]
    for stage in (
        "semantic_search",
        "keyword_search",
        "combine_rankings",
        "check_citations",
    ):
        assert stages[stage]["model_calls"] == 0
        assert set(stages[stage]["tokens"].values()) == {0}
        assert Decimal(stages[stage]["known_cost_usd"]) == 0
        assert stages[stage]["unknown_cost_calls"] == 0
        assert stages[stage]["cost_complete"] is True
        assert stages[stage]["models"] == stages[stage]["price_dates"] == []
    assert stages["plan_query"]["model_calls"] == 1
    assert stages["embed_query"]["model_calls"] == 1
    assert stages["embed_query"]["tokens"] == {
        "input_tokens": 1000,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }
    assert stages["rerank_evidence"]["model_calls"] == 10
    assert Decimal(stages["rerank_evidence"]["known_cost_usd"]) == Decimal("0.0028")
    assert stages["generate_answer"]["model_calls"] == 1
    records = [
        json.loads(line)
        for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
    ]
    assert len(records) == 39
    ids = {r.headers["x-request-id"] for r in (response, legacy, second)}
    assert len(ids) == 3
    for request_id in ids:
        request_records = [r for r in records if r["request_id"] == request_id]
        assert len(request_records) == 13
        assert all(
            r["run_id"] == request_id and r["run_name"] == "ask"
            for r in request_records
        )
    assert all(
        "question" not in r and "answer" not in r and "prompt" not in r for r in records
    )


@pytest.mark.parametrize("missing", ["all_usage", "cache_write", "reasoning"])
def test_missing_usage_stays_unknown_while_preserving_known_categories(
    metered_provider, missing
):
    if missing == "all_usage":
        metered_provider.usage["answer"] = None
    elif missing == "cache_write":
        metered_provider.usage["answer"].input_tokens_details.cache_write_tokens = None
    else:
        metered_provider.usage["answer"].output_tokens_details.reasoning_tokens = None
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    assert flow[-1]["type"] == "run.completed"
    total = flow[-1]["data"]["metrics"]
    stage = flow[-1]["data"]["stages"][6]["metrics"]
    assert total["model_calls"] == 13
    assert stage["model_calls"] == 1
    if missing == "all_usage":
        assert set(total["tokens"].values()) == {None}
        assert set(stage["tokens"].values()) == {None}
    else:
        assert total["tokens"] == {
            "input_tokens": 15400,
            "cached_input_tokens": 6000,
            "cache_write_tokens": None if missing == "cache_write" else 2400,
            "output_tokens": 1200,
            "reasoning_tokens": None if missing == "reasoning" else 300,
        }
    # Existing pricing does not require reasoning breakdown: it is part of output.
    assert total["cost_complete"] is (missing == "reasoning")
    assert total["unknown_cost_calls"] == (0 if missing == "reasoning" else 1)
    assert Decimal(total["known_cost_usd"]) == Decimal(
        "0.00338" if missing == "reasoning" else "0.00310"
    )


def test_unknown_rates_preserve_tokens_and_only_the_known_embedding_subtotal(
    metered_provider, monkeypatch
):
    from nasa_rag import model_costs

    monkeypatch.delitem(model_costs.PRICES, "gpt-5.6-luna")
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    total = events(response)[-1]["data"]["metrics"]
    assert total["model_calls"] == 13
    assert total["tokens"]["input_tokens"] == 15400
    assert total["tokens"]["output_tokens"] == 1200
    assert total["unknown_cost_calls"] == 12
    assert total["cost_complete"] is False
    assert Decimal(total["known_cost_usd"]) == Decimal("0.00002")
    assert total["price_dates"] == ["2026-09-29"]


@pytest.mark.parametrize("validation_failure", [False, True])
def test_failed_stage_reports_only_usage_actually_recorded(
    metered_provider, validation_failure, tmp_path
):
    if validation_failure:
        metered_provider.outputs["answer"] = "  "
    else:

        def fail():
            raise RuntimeError("private provider failure")

        metered_provider.hooks["answer"] = fail
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    assert flow[-2]["type"] == "stage.failed"
    assert flow[-2]["stage_id"] == "generate_answer"
    failed = flow[-2]["data"]["metrics"]
    total = flow[-1]["data"]["metrics"]
    assert failed["model_calls"] == 1
    assert total["model_calls"] == 13
    assert total["cost_complete"] is validation_failure
    assert failed["cost_complete"] is validation_failure
    assert failed["unknown_cost_calls"] == (0 if validation_failure else 1)
    assert total["unknown_cost_calls"] == (0 if validation_failure else 1)
    if validation_failure:
        assert failed["tokens"]["input_tokens"] == 1200
        assert failed["tokens"]["output_tokens"] == 100
        assert Decimal(failed["known_cost_usd"]) == Decimal("0.00028")
        assert Decimal(total["known_cost_usd"]) == Decimal("0.00338")
    else:
        assert set(failed["tokens"].values()) == {None}
        assert set(total["tokens"].values()) == {None}
        assert Decimal(failed["known_cost_usd"]) == 0
        assert Decimal(total["known_cost_usd"]) == Decimal("0.00310")
    assert flow[-1]["data"]["stages"][6]["metrics"] == failed
    assert flow[-1]["data"]["stages"][7]["metrics"] is None
    records = [
        json.loads(line)
        for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
    ]
    assert len(records) == 13
    assert records[-1]["status"] == ("response" if validation_failure else "error")
    assert records[-1]["request_id"] == response.headers["x-request-id"]


def test_ledger_write_failure_keeps_in_memory_usage_and_success(
    metered_provider, monkeypatch, tmp_path
):
    # A directory cannot be opened as an append-only ledger file.
    monkeypatch.setenv("NASA_RAG_COST_LOG_PATH", str(tmp_path))
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    terminal = events(response)[-1]
    assert terminal["type"] == "run.completed"
    assert terminal["data"]["answer"] == ANSWER
    assert terminal["data"]["metrics"]["model_calls"] == 13
    assert Decimal(terminal["data"]["metrics"]["known_cost_usd"]) == Decimal("0.00338")
    assert terminal["data"]["metrics"]["cost_complete"] is True


def test_no_usage_is_an_incomplete_zero_subtotal_not_free_model_work(provider):
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    terminal = events(response)[-1]["data"]
    metrics = terminal["metrics"]
    assert metrics["model_calls"] == metrics["unknown_cost_calls"] == 13
    assert metrics["cost_complete"] is False
    assert Decimal(metrics["known_cost_usd"]) == 0
    assert metrics["price_dates"] == []
    assert set(metrics["tokens"].values()) == {None}
    assert terminal["stages"][1]["metrics"]["tokens"] == {
        "input_tokens": None,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }


def test_startup_usage_is_excluded_from_http_request_accounting(
    metered_provider, tmp_path
):
    from nasa_rag.model_costs import call_model

    def factory():
        call_model(
            "document_embedding",
            "embeddings",
            "text-embedding-3-small",
            lambda **_: SimpleNamespace(usage=SimpleNamespace(prompt_tokens=9999)),
        )
        return web.load_pipeline()

    with TestClient(web.create_app(factory)) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    metrics = events(response)[-1]["data"]["metrics"]
    assert metrics["model_calls"] == 13
    assert metrics["tokens"]["input_tokens"] == 15400
    assert Decimal(metrics["known_cost_usd"]) == Decimal("0.00338")
    records = [
        json.loads(line)
        for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
    ]
    assert len(records) == 14
    assert records[0]["operation"] == "document_embedding"
    assert "request_id" not in records[0]
    assert records[0]["run_id"] != response.headers["x-request-id"]
    assert all(r["request_id"] == response.headers["x-request-id"] for r in records[1:])


@pytest.mark.parametrize("route", ["/ask", "/ask/stream"])
def test_worker_keeps_request_accounting_after_http_timeout(
    metered_provider, monkeypatch, tmp_path, route
):
    monkeypatch.setenv("NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "0.2")
    entered = Event()
    release = Event()

    def block():
        entered.set()
        assert release.wait(10), "Test failed to release provider"

    metered_provider.hooks["answer"] = block
    with TestClient(web.create_app()) as client:
        try:
            response = client.post(route, json={"question": "Hubble?"})
            assert entered.is_set()
            request_id = response.headers["x-request-id"]
            original_body = response.content
            records_so_far = [
                json.loads(line)
                for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
            ]
            assert len(records_so_far) == 12
            if route == "/ask/stream":
                terminal = events(response)[-1]
                assert terminal["type"] == "run.failed"
                assert terminal["data"]["processing_may_continue"] is True
                assert terminal["data"]["metrics"]["model_calls"] == 12
                assert terminal["data"]["metrics"]["tokens"]["input_tokens"] == 14200
                assert Decimal(
                    terminal["data"]["metrics"]["known_cost_usd"]
                ) == Decimal("0.00310")
                active = terminal["data"]["stages"][6]
                assert active["status"] == "unknown"
                assert active["metrics"]["model_calls"] == 0
                assert active["metrics"]["duration_ms"] > 0
                assert active["metrics"]["cost_complete"] is True
                assert terminal["data"]["stages"][7]["metrics"] is None
            else:
                assert response.status_code == 504
                assert response.json()["error"]["code"] == "response_timeout"
            assert client.post("/ask", json={"question": "Busy?"}).status_code == 503
        finally:
            release.set()
    # Lifespan shutdown waits for the actual worker, including its late call.
    records = [
        json.loads(line)
        for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
    ]
    assert len(records) == 13
    assert all(r["request_id"] == r["run_id"] == request_id for r in records)
    assert all(r["run_name"] == "ask" for r in records)
    assert records[-1]["operation"] == "answer_generation"
    assert Decimal(records[-1]["estimated_cost_usd"]) == Decimal("0.00028")
    assert response.content == original_body
    if route == "/ask/stream":
        assert events(response)[-1] == terminal


def test_worker_keeps_request_accounting_after_stream_disconnect(
    metered_provider, tmp_path
):
    import httpx

    entered = Event()
    release = Event()

    def block():
        entered.set()
        assert release.wait(10), "Test failed to release provider"

    metered_provider.hooks["answer"] = block
    with (
        loopback(web.create_app()) as url,
        httpx.Client(base_url=url, timeout=5) as client,
    ):
        try:
            with client.stream(
                "POST", "/ask/stream", json={"question": "Hubble?"}
            ) as response:
                request_id = response.headers["x-request-id"]
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        if (
                            event["type"] == "stage.started"
                            and event["stage_id"] == "generate_answer"
                        ):
                            assert entered.wait(2)
                            break
            assert not release.is_set()
            records_so_far = (tmp_path / "model_costs.jsonl").read_text().splitlines()
            assert len(records_so_far) == 12
        finally:
            release.set()
    records = [
        json.loads(line)
        for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
    ]
    assert len(records) == 13
    assert all(r["request_id"] == r["run_id"] == request_id for r in records)
    assert records[-1]["operation"] == "answer_generation"


def test_partial_reranking_timeout_counts_only_recorded_calls(
    metered_provider, small_corpus, monkeypatch, tmp_path
):
    monkeypatch.setenv("NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "0.2")
    release = Event()
    entered = Event()
    calls = [0]

    def block_second():
        calls[0] += 1
        if calls[0] == 2:
            entered.set()
            assert release.wait(10), "Test failed to release provider"

    metered_provider.hooks["rerank_result"] = block_second
    with TestClient(web.create_app()) as client:
        try:
            response = client.post("/ask/stream", json={"question": "Hubble?"})
            assert entered.is_set()
            terminal = events(response)[-1]["data"]
            assert terminal["processing_may_continue"] is True
            assert terminal["metrics"]["model_calls"] == 3
            assert Decimal(terminal["metrics"]["known_cost_usd"]) == Decimal("0.00058")
            active = terminal["stages"][5]
            assert active["status"] == "unknown"
            assert len(active["details"]["evaluated_results"]) == 1
            assert active["metrics"]["model_calls"] == 1
            assert active["metrics"]["tokens"]["input_tokens"] == 1200
            assert active["metrics"]["tokens"]["output_tokens"] == 100
            assert active["metrics"]["unknown_cost_calls"] == 0
            assert Decimal(active["metrics"]["known_cost_usd"]) == Decimal("0.00028")
        finally:
            release.set()
    records = [
        json.loads(line)
        for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
    ]
    assert len(records) == 7
    assert all(r["request_id"] == response.headers["x-request-id"] for r in records)
    assert events(response)[-1]["data"] == terminal


def test_recorded_usage_is_frozen_before_a_provider_object_is_reused(metered_provider):
    def reuse_usage():
        old_usage = metered_provider.usage["retrieval_plan"]
        old_usage.input_tokens = 999999
        old_usage.input_tokens_details.cached_tokens = 999999

    metered_provider.hooks["answer"] = reuse_usage
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    terminal = flow[-1]["data"]
    completed_plan = next(e for e in flow if e["type"] == "stage.completed")
    assert completed_plan["data"]["metrics"] == terminal["stages"][0]["metrics"]
    assert terminal["stages"][0]["metrics"]["tokens"]["input_tokens"] == 1200
    assert terminal["metrics"]["tokens"]["input_tokens"] == 15400
    assert terminal["metrics"]["tokens"]["cached_input_tokens"] == 6000
    assert Decimal(terminal["metrics"]["known_cost_usd"]) == Decimal("0.00338")


def test_monotonic_timings_cover_provider_retries_and_independent_run_duration(
    monkeypatch,
):
    from nasa_rag import search_flow, web_stream
    from nasa_rag.model_costs import call_model

    now = [100.0]
    for module in (web, search_flow, web_stream):
        monkeypatch.setattr(module, "monotonic", lambda: now[0])

    def provider_with_retries(**_):
        # One application call containing two attempts, with backoff between.
        now[0] += 1
        now[0] += 2
        now[0] += 2
        return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1000))

    def pipeline(question):
        with search_flow.search_stage("embed_query"):
            call_model(
                "query_embedding",
                "embeddings",
                "text-embedding-3-small",
                provider_with_retries,
            )
        now[0] += 2  # Observed work between stages is part of overall duration.
        with search_flow.search_stage("generate_answer"):
            now[0] += 4
        return "Answer"

    with TestClient(web.create_app(lambda: pipeline)) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    terminal = events(response)[-1]["data"]
    metrics = terminal["metrics"]
    assert metrics["duration_ms"] == 11000
    assert metrics["model_calls"] == 1
    assert terminal["stages"][1]["metrics"]["duration_ms"] == 5000
    assert terminal["stages"][6]["metrics"]["duration_ms"] == 4000


@pytest.fixture
def ranked_corpus(provider):
    """Opposing base rankings make full-ranking fusion observable over HTTP."""
    from nasa_rag.ingestion.file_loader import save_document_cache
    from nasa_rag.models import DocumentChunk

    texts = [
        " ".join(["rare"] * (i + 1) + ["filler"] * (78 - i) + ["Ω"]) for i in range(40)
    ]
    save_document_cache(
        provider.cache / "embeds/document_cache_100_20.json",
        {
            "hubble.txt": [
                DocumentChunk("hubble.txt", i, text, [1.0, i / 40])
                for i, text in enumerate(texts)
            ],
            "iss.txt": [
                DocumentChunk("iss.txt", i, "other " * 80, [0.0, 1.0])
                for i in range(50)
            ],
            "nasa_overview.txt": [],
            "space_shuttle.txt": [],
        },
    )
    provider.vector[:] = [1.0, 0.0]
    provider.outputs["retrieval_plan"] = (
        '{"search_query":"rare", "source_file_filter":"hubble.txt"}'
    )
    return texts


def events(response):
    result = []
    for frame in response.text.split("\n\n"):
        if not frame or frame.startswith(":"):
            continue
        name, sequence, data = frame.splitlines()
        payload = json.loads(data.removeprefix("data: "))
        assert name == "event: " + payload["type"]
        assert sequence == "id: " + str(payload["sequence"])
        result.append(payload)
    return result


def test_reranking_progress_and_final_order_preserve_validated_candidate_data(
    provider, small_corpus
):
    scores = iter([0.2, 0.9, 0.9, 0.1])
    provider.outputs["rerank_result"] = lambda _: json.dumps(
        {"score": next(scores), "reason": "  Evidence Ω  "}
    )
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    details = completed_details(flow)
    candidates = details["combine_rankings"]["results"]
    progress = [e for e in flow if e["type"] == "stage.progress"]
    assert len(progress) == 4
    for i, event in enumerate(progress):
        assert event["stage_id"] == "rerank_evidence"
        assert event["data"] == {
            "completed": i + 1,
            "total": 4,
            "result": {
                **{k: v for k, v in candidates[i].items() if k != "rank"},
                "rerank_score": [0.2, 0.9, 0.9, 0.1][i],
                "reason": "Evidence Ω",
            },
        }
    results = details["rerank_evidence"]["results"]
    assert results == [
        {**progress[index]["data"]["result"], "rank": rank}
        for rank, index in enumerate([1, 2, 0, 3], 1)
    ]
    snapshot = flow[-1]["data"]["stages"][5]
    assert snapshot["details"] == {"results": results}
    assert snapshot["progress"] == progress[-1]["data"]
    assert [kind for kind, _ in provider.operations] == [
        "retrieval_plan",
        "query_embedding",
        *(["rerank_result"] * 4),
        "answer",
    ]
    assert "provider-only-secret" not in response.text


@pytest.mark.parametrize("later_failure", [False, True])
def test_candidate_progress_arrives_before_later_evaluation_finishes(
    provider, small_corpus, later_failure
):
    import httpx

    entered = Event()
    release = Event()

    def block_third_candidate():
        if sum(kind == "rerank_result" for kind, _ in provider.operations) == 3:
            entered.set()
            assert release.wait(10), "Test failed to release the provider"
            if later_failure:
                provider.outputs["rerank_result"] = (
                    '{"score":7,"reason":"unvalidated-private-reason"}'
                )

    provider.hooks["rerank_result"] = block_third_candidate
    with (
        loopback(web.create_app()) as url,
        httpx.Client(base_url=url, timeout=5) as client,
    ):
        try:
            with client.stream(
                "POST", "/ask/stream", json={"question": "Hubble?"}
            ) as response:
                received = []
                progress = []
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    received.append(event)
                    if event["type"] == "stage.progress":
                        progress.append(event["data"])
                        if len(progress) == 2:
                            assert entered.wait(2)
                            assert not release.is_set()
                            assert progress[-1]["completed"] == 2
                            assert progress[-1]["total"] == 4
                            assert all("answer" not in e["data"] for e in received)
                            release.set()
                assert release.is_set(), "No live candidate progress was delivered"
                terminal = received[-1]
                assert terminal["type"] == (
                    "run.failed" if later_failure else "run.completed"
                )
                snapshot = terminal["data"]["stages"][5]
                assert snapshot["progress"] == progress[-1]
                if later_failure:
                    assert len(progress) == 2
                    assert snapshot["status"] == "failed"
                    assert snapshot["details"] == {
                        "evaluated_results": [p["result"] for p in progress]
                    }
                    assert terminal["data"]["http_equivalent_status"] == 502
                    assert "answer" not in terminal["data"]
                    assert [s["status"] for s in terminal["data"]["stages"][6:]] == [
                        "skipped",
                        "skipped",
                    ]
                    assert "unvalidated-private-reason" not in json.dumps(received)
                else:
                    assert len(progress) == 4
                    assert terminal["data"]["answer"] == ANSWER
                assert [kind for kind, _ in provider.operations] == [
                    "retrieval_plan",
                    "query_embedding",
                    *(["rerank_result"] * (3 if later_failure else 4)),
                    *([] if later_failure else ["answer"]),
                ]
        finally:
            release.set()


@pytest.mark.parametrize(
    ("answer", "outcome", "checked", "invalid", "warning"),
    [
        (
            "A claim. [hubble.txt, chunk 0][hubble.txt, chunk 0]",
            "valid",
            ["[hubble.txt, chunk 0]"],
            [],
            "",
        ),
        (
            "A claim. [z.txt, chunk 9][hubble.txt, chunk 0][a.txt, chunk 8]",
            "warning",
            ["[a.txt, chunk 8]", "[hubble.txt, chunk 0]", "[z.txt, chunk 9]"],
            ["[a.txt, chunk 8]", "[z.txt, chunk 9]"],
            "\n\n[Validation warning: citations not in retrieved chunks: "
            "[a.txt, chunk 8], [z.txt, chunk 9]]",
        ),
        (
            "The provided documents do not contain enough information.",
            "no_citations",
            [],
            [],
            "",
        ),
    ],
)
def test_generation_context_and_citation_outcomes_preserve_the_exact_answer(
    provider, small_corpus, answer, outcome, checked, invalid, warning
):
    from nasa_rag.generation.generator import GENERATION_INSTRUCTIONS

    scores = [0.2, 0.9, 0.9, 0.1]
    evaluation = iter(scores)
    provider.outputs["rerank_result"] = lambda _: json.dumps(
        {"score": next(evaluation), "reason": "Evidence"}
    )
    provider.outputs["answer"] = " \n" + answer + " \n"
    with TestClient(web.create_app()) as client:
        flow = events(
            client.post("/ask/stream", json={"question": "Visitor question?"})
        )
        stream_calls = provider.operations.copy()
        provider.operations.clear()
        evaluation = iter(scores)
        legacy = client.post("/ask", json={"question": "Visitor question?"})
    details = completed_details(flow)
    results = details["rerank_evidence"]["results"]
    assert details["generate_answer"] == {
        "context_references": [p["reference"] for p in results]
    }
    assert details["check_citations"] == {
        "outcome": outcome,
        "checked_references": checked,
        "invalid_references": invalid,
    }
    for stage in flow[-1]["data"]["stages"][6:]:
        assert stage["details"] == details[stage["stage_id"]]
    generation = stream_calls[-1][1]
    assert generation["input"] == (
        "Context:\n"
        + "\n\n---\n\n".join(p["reference"] + "\n" + p["text"] for p in results)
        + "\n\nQuestion:\nVisitor question?"
    )
    assert generation["instructions"] == GENERATION_INSTRUCTIONS
    assert flow[-1]["type"] == "run.completed"
    assert flow[-1]["data"]["answer"] == legacy.json()["answer"] == answer + warning
    assert all("answer" not in e["data"] for e in flow[:-1])
    assert answer not in json.dumps(flow[:-1])
    assert stream_calls == provider.operations
    assert [kind for kind, _ in stream_calls] == [
        "retrieval_plan",
        "query_embedding",
        *(["rerank_result"] * 4),
        "answer",
    ]


def test_incomplete_reranking_snapshot_retains_results_when_observation_ends(
    provider, small_corpus, monkeypatch
):
    from time import monotonic

    from nasa_rag import web_stream

    offset = [0.0]
    monkeypatch.setenv("NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "120")
    monkeypatch.setattr(web_stream, "monotonic", lambda: monotonic() + offset[0])

    def end_observation():
        if sum(kind == "rerank_result" for kind, _ in provider.operations) == 3:
            offset[0] = 121.0

    provider.hooks["rerank_result"] = end_observation
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    progress = [e["data"] for e in flow if e["type"] == "stage.progress"]
    assert len(progress) == 2
    terminal = flow[-1]
    assert terminal["type"] == "run.failed"
    assert terminal["data"]["error"]["code"] == "response_timeout"
    snapshot = terminal["data"]["stages"][5]
    assert snapshot["status"] == "unknown"
    assert snapshot["progress"] == progress[-1]
    assert snapshot["details"] == {"evaluated_results": [p["result"] for p in progress]}
    assert "answer" not in terminal["data"]
    assert not any(e["type"] == "stage.failed" for e in flow)


def completed_details(flow):
    return {
        event["stage_id"]: event["data"]["details"]
        for event in flow
        if event["type"] == "stage.completed"
    }


@pytest.mark.parametrize("source", ["hubble.txt", None])
def test_plan_and_embedding_details_reflect_the_actual_requests(provider, source):
    provider.outputs["retrieval_plan"] = json.dumps(
        {"search_query": "  planned Hubble  ", "source_file_filter": source}
    )
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    details = completed_details(flow)
    assert details["plan_query"] == {
        "search_query": "planned Hubble",
        "source_file_filter": source,
    }
    assert details["embed_query"] == {
        "model": "text-embedding-3-small",
        "dimensions": 2,
    }
    assert provider.operations[1][1] == {
        "model": "text-embedding-3-small",
        "input": "planned Hubble",
    }
    terminal = {stage["stage_id"]: stage for stage in flow[-1]["data"]["stages"]}
    for stage in ("plan_query", "embed_query"):
        assert terminal[stage]["details"] == details[stage]


def test_embedding_details_name_the_requested_model(provider, monkeypatch):
    from nasa_rag import embedder

    with TestClient(web.create_app()) as client:
        monkeypatch.setattr(embedder, "EMBEDDING_MODEL", "requested-embedding-model")
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    details = completed_details(events(response))
    assert details["embed_query"]["model"] == "requested-embedding-model"
    assert provider.operations[1][1]["model"] == "requested-embedding-model"


def test_native_rankings_use_bounded_ordered_passages_and_explicit_fields(
    provider, ranked_corpus
):
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Find rare"})
    details = completed_details(events(response))
    semantic = details["semantic_search"]["results"]
    keyword = details["keyword_search"]["results"]
    assert [p["chunk_index"] for p in semantic] == list(range(30))
    assert [p["chunk_index"] for p in keyword] == list(range(39, 9, -1))
    assert semantic[0] == {
        "source": "hubble.txt",
        "chunk_index": 0,
        "reference": "[hubble.txt, chunk 0]",
        "text": ranked_corpus[0],
        "rank": 1,
        "similarity": 1.0,
    }
    assert keyword[0] == {
        "source": "hubble.txt",
        "chunk_index": 39,
        "reference": "[hubble.txt, chunk 39]",
        "text": ranked_corpus[39],
        "rank": 1,
        "bm25_score": pytest.approx(0.531738, abs=0.000001),
    }
    for results, score in ((semantic, "similarity"), (keyword, "bm25_score")):
        assert [p["rank"] for p in results] == list(range(1, 31))
        assert all(p["source"] == "hubble.txt" for p in results)
        assert all(
            set(p) == {"source", "chunk_index", "reference", "text", "rank", score}
            for p in results
        )


def test_fusion_uses_full_rankings_and_preserves_candidates_and_model_work(
    provider, ranked_corpus
):
    with TestClient(web.create_app()) as client:
        flow = events(client.post("/ask/stream", json={"question": "Find rare"}))
        streamed_calls = provider.operations.copy()
        provider.operations.clear()
        legacy = client.post("/ask", json={"question": "Find rare"})
    details = completed_details(flow)
    fusion = details["combine_rankings"]
    assert fusion["rrf_k"] == 60
    candidates = fusion["results"]
    # Opposing 40-item lists: both extremes win, with stable corpus-order ties.
    assert [p["chunk_index"] for p in candidates] == [0, 39, 1, 38, 2, 37, 3, 36, 4, 35]
    assert candidates[0] == {
        "source": "hubble.txt",
        "chunk_index": 0,
        "reference": "[hubble.txt, chunk 0]",
        "text": ranked_corpus[0],
        "rank": 1,
        "rrf_score": pytest.approx(0.02639344262295082),
        "faiss_rank": 1,
        "bm25_rank": 40,
    }
    assert candidates[1]["faiss_rank"] == 40
    assert candidates[1]["bm25_rank"] == 1
    assert candidates[1]["rrf_score"] == candidates[0]["rrf_score"]
    assert [p["rank"] for p in candidates] == list(range(1, 11))
    assert all(set(p) == set(candidates[0]) for p in candidates)
    assert flow[-1]["data"]["answer"] == legacy.json()["answer"] == ANSWER
    assert streamed_calls == provider.operations
    assert [kind for kind, _ in streamed_calls] == [
        "retrieval_plan",
        "query_embedding",
        *(["rerank_result"] * 10),
        "answer",
    ]
    rerank_inputs = [
        args["input"] for kind, args in streamed_calls if kind == "rerank_result"
    ]
    assert rerank_inputs == [
        "Query:\nFind rare\n\nChunk:\n" + ranked_corpus[i]
        for i in [0, 39, 1, 38, 2, 37, 3, 36, 4, 35]
    ]
    generation_input = streamed_calls[-1][1]["input"]
    assert generation_input == (
        "Context:\n"
        + "\n\n---\n\n".join(p["reference"] + "\n" + p["text"] for p in candidates)
        + "\n\nQuestion:\nFind rare"
    )
    for snapshot in flow[-1]["data"]["stages"][:5]:
        assert snapshot["details"] == details[snapshot["stage_id"]]


@pytest.mark.parametrize("later_failure", [False, True])
def test_published_retrieval_snapshots_survive_chunk_mutation_and_later_failure(
    provider, ranked_corpus, monkeypatch, later_failure
):
    from nasa_rag.retrieval.retriever import Retriever

    # Retain the real loaded objects solely to inject later shared-state mutation.
    # Retrieval and all model work still follow the production pipeline.
    load = Retriever.load

    def load_with_mutation(retriever):
        load(retriever)

        def mutate():
            for chunk in retriever.document_chunks:
                chunk.source = "mutated-source.txt"
                chunk.chunk_index += 1000
                chunk.text = "mutated-after-publication"
                chunk.similarity = -123.0
                chunk.rrf_score = -456.0
                chunk.faiss_rank = 999
                chunk.bm25_rank = 999
            if later_failure:
                raise RuntimeError("private-later-failure")

        provider.hooks["rerank_result"] = mutate

    monkeypatch.setattr(Retriever, "load", load_with_mutation)
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Find rare"})
    flow = events(response)
    details = completed_details(flow)
    assert flow[-1]["type"] == ("run.failed" if later_failure else "run.completed")
    for snapshot in flow[-1]["data"]["stages"][:5]:
        assert snapshot["status"] == "completed"
        assert snapshot["details"] == details[snapshot["stage_id"]]
    for stage in ("semantic_search", "keyword_search", "combine_rankings"):
        for passage in details[stage]["results"]:
            assert passage["text"] == ranked_corpus[passage["chunk_index"]]
    assert details["semantic_search"]["results"][0]["similarity"] == 1.0
    assert details["combine_rankings"]["results"][0]["rrf_score"] == pytest.approx(
        0.02639344262295082
    )
    # Later stages may expose the deliberately changed objects; the already
    # published retrieval snapshots must continue to show the original data.
    retrieval_details = json.dumps({stage: details[stage] for stage in STAGES[:5]})
    assert "mutated-after-publication" not in retrieval_details
    assert "mutated-source.txt" not in retrieval_details
    assert "private-later-failure" not in response.text
    assert "provider-only-secret" not in response.text
    if later_failure:
        snapshots = flow[-1]["data"]["stages"]
        assert snapshots[5]["status"] == "failed"
        assert [s["status"] for s in snapshots[6:]] == ["skipped", "skipped"]


@pytest.mark.parametrize(
    "output",
    [
        "[]",
        '{"search_query":" ","source_file_filter":null}',
        '{"search_query":"x","source_file_filter":123}',
        '{"search_query":"x","source_file_filter":" "}',
        '{"search_query":"x"}',
        '{"search_query":"x","source_file_filter":null,"extra":"provider-only-secret"}',
    ],
)
def test_invalid_plans_never_publish_success_or_start_embedding(provider, output):
    provider.outputs["retrieval_plan"] = output
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    assert [(e["type"], e["stage_id"]) for e in flow] == [
        ("run.started", None),
        ("stage.started", "plan_query"),
        ("stage.failed", "plan_query"),
        ("run.failed", None),
    ]
    assert flow[-1]["data"]["http_equivalent_status"] == 502
    assert flow[-1]["data"]["stages"][0]["details"] is None
    assert [kind for kind, _ in provider.operations] == ["retrieval_plan"]
    assert "provider-only-secret" not in response.text


@pytest.mark.parametrize("stage", ["semantic_search", "keyword_search"])
@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_native_scores_fail_the_stage_before_completion(
    provider, ranked_corpus, monkeypatch, stage, score
):
    if stage == "semantic_search":
        import faiss

        search = faiss.IndexFlatIP.search

        def invalid_search(index, *args, **kwargs):
            scores, indexes = search(index, *args, **kwargs)
            scores[0, 0] = score
            return scores, indexes

        monkeypatch.setattr(faiss.IndexFlatIP, "search", invalid_search)
    else:
        from rank_bm25 import BM25Okapi

        get_scores = BM25Okapi.get_scores

        def invalid_scores(index, *args, **kwargs):
            scores = get_scores(index, *args, **kwargs)
            # Set every eligible score so truncation cannot hide the fault.
            scores[:40] = score
            return scores

        monkeypatch.setattr(BM25Okapi, "get_scores", invalid_scores)
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Find rare"})
    flow = events(response)
    assert [(e["type"], e["stage_id"]) for e in flow[-2:]] == [
        ("stage.failed", stage),
        ("run.failed", None),
    ]
    assert stage not in completed_details(flow)
    assert flow[-1]["data"]["stages"][0]["status"] == "completed"
    assert all(kind != "rerank_result" for kind, _ in provider.operations)

    # parse_constant rejects Python's otherwise permissive NaN/Infinity handling.
    def reject_constant(value):
        pytest.fail(f"Invalid JSON number: {value}")

    for line in response.text.splitlines():
        if line.startswith("data: "):
            json.loads(line[6:], parse_constant=reject_constant)


def test_stream_preserves_real_stage_order_answer_and_model_calls(provider):
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert "content-length" not in response.headers
        flow = events(response)
        assert flow[0]["type"] == "run.started"
        assert flow[0]["data"] == {"stage_ids": STAGES}
        assert [
            (e["type"], e["stage_id"])
            for e in flow[1:-1]
            if e["type"] != "stage.progress"
        ] == [
            (kind, stage)
            for stage in STAGES
            for kind in ("stage.started", "stage.completed")
        ]
        assert flow[-1]["type"] == "run.completed"
        assert flow[-1]["data"]["answer"] == ANSWER
        assert [stage["status"] for stage in flow[-1]["data"]["stages"]] == [
            "completed"
        ] * 8
        for i, event in enumerate(flow, 1):
            assert event["schema_version"] == 1
            assert event["sequence"] == i
            assert event["request_id"] == response.headers["x-request-id"]
            UUID(event["request_id"])
            assert (
                datetime.fromisoformat(event["timestamp_utc"])
                .utcoffset()
                .total_seconds()
                == 0
            )
            assert event["elapsed_ms"] >= 0
        assert [e["elapsed_ms"] for e in flow] == sorted(e["elapsed_ms"] for e in flow)
        assert [kind for kind, _ in provider.operations] == [
            "retrieval_plan",
            "query_embedding",
            *(["rerank_result"] * 10),
            "answer",
        ]
        assert provider.operations[1][1]["input"] == "planned Hubble"
        legacy = client.post("/ask", json={"question": "Hubble?"})
        assert legacy.json()["answer"] == flow[-1]["data"]["answer"]
        assert set(legacy.json()) == {"request_id", "answer"}


def test_live_stage_and_heartbeat_arrive_while_provider_is_blocked(
    provider, monkeypatch
):
    import httpx

    from nasa_rag import web_stream

    monkeypatch.setattr(web_stream, "HEARTBEAT_SECONDS", 0.02)
    entered = Event()
    release = Event()

    def block():
        entered.set()
        assert release.wait(10), "Test failed to release the provider"

    provider.hooks["answer"] = block
    with (
        loopback(web.create_app()) as url,
        httpx.Client(base_url=url, timeout=5) as client,
    ):
        try:
            with client.stream(
                "POST", "/ask/stream", json={"question": "Hubble?"}
            ) as response:
                assert response.status_code == 200
                received = []
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        received.append(json.loads(line[6:]))
                    if (
                        line.startswith(":")
                        and received
                        and received[-1]["stage_id"] == "generate_answer"
                        and not release.is_set()
                    ):
                        assert entered.wait(2)
                        assert not release.is_set()
                        assert received[-1]["type"] == "stage.started"
                        assert received[-1]["stage_id"] == "generate_answer"
                        assert client.get("/health").status_code == 200
                        for route in ("/ask", "/ask/stream"):
                            busy = client.post(route, json={"question": "Concurrent"})
                            assert busy.status_code == 503
                            assert busy.json()["error"]["code"] == "busy"
                        release.set()
                    if received and received[-1]["type"] == "run.completed":
                        break
                assert received[-1]["data"]["answer"] == ANSWER
                assert len(received) == 28
        finally:
            release.set()


@pytest.mark.parametrize(
    ("operation", "stage", "output"),
    [
        (
            "retrieval_plan",
            "plan_query",
            '{"search_query":"x","source_file_filter":"private.txt"}',
        ),
        ("rerank_result", "rerank_evidence", '{"score":7,"reason":"private reason"}'),
        ("answer", "generate_answer", "  "),
    ],
)
def test_invalid_model_outputs_fail_the_actual_stage_without_leaking_details(
    provider, operation, stage, output, caplog
):
    provider.outputs[operation] = output
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "private question"})
    assert response.status_code == 200
    flow = events(response)
    assert flow[-2]["type"] == "stage.failed"
    assert flow[-2]["stage_id"] == stage
    assert flow[-1]["type"] == "run.failed"
    assert flow[-1]["data"]["http_equivalent_status"] == 502
    assert flow[-1]["data"]["processing_may_continue"] is False
    assert flow[-1]["data"]["error"] == {
        "code": "upstream_error",
        "message": "The model provider could not answer.",
    }
    for secret in (
        "private question",
        "private reason",
        "private.txt",
        "provider-only-secret",
    ):
        assert secret not in response.text + caplog.text
    assert sum(e["type"].startswith("run.") for e in flow) == 2
    record = [r for r in caplog.records if r.name == "nasa_rag.web"][-1]
    assert record.http_status == 200
    assert record.stream_outcome == "failed"
    assert record.failure_code == "upstream_error"


def test_stream_and_json_share_submission_allowance_and_proxy_identity(monkeypatch):
    monkeypatch.setenv("NASA_RAG_TRUSTED_PROXIES", "10.0.0.0/24")
    with TestClient(
        web.create_app(lambda: lambda question: question), client=("10.0.0.5", 1000)
    ) as client:
        for i in range(10):
            route = "/ask" if i % 2 else "/ask/stream"
            response = client.post(
                route, json={}, headers={"X-Forwarded-For": "192.0.2.1"}
            )
            assert response.status_code == 422
            assert response.json()["request_id"] == response.headers["x-request-id"]
        for route in ("/ask", "/ask/stream"):
            response = client.post(
                route,
                json={"question": "Hello"},
                headers={"X-Forwarded-For": "192.0.2.1"},
            )
            assert response.status_code == 429
            assert response.headers["content-type"] == "application/json"
            assert response.json()["error"]["code"] == "rate_limited"
        other = client.post(
            "/ask/stream",
            json={"question": "Hello"},
            headers={"X-Forwarded-For": "192.0.2.2"},
        )
        assert other.status_code == 200


def test_deadline_terminal_does_not_release_the_running_worker(
    provider, monkeypatch, caplog
):
    from nasa_rag import web_stream

    monkeypatch.setattr(web_stream, "HEARTBEAT_SECONDS", 0.02)
    monkeypatch.setenv("NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "0.1")
    entered = Event()
    release = Event()

    def block():
        entered.set()
        assert release.wait(5)

    provider.hooks["retrieval_plan"] = block
    with TestClient(web.create_app()) as client:
        try:
            response = client.post("/ask/stream", json={"question": "Hubble?"})
            assert entered.is_set()
            flow = events(response)
            assert [e["type"] for e in flow] == [
                "run.started",
                "stage.started",
                "run.failed",
            ]
            assert flow[-1]["data"]["error"]["code"] == "response_timeout"
            assert flow[-1]["data"]["processing_may_continue"] is True
            assert ": heartbeat\n\n" in response.text
            record = [r for r in caplog.records if r.name == "nasa_rag.web"][-1]
            assert record.http_status == 200
            assert record.stream_outcome == "timeout"
            assert record.failure_code == "response_timeout"
            for route in ("/ask", "/ask/stream"):
                busy = client.post(route, json={"question": "Hubble?"})
                assert busy.status_code == 503
                assert busy.json()["error"]["code"] == "busy"
            assert client.get("/health").status_code == 200
        finally:
            release.set()


def test_unexpected_stream_failure_uses_the_legacy_public_error_mapping(provider):
    def fail():
        raise RuntimeError("private implementation error")

    provider.hooks["query_embedding"] = fail
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
        flow = events(response)
        legacy = client.post("/ask", json={"question": "Hubble?"})
    assert response.status_code == 200
    assert flow[-2]["type"] == "stage.failed"
    assert flow[-2]["stage_id"] == "embed_query"
    assert flow[-1]["data"]["http_equivalent_status"] == legacy.status_code == 500
    assert flow[-1]["data"]["error"] == legacy.json()["error"]
    assert "private" not in response.text + legacy.text


def test_worker_cannot_publish_success_after_the_absolute_deadline(
    provider, monkeypatch
):
    from time import monotonic

    from nasa_rag import web_stream

    offset = [0.0]
    monkeypatch.setenv("NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "120")
    monkeypatch.setattr(web_stream, "monotonic", lambda: monotonic() + offset[0])
    provider.hooks["answer"] = lambda: offset.__setitem__(0, 121.0)
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
    flow = events(response)
    assert flow[-1]["type"] == "run.failed"
    assert flow[-1]["data"]["error"]["code"] == "response_timeout"
    assert not any(e["type"] == "run.completed" for e in flow)
    assert not any(e["type"] == "stage.failed" for e in flow)


@pytest.mark.parametrize(
    "vector", [[], [1.0, 0.0, 0.0], [float("nan"), 0.0], [0.0, 0.0]]
)
def test_embedding_stage_validates_provider_vectors_before_completing(provider, vector):
    provider.vector[:] = vector
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Hubble?"})
        legacy = client.post("/ask", json={"question": "Hubble?"})
    flow = events(response)
    assert [(e["type"], e["stage_id"]) for e in flow[-3:]] == [
        ("stage.started", "embed_query"),
        ("stage.failed", "embed_query"),
        ("run.failed", None),
    ]
    assert flow[-1]["data"]["http_equivalent_status"] == legacy.status_code == 500
    assert flow[-1]["data"]["error"] == legacy.json()["error"]
    assert [kind for kind, _ in provider.operations] == [
        "retrieval_plan",
        "query_embedding",
        "retrieval_plan",
        "query_embedding",
    ]
