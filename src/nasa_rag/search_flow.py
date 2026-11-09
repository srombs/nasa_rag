"""Optional observation of actual search operations, independent of HTTP."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from .search_details import StageDetails

StageId = Literal[
    "plan_query",
    "embed_query",
    "semantic_search",
    "keyword_search",
    "combine_rankings",
    "rerank_evidence",
    "generate_answer",
    "check_citations",
]
STAGE_IDS: tuple[StageId, ...] = (
    "plan_query",
    "embed_query",
    "semantic_search",
    "keyword_search",
    "combine_rankings",
    "rerank_evidence",
    "generate_answer",
    "check_citations",
)


@dataclass(frozen=True)
class StageEvent:
    type: Literal["stage.started", "stage.completed", "stage.failed"]
    stage_id: StageId
    duration_ms: float | None = None
    error: Exception | None = None
    details: StageDetails = StageDetails()


@dataclass
class StageCompletion:
    """The observed operation supplies its snapshot before leaving the stage."""

    details: StageDetails = StageDetails()


Observer = Callable[[StageEvent], None]
_observer: ContextVar[Observer | None] = ContextVar("search_observer", default=None)


@contextmanager
def observe_search(observer: Observer) -> Iterator[None]:
    """Observe this execution context only; startup and other runs stay separate."""
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


@contextmanager
def search_stage(stage_id: StageId) -> Iterator[StageCompletion | None]:
    """Publish boundaries and optional details from the actual operation."""
    observer = _observer.get()
    if observer is None:
        yield None
        return
    started = monotonic()
    observer(StageEvent("stage.started", stage_id))
    completion = StageCompletion()
    try:
        yield completion
    except Exception as error:
        observer(
            StageEvent("stage.failed", stage_id, (monotonic() - started) * 1000, error)
        )
        raise
    else:
        observer(
            StageEvent(
                "stage.completed",
                stage_id,
                (monotonic() - started) * 1000,
                details=completion.details,
            )
        )
