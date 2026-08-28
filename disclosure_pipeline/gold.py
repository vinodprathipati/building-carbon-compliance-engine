from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg
from pyspark.sql import SparkSession
from pyspark.sql.types import DoubleType, IntegerType, StringType, StructField, StructType

from disclosure_pipeline.config import Settings

# Silver column -> canonical fuel_coefficients.fuel_type (see
# regulation_pipeline's extraction_fields.json for the canonical list).
# fuel_oil_5_6 is deliberately omitted: no confirmed LL97 coefficient
# mapping exists for it yet — the closest candidate is RCNY's "Other Oil
# (> 401 deg F)", but that's an inference, not a confirmed statutory
# mapping (see the ll97-disclosure-csv-columns memory).
FUEL_COLUMN_TO_TYPE = {
    "electricity_use_kwh": "Grid Electricity",
    "natural_gas_use_kbtu": "Natural Gas",
    "fuel_oil_1_use_kbtu": "Distillate Fuel Oil No. 1",
    "fuel_oil_2_use_kbtu": "Fuel Oil #2",
    "fuel_oil_4_use_kbtu": "Fuel Oil #4",
    "diesel_2_use_kbtu": "Diesel",
    "propane_use_kbtu": "Propane",
    "district_steam_use_kbtu": "District Steam",
}

PENALTY_RULE_TYPE = "excess_emissions"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    return d if d.is_finite() else None


def _pick_period_row(rows: list[dict], period_start: int, period_end: int) -> dict | None:
    """Pick the coefficient/cap row that applies to a target period.

    Order of preference:
    1. A row whose own [period_start, period_end] contains the target period.
    2. A null-period row (meaning "applies uniformly across all periods"
       per the schema's documented semantics — some fuel-coefficient
       tables aren't organized by compliance period at all).
    3. The most recent period-scoped row that ends before the target
       period starts — a carry-forward fallback for periods the source
       regulation hasn't set a coefficient for yet (e.g. electricity/gas
       coefficients are only codified through 2034 as of this writing;
       2035-2039 and 2040-2049 caps already exist, but DOB hasn't
       published updated utility coefficients for them). Reusing the most
       recent known coefficient is far closer to correct than silently
       treating that fuel's contribution as zero, which is what happens
       if this fallback isn't applied.
    """
    scoped = [
        r
        for r in rows
        if r["period_start"] is not None and r["period_start"] <= period_start and r["period_end"] >= period_end
    ]
    if scoped:
        return scoped[0]

    unscoped = [r for r in rows if r["period_start"] is None]
    if unscoped:
        return unscoped[0]

    prior = [r for r in rows if r["period_end"] is not None and r["period_end"] < period_start]
    if prior:
        return max(prior, key=lambda r: r["period_end"])

    return None


def is_building_covered(
    building: dict[str, Any], covered_threshold_sf: Decimal | None, is_on_covered_list: bool
) -> bool:
    """A building's BBL being on DOF's own covered_buildings list is the
    primary signal; the GFA > statutory threshold check is only a fallback
    for BBLs not on that list (format mismatches, new construction, etc.).
    """
    if is_on_covered_list:
        return True
    gfa = _to_decimal(building.get("gross_floor_area_ft"))
    return covered_threshold_sf is not None and gfa is not None and gfa > covered_threshold_sf


def compute_actual_emissions(
    building: dict[str, Any], coefficients_by_fuel: dict[str, list[dict]], period_start: int, period_end: int
) -> Decimal:
    """Actual emissions = Σ(fuel use × LL97's own coefficient for that
    fuel, for the target period) — not the disclosure CSV's own reported
    Total GHG Emissions column, which uses a different (EPA/eGRID)
    methodology."""
    total = Decimal(0)
    for column, fuel_type in FUEL_COLUMN_TO_TYPE.items():
        usage = _to_decimal(building.get(column))
        if not usage:
            continue
        rows = coefficients_by_fuel.get(fuel_type)
        if not rows:
            continue
        matched = _pick_period_row(rows, period_start, period_end)
        if matched is None:
            continue
        total += usage * matched["value"]
    return total


def compute_emissions_cap(
    property_type: str | None,
    gross_floor_area_ft: Any,
    caps_by_property_type: dict[str, list[dict]],
    period_start: int,
    period_end: int,
) -> Decimal | None:
    """Cap = gross floor area × the property type's per-sf cap rate for
    the target period. Returns None when property_type has no matching
    row in emissions_factors at all — this is what naturally happens for
    a literal "Mixed Use Property" self-selection (RCNY's cap table has no
    such entry; the real methodology blends caps across each use type per
    Equation 103-14.1, not yet implemented) or any other unmapped type,
    rather than silently guessing a wrong number.
    """
    if not property_type:
        return None
    rows = caps_by_property_type.get(property_type)
    if not rows:
        return None
    matched = _pick_period_row(rows, period_start, period_end)
    if matched is None:
        return None
    gfa = _to_decimal(gross_floor_area_ft)
    if gfa is None:
        return None
    return gfa * matched["value"]


