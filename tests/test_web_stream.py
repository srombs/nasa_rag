"""Live search flow through HTTP, with providers replaced and no paid calls."""

import json
import socket
from contextlib import contextmanager
from datetime import datetime
from threading import Event, Thread
from types import SimpleNamespace
from uuid import UUID

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

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


@pytest.fixture
def provider(monkeypatch, tmp_path):
    import openai

    from nasa_rag.ingestion.chunkers import chunk_text
    from nasa_rag.ingestion.file_loader import save_document_cache
    from nasa_rag.models import DocumentChunk
    from nasa_rag.paths import data_directory

    cache = tmp_path / "cache"
    save_document_cache(
        cache / "embeds/document_cache_100_20.json",
        {
            source.name: [
                DocumentChunk(source.name, i, text, [1.0, 0.5])
                for i, text in enumerate(chunk_text(source.read_text(), 100, 20))
            ]
            for source in sorted(data_directory().glob("*.txt"))
        },
    )
    operations = []
    hooks = {}
    outputs = {}

    def record(kind, arguments):
        operations.append((kind, arguments))
        if kind in hooks:
            hooks[kind]()

    def embeddings_create(**arguments):
        assert isinstance(arguments["input"], str), "Startup must use cached vectors"
        record("query_embedding", arguments)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 0.5])])

    def responses_create(**arguments):
        kind = arguments.get("text", {}).get("format", {}).get("name", "answer")
        record(kind, arguments)
        if kind == "retrieval_plan":
            output = (
                '{"search_query":"planned Hubble", "source_file_filter":"hubble.txt"}'
            )
        elif kind == "rerank_result":
            output = '{"score":0.8,"reason":"Evidence"}'
        elif kind == "answer":
            output = GENERATED
        else:
            pytest.fail("Unexpected extra rewrite/model call")
        return SimpleNamespace(output_text=outputs.get(kind, output))

    client = SimpleNamespace(
        embeddings=SimpleNamespace(create=embeddings_create),
        responses=SimpleNamespace(create=responses_create),
    )
    monkeypatch.setattr(openai, "OpenAI", lambda: client)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("NASA_RAG_CACHE_DIR", str(cache))
    return SimpleNamespace(operations=operations, hooks=hooks, outputs=outputs)


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
        assert [(e["type"], e["stage_id"]) for e in flow[1:-1]] == [
            (kind, stage)
            for stage in STAGES
            for kind in ("stage.started", "stage.completed")
        ]
        assert flow[-1]["type"] == "run.completed"
        assert flow[-1]["data"]["answer"] == ANSWER
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
                assert len(received) == 18
        finally:
            release.set()


@contextmanager
def loopback(app):
    """Use an actual TCP socket; startup is synchronized rather than sleep-polled."""
    import uvicorn

    ready = Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = Server(
            uvicorn.Config(
                app,
                proxy_headers=False,
                access_log=False,
                log_level="warning",
                ws="none",
            )
        )
        thread = Thread(target=server.run, kwargs={"sockets": [listener]})
        thread.start()
        try:
            assert ready.wait(10), "Loopback server failed to start"
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive(), "Loopback server failed to stop"


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
    assert "private" not in response.text + caplog.text
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
