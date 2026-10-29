"""Optional HTTP adapter for independent NASA questions."""

import asyncio
import logging
import math
import os
from collections import deque
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager, suppress
from http import HTTPStatus
from json import JSONDecodeError
from pathlib import Path
from tempfile import TemporaryFile
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

Pipeline = Callable[[str], str]
LOGGER = logging.getLogger(__name__)


@contextmanager
def web_logging():
    """Silence prompt/exception-bearing libraries for the web process lifespan."""
    namespaces = (
        "nasa_rag.generation",
        "nasa_rag.retrieval",
        "nasa_rag.ingestion",
        "nasa_rag.embedder",
        "nasa_rag.search",
        "nasa_rag.model_costs",
        "openai",
        "httpx",
        "httpx2",
        "httpcore",
    )
    saved = []
    for name in namespaces:
        logger = logging.getLogger(name)
        saved.append((logger, logger.level, logger.handlers, logger.propagate))
        logger.setLevel(logging.CRITICAL + 1)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
    original_level = LOGGER.level
    handler = None
    if not LOGGER.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    try:
        yield
    finally:
        LOGGER.setLevel(original_level)
        if handler is not None:
            LOGGER.removeHandler(handler)
            handler.close()
        for logger, level, handlers, propagate in saved:
            logger.setLevel(level)
            logger.handlers = handlers
            logger.propagate = propagate


def is_upstream_failure(error: Exception) -> bool:
    """Recognize provider failures through the existing adapter exception chain."""
    from openai import APIError

    from .embedder import EmbeddingError
    from .generation.generator import GenerationError
    from .retrieval.query_rewriter import QueryRewriteError
    from .retrieval.reranker import RerankingError
    from .retrieval.retrieval_planner import RetrievalPlanningError

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, APIError):
            return True
        cause = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
        if isinstance(
            current,
            (
                EmbeddingError,
                GenerationError,
                QueryRewriteError,
                RerankingError,
                RetrievalPlanningError,
            ),
        ) and (cause is None or isinstance(cause, JSONDecodeError)):
            return True
        current = cause
    return False


def load_pipeline() -> Pipeline:
    """Initialize the existing pipeline at server startup."""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY must be set before starting the API.")
    cache_setting = os.environ.get("NASA_RAG_CACHE_DIR", "")
    if not cache_setting.strip():
        raise RuntimeError("NASA_RAG_CACHE_DIR must name a writable cache directory.")

    from .paths import data_directory
    from .retrieval.retrieval_planner import RetrievalPlanner, RetrievalPlanningError
    from .retrieval.retriever import Retriever
    from .search import generate_rag_answer, run_both_searches

    try:
        cache = Path(cache_setting).expanduser()
        cache.mkdir(parents=True, exist_ok=True)
        with TemporaryFile(dir=cache):
            pass
        retriever = Retriever(data_directory(), cache_directory=cache)
        retriever.load()
    except Exception as error:
        raise RuntimeError(
            "Unable to initialize the API retriever and cache."
        ) from error
    planner = RetrievalPlanner()

    def answer(question: str) -> str:
        plan = planner.infer(question)
        try:
            retriever.validate_source_file_filter(plan.source_file_filter)
        except ValueError:
            raise RetrievalPlanningError(
                "The provider plan names an unavailable source."
            ) from None
        _, _, _, reranked, _ = run_both_searches(
            question,
            retriever,
            source_file_filter=plan.source_file_filter,
            search_query=plan.search_query,
        )
        return generate_rag_answer(question, [result.chunk for result in reranked])

    return answer


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(strict=True, min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question cannot be blank.")
        return value


def error_response(
    request: Request, status: int, code: str, message: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "request_id": request.state.request_id,
            "error": {"code": code, "message": message},
        },
    )


async def wait_for_disconnect(request: Request) -> None:
    """Watch the connection after FastAPI has consumed the request body."""
    while True:
        if (await request.receive())["type"] == "http.disconnect":
            return


