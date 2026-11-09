"""Search observation lifecycle through HTTP/ASGI, without paid model calls."""

import asyncio
import gc
import json
from threading import Event

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from nasa_rag import web  # noqa: E402
from nasa_rag.model_costs import call_model  # noqa: E402
from nasa_rag.models import DocumentChunk, RerankResult  # noqa: E402
from nasa_rag.search_flow import (  # noqa: E402
    report_rerank_progress,
    search_stage,
)


async def request(app, send, *, route="/ask/stream", spec_version="2.4"):
    """Drive the public ASGI transport with controllable delivery/backpressure."""
    incoming = asyncio.Queue()
    incoming.put_nowait(
        {"type": "http.request", "body": b'{"question":"private question"}'}
    )
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": spec_version},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": route,
            "raw_path": route.encode(),
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("192.0.2.1", 1000),
            "server": ("testserver", 80),
        },
        incoming.get,
        send,
    )


def application_events(messages):
    return [
        json.loads(line[6:])
        for message in messages
        for line in message.get("body", b"").decode().splitlines()
        if line.startswith("data: ")
    ]


def report_candidates(total):
    """Feed a synthetic pipeline's validated candidates through its public hook."""
    for i in range(total):
        chunk = DocumentChunk("example.txt", i, "private passage", [])
        chunk.rrf_score = 0.02
        report_rerank_progress(RerankResult(chunk, 0.8, "private reason"), i + 1, total)


@pytest.mark.parametrize("route", ["/ask", "/ask/stream"])
@pytest.mark.parametrize("failure", ["validation", "provider", "internal"])
def test_request_log_retains_known_public_failure_code(route, failure, caplog):
    from nasa_rag.generation.generator import GenerationError

    def pipeline(question):
        if failure == "provider":
            raise GenerationError("private provider details")
        raise RuntimeError("private server details")

    with TestClient(web.create_app(lambda: pipeline)) as client:
        response = client.post(
            route, json={} if failure == "validation" else {"question": "private"}
        )

    code = {
        "validation": "invalid_request",
        "provider": "upstream_error",
        "internal": "internal_error",
    }[failure]
    records = [r for r in caplog.records if r.name == "nasa_rag.web"]
    assert len(records) == 1
    record = records[0]
    assert record.failure_code == code
    assert record.http_status == response.status_code
    assert record.request_id == response.headers["x-request-id"]
    assert record.elapsed_ms >= 0
    assert "private" not in caplog.text
    assert record.exc_info is None


