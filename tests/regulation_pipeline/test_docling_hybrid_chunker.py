from dataclasses import dataclass
from typing import Any

from docling_core.transforms.chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc import DoclingDocument, DocItemLabel
from docling_core.types.doc.base import BoundingBox
from docling_core.types.doc.document import ProvenanceItem

from regulation_pipeline.chunking.docling_hybrid_chunker import chunk_document


class WordCountTokenizer(BaseTokenizer):
    """Local, network-free stand-in for HuggingFaceTokenizer in tests."""

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def get_max_tokens(self) -> int:
        return 4096

    def get_tokenizer(self) -> Any:
        return None


def _prov(page_no: int) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no, bbox=BoundingBox(l=0, t=100, r=100, b=0), charspan=(0, 10)
    )


def test_chunk_document_captures_page_and_section():
    doc = DoclingDocument(name="test-doc")
    heading = doc.add_heading(text="Article 320 Penalties", level=1, prov=_prov(1))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="An owner who exceeds the limit is liable for a civil penalty.",
        prov=_prov(1),
        parent=heading,
    )
    chunker = HybridChunker(tokenizer=WordCountTokenizer())

    chunks = chunk_document(doc, document_key="test-doc", chunker=chunker)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_id == 0
    assert chunk.document_key == "test-doc"
    assert chunk.page_number == 1
    assert chunk.section == "Article 320 Penalties"
    assert chunk.section_path == "Article 320 Penalties"
    assert "civil penalty" in chunk.raw_text
    assert "Article 320 Penalties" in chunk.full_text


@dataclass
class _FakeItem:
    label: str
    prov: list[Any]


@dataclass
class _FakeMeta:
    doc_items: list[_FakeItem]
    headings: list[str] | None


@dataclass
class _FakeDocChunk:
    text: str
    meta: _FakeMeta


class _FakeProv:
    def __init__(self, page_no: int) -> None:
        self.page_no = page_no


class _FakeChunker:
    def __init__(self, chunks: list[_FakeDocChunk]) -> None:
        self._chunks = chunks

    def chunk(self, dl_doc: Any) -> list[_FakeDocChunk]:
        return self._chunks

    def contextualize(self, chunk: _FakeDocChunk) -> str:
        return f"CONTEXT: {chunk.text}"


def test_chunk_document_marks_mixed_block_types_and_multi_page_span():
    fake_chunk = _FakeDocChunk(
        text="row data",
        meta=_FakeMeta(
            doc_items=[
                _FakeItem(label="table", prov=[_FakeProv(5)]),
                _FakeItem(label="text", prov=[_FakeProv(6)]),
            ],
            headings=["Article A", "Section A.1"],
        ),
    )
    chunker = _FakeChunker([fake_chunk])

    chunks = chunk_document(object(), document_key="doc-2", chunker=chunker)  # type: ignore[arg-type]

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.page_number == 5
    assert chunk.block_type == "mixed"
    assert chunk.section == "Section A.1"
    assert chunk.section_path == "Article A > Section A.1"
    assert chunk.chunk_meta == {"page_numbers": [5, 6], "block_types": ["table", "text"]}
    assert chunk.full_text == "CONTEXT: row data"


def test_chunk_document_handles_missing_headings_and_provenance():
    fake_chunk = _FakeDocChunk(
        text="orphan text",
        meta=_FakeMeta(doc_items=[_FakeItem(label="text", prov=[])], headings=None),
    )
    chunker = _FakeChunker([fake_chunk])

    chunks = chunk_document(object(), document_key="doc-3", chunker=chunker)  # type: ignore[arg-type]

    assert chunks[0].page_number is None
    assert chunks[0].section is None
    assert chunks[0].section_path is None
