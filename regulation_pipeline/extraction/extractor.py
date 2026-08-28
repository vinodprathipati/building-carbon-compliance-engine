from __future__ import annotations

from typing import Any

import psycopg
from sentence_transformers import SentenceTransformer

from regulation_pipeline.db.queries import sql
from regulation_pipeline.extraction.json_utils import extract_json
from regulation_pipeline.extraction.llm_provider import AnthropicProvider
from regulation_pipeline.extraction.prompts import (
    SYSTEM_PROMPT,
    build_document_jurisdiction_prompt,
    build_prose_extraction_prompt,
    build_single_table_match_prompt,
)
from regulation_pipeline.extraction.retriever import CandidateChunk, embed_query, search_chunks
from regulation_pipeline.extraction.schema import ConceptSchema, label_field

DEFAULT_TOP_K = 8
MATCH_MAX_TOKENS = 512
# A dense chunk's JSON output expands well past its source size once every
# field (jurisdiction, both period years, value, unit, and a duplicated
# extracted_quote) is spelled out per record — a 3.2KB source chunk of
# packed property-type entries hit this limit and got truncated mid-JSON
# at 4096. Sized with headroom for the largest dense chunks seen so far.
PROSE_MAX_TOKENS = 8192
JURISDICTION_MAX_TOKENS = 128
JURISDICTION_SAMPLE_CHUNKS = 3


def infer_document_jurisdiction(conn: psycopg.Connection, llm: AnthropicProvider, rag_id: int) -> str | None:
    """Infer a document's jurisdiction once, from its opening pages, rather
    than re-guessing it per candidate during extraction.

    Asking each table/prose candidate to infer jurisdiction from its own
    narrow local context is unreliable — many candidates simply don't
    happen to mention the municipality nearby, even though the document as
    a whole clearly does (in its title/letterhead). That per-candidate
    approach was measured to return a placeholder or null on the majority
    of records. A single call over the document's opening pages is both
    cheaper and more accurate; every extracted record for this rag_id
    should be stamped with this one value.
    """
    with conn.cursor() as cur:
        cur.execute(sql("select_early_chunks_text"), (rag_id, JURISDICTION_SAMPLE_CHUNKS))
        rows = cur.fetchall()
    full_text = "\n---\n".join(r[0] for r in rows if r[0])
    if not full_text:
        return None

    prompt = build_document_jurisdiction_prompt(full_text)
    response = llm.messages_create(
        messages=[{"role": "user", "content": prompt}], max_tokens=JURISDICTION_MAX_TOKENS, system=SYSTEM_PROMPT
    )
    parsed = extract_json(response.text)
    if isinstance(parsed, dict):
        jurisdiction = parsed.get("jurisdiction")
        if isinstance(jurisdiction, str) and jurisdiction.strip():
            return jurisdiction.strip()
    return None


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


def _extract_matched_table_rows(
    conn: psycopg.Connection,
    llm: AnthropicProvider,
    concept: ConceptSchema,
    rag_id: int,
    candidates: list[CandidateChunk],
) -> list[dict[str, Any]]:
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


def _extract_from_prose_candidate(
    llm: AnthropicProvider, concept: ConceptSchema, candidate: CandidateChunk
) -> list[dict[str, Any]]:
    """Extract every match from ONE candidate chunk. Isolating to one
    candidate per call, rather than batching several into one prompt,
    avoids the same reliability failure mode already fixed for table
    matching (_classify_candidate): a single call over multiple candidates
    was measured to under-report — e.g. correctly extracting every record
    from one dense chunk while silently skipping a second chunk sitting in
    the same batch."""
    prompt = build_prose_extraction_prompt(concept, [candidate])
    response = llm.messages_create(
        messages=[{"role": "user", "content": prompt}], max_tokens=PROSE_MAX_TOKENS, system=SYSTEM_PROMPT
    )
    try:
        parsed = extract_json(response.text)
    except ValueError:
        # A malformed/truncated response for one candidate shouldn't abort
        # extraction for every other candidate — skip it and keep going,
        # same as a table candidate that fails classification.
        print(f"WARNING: unparsable extraction response for chunk_id={candidate.chunk_id}, skipping")
        return []
    return parsed.get("records", []) if isinstance(parsed, dict) else []


def extract_table_concept(
    conn: psycopg.Connection,
    llm: AnthropicProvider,
    embed_model: SentenceTransformer,
    concept: ConceptSchema,
    rag_id: int,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Table-shaped concepts usually live inside a Docling-detected table,
    but the same fact can also turn up as prose in a different document
    (e.g. FuelCoefficient's 2030-2034 utility exceptions live in a dense
    paragraph in RCNY 103-14, not a table — confirmed by direct inspection,
    not assumption). Route each retrieved candidate by its own block_type
    rather than assuming every candidate for a "table" concept is a table;
    non-table candidates would otherwise be silently discarded."""
    query_embedding = embed_query(embed_model, concept.retrieval_hint)
    candidates = search_chunks(conn, rag_id, query_embedding, top_k)
    table_candidates = [c for c in candidates if c.block_type == "table"]
    prose_candidates = [c for c in candidates if c.block_type != "table"]

    records: list[dict[str, Any]] = []
    if table_candidates:
        records.extend(_extract_matched_table_rows(conn, llm, concept, rag_id, table_candidates))
    for candidate in prose_candidates:
        records.extend(_extract_from_prose_candidate(llm, concept, candidate))
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
    try:
        parsed = extract_json(response.text)
    except ValueError:
        print(f"WARNING: unparsable extraction response for rag_id={rag_id}, concept={concept.name}, skipping")
        return []
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
