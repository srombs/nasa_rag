"""HTTP contract tests with a local pipeline substitute and no paid requests."""

import asyncio
import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import UUID

import pytest

pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from nasa_rag import web  # noqa: E402


def test_health_and_questions_reuse_startup_pipeline_and_preserve_answers():
    starts = []
    questions = []
    answer = (
        "Hubble launched on STS-31. [hubble.txt, chunk 999]\n\n"
        "[Validation warning: citations not in retrieved chunks: "
        "[hubble.txt, chunk 999]]"
    )

    def initialize():
        starts.append(True)

        def ask(question):
            questions.append(question)
            return answer

        return ask

    app = web.create_app(pipeline_factory=initialize)
    assert starts == []
    with TestClient(app) as client:
        assert starts == [True]
        assert client.get("/health").json() == {"status": "ok"}
        assert questions == []
        first = client.post("/ask", json={"question": "What launched Hubble?"})
        second = client.post("/ask", json={"question": "  And when?  "})
        assert first.status_code == second.status_code == 200
        for response in (first, second):
            assert set(response.json()) == {"request_id", "answer"}
            UUID(response.json()["request_id"])
            assert response.json()["answer"] == answer
        assert first.json()["request_id"] != second.json()["request_id"]
        assert client.get("/health").status_code == 200
        assert starts == [True]
        assert questions == ["What launched Hubble?", "  And when?  "]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": ""},
        {"question": " \n\t"},
        {"question": "x" * 1001},
        {"question": 5},
        {"question": True},
        {"question": None},
        {"question": []},
        {"question": {}},
        {"question": "Hello", "top_k": 2},
        ["Hello"],
        "Hello",
        None,
    ],
)
def test_invalid_requests_have_public_error_and_never_run_pipeline(payload):
    def unexpected(question):
        pytest.fail("Invalid input reached the pipeline")

    with TestClient(web.create_app(lambda: unexpected)) as client:
        response = client.post("/ask", json=payload)
        assert response.status_code == 422
        body = response.json()
        assert set(body) == {"request_id", "error"}
        UUID(body["request_id"])
        assert body["error"] == {
            "code": "invalid_request",
            "message": "Provide only a nonblank question of at most 1,000 characters.",
        }


