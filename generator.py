"""Answer generation grounded in retrieved document context."""

from collections.abc import Sequence
import logging

from models import DocumentChunk


GENERATION_MODEL = "gpt-5.6-luna"
LOGGER = logging.getLogger(__name__)


def build_context(results: Sequence[DocumentChunk]) -> str:
    """Format retrieved chunks into a labeled context string for generation."""
    return "\n\n---\n\n".join(
        f"Source: {chunk.source}\nChunk: {chunk.chunk_index}\n{chunk.text}"
        for chunk in results
    )


def generate_answer(context: str, question: str) -> str:
    """Generate an answer to ``question`` using only the supplied context."""
    if not context.strip():
        raise ValueError("Context cannot be empty.")
    if not question.strip():
        raise ValueError("Question cannot be empty.")

    from openai import OpenAI

    input_text = f"Context:\n{context}\n\nQuestion:\n{question}"
    LOGGER.info(
        "Sending generation request to %s with input:\n%s",
        GENERATION_MODEL,
        input_text,
    )
    response = OpenAI().responses.create(
        model=GENERATION_MODEL,
        instructions=(
            "Answer the user's question using only the provided context."

            "If the context does not contain enough information to answer the question,"
            "say that the provided documents do not contain enough information."

            "Do not use outside knowledge."
        ),
        input=input_text,
    )
    LOGGER.info("Received generation response from %s.", GENERATION_MODEL)
    answer = response.output_text.strip()
    if not answer:
        raise ValueError("The generation API returned an empty answer.")
    return answer
