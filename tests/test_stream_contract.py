"""Public version-1 examples checked against actual server serialization."""

import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from uuid import UUID

import pytest

pytest.importorskip("fastapi")
import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from stream_support import loopback  # noqa: E402

from nasa_rag import web  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "docs/fixtures/search-stream-v1"
EXAMPLE_ID = "00000000-0000-4000-8000-000000000001"
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
VALID_ANSWER = "Synthetic evidence Ω. [hubble.txt, chunk 0]"


def decode_frame(frame):
    name, sequence, data = frame.splitlines()
    payload = json.loads(data.removeprefix("data: "))
    assert name == "event: " + payload["type"]
    assert sequence == "id: " + str(payload["sequence"])
    return payload


def assert_envelopes(flow, request_id):
    UUID(request_id)
    for i, event in enumerate(flow, 1):
        assert event["schema_version"] == 1
        assert event["sequence"] == i
        assert event["request_id"] == request_id
        assert datetime.fromisoformat(event["timestamp_utc"]).utcoffset() == timedelta(
            0
        )
        assert event["elapsed_ms"] >= 0
        assert (
            event["stage_id"] in STAGES
            if event["type"].startswith("stage.")
            else event["stage_id"] is None
        )
    assert [e["elapsed_ms"] for e in flow] == sorted(e["elapsed_ms"] for e in flow)
    assert flow[0]["type"] == "run.started"
    assert flow[0]["data"] == {"stage_ids": STAGES}
    assert [
        e["type"] for e in flow if e["type"] in {"run.completed", "run.failed"}
    ] == [flow[-1]["type"]]
    assert flow[-1]["type"] in {"run.completed", "run.failed"}
    assert all("answer" not in e["data"] for e in flow[:-1])


