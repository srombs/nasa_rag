"""Record OpenAI request usage and estimate the cost of each run."""

import json
import logging
import os
from collections import Counter, defaultdict
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

LOGGER = logging.getLogger(__name__)
MODULE_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_LOG_PATH = (
    MODULE_DIRECTORY / "logs" / "model_costs.jsonl"
    if (MODULE_DIRECTORY / "pyproject.toml").is_file()
    else Path.home() / ".local" / "state" / "nasa_rag" / "model_costs.jsonl"
)
LOG_PATH_ENV = "NASA_RAG_COST_LOG_PATH"
PRICE_DATE = "2026-09-29"
MILLION = Decimal(1_000_000)

# USD per million tokens. Update these rates and PRICE_DATE together.
PRICES = {
    "gpt-5.6-luna": {
        "input": Decimal("0.20"),
        "cached_input": Decimal("0.02"),
        "cache_write": Decimal("0.25"),
        "output": Decimal("1.20"),
    },
    "text-embedding-3-small": {"input": Decimal("0.02")},
}


@dataclass
class CostRun:
    """Accumulate the model requests made during one CLI or evaluation run."""

    name: str
    id: str = field(default_factory=lambda: uuid4().hex)
    calls: int = 0
    unknown_calls: int = 0
    total_usd: Decimal = Decimal(0)
    by_operation: dict[str, Decimal] = field(
        default_factory=lambda: defaultdict(Decimal)
    )
    operation_counts: Counter[str] = field(default_factory=Counter)
    unknown_by_operation: Counter[str] = field(default_factory=Counter)


_CURRENT_RUN: ContextVar[CostRun | None] = ContextVar("model_cost_run", default=None)
_PROCESS_RUN = CostRun("unscoped")
F = TypeVar("F", bound=Callable[..., Any])


def _usage_value(usage: Any, field_name: str) -> int | None:
    value = getattr(usage, field_name, None)
    return value if type(value) is int and value >= 0 else None


def _estimate_cost(
    endpoint: str, model: str, usage: Any
) -> tuple[dict, Decimal | None]:
    """Return token counts and a price estimate, or None when data is incomplete."""
    prices = PRICES.get(model)
    if endpoint == "embeddings":
        input_tokens = _usage_value(usage, "prompt_tokens")
        counts = {"input_tokens": input_tokens}
        if input_tokens is None or prices is None:
            return counts, None
        return counts, Decimal(input_tokens) * prices["input"] / MILLION

    input_tokens = _usage_value(usage, "input_tokens")
    output_tokens = _usage_value(usage, "output_tokens")
    details = getattr(usage, "input_tokens_details", None)
    cached_tokens = _usage_value(details, "cached_tokens")
    cache_write_tokens = _usage_value(details, "cache_write_tokens")
    counts = {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": _usage_value(
            getattr(usage, "output_tokens_details", None), "reasoning_tokens"
        ),
    }
    if input_tokens is None or output_tokens is None or prices is None:
        return counts, None
    if cached_tokens is None or cache_write_tokens is None:
        # A complete no-cache breakdown is required before assigning a price.
        return counts, None
    ordinary_tokens = input_tokens - cached_tokens - cache_write_tokens
    if ordinary_tokens < 0:
        return counts, None
    input_cost = (
        Decimal(ordinary_tokens) * prices["input"]
        + Decimal(cached_tokens) * prices["cached_input"]
        + Decimal(cache_write_tokens) * prices["cache_write"]
    ) / MILLION
    # Reasoning tokens are already included in output_tokens.
    output_cost = Decimal(output_tokens) * prices["output"] / MILLION
    if model == "gpt-5.6-luna" and input_tokens > 272_000:
        input_cost *= 2
        output_cost *= Decimal("1.5")
    return counts, input_cost + output_cost


def _record(
    operation: str,
    endpoint: str,
    requested_model: str,
    response: Any = None,
    error: Exception | None = None,
) -> None:
    run = _CURRENT_RUN.get() or _PROCESS_RUN
    response_model = getattr(response, "model", None)
    model = requested_model  # The requested model defines the known rate.
    usage = getattr(response, "usage", None)
    counts, cost = _estimate_cost(endpoint, model, usage)
    run.calls += 1
    run.operation_counts[operation] += 1
    if cost is None:
        run.unknown_calls += 1
        run.unknown_by_operation[operation] += 1
    else:
        run.total_usd += cost
        run.by_operation[operation] += cost

    record = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "run_id": run.id,
        "run_name": run.name,
        "operation": operation,
        "endpoint": endpoint,
        "requested_model": requested_model,
        "response_model": response_model,
        "status": "error" if error is not None else "response",
        "error_type": type(error).__name__ if error is not None else None,
        "tokens": counts,
        "estimated_cost_usd": str(cost) if cost is not None else None,
        "price_date": PRICE_DATE,
        "rates_usd_per_million": {
            key: str(value) for key, value in PRICES.get(model, {}).items()
        },
    }
    path = Path(os.environ.get(LOG_PATH_ENV, DEFAULT_LOG_PATH))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        LOGGER.warning("Unable to write model cost record to %s.", path, exc_info=True)


def call_model(
    operation: str,
    endpoint: str,
    model: str,
    create: Callable[..., Any],
    **kwargs: Any,
) -> Any:
    """Call an OpenAI endpoint and record returned usage or an unknown-cost error."""
    try:
        response = create(model=model, **kwargs)
    except Exception as error:
        _record(operation, endpoint, model, error=error)
        raise
    _record(operation, endpoint, model, response=response)
    return response


def print_cost_summary(run: CostRun) -> None:
    """Print a run's known cost and the number of unpriced requests."""
    print(f"\nModel costs ({run.name}; {run.id}):")
    for operation, count in sorted(run.operation_counts.items()):
        unknown = run.unknown_by_operation[operation]
        suffix = f", {unknown} unknown" if unknown else ""
        print(
            f"  {operation}: {count} call(s), "
            f"known ~${run.by_operation[operation]:.8f}{suffix}"
        )
    print(
        f"  Known total: {run.calls - run.unknown_calls} call(s), "
        f"~${run.total_usd:.8f}"
    )
    if run.unknown_calls:
        print(f"  Unknown cost: {run.unknown_calls} call(s)")


def report_run_costs(name: str) -> Callable[[F], F]:
    """Print a cost summary after a command-line run, including failed runs."""

    def decorate(function: F) -> F:
        @wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            run = CostRun(name)
            token = _CURRENT_RUN.set(run)
            show_summary = True
            try:
                return function(*args, **kwargs)
            except SystemExit as error:
                if error.code in (None, 0) and run.calls == 0:
                    show_summary = False
                raise
            finally:
                _CURRENT_RUN.reset(token)
                if show_summary:
                    print_cost_summary(run)

        return wrapper  # type: ignore[return-value]

    return decorate
