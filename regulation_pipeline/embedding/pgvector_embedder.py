from __future__ import annotations

import json

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from regulation_pipeline.chunking.docling_hybrid_chunker import Chunk
from regulation_pipeline.chunking.table_extractor import TableDescriptor, to_chunk
from regulation_pipeline.config import Settings

SEARCH_DOCUMENT_PREFIX = "search_document: "


def get_connection(settings: Settings) -> psycopg.Connection:
    conn = psycopg.connect(settings.database_url)
    register_vector(conn)
    return conn


def embed_chunks(model_name: str, chunks: list[Chunk]) -> list[list[float]]:
    model = SentenceTransformer(model_name, trust_remote_code=True)
    texts = [SEARCH_DOCUMENT_PREFIX + chunk.full_text for chunk in chunks]
    return model.encode(texts, normalize_embeddings=True).tolist()


def store_chunks(
    conn: psycopg.Connection,
    rag_id: int,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    model_name: str,
) -> None:
    with conn.cursor() as cur:
        for chunk, embedding in zip(chunks, embeddings):
            cur.execute(
                """
                insert into document_chunks
                    (rag_id, chunk_id, document_key, page_number, block_type,
                     section, section_path, raw_text, full_text, chunk_meta)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rag_id,
                    chunk.chunk_id,
                    chunk.document_key,
                    chunk.page_number,
                    chunk.block_type,
                    chunk.section,
                    chunk.section_path,
                    chunk.raw_text,
                    chunk.full_text,
                    json.dumps(chunk.chunk_meta),
                ),
            )
            cur.execute(
                """
                insert into chunk_embeddings (rag_id, chunk_id, embedding, model_name)
                values (%s, %s, %s, %s)
                """,
                (rag_id, chunk.chunk_id, embedding, model_name),
            )
    conn.commit()


def embed_and_store(
    conn: psycopg.Connection,
    settings: Settings,
    rag_id: int,
    chunks: list[Chunk],
) -> None:
    embeddings = embed_chunks(settings.embed_model_hf_id, chunks)
    store_chunks(conn, rag_id, chunks, embeddings, settings.embed_model_hf_id)


def store_document_tables(
    conn: psycopg.Connection,
    rag_id: int,
    descriptors: list[TableDescriptor],
) -> None:
    with conn.cursor() as cur:
        for descriptor in descriptors:
            cur.execute(
                """
                insert into document_tables
                    (rag_id, table_ref, chunk_id, page_number, caption, column_headers, rows)
                values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rag_id,
                    descriptor.table_ref,
                    descriptor.chunk_id,
                    descriptor.page_number,
                    descriptor.caption,
                    json.dumps(descriptor.column_headers),
                    json.dumps(descriptor.rows),
                ),
            )
    conn.commit()


def embed_and_store_tables(
    conn: psycopg.Connection,
    settings: Settings,
    rag_id: int,
    descriptors: list[TableDescriptor],
) -> None:
    chunks = [to_chunk(descriptor) for descriptor in descriptors]
    embed_and_store(conn, settings, rag_id, chunks)
    store_document_tables(conn, rag_id, descriptors)