@pytest.mark.parametrize(
    "end", ["timeout", "send_failure", "cancel", "encoding_failure"]
)
def test_late_provider_exception_keeps_slot_accounting_and_shutdown_wait(
    end, monkeypatch, tmp_path, caplog
):
    from time import monotonic

    import httpx
    from starlette.requests import ClientDisconnect

    from nasa_rag import web_stream
    from nasa_rag.generation.generator import GenerationError
    from nasa_rag.models import RetrievalPlan
    from nasa_rag.search_details import StageDetails

    entered = Event()
    release = Event()
    offset = [0.0]
    monkeypatch.setattr(web_stream, "monotonic", lambda: monotonic() + offset[0])
    calls = []

    def provider(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5), "Test did not release the provider"
        raise GenerationError("private late provider error")

    def pipeline(question):
        with search_stage("plan_query") as stage:
            # A lone surrogate cannot be encoded as UTF-8. Observation must not
            # turn a serialization fault into a pipeline failure.
            query = "\ud800" if end == "encoding_failure" else "planned"
            stage.details = StageDetails.plan(RetrievalPlan(query, None))
        with search_stage("generate_answer"):
            return call_model(
                "answer_generation", "responses", "gpt-5.6-luna", provider
            )

    app = web.create_app(lambda: pipeline)

    async def exercise():
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        unhandled = []
        loop.set_exception_handler(lambda loop, context: unhandled.append(context))
        messages = []
        body_started = asyncio.Event()
        shutdown_finished = asyncio.Event()

        async def send(message):
            if message["type"] == "http.response.start":
                assert await asyncio.to_thread(entered.wait, 2)
                if end == "timeout":
                    offset[0] = 121.0
            elif message.get("body"):
                body_started.set()
                if end == "send_failure":
                    raise OSError("private transport error")
                if end == "cancel":
                    await asyncio.Event().wait()
            messages.append(message)

        try:
            async with app.router.lifespan_context(app):
                try:
                    task = asyncio.create_task(request(app, send))
                    if end == "cancel":
                        await asyncio.wait_for(body_started.wait(), 2)
                        task.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await task
                    elif end == "send_failure":
                        with pytest.raises(ClientDisconnect):
                            await task
                    else:
                        await asyncio.wait_for(task, 2)
                    frozen = json.dumps(application_events(messages), sort_keys=True)
                    if end == "encoding_failure":
                        assert application_events(messages) == []
                    if end == "timeout":
                        terminal = application_events(messages)[-1]["data"]
                        assert terminal["processing_may_continue"] is True
                        assert terminal["metrics"]["model_calls"] == 0
                        assert (
                            terminal["stages"][0]["details"]["search_query"]
                            == "planned"
                        )
                        assert terminal["stages"][6]["status"] == "unknown"
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app), base_url="http://testserver"
                    ) as client:
                        for route in ("/ask", "/ask/stream"):
                            busy = await client.post(route, json={"question": "Next"})
                            assert busy.status_code == 503
                            assert busy.json()["error"]["code"] == "busy"
                    assert not (tmp_path / "model_costs.jsonl").exists()
                finally:
                    # Shutdown starts while the real provider is still blocked.
                    # Release it on the next loop turn, after lifespan begins waiting.
                    async def release_during_shutdown():
                        await asyncio.sleep(0)
                        try:
                            assert not shutdown_finished.is_set()
                            assert not release.is_set()
                            assert len(calls) == 1
                        finally:
                            release.set()

                    release_task = asyncio.create_task(release_during_shutdown())
            shutdown_finished.set()
            await release_task
            assert json.dumps(application_events(messages), sort_keys=True) == frozen
            records = [
                json.loads(line)
                for line in (tmp_path / "model_costs.jsonl").read_text().splitlines()
            ]
            headers = dict(messages[0]["headers"])
            request_id = headers[b"x-request-id"].decode()
            assert len(records) == 1
            assert records[0]["request_id"] == records[0]["run_id"] == request_id
            assert records[0]["run_name"] == "ask"
            assert records[0]["status"] == "error"
            assert records[0]["estimated_cost_usd"] is None
            gc.collect()
            await asyncio.sleep(0)
            assert not unhandled
        finally:
            release.set()
            loop.set_exception_handler(previous_handler)

    asyncio.run(exercise())
    first = [r for r in caplog.records if r.name == "nasa_rag.web"][0]
    assert first.http_status == 200
    assert first.stream_outcome == ("timeout" if end == "timeout" else "disconnected")
    assert "private" not in caplog.text


@pytest.mark.parametrize("overflow", [False, True])
def test_interrupted_delivery_retains_a_known_run_failure_code(overflow, caplog):
    from starlette.requests import ClientDisconnect

    from nasa_rag.generation.generator import GenerationError

    failed = Event()

    def pipeline(question):
        try:
            with search_stage("rerank_evidence"):
                if overflow:
                    report_candidates(62)
                raise GenerationError("private provider details")
        finally:
            failed.set()

    app = web.create_app(lambda: pipeline)

    async def fail_terminal_delivery():
        messages = []

        async def send(message):
            if message["type"] == "http.response.start":
                assert await asyncio.to_thread(failed.wait, 5)
            if any(e["type"] == "run.failed" for e in application_events([message])):
                raise OSError("private connection details")
            messages.append(message)

        if overflow:
            await request(app, send)
        else:
            with pytest.raises(ClientDisconnect):
                await request(app, send)
        return messages

    with TestClient(app) as client:
        messages = client.portal.call(fail_terminal_delivery)
    assert messages[0]["status"] == 200
    if overflow:
        assert application_events(messages) == []
    else:
        assert application_events(messages)[-1]["type"] == "stage.failed"
    records = [r for r in caplog.records if r.name == "nasa_rag.web"]
    assert len(records) == 1
    assert records[0].stream_outcome == "disconnected"
    assert records[0].http_status == 200
    assert records[0].failure_code == "upstream_error"
    assert "private" not in caplog.text


def test_observed_stage_failure_wins_over_a_later_deadline(monkeypatch):
    from time import monotonic

    from nasa_rag import web_stream
    from nasa_rag.generation.generator import GenerationError

    cleanup = Event()
    release = Event()
    offset = [0.0]
    monkeypatch.setattr(web_stream, "monotonic", lambda: monotonic() + offset[0])

    def pipeline(question):
        try:
            with search_stage("plan_query"):
                raise GenerationError("private provider details")
        finally:
            cleanup.set()
            assert release.wait(5), "Test did not release failed worker cleanup"

    app = web.create_app(lambda: pipeline)

    async def collect():
        messages = []

        async def send(message):
            if message["type"] == "http.response.start":
                assert await asyncio.to_thread(cleanup.wait, 2)
                offset[0] = 121.0
            messages.append(message)

        await request(app, send)
        return application_events(messages)

    with TestClient(app) as client:
        try:
            flow = client.portal.call(collect)
            assert [e["type"] for e in flow] == [
                "run.started",
                "stage.started",
                "stage.failed",
                "run.failed",
            ]
            terminal = flow[-1]["data"]
            assert terminal["error"]["code"] == "upstream_error"
            assert terminal["processing_may_continue"] is False
            assert [s["status"] for s in terminal["stages"]] == [
                "failed",
                *["skipped"] * 7,
            ]
        finally:
            release.set()


