from __future__ import annotations

from pathlib import Path

from regulation_pipeline.extraction.retriever import CandidateChunk
from regulation_pipeline.extraction.schema import ConceptSchema, label_field
from regulation_pipeline.text_blocks import load_named_blocks

TEMPLATES_PATH = Path(__file__).resolve().parent / "prompt_templates.txt"


def _template(name: str) -> str:
    return load_named_blocks(TEMPLATES_PATH)[name]


SYSTEM_PROMPT = _template("system_prompt")


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
    return _template("table_match").format(
        concept_name=concept.name,
        concept_description=concept.description,
        label_display_name=label.display_name.lower(),
        chunk_id=candidate.chunk_id,
        page_number=candidate.page_number,
        full_text=candidate.full_text,
        columns_line=columns_line,
    )


def build_prose_extraction_prompt(concept: ConceptSchema, candidates: list[CandidateChunk]) -> str:
    field_lines = []
    for field in concept.fields:
        line = f"  - {field.id} ({field.data_type}{', required' if field.required else ''}): {field.description}"
        if field.allowed_values:
            line += f" [allowed: {', '.join(field.allowed_values)}]"
        field_lines.append(line)
    field_definitions = "\n".join(field_lines)

    return _template("prose_extraction").format(
        concept_name=concept.name,
        concept_description=concept.description,
        field_definitions=field_definitions,
        candidate_blocks=_candidate_blocks(candidates, use_full_text=False),
    )