def compute_compliance_projection(
    building: dict[str, Any],
    coefficients_by_fuel: dict[str, list[dict]],
    caps_by_property_type: dict[str, list[dict]],
    penalty_rate: Decimal | None,
    periods: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    """One compliance/penalty projection row per compliance period, for one
    COVERED building (callers must filter with is_building_covered() first
    — Gold only stores rows for covered buildings). Flat carry-forward: the
    building's single reported year of fuel usage is held constant and
    compared against each period's own (stricter) cap.
    """
    results: list[dict[str, Any]] = []
    for period_start, period_end in periods:
        actual = compute_actual_emissions(building, coefficients_by_fuel, period_start, period_end)
        cap = compute_emissions_cap(
            building.get("primary_property_type"), building.get("gross_floor_area_ft"), caps_by_property_type,
            period_start, period_end,
        )

        if cap is None:
            status, excess, penalty = "cap_unavailable", None, None
        else:
            excess = max(Decimal(0), actual - cap)
            status = "compliant" if excess == 0 else "exceeds"
            penalty = (excess * penalty_rate) if penalty_rate is not None else None

        results.append(
            {
                "period_start": period_start,
                "period_end": period_end,
                "status": status,
                "cap_tco2e": cap,
                "actual_emissions_tco2e": actual,
                "excess_emissions_tco2e": excess,
                "penalty_rate_usd_per_ton": penalty_rate,
                "potential_penalty_usd": penalty,
            }
        )
    return results


# --------------------------------------------------------------------------
# Reference-data loaders (Postgres -> plain Python; these tables are small —
# a few hundred rows total — so it's simplest to fully load them once
# rather than query per building).
# --------------------------------------------------------------------------


def load_fuel_coefficients(conn: psycopg.Connection, jurisdiction: str) -> dict[str, list[dict]]:
    by_fuel: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fuel_type, value, period_start, period_end FROM fuel_coefficients WHERE jurisdiction = %s",
            (jurisdiction,),
        )
        for fuel_type, value, period_start, period_end in cur.fetchall():
            by_fuel.setdefault(fuel_type, []).append(
                {"value": Decimal(value), "period_start": period_start, "period_end": period_end}
            )
    return by_fuel


def load_emissions_caps(conn: psycopg.Connection, jurisdiction: str) -> dict[str, list[dict]]:
    by_type: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT property_type, value, period_start, period_end FROM emissions_factors WHERE jurisdiction = %s",
            (jurisdiction,),
        )
        for property_type, value, period_start, period_end in cur.fetchall():
            by_type.setdefault(property_type, []).append(
                {"value": Decimal(value), "period_start": period_start, "period_end": period_end}
            )
    return by_type


def load_penalty_rate(
    conn: psycopg.Connection, jurisdiction: str, rule_type: str = PENALTY_RULE_TYPE
) -> Decimal | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT rate FROM penalty_rules WHERE jurisdiction = %s AND rule_type = %s LIMIT 1",
            (jurisdiction, rule_type),
        )
        row = cur.fetchone()
    return Decimal(row[0]) if row else None


def load_covered_building_threshold(conn: psycopg.Connection, jurisdiction: str) -> Decimal | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT threshold_sf FROM covered_building_rules "
            "WHERE jurisdiction = %s AND threshold_type = 'single_building' LIMIT 1",
            (jurisdiction,),
        )
        row = cur.fetchone()
    return Decimal(row[0]) if row else None


