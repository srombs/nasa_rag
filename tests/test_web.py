"""HTTP contract tests with a local pipeline substitute and no paid requests."""

import json
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
    ],
)
def test_default_api_runs_existing_full_pipeline_with_mocked_model_provider(
    monkeypatch, tmp_path, generated
):
    import openai

    operations = []

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
                    "source_file_filter": "hubble.txt",
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