class RequestControls:
    """Bound submissions, sanitize failures, and log one safe request record."""

    def __init__(
        self,
        app: ASGIApp,
        submissions: dict[str, deque[float]],
        clock: Callable[[], float],
    ):
        self.app = app
        self.submissions = submissions
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        request.state.request_id = str(uuid4())
        started = monotonic()
        status = 500
        response_started = False

        async def observed_send(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                message.setdefault("headers", []).append(
                    (b"x-request-id", request.state.request_id.encode("ascii"))
                )
            await send(message)

        try:
            if scope["method"] == "POST" and scope["path"] == "/ask":
                now = self.clock()
                for address, times in list(self.submissions.items()):
                    while times and times[0] <= now - 600:
                        times.popleft()
                    if not times:
                        del self.submissions[address]
                address = scope["client"][0] if scope.get("client") else "unknown"
                times = self.submissions.setdefault(address, deque())
                if len(times) >= 10:
                    response = error_response(
                        request,
                        429,
                        "rate_limited",
                        "Limit of 10 submissions per 10 minutes reached.",
                    )
                    await response(scope, receive, observed_send)
                    return
                times.append(now)
            await self.app(scope, receive, observed_send)
        except asyncio.CancelledError:
            status = 499
            raise
        except Exception as error:
            if response_started:
                raise
            if is_upstream_failure(error):
                response = error_response(
                    request,
                    502,
                    "upstream_error",
                    "The model provider could not answer.",
                )
            else:
                response = error_response(
                    request, 500, "internal_error", "Unable to answer the question."
                )
            await response(scope, receive, observed_send)
        finally:
            elapsed = (monotonic() - started) * 1000
            LOGGER.info(
                "request_id=%s status=%d elapsed_ms=%.2f",
                request.state.request_id,
                status,
                elapsed,
                extra={
                    "request_id": request.state.request_id,
                    "http_status": status,
                    "elapsed_ms": elapsed,
                },
            )


def create_app(
    pipeline_factory: Callable[[], Pipeline] = load_pipeline,
    *,
    clock: Callable[[], float] = monotonic,
) -> FastAPI:
    """Create an application; initialization happens during its lifespan."""
    pipeline: Pipeline | None = None
    running: asyncio.Task[str] | None = None
    submissions: dict[str, deque[float]] = {}
    deadline = 120.0

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal pipeline, deadline
        try:
            deadline = float(os.environ.get("NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "120"))
            if not math.isfinite(deadline) or deadline <= 0:
                raise ValueError
        except ValueError:
            raise RuntimeError(
                "NASA_RAG_RESPONSE_TIMEOUT_SECONDS must be a positive finite number."
            ) from None
        submissions.clear()
        with web_logging():
            pipeline = await asyncio.to_thread(pipeline_factory)
            try:
                yield
            finally:
                pipeline = None
                if running is not None:
                    with suppress(Exception):
                        await asyncio.shield(running)

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(RequestControls, submissions=submissions, clock=clock)
    app.add_middleware(
        ProxyHeadersMiddleware,
        trusted_hosts=os.environ.get("NASA_RAG_TRUSTED_PROXIES", ""),
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return error_response(
            request,
            422,
            "invalid_request",
            "Provide only a nonblank question of at most 1,000 characters.",
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        response = error_response(
            request,
            error.status_code,
            "http_error",
            HTTPStatus(error.status_code).phrase,
        )
        if error.headers:
            response.headers.update(error.headers)
        return response

    @app.get("/health")
    async def health(request: Request):
        if pipeline is None:
            return error_response(
                request, 503, "not_ready", "The service is not ready."
            )
        return {"status": "ok"}

    @app.post("/ask")
    async def ask(body: Question, request: Request):
        nonlocal running
        if pipeline is None:
            return error_response(
                request, 503, "not_ready", "The service is not ready."
            )
        if running is not None and not running.done():
            return error_response(
                request, 503, "busy", "The service is processing a question."
            )
        task = asyncio.create_task(asyncio.to_thread(pipeline, body.question))
        running = task
        task.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None
        )
        disconnected = asyncio.create_task(wait_for_disconnect(request))
        try:
            done, _ = await asyncio.wait(
                {task, disconnected},
                timeout=deadline,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if task in done:
                answer = task.result()
            elif disconnected in done:
                return error_response(
                    request, 499, "client_disconnected", "The client disconnected."
                )
            else:
                return error_response(
                    request,
                    504,
                    "response_timeout",
                    "The response deadline was exceeded; "
                    "processing may still be running.",
                )
        finally:
            disconnected.cancel()
            with suppress(asyncio.CancelledError):
                await disconnected
        return {"request_id": request.state.request_id, "answer": answer}

    return app


app = create_app()
