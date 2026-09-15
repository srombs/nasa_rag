"""Model-backed query rewriting."""

import logging
from typing import Any


QUERY_REWRITE_MODEL = "gpt-5.6-luna"
QUERY_REWRITE_INSTRUCTIONS = """Rewrite the user's question into a concise search query
that improves retrieval.

Preserve the original meaning and important entities.

Do not answer the question.
Do not add facts, entities, names, dates, or terminology
that are not present or directly implied by the original question.

Return only the rewritten search query."""
LOGGER = logging.getLogger(__name__)


class QueryRewriteError(RuntimeError):
    """Raised when a query-rewrite request cannot be completed."""


class QueryRewriter:
    """Rewrite a user query with the configured search-query instructions."""

    def __init__(self, client: Any | None = None) -> None:
        self.instructions = QUERY_REWRITE_INSTRUCTIONS
        self._client = client

    def rewrite(self, query: str) -> str:
        """Send one user query to the model and return its rewritten form."""
        if not query.strip():
            raise ValueError("Query text cannot be empty.")

        LOGGER.info(
            "Sending query rewrite request to %s with input:\n%s",
            QUERY_REWRITE_MODEL,
            query,
        )
        try:
            response = self._get_client().responses.create(
                model=QUERY_REWRITE_MODEL,
                instructions=self.instructions,
                input=query,
            )
            rewritten_query = response.output_text.strip()
            if not rewritten_query:
                raise QueryRewriteError(
                    "The query rewrite API returned an empty query."
                )
            LOGGER.info("Received query rewrite response from %s.", QUERY_REWRITE_MODEL)
            return rewritten_query
        except QueryRewriteError:
            raise
        except Exception as error:
            LOGGER.exception("Failed to rewrite query with %s.", QUERY_REWRITE_MODEL)
            raise QueryRewriteError("Unable to rewrite the query.") from error

    def _get_client(self) -> Any:
        """Create and retain the API client only when rewriting is requested."""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client