def test_completed_run_stays_successful_when_terminal_delivery_crosses_deadline(
    monkeypatch, caplog
):
    from time import monotonic

    from nasa_rag import web_stream

    offset = [0.0]
    monkeypatch.setattr(web_stream, "monotonic", lambda: monotonic() + offset[0])
    app = web.create_app(lambda: lambda question: "Answer")

    async def collect():
        messages = []

        async def send(message):
            messages.append(message)
            if any(e["type"] == "run.completed" for e in application_events([message])):
                # The server has published success; transport resumes after expiry.
                offset[0] = 121.0

        await request(app, send)
        return application_events(messages)

    with TestClient(app) as client:
        flow = client.portal.call(collect)
    assert [e["type"] for e in flow] == ["run.started", "run.completed"]
    assert flow[-1]["data"]["answer"] == "Answer"
    assert flow[-1]["data"]["metrics"]["duration_ms"] < 120_000
    record = [r for r in caplog.records if r.name == "nasa_rag.web"][-1]
    assert record.stream_outcome == "completed"
    assert record.failure_code is None


@pytest.mark.parametrize(
    ("blocked_send", "progress_count", "overflow"),
    [
        ("headers", 62, False),
        ("headers", 63, True),
        ("body", 63, False),
        ("body", 64, True),
    ],
)
def test_slow_or_absent_consumer_detaches_only_after_exhausting_64_event_queue(
    blocked_send, progress_count, overflow, caplog
):
    """A synthetic pipeline stresses the bound without changing production limits."""
    queued = Event()
    produce = Event()
    release = Event()
    finished = Event()
    questions = []

    def pipeline(question):
        questions.append(question)
        if question != "private question":
            return "Recovered"
        try:
            assert produce.wait(5), "Test did not start synthetic event production"
            with search_stage("rerank_evidence"):
                report_candidates(progress_count)
                # Also count run.started when it has not left the queue yet.
                queued.set()
                assert release.wait(5), "Test did not release synthetic pipeline"
            if overflow:
                raise RuntimeError("private late worker exception")
            return "Completed"
        finally:
            finished.set()

    app = web.create_app(lambda: pipeline)

    async def collect():
        messages = []

        async def send(message):
            stalled = (
                message["type"] == "http.response.start"
                if blocked_send == "headers"
                else any(
                    e["type"] == "run.started" for e in application_events([message])
                )
            )
            if stalled:
                produce.set()
                assert await asyncio.to_thread(queued.wait, 2)
            messages.append(message)
            for event in application_events([message]):
                if (
                    event["type"] == "stage.progress"
                    and event["data"]["completed"] == progress_count
                ):
                    release.set()

        await asyncio.wait_for(request(app, send), 3)
        return messages

    with TestClient(app) as client:
        try:
            messages = client.portal.call(collect)
            flow = application_events(messages)
            assert messages[0]["status"] == 200
            first_record = [r for r in caplog.records if r.name == "nasa_rag.web"][-1]
            if not overflow:
                assert flow[-1]["type"] == "run.completed"
                assert (
                    len([e for e in flow if e["type"] == "stage.progress"])
                    == progress_count
                )
                assert first_record.stream_outcome == "completed"
            else:
                assert [e["type"] for e in flow] == (
                    [] if blocked_send == "headers" else ["run.started"]
                )
                assert first_record.stream_outcome == "disconnected"
                assert not finished.is_set()
                for route in ("/ask", "/ask/stream"):
                    busy = client.post(route, json={"question": "Busy?"})
                    assert busy.status_code == 503
                    assert busy.json()["error"]["code"] == "busy"
                assert client.get("/health").status_code == 200
        finally:
            release.set()
        assert client.portal.call(asyncio.to_thread, finished.wait, 2)
        # Let the worker's thread completion reach the ASGI loop.
        client.portal.call(asyncio.sleep, 0)
        for route in ("/ask", "/ask/stream"):
            recovered = client.post(route, json={"question": "Next"})
            assert recovered.status_code == 200
        assert questions == ["private question", "Next", "Next"]
    assert "private" not in caplog.text