def normalize(value):
    """Normalize only run identity and timing; preserve all protocol results."""
    if isinstance(value, dict):
        return {
            key: EXAMPLE_ID
            if key == "request_id"
            else "2026-11-09T00:00:00+00:00"
            if key == "timestamp_utc"
            else 0.0
            if key in {"elapsed_ms", "duration_ms"}
            else normalize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def check_fixture(name, body, pytestconfig):
    path = FIXTURES / name
    if pytestconfig.getoption("--update-stream-fixtures"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == body


def check_stream_fixture(name, frames, request_id, pytestconfig):
    flow = [decode_frame(frame) for frame in frames if not frame.startswith(":")]
    assert_envelopes(flow, request_id)
    # Preserve server framing, key order, Unicode and number serialization.
    body = "".join(
        f"event: {event['type']}\nid: {event['sequence']}\n"
        f"data: {json.dumps(normalize(event), ensure_ascii=False, allow_nan=False)}\n\n"
        for event in flow
    )
    check_fixture(name + ".sse", body, pytestconfig)
    return flow


def test_complete_contract_arrives_live_over_loopback(
    metered_provider, small_corpus, pytestconfig
):
    entered, release = Event(), Event()

    def block():
        entered.set()
        assert release.wait(10), "Test did not release generation"

    metered_provider.hooks["answer"] = block
    metered_provider.outputs["answer"] = VALID_ANSWER
    scores = iter([0.2, 0.9, 0.9, 0.1])
    metered_provider.outputs["rerank_result"] = lambda _: json.dumps(
        {"score": next(scores), "reason": "Synthetic evidence Ω"}
    )
    with (
        loopback(web.create_app()) as url,
        httpx.Client(base_url=url, timeout=5) as client,
    ):
        try:
            with client.stream(
                "POST", "/ask/stream", json={"question": "Synthetic Hubble?"}
            ) as response:
                assert response.status_code == 200
                assert (
                    response.headers["content-type"]
                    == "text/event-stream; charset=utf-8"
                )
                assert response.headers["cache-control"] == "no-cache, no-transform"
                assert "content-length" not in response.headers
                frames, lines = [], []
                for line in response.iter_lines():
                    if line:
                        lines.append(line)
                        continue
                    frame = "\n".join(lines)
                    lines = []
                    if not frame or frame.startswith(":"):
                        continue
                    frames.append(frame)
                    event = decode_frame(frame)
                    if (
                        event["type"] == "stage.started"
                        and event["stage_id"] == "generate_answer"
                    ):
                        assert entered.wait(2)
                        assert not release.is_set()
                        assert len(frames) == 18
                        assert client.get("/health").json() == {"status": "ok"}
                        for route in ("/ask", "/ask/stream"):
                            busy = client.post(
                                route, json={"question": "Synthetic concurrent?"}
                            )
                            assert busy.status_code == 503
                            assert busy.json()["error"]["code"] == "busy"
                        release.set()
                assert not lines, "EOF within an SSE frame"
        finally:
            release.set()
    flow = check_stream_fixture(
        "success", frames, response.headers["x-request-id"], pytestconfig
    )
    assert [
        (e["type"], e["stage_id"]) for e in flow[1:-1] if e["type"] != "stage.progress"
    ] == [
        (kind, stage)
        for stage in STAGES
        for kind in ("stage.started", "stage.completed")
    ]
    completed = {
        e["stage_id"]: e["data"] for e in flow if e["type"] == "stage.completed"
    }
    assert completed["plan_query"]["details"] == {
        "search_query": "planned Hubble",
        "source_file_filter": "hubble.txt",
    }
    assert completed["embed_query"]["details"] == {
        "model": "text-embedding-3-small",
        "dimensions": 2,
    }
    for stage, score in (
        ("semantic_search", "similarity"),
        ("keyword_search", "bm25_score"),
        ("combine_rankings", "rrf_score"),
        ("rerank_evidence", "rerank_score"),
    ):
        passages = completed[stage]["details"]["results"]
        assert len(passages) == 4
        assert [p["rank"] for p in passages] == [1, 2, 3, 4]
        assert all(
            p["text"].startswith("Hubble evidence") and score in p for p in passages
        )
    assert completed["combine_rankings"]["details"]["rrf_k"] == 60
    progress = [e["data"] for e in flow if e["type"] == "stage.progress"]
    assert [p["completed"] for p in progress] == [1, 2, 3, 4]
    assert all(p["total"] == 4 and "rank" not in p["result"] for p in progress)
    reranked = completed["rerank_evidence"]["details"]["results"]
    assert [p["rerank_score"] for p in reranked] == [0.9, 0.9, 0.2, 0.1]
    assert completed["generate_answer"]["details"]["context_references"] == [
        p["reference"] for p in reranked
    ]
    assert completed["check_citations"]["details"] == {
        "outcome": "valid",
        "checked_references": ["[hubble.txt, chunk 0]"],
        "invalid_references": [],
    }
    terminal = flow[-1]["data"]
    assert terminal["answer"] == VALID_ANSWER
    assert terminal["metrics"]["model_calls"] == 7
    assert terminal["metrics"]["tokens"]["input_tokens"] == 8200
    assert Decimal(terminal["metrics"]["known_cost_usd"]) == Decimal("0.00170")
    assert terminal["metrics"]["cost_complete"] is True
    for stage in terminal["stages"]:
        assert stage["status"] == "completed"
        assert stage["details"] == completed[stage["stage_id"]]["details"]
        assert stage["metrics"] == completed[stage["stage_id"]]["metrics"]


@pytest.mark.parametrize(
    "scenario", ["citation-warning", "no-citations", "unknown-usage", "stage-failure"]
)
def test_public_outcome_fixtures_match_server(
    metered_provider, small_corpus, scenario, pytestconfig
):
    metered_provider.outputs["answer"] = VALID_ANSWER
    if scenario == "citation-warning":
        metered_provider.outputs["answer"] = "Synthetic claim. [unknown.txt, chunk 999]"
    elif scenario == "no-citations":
        metered_provider.outputs["answer"] = "Synthetic answer without references."
    elif scenario == "unknown-usage":
        metered_provider.usage.clear()
    else:
        outputs = iter(
            [
                '{"score":0.8,"reason":"Synthetic evidence"}',
                '{"score":2,"reason":"invalid"}',
            ]
        )
        metered_provider.outputs["rerank_result"] = lambda _: next(outputs)
    with TestClient(web.create_app()) as client:
        response = client.post("/ask/stream", json={"question": "Synthetic Hubble?"})
    assert response.status_code == 200
    flow = check_stream_fixture(
        scenario,
        response.text.strip().split("\n\n"),
        response.headers["x-request-id"],
        pytestconfig,
    )
    terminal = flow[-1]["data"]
    if scenario == "stage-failure":
        assert [e["type"] for e in flow[-2:]] == ["stage.failed", "run.failed"]
        assert terminal["error"] == {
            "code": "upstream_error",
            "message": "The model provider could not answer.",
        }
        assert terminal["http_equivalent_status"] == 502
        assert terminal["processing_may_continue"] is False
        assert [s["status"] for s in terminal["stages"]] == ["completed"] * 5 + [
            "failed",
            "skipped",
            "skipped",
        ]
        progress = [e["data"] for e in flow if e["type"] == "stage.progress"]
        assert len(progress) == 1
        assert terminal["stages"][5]["details"] == {
            "evaluated_results": [progress[0]["result"]]
        }
        assert terminal["metrics"]["model_calls"] == 4
        assert terminal["metrics"]["cost_complete"] is True
    else:
        assert flow[-1]["type"] == "run.completed"
        assert (
            terminal["stages"][7]["details"]["outcome"]
            == {
                "citation-warning": "warning",
                "no-citations": "no_citations",
                "unknown-usage": "valid",
            }[scenario]
        )
        if scenario == "unknown-usage":
            assert terminal["metrics"]["unknown_cost_calls"] == 7
            assert terminal["metrics"]["cost_complete"] is False
            assert set(terminal["metrics"]["tokens"].values()) == {None}
            assert Decimal(terminal["metrics"]["known_cost_usd"]) == 0


@pytest.mark.parametrize("route", ["/ask", "/ask/stream"])
def test_pre_stream_json_rejection_fixture(provider, route, pytestconfig):
    with TestClient(web.create_app()) as client:
        response = client.post(route, json={"question": " ", "extra": True})
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert provider.operations == []
    captured = {
        "status": response.status_code,
        "headers": {
            "content-type": response.headers["content-type"],
            "x-request-id": EXAMPLE_ID,
        },
        "body": normalize(response.json()),
    }
    check_fixture(
        "pre-stream-rejection.http.json",
        json.dumps(captured, indent=2) + "\n",
        pytestconfig,
    )


def test_timeout_fixture_freezes_partial_work_while_late_usage_and_slots_recover(
    metered_provider, small_corpus, monkeypatch, tmp_path, pytestconfig
):
    monkeypatch.setenv("NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "0.5")
    entered, release = Event(), Event()

    def block_second_candidate():
        if sum(kind == "rerank_result" for kind, _ in metered_provider.operations) == 2:
            entered.set()
            assert release.wait(10), "Test did not release reranking"

    metered_provider.hooks["rerank_result"] = block_second_candidate
    metered_provider.outputs["answer"] = VALID_ANSWER
    with (
        loopback(web.create_app()) as url,
        httpx.Client(base_url=url, timeout=5) as client,
    ):
        try:
            response = client.post(
                "/ask/stream", json={"question": "Synthetic Hubble?"}
            )
            assert entered.is_set() and not release.is_set()
            assert response.status_code == 200
            request_id = response.headers["x-request-id"]
            frames = response.text.strip().split("\n\n")
            flow = check_stream_fixture(
                "timeout-unfinished", frames, request_id, pytestconfig
            )
            terminal = flow[-1]["data"]
            assert terminal["error"]["code"] == "response_timeout"
            assert terminal["http_equivalent_status"] == 504
            assert terminal["processing_may_continue"] is True
            assert not any(e["type"] == "stage.failed" for e in flow)
            assert [s["status"] for s in terminal["stages"]] == ["completed"] * 5 + [
                "unknown"
            ] * 3
            progress = [e["data"] for e in flow if e["type"] == "stage.progress"]
            assert len(progress) == 1
            assert terminal["stages"][5]["details"] == {
                "evaluated_results": [progress[0]["result"]]
            }
            assert terminal["metrics"]["model_calls"] == 3
            assert terminal["metrics"]["cost_complete"] is True
            frozen = json.dumps(terminal)
            for route in ("/ask", "/ask/stream"):
                busy = client.post(route, json={"question": "Synthetic concurrent?"})
                assert busy.status_code == 503
                assert busy.json()["error"]["code"] == "busy"
        finally:
            release.set()
        # Real provider work completes before admission can recover. Check through
        # HTTP with a bounded backoff; do not assume one event-loop turn suffices.
        for attempt in range(5):
            recovered = client.post("/ask", json={"question": "Synthetic recovered?"})
            if recovered.status_code != 503:
                break
            assert recovered.json()["error"]["code"] == "busy"
            time.sleep(0.05 * 2**attempt)
        assert recovered.status_code == 200
        assert recovered.json()["answer"] == VALID_ANSWER
        recovered_stream = client.post(
            "/ask/stream", json={"question": "Synthetic recovered?"}
        )
        assert recovered_stream.status_code == 200
        assert (
            decode_frame(recovered_stream.text.strip().split("\n\n")[-1])["type"]
            == "run.completed"
        )
        assert json.dumps(terminal) == frozen
    records = [
        json.loads(line)
        for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
    ]
    late_run = [record for record in records if record["request_id"] == request_id]
    assert len(late_run) == 7
    assert all(r["run_id"] == request_id for r in late_run)
    assert late_run[-1]["operation"] == "answer_generation"
    assert Decimal(late_run[-1]["estimated_cost_usd"]) == Decimal("0.00028")
