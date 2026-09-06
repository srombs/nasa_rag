import json

import file_loader
import semantic_search
from models import DocumentChunk

from nasa_rag import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_load_and_embed_directory_caches_each_text_file(monkeypatch, tmp_path) -> None:
    (tmp_path / "b.txt").write_text("four five", encoding="utf-8")
    (tmp_path / "a.txt").write_text("one two three", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("not a source", encoding="utf-8")

    embedded_inputs: list[tuple[list[str], str]] = []

    def fake_embed_documents(texts, source):
        text_list = list(texts)
        embedded_inputs.append((text_list, source))
        return [
            DocumentChunk(source, index, text, [float(index)])
            for index, text in enumerate(text_list)
        ]

    monkeypatch.setattr(file_loader, "embed_documents", fake_embed_documents)

    chunks = file_loader.load_and_embed_directory(
        tmp_path, chunk_size=2, overlap_size=0
    )

    assert embedded_inputs == [
        (["one two", "three"], "a.txt"),
        (["four five"], "b.txt"),
    ]
    assert [(chunk.source, chunk.chunk_index, chunk.text) for chunk in chunks] == [
        ("a.txt", 0, "one two"),
        ("a.txt", 1, "three"),
        ("b.txt", 0, "four five"),
    ]

    cache_path = tmp_path / file_loader.CACHE_FILE_NAME
    assert json.loads(cache_path.read_text(encoding="utf-8")) == {
        "documents": {
            "a.txt": [
                {
                    "source": "a.txt",
                    "chunk_index": 0,
                    "text": "one two",
                    "embed": [0.0],
                },
                {
                    "source": "a.txt",
                    "chunk_index": 1,
                    "text": "three",
                    "embed": [1.0],
                },
            ],
            "b.txt": [
                {
                    "source": "b.txt",
                    "chunk_index": 0,
                    "text": "four five",
                    "embed": [0.0],
                }
            ],
        }
    }

    cached_chunks = file_loader.load_and_embed_directory(
        tmp_path, chunk_size=2, overlap_size=0
    )

    assert embedded_inputs == [
        (["one two", "three"], "a.txt"),
        (["four five"], "b.txt"),
    ]
    assert cached_chunks == chunks


def test_print_ranked_chunks_uses_top_k(capsys) -> None:
    chunks = [
        DocumentChunk("a.txt", 0, "first", [1.0], similarity=0.9),
        DocumentChunk("b.txt", 0, "second", [1.0], similarity=0.8),
    ]

    semantic_search.print_ranked_chunks(chunks, top_k=1)

    assert capsys.readouterr().out == "0.9000 | a.txt | chunk 0 | first\n"
