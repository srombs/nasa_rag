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
    vector = [1.0, 0.5]

    def record(kind, arguments):
        operations.append((kind, arguments))
        if kind in hooks:
            hooks[kind]()

    def embeddings_create(**arguments):
        assert isinstance(arguments["input"], str), "Startup must use cached vectors"
        record("query_embedding", arguments)
        return SimpleNamespace(
            model="provider-alias",
            private="provider-only-secret",
            data=[
                SimpleNamespace(embedding=vector.copy(), private="provider-only-secret")
            ],
        )

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
        return SimpleNamespace(
            output_text=outputs.get(kind, output), private="provider-only-secret"
        )

    client = SimpleNamespace(
        embeddings=SimpleNamespace(create=embeddings_create),
        responses=SimpleNamespace(create=responses_create),
    )
    monkeypatch.setattr(openai, "OpenAI", lambda: client)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("NASA_RAG_CACHE_DIR", str(cache))
    return SimpleNamespace(
        operations=operations, hooks=hooks, outputs=outputs, vector=vector, cache=cache
    )


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
    assert "mutated-after-publication" not in response.text
    assert "mutated-source.txt" not in response.text
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
        assert [(e["type"], e["stage_id"]) for e in flow[1:-1]] == [
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