def test_question_length_boundary_and_malformed_json():
    with TestClient(web.create_app(lambda: lambda question: question)) as client:
        question = "x" * 1000
        assert (
            client.post("/ask", json={"question": question}).json()["answer"]
            == question
        )
        response = client.post(
            "/ask", content="{", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("fail", [False, True])
def test_busy_requests_fail_fast_health_stays_responsive_and_slot_recovers(fail):
    started = Event()
    finish = Event()

    def ask(question):
        if question == "First":
            started.set()
            assert finish.wait(5), "Test did not release pipeline"
            if fail:
                raise RuntimeError("Private provider details")
        return "Unchanged answer"

    with (
        TestClient(web.create_app(lambda: ask)) as client,
        ThreadPoolExecutor(3) as pool,
    ):
        first = pool.submit(client.post, "/ask", json={"question": "First"})
        try:
            assert started.wait(2)
            health = pool.submit(client.get, "/health").result(timeout=2)
            busy = pool.submit(client.post, "/ask", json={"question": "Second"}).result(
                timeout=2
            )
            assert health.status_code == 200
            assert busy.status_code == 503
            assert busy.json()["error"]["code"] == "busy"
            UUID(busy.json()["request_id"])
        finally:
            finish.set()
        response = first.result(timeout=2)
        assert response.status_code == (500 if fail else 200)
        if fail:
            assert "Private provider details" not in response.text
        recovered = client.post("/ask", json={"question": "Next"})
        assert recovered.status_code == 200
        assert recovered.json()["answer"] == "Unchanged answer"


@pytest.mark.parametrize(
    "generated",
    [
        "A claim. [unknown.txt, chunk 999]",
        "The provided documents do not contain enough information.",
        "invalid_source_plan",
    ],
)
def test_default_api_runs_existing_full_pipeline_with_mocked_model_provider(
    monkeypatch, tmp_path, generated, caplog
):
    import openai

    operations = []
    caplog.set_level(logging.INFO)

    def embeddings_create(**arguments):
        inputs = arguments["input"]
        if isinstance(inputs, str):
            operations.append(("query_embedding", inputs))
            inputs = [inputs]
        else:
            operations.append(("document_embedding", len(inputs)))
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=i, embedding=[1.0, 0.5])
                for i, text in enumerate(inputs)
            ]
        )

    def responses_create(**arguments):
        kind = arguments.get("text", {}).get("format", {}).get("name")
        operations.append((kind or "answer_generation", arguments["input"]))
        if kind == "retrieval_plan":
            output = json.dumps(
                {
                    "search_query": "hubble planned search",
                    "source_file_filter": (
                        "unavailable.txt"
                        if generated == "invalid_source_plan"
                        else "hubble.txt"
                    ),
                }
            )
        elif kind == "rerank_result":
            output = '{"score": 0.8, "reason": "Contains evidence"}'
        elif kind is None:
            output = generated
        else:
            pytest.fail("Unexpected second query rewrite")
        return SimpleNamespace(output_text=output)

    client = SimpleNamespace(
        embeddings=SimpleNamespace(create=embeddings_create),
        responses=SimpleNamespace(create=responses_create),
    )
    monkeypatch.setattr(openai, "OpenAI", lambda: client)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("NASA_RAG_CACHE_DIR", str(tmp_path / "cache"))

    with TestClient(web.create_app()) as http:
        assert {kind for kind, value in operations} == {"document_embedding"}
        operations.clear()
        assert http.get("/health").status_code == 200
        assert operations == []
        question = "What does the Hubble source say?"
        response = http.post("/ask", json={"question": question})
        if generated == "invalid_source_plan":
            assert response.status_code == 502
            assert response.json()["error"]["code"] == "upstream_error"
            assert "unavailable.txt" not in response.text
            assert [kind for kind, value in operations] == ["retrieval_plan"]
            return
        assert response.status_code == 200
        expected = generated
        if "unknown.txt" in generated:
            expected += (
                "\n\n[Validation warning: citations not in retrieved chunks: "
                "[unknown.txt, chunk 999]]"
            )
        assert response.json()["answer"] == expected
        assert [kind for kind, value in operations] == [
            "retrieval_plan",
            "query_embedding",
            *(["rerank_result"] * 10),
            "answer_generation",
        ]
        assert operations[0][1] == question
        assert operations[1][1] == "hubble planned search"
        assert "[hubble.txt, chunk " in operations[-1][1]
        assert "[iss.txt, chunk " not in operations[-1][1]
        assert (tmp_path / "cache" / "embeds" / "document_cache_100_20.json").is_file()
        assert (tmp_path / "cache" / "faiss" / "document_100_20.index").is_file()
        assert question not in caplog.text
        assert operations[-1][1] not in caplog.text


