from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc import DoclingDocument
from transformers import AutoTokenizer

from regulation_pipeline.config import Settings


@dataclass
class Chunk:
    chunk_id: int
    document_key: str
    page_number: int | None
    block_type: str | None
    section: str | None
    section_path: str | None
    raw_text: str
    full_text: str
    chunk_meta: dict[str, Any] = field(default_factory=dict)


def build_tokenizer(settings: Settings) -> BaseTokenizer:
    return HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained(settings.embed_model_hf_id),
        max_tokens=settings.embed_max_tokens,
    )


def build_chunker(settings: Settings) -> HybridChunker:
    return HybridChunker(tokenizer=build_tokenizer(settings))


def chunk_document(
    document: DoclingDocument, document_key: str, chunker: HybridChunker
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for chunk_id, dl_chunk in enumerate(chunker.chunk(dl_doc=document)):
        doc_items = dl_chunk.meta.doc_items
        page_numbers = sorted({prov.page_no for item in doc_items for prov in item.prov})
        block_types = sorted({str(item.label) for item in doc_items})
        headings = dl_chunk.meta.headings or []

        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_key=document_key,
                page_number=page_numbers[0] if page_numbers else None,
                block_type=block_types[0] if len(block_types) == 1 else "mixed",
                section=headings[-1] if headings else None,
                section_path=" > ".join(headings) if headings else None,
                raw_text=dl_chunk.text,
                full_text=chunker.contextualize(chunk=dl_chunk),
                chunk_meta={"page_numbers": page_numbers, "block_types": block_types},
            )
        )
    return chunks


def chunk_pdf(pdf_path: Path, document_key: str, settings: Settings) -> list[Chunk]:
    document = DocumentConverter().convert(pdf_path).document
    chunker = build_chunker(settings)
    return chunk_document(document, document_key, chunker)
