from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "schema" / "extraction_fields.json"


@dataclass
class FieldSpec:
    id: str
    display_name: str
    data_type: str
    required: bool
    description: str
    allowed_values: list[str] | None = None


@dataclass
class ConceptSchema:
    name: str
    description: str
    extraction_method: str
    retrieval_hint: str
    natural_key: list[str]
    fields: list[FieldSpec]


_STANDARD_TABLE_FIELDS = {"jurisdiction", "period_start", "period_end", "value", "unit"}


def label_field(concept: ConceptSchema) -> FieldSpec:
    """The one concept-specific field on a 'table' concept — its per-row category/label
    (e.g. property_type on EmissionsFactor, fuel_type on FuelCoefficient)."""
    for field in concept.fields:
        if field.id not in _STANDARD_TABLE_FIELDS:
            return field
    raise ValueError(f"concept {concept.name!r} has no label field for table extraction")


def load_schema(path: Path = DEFAULT_SCHEMA_PATH) -> dict[str, ConceptSchema]:
    data = json.loads(Path(path).read_text())
    concepts: dict[str, ConceptSchema] = {}
    for name, concept in data["concepts"].items():
        fields = [
            FieldSpec(
                id=f["id"],
                display_name=f["displayName"],
                data_type=f["dataType"],
                required=f.get("required", False),
                description=f["description"],
                allowed_values=f.get("allowedValues"),
            )
            for f in concept["fields"]
        ]
        concepts[name] = ConceptSchema(
            name=name,
            description=concept["description"],
            extraction_method=concept["extractionMethod"],
            retrieval_hint=concept["retrievalHint"],
            natural_key=concept["naturalKey"],
            fields=fields,
        )
    return concepts