def load_covered_bbls(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT bbl FROM covered_buildings")
        return {row[0] for row in cur.fetchall()}


def load_compliance_periods(conn: psycopg.Connection, jurisdiction: str) -> list[tuple[int, int]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT period_start, period_end FROM emissions_factors WHERE jurisdiction = %s "
            "ORDER BY period_start",
            (jurisdiction,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


# --------------------------------------------------------------------------
# Orchestration: Silver rows (plain dicts) + reference data -> flat Gold
# rows. Kept Spark-independent so it's directly testable; the Spark
# wrapper below just collects Silver to plain dicts and calls this.
# --------------------------------------------------------------------------


def build_gold_rows(
    buildings: list[dict[str, Any]],
    coefficients_by_fuel: dict[str, list[dict]],
    caps_by_property_type: dict[str, list[dict]],
    penalty_rate: Decimal | None,
    periods: list[tuple[int, int]],
    covered_threshold_sf: Decimal | None,
    covered_bbls: set[str],
) -> list[dict[str, Any]]:
    """One row per (covered building, compliance period). Buildings that
    aren't covered are omitted entirely — Gold only stores projections for
    buildings actually subject to LL97."""
    rows: list[dict[str, Any]] = []
    for building in buildings:
        is_on_list = building.get("bbl") in covered_bbls
        if not is_building_covered(building, covered_threshold_sf, is_on_list):
            continue
        for projection in compute_compliance_projection(
            building, coefficients_by_fuel, caps_by_property_type, penalty_rate, periods
        ):
            rows.append(
                {
                    "property_id": building.get("property_id"),
                    "bbl": building.get("bbl"),
                    "property_name": building.get("property_name"),
                    "borough": building.get("borough"),
                    "primary_property_type": building.get("primary_property_type"),
                    "gross_floor_area_ft": building.get("gross_floor_area_ft"),
                    "year_ending": building.get("year_ending"),
                    "reported_emissions_tco2e": building.get("total_ghg_emissions_tons"),
                    **projection,
                }
            )
    return rows


GOLD_SCHEMA = StructType(
    [
        StructField("property_id", StringType(), True),
        StructField("bbl", StringType(), True),
        StructField("property_name", StringType(), True),
        StructField("borough", StringType(), True),
        StructField("primary_property_type", StringType(), True),
        StructField("gross_floor_area_ft", DoubleType(), True),
        StructField("year_ending", StringType(), True),
        StructField("period_start", IntegerType(), True),
        StructField("period_end", IntegerType(), True),
        StructField("status", StringType(), True),
        StructField("cap_tco2e", DoubleType(), True),
        StructField("actual_emissions_tco2e", DoubleType(), True),
        StructField("reported_emissions_tco2e", DoubleType(), True),
        StructField("excess_emissions_tco2e", DoubleType(), True),
        StructField("penalty_rate_usd_per_ton", DoubleType(), True),
        StructField("potential_penalty_usd", DoubleType(), True),
    ]
)

_DECIMAL_COLUMNS = (
    "gross_floor_area_ft",
    "cap_tco2e",
    "actual_emissions_tco2e",
    "reported_emissions_tco2e",
    "excess_emissions_tco2e",
    "penalty_rate_usd_per_ton",
    "potential_penalty_usd",
)


def _to_jdbc_row(row: dict[str, Any]) -> dict[str, Any]:
    # Decimal -> float for Spark/JDBC. Gold is a serving/analytics table,
    # not a ledger — double precision is more than sufficient here, and
    # Spark's createDataFrame doesn't accept Decimal against a DoubleType
    # schema.
    out = dict(row)
    for key in _DECIMAL_COLUMNS:
        value = out.get(key)
        if isinstance(value, Decimal):
            out[key] = float(value)
    return out


def run_gold(spark: SparkSession, settings: Settings, jurisdiction: str = "New York City") -> dict[str, Any]:
    """Read disclosure_pipeline Silver + regulation_pipeline's Postgres
    reference tables, compute per-building-per-period compliance
    projections for every covered building, and write the result to
    gold_building_compliance_projections (full overwrite each run — the
    table is small enough, ~24k covered buildings x 4 periods, that a
    full rebuild is simpler and safer than incremental upserts)."""
    silver_path = f"{settings.lake_root}/silver/nyc_ll97_disclosures"
    buildings = [row.asDict() for row in spark.read.format("delta").load(silver_path).collect()]

    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(dsn)
    try:
        coefficients_by_fuel = load_fuel_coefficients(conn, jurisdiction)
        caps_by_property_type = load_emissions_caps(conn, jurisdiction)
        penalty_rate = load_penalty_rate(conn, jurisdiction)
        covered_threshold_sf = load_covered_building_threshold(conn, jurisdiction)
        covered_bbls = load_covered_bbls(conn)
        periods = load_compliance_periods(conn, jurisdiction)
    finally:
        conn.close()

    rows = build_gold_rows(
        buildings, coefficients_by_fuel, caps_by_property_type, penalty_rate, periods, covered_threshold_sf,
        covered_bbls,
    )
    jdbc_rows = [_to_jdbc_row(r) for r in rows]

    gold_df = spark.createDataFrame(jdbc_rows, schema=GOLD_SCHEMA)
    (
        gold_df.write.format("jdbc")
        .option("url", settings.jdbc_url)
        .option("dbtable", "gold_building_compliance_projections")
        .option("user", settings.jdbc_user)
        .option("password", settings.jdbc_password)
        .option("driver", "org.postgresql.Driver")
        .option("truncate", "true")
        .mode("overwrite")
        .save()
    )

    return {
        "buildings_evaluated": len(buildings),
        "buildings_covered": len({r["property_id"] for r in rows}),
        "rows_written": len(rows),
    }
