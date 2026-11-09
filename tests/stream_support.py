"""Shared provider and loopback boundaries for offline stream verification."""

import socket
from contextlib import contextmanager
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

import pytest

GENERATED = "A claim. [unknown.txt, chunk 999]"


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
    hooks: dict[str, Any] = {}
    outputs: dict[str, Any] = {}
    usage: dict[str, Any] = {}
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
            usage=usage.get("query_embedding"),
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
        output = outputs.get(kind, output)
        if callable(output):
            output = output(arguments)
        return SimpleNamespace(
            output_text=output,
            usage=usage.get(kind),
            private="provider-only-secret",
        )

    client = SimpleNamespace(
        embeddings=SimpleNamespace(create=embeddings_create),
        responses=SimpleNamespace(create=responses_create),
    )
    monkeypatch.setattr(openai, "OpenAI", lambda: client)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    monkeypatch.setenv("NASA_RAG_CACHE_DIR", str(cache))
    return SimpleNamespace(
        operations=operations,
        hooks=hooks,
        outputs=outputs,
        vector=vector,
        cache=cache,
        usage=usage,
    )


@pytest.fixture
def metered_provider(provider):
    provider.usage["query_embedding"] = SimpleNamespace(prompt_tokens=1000)
    for kind in ("retrieval_plan", "rerank_result", "answer"):
        provider.usage[kind] = SimpleNamespace(
            input_tokens=1200,
            output_tokens=100,
            input_tokens_details=SimpleNamespace(
                cached_tokens=500, cache_write_tokens=200
            ),
            output_tokens_details=SimpleNamespace(reasoning_tokens=25),
        )
    return provider


@pytest.fixture
def small_corpus(provider):
    from nasa_rag.ingestion.file_loader import save_document_cache
    from nasa_rag.models import DocumentChunk

    save_document_cache(
        provider.cache / "embeds/document_cache_100_20.json",
        {
            "hubble.txt": [
                DocumentChunk("hubble.txt", i, f"Hubble evidence {i}", [1.0, 0.5])
                for i in range(4)
            ],
            "iss.txt": [
                DocumentChunk("iss.txt", i, "Other station", [0.0, 1.0])
                for i in range(30)
            ],
            "nasa_overview.txt": [],
            "space_shuttle.txt": [],
        },
    )


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
