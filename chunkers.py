"""Text chunking strategies."""


def chunk_text(text: str, chunk_size: int, overlap_size: int) -> list[str]:
    """Split text into word-based chunks with overlapping words."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")
    if overlap_size < 0 or overlap_size >= chunk_size:
        raise ValueError("overlap_size must be at least zero and less than chunk_size.")

    words = text.split()
    step_size = chunk_size - overlap_size
    chunks = []
    for start in range(0, len(words), step_size):
        chunk = words[start : start + chunk_size]
        if not chunk:
            break
        chunks.append(" ".join(chunk))
        if start + chunk_size >= len(words):
            break
    print(f"Created {len(chunks)} chunks.")
    return chunks
