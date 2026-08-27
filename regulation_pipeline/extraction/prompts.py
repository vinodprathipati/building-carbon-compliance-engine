from __future__ import annotations

from regulation_pipeline.extraction.retriever import CandidateChunk
from regulation_pipeline.extraction.schema import ConceptSchema, label_field

SYSTEM_PROMPT = (
    "You are a precise municipal building-regulation data extraction AI. "
    "Follow all extraction instructions exactly. "
    "Only extract values explicitly stated in the provided text — never guess, infer, or derive a value. "
    "Always return valid JSON with no explanation text outside the JSON object."
)


def _candidate_blocks(candidates: list[CandidateChunk], *, use_full_text: bool) -> str:
    parts = []
    for c in candidates:
        text = c.full_text if use_full_text else c.raw_text
        parts.append(f"[chunk_id={c.chunk_id} page={c.page_number}]\n{text}")
    return "\n---\n".join(parts)


def build_single_table_match_prompt(concept: ConceptSchema, candidate: CandidateChunk) -> str:
    label = label_field(concept)
    column_headers = candidate.chunk_meta.get("column_headers") or []
    columns_line = ", ".join(repr(h) for h in column_headers if h) or "(none listed)"
    return (
        f"You are checking whether ONE table found in a regulation document matches a data concept.\n\n"
        f"CONCEPT: {concept.name} — {concept.description}\n\n"
        f"The candidate below describes one table (its section heading, an intro sentence, and its "
        f"column headers — not the row data). It may be a continuation of a larger table split across "
        f"multiple PDF pages — treat a continuation (same period and {label.display_name.lower()} "
        f"category as another such table, just a different page/row range) as a match the same as any "
        f"other genuine match.\n\n"
        f"CANDIDATE:\n[chunk_id={candidate.chunk_id} page={candidate.page_number}]\n{candidate.full_text}\n\n"
        f"This table's column headers, exactly as detected: {columns_line}\n\n"
        f"Rules:\n"
        f'- Return a JSON object with key "is_match" (boolean).\n'
        f"- If is_match is true, also include: jurisdiction (string, inferred from the surrounding text), "
        f"label_column (string, copied EXACTLY from the column headers listed above — the one holding "
        f"each row's category/label), value_column (string, copied EXACTLY from the column headers "
        f"listed above — the one holding each row's numeric value), period_start (integer), period_end "
        f"(integer), unit (string, exactly as shown in the value column header).\n"
        f'- If is_match is false, return only {{"is_match": false}}.\n'
        f"- Return ONLY the JSON object. No explanation text outside the JSON.\n"
    )


def build_prose_extraction_prompt(concept: ConceptSchema, candidates: list[CandidateChunk]) -> str:
    field_lines = []
    for field in concept.fields:
        line = f"  - {field.id} ({field.data_type}{', required' if field.required else ''}): {field.description}"
        if field.allowed_values:
            line += f" [allowed: {', '.join(field.allowed_values)}]"
        field_lines.append(line)
    field_definitions = "\n".join(field_lines)

    return (
        f"Extract every {concept.name} from the document excerpts below.\n\n"
        f"CONCEPT: {concept.description}\n\n"
        f"Each record has these fields:\n{field_definitions}\n\n"
        f"Every record must also include:\n"
        f"  - chunk_id (integer): which excerpt's chunk_id this record was extracted from.\n"
        f"  - extracted_quote (string): the exact sentence or clause this record was extracted from, verbatim.\n\n"
        f"EXCERPTS:\n{_candidate_blocks(candidates, use_full_text=False)}\n\n"
        f"Rules:\n"
        f'- Return a JSON object: {{"records": [...]}}.\n'
        f"- Use null for any field not explicitly stated in the text.\n"
        f'- If nothing in the text matches this concept, return {{"records": []}}.\n'
        f"- Return ONLY the JSON object. No explanation text outside the JSON.\n"
    )
