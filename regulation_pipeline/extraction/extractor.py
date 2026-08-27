from __future__ import annotations

from typing import Any

import psycopg
from sentence_transformers import SentenceTransformer

from regulation_pipeline.db.queries import sql
from regulation_pipeline.extraction.json_utils import extract_json
from regulation_pipeline.extraction.llm_provider import AnthropicProvider
from regulation_pipeline.extraction.prompts import (
    SYSTEM_PROMPT,
    build_prose_extraction_prompt,
    build_single_table_match_prompt,
)
from regulation_pipeline.extraction.retriever import CandidateChunk, embed_query, search_chunks
from regulation_pipeline.extraction.schema import ConceptSchema, label_field

DEFAULT_TOP_K = 8
MATCH_MAX_TOKENS = 512
PROSE_MAX_TOKENS = 4096


def _classify_candidate(
    llm: AnthropicProvider, concept: ConceptSchema, candidate: CandidateChunk
) -> dict[str, Any] | None:
    """Ask about exactly one candidate. Returns the match dict if it's a genuine match, else None.

    Classifying one candidate per call, rather than asking for every match across a whole
    candidate list in one call, is deliberate: batch classification over several
    similar-looking table candidates (e.g. continuation tables of the same period) was
    measured to under-report — the model doesn't reliably judge every item in a long,
    lookalike-heavy list. One focused yes/no question per candidate doesn't have that
    failure mode.
    """
    prompt = build_single_table_match_prompt(concept, candidate)
    response = llm.messages_create(
        messages=[{"role": "user", "content": prompt}], max_tokens=MATCH_MAX_TOKENS, system=SYSTEM_PROMPT
    )
    parsed = extract_json(response.text)
    if isinstance(parsed, dict) and parsed.get("is_match"):
        return parsed
    return None


def extract_table_concept(
    conn: psycopg.Connection,
    llm: AnthropicProvider,
    embed_model: SentenceTransformer,
    concept: ConceptSchema,
    rag_id: int,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    query_embedding = embed_query(embed_model, concept.retrieval_hint)
    candidates = [c for c in search_chunks(conn, rag_id, query_embedding, top_k) if c.block_type == "table"]
    if not candidates:
        return []

    matched: list[tuple[CandidateChunk, dict[str, Any]]] = []
    for candidate in candidates:
        match = _classify_candidate(llm, concept, candidate)
        if match is not None:
            matched.append((candidate, match))

    label_field_id = label_field(concept).id
    records: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for candidate, match in matched:
            cur.execute(
                sql("select_document_table_rows"),
                (rag_id, candidate.chunk_id),
            )
            row = cur.fetchone()
            if row is None:
                continue
            for table_row in row[0]:
                label = table_row.get(match["label_column"])
                value = table_row.get(match["value_column"])
                if label is None or value is None:
                    continue
                records.append(
                    {
                        label_field_id: label,
                        "value": value,
                        "jurisdiction": match["jurisdiction"],
                        "period_start": match["period_start"],
                        "period_end": match["period_end"],
                        "unit": match["unit"],
                        "chunk_id": candidate.chunk_id,
                    }
                )
    return records


def extract_prose_concept(
    conn: psycopg.Connection,
    llm: AnthropicProvider,
    embed_model: SentenceTransformer,
    concept: ConceptSchema,
    rag_id: int,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    query_embedding = embed_query(embed_model, concept.retrieval_hint)
    candidates = search_chunks(conn, rag_id, query_embedding, top_k)
    if not candidates:
        return []

    prompt = build_prose_extraction_prompt(concept, candidates)
    response = llm.messages_create(
        messages=[{"role": "user", "content": prompt}], max_tokens=PROSE_MAX_TOKENS, system=SYSTEM_PROMPT
    )
    parsed = extract_json(response.text)
    return parsed.get("records", []) if isinstance(parsed, dict) else []


def extract_concept(
    conn: psycopg.Connection,
    llm: AnthropicProvider,
    embed_model: SentenceTransformer,
    concept: ConceptSchema,
    rag_id: int,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    if concept.extraction_method == "table":
        return extract_table_concept(conn, llm, embed_model, concept, rag_id, top_k)
    return extract_prose_concept(conn, llm, embed_model, concept, rag_id, top_k)
