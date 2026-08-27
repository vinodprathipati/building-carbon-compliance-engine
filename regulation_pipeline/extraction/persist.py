from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg

from regulation_pipeline.db.queries import sql


@dataclass
class SkippedRecord:
    record: dict[str, Any]
    reason: str


def _to_decimal(value: Any) -> Decimal | None:
    """Parse a single numeric value. Rejects anything that isn't cleanly one
    number — e.g. a malformed cell like "0.004329281 0.003459842" (two values
    concatenated, seen on a real table where two source rows got merged into
    one during table-structure detection)."""
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _missing_required_text_fields(record: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    """Required (NOT NULL) text/enum columns the LLM may still return as null
    or omit entirely when it can't confidently determine them from a given
    candidate's context — seen live (a table's surrounding text wasn't
    enough to pin down jurisdiction). Checked generically here rather than
    one column at a time as each one turns up in practice."""
    return [f for f in fields if record.get(f) is None]


def store_emissions_factors(
    conn: psycopg.Connection, rag_id: int, model_name: str, records: list[dict[str, Any]]
) -> list[SkippedRecord]:
    skipped: list[SkippedRecord] = []
    with conn.cursor() as cur:
        for record in records:
            missing = _missing_required_text_fields(
                record, ("jurisdiction", "property_type", "period_start", "period_end", "unit")
            )
            value = _to_decimal(record.get("value"))
            if value is None:
                missing.append("value")
            if missing:
                skipped.append(SkippedRecord(record, f"missing/invalid required field(s): {missing}"))
                continue
            cur.execute(
                sql("insert_emissions_factor"),
                (
                    rag_id,
                    record["chunk_id"],
                    record["jurisdiction"],
                    record["property_type"],
                    record["period_start"],
                    record["period_end"],
                    value,
                    record["unit"],
                    record.get("extracted_quote"),
                    model_name,
                ),
            )
    conn.commit()
    return skipped


def store_fuel_coefficients(
    conn: psycopg.Connection, rag_id: int, model_name: str, records: list[dict[str, Any]]
) -> list[SkippedRecord]:
    skipped: list[SkippedRecord] = []
    with conn.cursor() as cur:
        for record in records:
            missing = _missing_required_text_fields(record, ("jurisdiction", "fuel_type", "unit"))
            value = _to_decimal(record.get("value"))
            if value is None:
                missing.append("value")
            if missing:
                skipped.append(SkippedRecord(record, f"missing/invalid required field(s): {missing}"))
                continue
            cur.execute(
                sql("insert_fuel_coefficient"),
                (
                    rag_id,
                    record["chunk_id"],
                    record["jurisdiction"],
                    record["fuel_type"],
                    record.get("period_start"),
                    record.get("period_end"),
                    value,
                    record["unit"],
                    record.get("extracted_quote"),
                    model_name,
                ),
            )
    conn.commit()
    return skipped


def store_penalty_rules(
    conn: psycopg.Connection, rag_id: int, model_name: str, records: list[dict[str, Any]]
) -> list[SkippedRecord]:
    skipped: list[SkippedRecord] = []
    with conn.cursor() as cur:
        for record in records:
            missing = _missing_required_text_fields(record, ("jurisdiction", "rule_type", "rate_unit"))
            rate = _to_decimal(record.get("rate"))
            if rate is None:
                missing.append("rate")
            if missing:
                skipped.append(SkippedRecord(record, f"missing/invalid required field(s): {missing}"))
                continue
            cur.execute(
                sql("insert_penalty_rule"),
                (
                    rag_id,
                    record["chunk_id"],
                    record["jurisdiction"],
                    record["rule_type"],
                    record.get("period_start"),
                    record.get("period_end"),
                    rate,
                    record["rate_unit"],
                    record.get("formula_description"),
                    record.get("extracted_quote"),
                    model_name,
                ),
            )
    conn.commit()
    return skipped


def store_covered_building_rules(
    conn: psycopg.Connection, rag_id: int, model_name: str, records: list[dict[str, Any]]
) -> list[SkippedRecord]:
    skipped: list[SkippedRecord] = []
    with conn.cursor() as cur:
        for record in records:
            missing = _missing_required_text_fields(record, ("jurisdiction", "threshold_type"))
            threshold_sf = _to_decimal(record.get("threshold_sf"))
            if threshold_sf is None:
                missing.append("threshold_sf")
            if missing:
                skipped.append(SkippedRecord(record, f"missing/invalid required field(s): {missing}"))
                continue
            exceptions = record.get("exceptions")
            cur.execute(
                sql("insert_covered_building_rule"),
                (
                    rag_id,
                    record["chunk_id"],
                    record["jurisdiction"],
                    record["threshold_type"],
                    threshold_sf,
                    record.get("aggregation_rule"),
                    json.dumps(exceptions) if exceptions is not None else None,
                    record.get("extracted_quote"),
                    model_name,
                ),
            )
    conn.commit()
    return skipped


STORE_FUNCS = {
    "EmissionsFactor": store_emissions_factors,
    "FuelCoefficient": store_fuel_coefficients,
    "PenaltyRule": store_penalty_rules,
    "CoveredBuildingRule": store_covered_building_rules,
}


def store_concept_records(
    conn: psycopg.Connection,
    concept_name: str,
    rag_id: int,
    model_name: str,
    records: list[dict[str, Any]],
) -> list[SkippedRecord]:
    return STORE_FUNCS[concept_name](conn, rag_id, model_name, records)
