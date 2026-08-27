import json
from decimal import Decimal
from unittest.mock import MagicMock

from regulation_pipeline.extraction.persist import (
    STORE_FUNCS,
    store_concept_records,
    store_covered_building_rules,
    store_emissions_factors,
    store_fuel_coefficients,
    store_penalty_rules,
)


def _conn_and_cursor():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_store_emissions_factors_inserts_with_on_conflict_do_nothing():
    conn, cursor = _conn_and_cursor()
    records = [
        {
            "property_type": "Office",
            "value": "0.00758",
            "jurisdiction": "New York City",
            "period_start": 2024,
            "period_end": 2029,
            "unit": "tCO2e/sf",
            "chunk_id": 47,
        }
    ]

    skipped = store_emissions_factors(conn, rag_id=6, model_name="claude-haiku-4-5-20251001", records=records)

    sql, params = cursor.execute.call_args.args
    assert "insert into emissions_factors" in sql
    assert "on conflict (rag_id, jurisdiction, property_type, period_start, period_end) do nothing" in sql
    assert params == (
        6, 47, "New York City", "Office", 2024, 2029, Decimal("0.00758"), "tCO2e/sf", None,
        "claude-haiku-4-5-20251001",
    )
    conn.commit.assert_called_once()
    assert skipped == []


def test_store_emissions_factors_skips_malformed_multi_value_cell():
    # Real case found on 1_RCNY_103-14.pdf page 46: two source rows merged
    # into one during table-structure detection, leaving two space-separated
    # numbers in a single value cell.
    conn, cursor = _conn_and_cursor()
    records = [
        {
            "property_type": "Urgent Care/Clinic/Other Outpatient Vocational School",
            "value": "0.004329281 0.003459842",
            "jurisdiction": "New York City",
            "period_start": 2035,
            "period_end": 2039,
            "unit": "tCO2e/sf",
            "chunk_id": 52,
        },
        {
            "property_type": "Office",
            "value": "0.00758",
            "jurisdiction": "New York City",
            "period_start": 2024,
            "period_end": 2029,
            "unit": "tCO2e/sf",
            "chunk_id": 47,
        },
    ]

    skipped = store_emissions_factors(conn, rag_id=6, model_name="m", records=records)

    assert cursor.execute.call_count == 1  # only the valid record was inserted
    assert len(skipped) == 1
    assert skipped[0].record["chunk_id"] == 52
    assert "value" in skipped[0].reason
    conn.commit.assert_called_once()  # still commits the valid inserts


def test_store_fuel_coefficients_skips_record_missing_required_jurisdiction():
    # Real case found on 1_RCNY_103-14.pdf's general combustion-fuel table:
    # the LLM couldn't confidently infer jurisdiction from that candidate's
    # surrounding context and correctly returned null rather than guessing —
    # which must not crash the whole batch.
    conn, cursor = _conn_and_cursor()
    records = [
        {
            "fuel_type": "Butane",
            "value": "0.00006502",
            "jurisdiction": None,
            "period_start": None,
            "period_end": None,
            "unit": "tCO2e per kBtu",
            "chunk_id": 39,
        },
        {
            "fuel_type": "Natural Gas",
            "value": "0.00005311",
            "jurisdiction": "New York City",
            "period_start": 2024,
            "period_end": 2029,
            "unit": "tCO2e/kBtu",
            "chunk_id": 55,
        },
    ]

    skipped = store_fuel_coefficients(conn, rag_id=6, model_name="m", records=records)

    assert cursor.execute.call_count == 1  # only the valid record was inserted
    assert len(skipped) == 1
    assert skipped[0].record["chunk_id"] == 39
    assert "jurisdiction" in skipped[0].reason
    conn.commit.assert_called_once()


def test_store_fuel_coefficients_inserts_correct_columns():
    conn, cursor = _conn_and_cursor()
    records = [
        {
            "fuel_type": "Natural Gas",
            "value": "0.00005311",
            "jurisdiction": "New York City",
            "period_start": 2024,
            "period_end": 2029,
            "unit": "tCO2e/kBtu",
            "chunk_id": 55,
        }
    ]

    store_fuel_coefficients(conn, rag_id=6, model_name="m", records=records)

    sql, params = cursor.execute.call_args.args
    assert "insert into fuel_coefficients" in sql
    assert params[3] == "Natural Gas"  # fuel_type in the fuel_type column slot
    conn.commit.assert_called_once()


def test_store_penalty_rules_defaults_missing_periods_to_none():
    conn, cursor = _conn_and_cursor()
    records = [
        {
            "jurisdiction": "New York City",
            "rule_type": "excess_emissions",
            "rate": 268,
            "rate_unit": "$/tCO2e",
            "formula_description": "desc",
            "chunk_id": 237,
            "extracted_quote": "quote",
        }
    ]

    store_penalty_rules(conn, rag_id=7, model_name="m", records=records)

    sql, params = cursor.execute.call_args.args
    assert "insert into penalty_rules" in sql
    assert "on conflict (rag_id, chunk_id, jurisdiction, rule_type) do nothing" in sql
    assert params == (7, 237, "New York City", "excess_emissions", None, None, Decimal("268"), "$/tCO2e", "desc", "quote", "m")
    conn.commit.assert_called_once()


def test_store_covered_building_rules_serializes_exceptions_as_json():
    conn, cursor = _conn_and_cursor()
    records = [
        {
            "jurisdiction": "New York City",
            "threshold_type": "single_building",
            "threshold_sf": 25000,
            "aggregation_rule": None,
            "exceptions": ["Rent regulated accommodation.", "Religious house of worship."],
            "chunk_id": 250,
        }
    ]

    store_covered_building_rules(conn, rag_id=7, model_name="m", records=records)

    sql, params = cursor.execute.call_args.args
    assert "insert into covered_building_rules" in sql
    assert json.loads(params[6]) == ["Rent regulated accommodation.", "Religious house of worship."]
    conn.commit.assert_called_once()


def test_store_covered_building_rules_handles_missing_exceptions():
    conn, cursor = _conn_and_cursor()
    records = [
        {
            "jurisdiction": "New York City",
            "threshold_type": "single_building",
            "threshold_sf": 25000,
            "chunk_id": 250,
        }
    ]

    store_covered_building_rules(conn, rag_id=7, model_name="m", records=records)

    _, params = cursor.execute.call_args.args
    assert params[6] is None


def test_store_concept_records_dispatches_by_concept_name():
    conn, cursor = _conn_and_cursor()
    records = [
        {
            "jurisdiction": "New York City",
            "rule_type": "late_filing",
            "rate": 0.5,
            "rate_unit": "$/sf/month",
            "chunk_id": 240,
        }
    ]

    skipped = store_concept_records(conn, "PenaltyRule", rag_id=7, model_name="m", records=records)

    sql, _ = cursor.execute.call_args.args
    assert "insert into penalty_rules" in sql
    assert skipped == []


def test_store_funcs_covers_all_four_concepts():
    assert set(STORE_FUNCS) == {
        "EmissionsFactor",
        "FuelCoefficient",
        "PenaltyRule",
        "CoveredBuildingRule",
    }
