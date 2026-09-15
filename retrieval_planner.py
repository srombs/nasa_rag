"""Model-backed retrieval planning."""

import json
import logging
from typing import Any

from models import RetrievalPlan

RETRIEVAL_PLANNER_MODEL = "gpt-5.6-luna"
RETRIEVAL_PLANNER_INSTRUCTIONS = """You create retrieval plans for a document
search system.

Available sources:
- hubble.txt
- space_shuttle.txt
- nasa_overview.txt
- iss.txt

Given a user's question:

1. Rewrite it into a concise retrieval query.
2. If the user explicitly requests information from one
   specific available source, set source_file_filter to that filename.
3. Otherwise set source_file_filter to null.

Do not answer the user's question.
Do not add facts or entities that aren't present or directly
implied by the question.
Do not invent source names."""
RETRIEVAL_PLANNER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "retrieval_plan",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "search_query": {"type": "string"},
            "source_file_filter": {"type": ["string", "null"]},
        },
        "required": ["search_query", "source_file_filter"],
        "additionalProperties": False,
    },
}
LOGGER = logging.getLogger(__name__)


class RetrievalPlanningError(RuntimeError):
    """Raised when a retrieval-plan request cannot be completed."""


class RetrievalPlanner:
    """Infer a search query and optional source-file filter from a question."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def infer(self, query: str) -> RetrievalPlan:
        """Request and validate a retrieval plan for one user query."""
        if not query.strip():
            raise ValueError("Query text cannot be empty.")

        LOGGER.info(
            "Sending retrieval-planning request to %s with input:\n%s",
            RETRIEVAL_PLANNER_MODEL,
            query,
        )
        try:
            response = self._get_client().responses.create(
                model=RETRIEVAL_PLANNER_MODEL,
                instructions=RETRIEVAL_PLANNER_INSTRUCTIONS,
                input=query,
                text={"format": RETRIEVAL_PLANNER_RESPONSE_FORMAT},
            )
            payload = json.loads(response.output_text)
            plan = self._validate_response(payload)
            LOGGER.info(
                "Received retrieval-planning response from %s:\n%s",
                RETRIEVAL_PLANNER_MODEL,
                plan,
            )
            return plan
        except RetrievalPlanningError:
            raise
        except Exception as error:
            LOGGER.exception(
                "Failed to infer a retrieval plan with %s.", RETRIEVAL_PLANNER_MODEL
            )
            raise RetrievalPlanningError("Unable to infer a retrieval plan.") from error

    def _get_client(self) -> Any:
        """Create and retain the API client only when inference is requested."""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    @staticmethod
    def _validate_response(payload: object) -> RetrievalPlan:
        """Validate the structured model response."""
        if not isinstance(payload, dict):
            raise RetrievalPlanningError(
                "The retrieval-plan API returned invalid JSON."
            )

        search_query = payload.get("search_query")
        source_file_filter = payload.get("source_file_filter")
        if not isinstance(search_query, str) or not search_query.strip():
            raise RetrievalPlanningError(
                "The retrieval-plan API returned an invalid search query."
            )
        if source_file_filter is not None and not isinstance(source_file_filter, str):
            raise RetrievalPlanningError(
                "The retrieval-plan API returned an invalid source file filter."
            )
        return RetrievalPlan(
            search_query=search_query.strip(), source_file_filter=source_file_filter
        )