def test_import_does_not_initialize_retriever_or_models(tmp_path):
    script = """
import openai
from nasa_rag.retrieval.retriever import Retriever
def forbidden(*args, **kwargs):
    raise AssertionError("Import initialized the pipeline")
openai.OpenAI = forbidden
Retriever.load = forbidden
import nasa_rag.web
"""
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    environment["NASA_RAG_CACHE_DIR"] = str(tmp_path / "unused-cache")
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "unused-cache").exists()


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "NASA_RAG_CACHE_DIR"])
def test_default_startup_requires_configuration(monkeypatch, tmp_path, missing):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("NASA_RAG_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv(missing, "  ")
    with pytest.raises(RuntimeError, match=missing), TestClient(web.create_app()):
        pytest.fail("Server accepted requests without required configuration")


@pytest.mark.parametrize("failure", ["cache_path_is_file", "corrupt_document_cache"])
def test_default_startup_aborts_on_cache_or_retriever_failure(
    monkeypatch, tmp_path, failure
):
    import openai

    def forbidden():
        pytest.fail("Invalid cache initialization called a model")

    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    cache = tmp_path / "cache"
    monkeypatch.setenv("NASA_RAG_CACHE_DIR", str(cache))
    if failure == "cache_path_is_file":
        cache.write_text("not a directory")
    else:
        (cache / "embeds").mkdir(parents=True)
        (cache / "embeds" / "document_cache_100_20.json").write_text("broken JSON")
    with (
        pytest.raises(RuntimeError, match="initialize the API retriever"),
        TestClient(web.create_app()),
    ):
        pytest.fail("Server accepted requests after initialization failure")


def test_uninitialized_app_does_not_report_health_or_accept_questions():
    client = TestClient(web.create_app(lambda: lambda question: question))
    assert client.get("/health").status_code == 503
    assert client.post("/ask", json={"question": "Hello"}).status_code == 503


def test_rate_limit_has_a_sliding_boundary_separate_ips_and_resets_on_restart(caplog):
    caplog.set_level(logging.INFO)
    now = [0.0]
    app = web.create_app(lambda: lambda question: question, clock=lambda: now[0])
    with TestClient(app, client=("192.0.2.1", 1000)) as client:
        for _ in range(9):
            assert client.post("/ask", json={"question": "Hello"}).status_code == 200
        now[0] = 300.0
        assert client.post("/ask", json={"question": "Hello"}).status_code == 200
        limited = client.post("/ask", json={"question": "Hello"})
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "rate_limited"
        UUID(limited.json()["request_id"])
        assert any(
            record.request_id == limited.json()["request_id"]
            and record.http_status == 429
            for record in caplog.records
            if record.name == "nasa_rag.web"
        )
        other = TestClient(app, client=("192.0.2.2", 1000))
        assert other.post("/ask", json={"question": "Hello"}).status_code == 200
        other.close()
        now[0] = 599.999
        assert client.post("/ask", json={"question": "Hello"}).status_code == 429
        now[0] = 600.0
        for _ in range(9):
            assert client.post("/ask", json={"question": "Hello"}).status_code == 200
        assert client.post("/ask", json={"question": "Hello"}).status_code == 429
        now[0] = 1200.0
        for _ in range(10):
            assert client.post("/ask", json={"question": "Hello"}).status_code == 200
    with TestClient(app, client=("192.0.2.1", 1000)) as client:
        assert client.post("/ask", json={"question": "Hello"}).status_code == 200


@pytest.mark.parametrize("trusted", [False, True])
def test_only_configured_proxy_connections_can_change_rate_identity(
    monkeypatch, trusted
):
    monkeypatch.setenv("NASA_RAG_TRUSTED_PROXIES", "10.0.0.0/24" if trusted else "")
    with TestClient(
        web.create_app(lambda: lambda question: question), client=("10.0.0.5", 1000)
    ) as client:
        for _ in range(10):
            # The proxy appends the real visitor after any visitor-supplied value.
            response = client.post(
                "/ask",
                json={},
                headers={"X-Forwarded-For": "198.51.100.99, 192.0.2.1"},
            )
            assert response.status_code == 422
        response = client.post(
            "/ask",
            json={"question": "Hello"},
            headers={"X-Forwarded-For": "198.51.100.100, 192.0.2.1"},
        )
        assert response.status_code == 429
        other_visitor = client.post(
            "/ask",
            json={"question": "Hello"},
            headers={"X-Forwarded-For": "192.0.2.2"},
        )
        assert other_visitor.status_code == (200 if trusted else 429)
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize("fail_after_timeout", [False, True])
def test_deadline_keeps_pipeline_busy_until_work_finishes(
    monkeypatch, fail_after_timeout, caplog
):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "0.02")
    started = Event()
    finish = Event()
    finished = Event()
    calls = []

    def ask(question):
        calls.append(question)
        if question == "First":
            started.set()
            assert finish.wait(5), "Test did not release pipeline"
            finished.set()
            if fail_after_timeout:
                raise RuntimeError("Private provider details")
        return "Unchanged answer"

    with TestClient(web.create_app(lambda: ask)) as client:
        try:
            response = client.post("/ask", json={"question": "First"})
            assert started.is_set()
            assert response.status_code == 504
            UUID(response.json()["request_id"])
            assert response.json()["error"]["code"] == "response_timeout"
            assert any(
                record.request_id == response.json()["request_id"]
                and record.http_status == 504
                for record in caplog.records
                if record.name == "nasa_rag.web"
            )
            assert client.get("/health").status_code == 200
            busy = client.post("/ask", json={"question": "Second"})
            assert busy.status_code == 503
            assert busy.json()["error"]["code"] == "busy"
            assert calls == ["First"]
        finally:
            finish.set()
        assert finished.wait(2)
        # Allow the thread completion to be delivered back to the event loop.
        client.portal.call(asyncio.sleep, 0.01)
        assert client.post("/ask", json={"question": "Next"}).status_code == 200
        assert calls == ["First", "Next"]


