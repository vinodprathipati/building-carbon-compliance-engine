from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import psycopg
from sentence_transformers import SentenceTransformer

from regulation_pipeline.chunking.docling_hybrid_chunker import Chunk, chunk_pdf
from regulation_pipeline.chunking.table_extractor import TableDescriptor, extract_tables_from_pdf
from regulation_pipeline.config import Settings
from regulation_pipeline.db.queries import sql
from regulation_pipeline.embedding.pgvector_embedder import embed_and_store, embed_and_store_tables
from regulation_pipeline.extraction.extractor import extract_concept
from regulation_pipeline.extraction.llm_provider import AnthropicProvider
from regulation_pipeline.extraction.persist import store_concept_records
from regulation_pipeline.extraction.schema import load_schema

DEFAULT_TOP_K = 15


def _get_or_create_rag_document(
    conn: psycopg.Connection,
    document_key: str,
    document_hash: str,
    embed_model_id: str,
    force_regen: bool,
) -> tuple[int, bool]:
    """Returns (rag_id, skipped_ingest). skipped_ingest is True when an active,
    unchanged version already exists and force_regen is False."""
    with conn.cursor() as cur:
        cur.execute(sql("select_active_rag_document"), (document_key,))
        existing = cur.fetchone()

    if existing and not force_regen and existing[1] == document_hash:
        return existing[0], True

    next_version = (existing[2] + 1) if existing else 1
    with conn.cursor() as cur:
        if existing:
            cur.execute(sql("deactivate_rag_document"), (existing[0],))
        cur.execute(
            sql("insert_rag_document"),
            (document_key, document_hash, embed_model_id, next_version),
        )
        rag_id = cur.fetchone()[0]
    conn.commit()
    return rag_id, False


def _start_run(conn: psycopg.Connection, doc_type: str, force_regen: bool) -> int:
    with conn.cursor() as cur:
        cur.execute(sql("insert_pipeline_run"), (force_regen, doc_type))
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def _finish_run(conn: psycopg.Connection, run_id: int, rag_id: int | None, status: str, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(sql("update_pipeline_run"), (status, error, rag_id, run_id))
    conn.commit()


def _run_step(
    conn: psycopg.Connection,
    run_id: int,
    step_name: str,
    fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(sql("insert_pipeline_step"), (run_id, step_name))
        step_id = cur.fetchone()[0]
    conn.commit()

    start = time.monotonic()
    try:
        meta = fn()
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        # A DB error mid-`fn()` leaves Postgres in an aborted-transaction
        # state; every subsequent query on this connection fails until
        # rolled back — including this very failure-recording update.
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(sql("update_pipeline_step_failed"), (str(exc), duration_ms, step_id))
        conn.commit()
        raise

    duration_ms = int((time.monotonic() - start) * 1000)
    with conn.cursor() as cur:
        cur.execute(sql("update_pipeline_step_success"), (json.dumps(meta), duration_ms, step_id))
    conn.commit()
    return meta


def _parse_document(
    pdf_path: Path, document_key: str, settings: Settings
) -> tuple[list[Chunk], list[TableDescriptor], dict[str, Any]]:
    """Docling parsing only — both chunking strategies, no DB writes. Table
    chunk_ids continue on from the general chunks so both strategies share
    one chunk_id space per document, matching how they're later embedded."""
    general_chunks = chunk_pdf(pdf_path, document_key=document_key, settings=settings)
    table_descriptors = extract_tables_from_pdf(
        pdf_path, document_key=document_key, start_chunk_id=len(general_chunks)
    )
    meta = {"general_chunk_count": len(general_chunks), "table_count": len(table_descriptors)}
    return general_chunks, table_descriptors, meta


def _embed_document(
    conn: psycopg.Connection,
    settings: Settings,
    rag_id: int,
    general_chunks: list[Chunk],
    table_descriptors: list[TableDescriptor],
) -> dict[str, Any]:
    """Embedding + pgvector storage only — assumes parsing already happened."""
    embed_and_store(conn, settings, rag_id=rag_id, chunks=general_chunks)
    if table_descriptors:
        embed_and_store_tables(conn, settings, rag_id=rag_id, descriptors=table_descriptors)
    return {"embedded_chunk_count": len(general_chunks) + len(table_descriptors)}


def _run_extraction(
    conn: psycopg.Connection,
    settings: Settings,
    llm: AnthropicProvider,
    embed_model: SentenceTransformer,
    rag_id: int,
    top_k: int,
) -> dict[str, Any]:
    concepts = load_schema()
    counts: dict[str, int] = {}
    for concept_name, concept in concepts.items():
        records = extract_concept(conn, llm, embed_model, concept, rag_id=rag_id, top_k=top_k)
        skipped = store_concept_records(conn, concept_name, rag_id, settings.anthropic_model, records)
        for s in skipped:
            print(f"WARNING: skipped {concept_name} record (chunk_id={s.record.get('chunk_id')}): {s.reason}")
        counts[concept_name] = len(records)
    return counts


def run_pipeline(
    conn: psycopg.Connection,
    settings: Settings,
    embed_model: SentenceTransformer,
    llm: AnthropicProvider,
    pdf_path: Path,
    document_key: str,
    doc_type: str,
    force_regen: bool = False,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    """Run the full pipeline for one PDF: parsing (Docling, both chunking
    strategies) -> embedding (nomic + pgvector storage) -> extraction (all
    four concepts, persisted) — three separately tracked pipeline_steps.
    Parsing/embedding are both skipped if an unchanged active version
    already exists and force_regen is False."""
    run_id = _start_run(conn, doc_type, force_regen)
    document_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    try:
        rag_id, skipped_ingest = _get_or_create_rag_document(
            conn, document_key, document_hash, settings.embed_model_hf_id, force_regen
        )

        if skipped_ingest:
            parsing_meta = {"skipped": True, "reason": "unchanged document_hash"}
            embedding_meta = {"skipped": True, "reason": "unchanged document_hash"}
        else:
            parsed: dict[str, Any] = {}

            def _do_parsing() -> dict[str, Any]:
                general_chunks, table_descriptors, meta = _parse_document(pdf_path, document_key, settings)
                parsed["general_chunks"] = general_chunks
                parsed["table_descriptors"] = table_descriptors
                return meta

            parsing_meta = _run_step(conn, run_id, "parsing", _do_parsing)

            embedding_meta = _run_step(
                conn, run_id, "embedding",
                lambda: _embed_document(
                    conn, settings, rag_id, parsed["general_chunks"], parsed["table_descriptors"]
                ),
            )

            total_chunks = parsing_meta["general_chunk_count"] + parsing_meta["table_count"]
            with conn.cursor() as cur:
                cur.execute(sql("update_rag_document_chunk_count"), (total_chunks, rag_id))
            conn.commit()

        extraction_counts = _run_step(
            conn, run_id, "extraction",
            lambda: _run_extraction(conn, settings, llm, embed_model, rag_id, top_k),
        )
    except Exception as exc:
        conn.rollback()  # defensive: covers failures outside _run_step's own rollback
        _finish_run(conn, run_id, None, "failed", error=str(exc))
        raise

    _finish_run(conn, run_id, rag_id, "success")
    return {
        "run_id": run_id,
        "rag_id": rag_id,
        "skipped_ingest": skipped_ingest,
        "parsing": parsing_meta,
        "embedding": embedding_meta,
        "extraction_counts": extraction_counts,
    }
