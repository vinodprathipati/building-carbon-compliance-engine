from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from sentence_transformers import SentenceTransformer

SEARCH_QUERY_PREFIX = "search_query: "


@dataclass
class CandidateChunk:
    chunk_id: int
    page_number: int | None
    block_type: str | None
    section: str | None
    raw_text: str
    full_text: str
    chunk_meta: dict[str, Any]
    similarity: float


def embed_query(model: SentenceTransformer, query: str) -> list[float]:
    return model.encode([SEARCH_QUERY_PREFIX + query], normalize_embeddings=True)[0].tolist()


def search_chunks(
    conn: psycopg.Connection,
    rag_id: int,
    query_embedding: list[float],
    top_k: int = 8,
) -> list[CandidateChunk]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select dc.chunk_id, dc.page_number, dc.block_type, dc.section, dc.raw_text, dc.full_text,
                   dc.chunk_meta, 1 - (ce.embedding <=> %s::vector) as similarity
            from chunk_embeddings ce
            join document_chunks dc using (rag_id, chunk_id)
            where ce.rag_id = %s
            order by ce.embedding <=> %s::vector
            limit %s
            """,
            (query_embedding, rag_id, query_embedding, top_k),
        )
        return [
            CandidateChunk(
                chunk_id=row[0],
                page_number=row[1],
                block_type=row[2],
                section=row[3],
                raw_text=row[4],
                full_text=row[5],
                chunk_meta=row[6],
                similarity=row[7],
            )
            for row in cur.fetchall()
        ]