@pytest.mark.parametrize("abort", ["disconnect", "cancel"])
def test_disconnected_request_keeps_slot_until_pipeline_finishes(abort):
    started = Event()
    finish = Event()
    finished = Event()

    def ask(question):
        if question == "First":
            started.set()
            assert finish.wait(5), "Test did not release pipeline"
            finished.set()
        return "Answer"

    app = web.create_app(lambda: ask)

    async def abandon_request():
        incoming = asyncio.Queue()
        incoming.put_nowait(
            {
                "type": "http.request",
                "body": b'{"question":"First"}',
                "more_body": False,
            }
        )
        messages = []

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/ask",
            "raw_path": b"/ask",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("192.0.2.1", 1000),
            "server": ("testserver", 80),
        }
        request = asyncio.create_task(app(scope, incoming.get, send))
        assert await asyncio.to_thread(started.wait, 2)
        if abort == "cancel":
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
        else:
            incoming.put_nowait({"type": "http.disconnect"})
            await asyncio.wait_for(request, timeout=1)
            assert messages[0]["status"] == 499

    with TestClient(app) as client:
        try:
            client.portal.call(abandon_request)
            busy = client.post("/ask", json={"question": "Second"})
            assert busy.status_code == 503
            assert busy.json()["error"]["code"] == "busy"
            assert client.get("/health").status_code == 200
        finally:
            finish.set()
        assert finished.wait(2)
        client.portal.call(asyncio.sleep, 0.01)
        assert client.post("/ask", json={"question": "Next"}).status_code == 200


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        ("connection", 502),
        ("provider_status", 502),
        ("wrapped_provider", 502),
        ("planning", 502),
        ("reranking", 502),
        ("generation", 502),
        ("embedding", 502),
        ("local_retrieval", 500),
        ("unexpected", 500),
        ("pipeline_timeout", 500),
        ("wrapped_local_fault", 500),
        ("invalid_provider_json", 502),
    ],
)
def test_failures_are_mapped_without_exposing_provider_details(failure, status):
    import httpx
    import openai

    from nasa_rag.embedder import EmbeddingError
    from nasa_rag.generation.generator import GenerationError
    from nasa_rag.retrieval.reranker import RerankingError
    from nasa_rag.retrieval.retrieval_planner import RetrievalPlanningError
    from nasa_rag.retrieval.retriever import RetrievalError

    secret = "secret-provider-credential-and-context"
    request = httpx.Request("POST", "https://provider.invalid", headers={"key": secret})
    error = {
        "connection": openai.APIConnectionError(message=secret, request=request),
        "provider_status": openai.APIStatusError(
            secret, response=httpx.Response(429, request=request), body={"key": secret}
        ),
        "planning": RetrievalPlanningError(secret),
        "reranking": RerankingError(secret),
        "generation": GenerationError(secret),
        "embedding": EmbeddingError(secret),
        "local_retrieval": RetrievalError(secret),
        "unexpected": RuntimeError(secret),
        "pipeline_timeout": TimeoutError(secret),
        "wrapped_provider": RetrievalError(secret),
        "wrapped_local_fault": GenerationError(secret),
        "invalid_provider_json": RetrievalPlanningError(secret),
    }[failure]
    if failure == "wrapped_provider":
        error.__cause__ = openai.APIConnectionError(message=secret, request=request)
    elif failure == "wrapped_local_fault":
        error.__cause__ = RuntimeError(secret)
    elif failure == "invalid_provider_json":
        error.__cause__ = json.JSONDecodeError("Invalid JSON", secret, 0)

    def ask(question):
        raise error

    with TestClient(web.create_app(lambda: ask)) as client:
        response = client.post("/ask", json={"question": "Hello"})
        assert response.status_code == status
        body = response.json()
        assert set(body) == {"request_id", "error"}
        UUID(body["request_id"])
        assert body["error"]["code"] == (
            "upstream_error" if status == 502 else "internal_error"
        )
        assert secret not in response.text


