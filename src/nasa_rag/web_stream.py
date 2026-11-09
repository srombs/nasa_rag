"""Bounded, detachable SSE observation of one synchronous search worker.

Publishes lifecycle events, stage details, reranking progress, and durations.
Usage metrics and complete interruption behavior arrive in later slices;
absent data is never fabricated.
"""

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Literal

from fastapi import Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from .search_details import StageDetails
from .search_flow import STAGE_IDS, StageEvent, StageId, StageProgress

HEARTBEAT_SECONDS = 15.0
MAX_QUEUED_EVENTS = 64
FailureMapper = Callable[[Exception], tuple[int, dict[str, str]]]


@dataclass
class StageSnapshot:
    """Observed lifecycle state, serialized through an explicit public allowlist."""

    stage_id: StageId
    status: Literal[
        "pending", "running", "completed", "failed", "skipped", "unknown"
    ] = "pending"
    duration_ms: float | None = None
    error: dict[str, str] | None = None
    details: StageDetails | None = None
    progress: StageProgress | None = None

    def public(self) -> dict:
        return {
            "stage_id": self.stage_id,
            "status": self.status,
            "details": self.details.public() if self.details is not None else None,
            "progress": self.progress.public() if self.progress is not None else None,
            "metrics": (
                {"duration_ms": self.duration_ms}
                if self.duration_ms is not None
                else None
            ),
            "error": self.error,
        }


class SearchStream:
    """Serialize at publication and bound both frames and worker notifications."""

    def __init__(
        self, request_id: str, admitted: float, deadline: float, failure: FailureMapper
    ):
        self.request_id = request_id
        self.admitted = admitted
        self.expires_at = admitted + deadline
        self.failure = failure
        self._loop = asyncio.get_running_loop()
        self._ready = asyncio.Event()
        self._lock = Lock()
        self._frames: deque[bytes] = deque()
        self._closed = False
        self._sequence = 0
        self._outcome = "disconnected"
        self._failure_code: str | None = None
        self._stages = {stage: StageSnapshot(stage) for stage in STAGE_IDS}
        self._publish("run.started", None, {"stage_ids": STAGE_IDS})

    def _publish(self, kind: str, stage_id: str | None, data: dict) -> None:
        """Caller holds the lock (except during construction). Never block work."""
        if len(self._frames) >= MAX_QUEUED_EVENTS:
            self._detach()
            return
        self._sequence += 1
        payload = {
            "schema_version": 1,
            "request_id": self.request_id,
            "sequence": self._sequence,
            "type": kind,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "elapsed_ms": (monotonic() - self.admitted) * 1000,
            "stage_id": stage_id,
            "data": data,
        }
        frame = (
            f"event: {kind}\nid: {self._sequence}\n"
            f"data: {json.dumps(payload, ensure_ascii=False, allow_nan=False)}\n\n"
        ).encode()
        notify = not self._frames
        self._frames.append(frame)
        if notify:
            self._loop.call_soon_threadsafe(self._ready.set)

    def stage(self, event: StageEvent) -> None:
        """Called on the worker; never touch an asyncio queue from that thread."""
        with self._lock:
            if self._closed:
                return
            if monotonic() >= self.expires_at:
                self._timeout_locked(True)
                return
            snapshot = self._stages[event.stage_id]
            data: dict = {}
            if event.type == "stage.started":
                snapshot.status = "running"
            elif event.progress is not None:
                snapshot.progress = event.progress
                snapshot.details = (
                    snapshot.details or StageDetails()
                ).append_evaluated(event.progress.result)
                data = event.progress.public()
            else:
                snapshot.duration_ms = event.duration_ms
                data["metrics"] = {"duration_ms": event.duration_ms}
                if event.error is None:
                    snapshot.status = "completed"
                    snapshot.details = event.details
                    data["details"] = event.details.public()
                else:
                    _, error = self.failure(event.error)
                    snapshot.status = "failed"
                    snapshot.error = error
                    data["error"] = error
            self._publish(event.type, event.stage_id, data)

    def complete(self, answer: str) -> None:
        with self._lock:
            if not self._closed:
                if monotonic() >= self.expires_at:
                    self._timeout_locked(False)
                else:
                    self._finish("run.completed", {"answer": answer}, "completed")

    def fail(self, error: Exception) -> None:
        status, public = self.failure(error)
        with self._lock:
            if self._closed:
                return
            if monotonic() >= self.expires_at:
                self._timeout_locked(False)
                return
            for stage in self._stages.values():
                if stage.status == "pending":
                    stage.status = "skipped"
            self._finish(
                "run.failed",
                {
                    "error": public,
                    "http_equivalent_status": status,
                    "processing_may_continue": False,
                },
                "failed",
            )

    def _timeout(self, processing: bool) -> None:
        with self._lock:
            if self._closed:
                return
            self._timeout_locked(processing)

    def _timeout_locked(self, processing: bool) -> None:
        for stage in self._stages.values():
            if stage.status in {"pending", "running"}:
                stage.status = "unknown"
        self._finish(
            "run.failed",
            {
                "error": {
                    "code": "response_timeout",
                    "message": "The response deadline was exceeded; "
                    "processing may still be running.",
                },
                "http_equivalent_status": 504,
                "processing_may_continue": processing,
            },
            "timeout",
        )

    def _finish(self, kind: str, data: dict, outcome: str) -> None:
        # Encode the terminal snapshot while locked, then freeze the event sink.
        data["metrics"] = {"duration_ms": (monotonic() - self.admitted) * 1000}
        data["stages"] = [stage.public() for stage in self._stages.values()]
        self._outcome = outcome
        self._failure_code = data.get("error", {}).get("code")
        self._publish(kind, None, data)
        self._closed = True

    def _detach(self) -> None:
        self._outcome = "disconnected"
        self._closed = True
        self._frames.clear()
        self._loop.call_soon_threadsafe(self._ready.set)

    def detach(self) -> None:
        """Drop queued observations; actual worker ownership remains with the app."""
        with self._lock:
            self._detach()

    async def body(
        self,
        request: Request,
        worker: asyncio.Task[str],
    ) -> AsyncIterator[bytes]:
        request.state.stream_outcome = "disconnected"
        try:
            while True:
                remaining = self.expires_at - monotonic()
                if remaining <= 0:
                    self._timeout(not worker.done())
                with self._lock:
                    frame = self._frames.popleft() if self._frames else None
                    finished = self._closed and not self._frames
                    self._ready.clear()
                if frame is not None:
                    yield frame
                if finished:
                    request.state.stream_outcome = self._outcome
                    request.state.failure_code = self._failure_code
                    return
                if frame is None:
                    try:
                        await asyncio.wait_for(
                            self._ready.wait(), min(HEARTBEAT_SECONDS, remaining)
                        )
                    except TimeoutError:
                        if monotonic() < self.expires_at:
                            yield b": heartbeat\n\n"
        finally:
            self.detach()


class SearchStreamResponse(StreamingResponse):
    """Detach even if transport fails before the body iterator is first entered."""

    def __init__(self, stream: SearchStream, *args, **kwargs):
        self.stream = stream
        super().__init__(*args, **kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.stream.detach()
