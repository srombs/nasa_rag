"""Optional HTTP adapter for independent NASA questions."""

import asyncio
import os
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from tempfile import TemporaryFile
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

Pipeline = Callable[[str], str]


def load_pipeline() -> Pipeline:
    """Initialize the existing pipeline at server startup."""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY must be set before starting the API.")
    cache_setting = os.environ.get("NASA_RAG_CACHE_DIR", "")
    if not cache_setting.strip():
        raise RuntimeError("NASA_RAG_CACHE_DIR must name a writable cache directory.")

    from .paths import data_directory
    from .retrieval.retrieval_planner import RetrievalPlanner
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
        retriever.validate_source_file_filter(plan.source_file_filter)
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


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "request_id": str(uuid4()),
            "error": {"code": code, "message": message},
        },
    )


def create_app(pipeline_factory: Callable[[], Pipeline] = load_pipeline) -> FastAPI:
    """Create an application; initialization happens during its lifespan."""
    pipeline: Pipeline | None = None
    running: asyncio.Task[str] | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal pipeline
        pipeline = await asyncio.to_thread(pipeline_factory)
        try:
            yield
        finally:
            pipeline = None
            if running is not None:
                with suppress(Exception):
                    await asyncio.shield(running)

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return error_response(
            422,
            "invalid_request",
            "Provide only a nonblank question of at most 1,000 characters.",
        )

    @app.get("/health")
    async def health():
        if pipeline is None:
            return error_response(503, "not_ready", "The service is not ready.")
        return {"status": "ok"}

    @app.post("/ask")
    async def ask(body: Question):
        nonlocal running
        if pipeline is None:
            return error_response(503, "not_ready", "The service is not ready.")
        if running is not None and not running.done():
            return error_response(503, "busy", "The service is processing a question.")
        running = asyncio.create_task(asyncio.to_thread(pipeline, body.question))
        running.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None
        )
        try:
            answer = await asyncio.shield(running)
        except Exception:
            return error_response(
                500, "internal_error", "Unable to answer the question."
            )
        return {"request_id": str(uuid4()), "answer": answer}

    return app


app = create_app()