def test_response_ids_match_safe_request_logs_and_rag_logs_are_suppressed(caplog):
    secret = "private-question-context-and-credential"
    rag_logger = logging.getLogger("nasa_rag.generation.generator")
    original_level = rag_logger.level

    def ask(question):
        rag_logger.info("Question and context: %s", secret)
        logging.getLogger("openai").debug("Provider credential: %s", secret)
        try:
            raise RuntimeError(secret)
        except RuntimeError:
            rag_logger.exception("Provider traceback")
            raise

    caplog.set_level(logging.DEBUG)
    with TestClient(web.create_app(lambda: ask)) as client:
        responses = [
            client.post(
                "/ask?credential=" + secret,
                json={"question": secret},
                headers={"Authorization": secret, "X-Request-ID": secret},
            ),
            client.post("/ask", json={"question": secret, "extra": secret}),
            client.get("/missing"),
            client.get("/ask"),
            client.get("/health"),
        ]
        assert [response.status_code for response in responses] == [
            500,
            422,
            404,
            405,
            200,
        ]
        logs = [record for record in caplog.records if record.name == "nasa_rag.web"]
        assert len(logs) == len(responses)
        for response, record in zip(responses, logs, strict=True):
            request_id = response.headers["X-Request-ID"]
            UUID(request_id)
            assert record.request_id == request_id
            assert record.http_status == response.status_code
            assert record.elapsed_ms >= 0
            assert request_id in record.getMessage()
            assert str(response.status_code) in record.getMessage()
            if response.status_code != 200:
                assert response.json()["request_id"] == request_id
                assert set(response.json()["error"]) == {"code", "message"}
                assert secret not in response.text
        assert secret not in caplog.text
        assert "Traceback" not in caplog.text
    assert rag_logger.level == original_level


def test_concurrent_requests_preserve_answers_as_processing_slot_turns_over():
    import httpx

    app = web.create_app(lambda: lambda question: question)

    async def submit_concurrently():
        for round_number in range(50):
            transport = httpx.ASGITransport(
                app, client=(f"192.0.2.{round_number + 1}", 1000)
            )
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                tasks = []
                questions = [f"Question {round_number}/{i}" for i in range(10)]
                for question in questions:
                    tasks.append(
                        asyncio.create_task(
                            client.post("/ask", json={"question": question})
                        )
                    )
                    await asyncio.sleep(0)
                responses = await asyncio.gather(*tasks)
                assert any(response.status_code == 200 for response in responses)
                for response, question in zip(responses, questions, strict=True):
                    assert response.status_code in {200, 503}
                    if response.status_code == 200:
                        assert response.json()["answer"] == question

    with TestClient(app) as client:
        client.portal.call(submit_concurrently)
