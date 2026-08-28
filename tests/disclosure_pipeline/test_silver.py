from __future__ import annotations

import csv
from pathlib import Path

from disclosure_pipeline.bronze import ingest_bronze
from disclosure_pipeline.silver import transform_silver

HEADER = [
    "Property Id",
    "Property Name",
    "Parent Property Id",
    "Parent Property Name",
    "Year Ending",
    "NYC Building Identification Number (BIN)",
    "Address 1",
    "City",
    "Postal Code",
    "Borough",
    "Primary Property Type - Self Selected",
    "List of All Property Use Types at Property",
    "Largest Property Use Type",
    "Largest Property Use Type - Gross Floor Area (ft²)",
    "2nd Largest Property Use Type",
    "2nd Largest Property Use - Gross Floor Area (ft²)",
    "3rd Largest Property Use Type",
    "3rd Largest Property Use Type - Gross Floor Area (ft²)",
    "Property GFA - Self-Reported (ft²)",
    "Total GHG Emissions (Metric Tons CO2e)",
    "Direct GHG Emissions (Metric Tons CO2e)",
    "Indirect GHG Emissions (Metric Tons CO2e)",
    "Electricity Use - Grid Purchase (kWh)",
    "Natural Gas Use (kBtu)",
    "Fuel Oil #1 Use (kBtu)",
    "Fuel Oil #2 Use (kBtu)",
    "Fuel Oil #4 Use (kBtu)",
    "Fuel Oil #5 & 6 Use (kBtu)",
    "Diesel #2 Use (kBtu)",
    "Propane Use (kBtu)",
    "District Steam Use (kBtu)",
    "NYC Borough, Block and Lot (BBL)",
    "Submission Date",
]

_DEFAULTS = {h: "Not Available" for h in HEADER}
_DEFAULTS.update(
    {
        "Property Id": "1001",
        "Property Name": "Test Tower",
        "Parent Property Id": "Not Applicable: Standalone Property",
        "Year Ending": "12/31/2021",
        "Submission Date": "01/01/2022 12:00:00 AM",
        "NYC Borough, Block and Lot (BBL)": "1-00100-0001",
    }
)


def _row(**overrides: str) -> dict[str, str]:
    row = dict(_DEFAULTS)
    row.update(overrides)
    return row


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _paths(tmp_path: Path) -> tuple[str, str]:
    return str(tmp_path / "bronze"), str(tmp_path / "silver")


def test_transform_silver_normalizes_null_sentinel_to_null(spark, tmp_path):
    bronze_path, silver_path = _paths(tmp_path)
    _write_csv(tmp_path / "disclosures.csv", [_row()])
    ingest_bronze(spark, tmp_path / "disclosures.csv", bronze_path)

    transform_silver(spark, bronze_path, silver_path)

    row = spark.read.format("delta").load(silver_path).collect()[0]
    assert row["total_ghg_emissions_tons"] is None
    assert row["primary_property_type"] is None


def test_transform_silver_casts_numeric_columns(spark, tmp_path):
    bronze_path, silver_path = _paths(tmp_path)
    _write_csv(
        tmp_path / "disclosures.csv",
        [_row(**{"Total GHG Emissions (Metric Tons CO2e)": "123.4", "Property GFA - Self-Reported (ft²)": "50000"})],
    )
    ingest_bronze(spark, tmp_path / "disclosures.csv", bronze_path)

    transform_silver(spark, bronze_path, silver_path)

    row = spark.read.format("delta").load(silver_path).collect()[0]
    assert row["total_ghg_emissions_tons"] == 123.4
    assert row["gross_floor_area_ft"] == 50000.0


def test_transform_silver_dedups_keeping_latest_submission(spark, tmp_path):
    bronze_path, silver_path = _paths(tmp_path)
    _write_csv(
        tmp_path / "disclosures.csv",
        [
            _row(
                **{
                    "Total GHG Emissions (Metric Tons CO2e)": "Not Available",
                    "Submission Date": "03/01/2022 12:00:00 AM",
                }
            ),
            _row(
                **{
                    "Total GHG Emissions (Metric Tons CO2e)": "245.8",
                    "Submission Date": "07/21/2022 12:00:00 AM",
                }
            ),
        ],
    )
    ingest_bronze(spark, tmp_path / "disclosures.csv", bronze_path)

    transform_silver(spark, bronze_path, silver_path)

    df = spark.read.format("delta").load(silver_path)
    assert df.count() == 1
    assert df.collect()[0]["total_ghg_emissions_tons"] == 245.8


def test_transform_silver_normalizes_bbl_with_dashes_and_multi_lot(spark, tmp_path):
    bronze_path, silver_path = _paths(tmp_path)
    _write_csv(
        tmp_path / "disclosures.csv",
        [_row(**{"NYC Borough, Block and Lot (BBL)": "1-02235-0029;1-02235-0035"})],
    )
    ingest_bronze(spark, tmp_path / "disclosures.csv", bronze_path)

    transform_silver(spark, bronze_path, silver_path)

    row = spark.read.format("delta").load(silver_path).collect()[0]
    assert row["bbl"] == "1022350029"
    assert row["bbl_list"] == ["1022350029", "1022350035"]


def test_transform_silver_skips_when_bronze_unchanged(spark, tmp_path):
    bronze_path, silver_path = _paths(tmp_path)
    _write_csv(tmp_path / "disclosures.csv", [_row()])
    ingest_bronze(spark, tmp_path / "disclosures.csv", bronze_path)

    first = transform_silver(spark, bronze_path, silver_path)
    second = transform_silver(spark, bronze_path, silver_path)

    assert first["skipped"] is False
    assert second == {"skipped": True, "reason": "bronze unchanged since last transform"}


def test_transform_silver_reruns_when_bronze_changes(spark, tmp_path):
    bronze_path, silver_path = _paths(tmp_path)
    _write_csv(tmp_path / "disclosures.csv", [_row()])
    ingest_bronze(spark, tmp_path / "disclosures.csv", bronze_path)
    first = transform_silver(spark, bronze_path, silver_path)

    _write_csv(tmp_path / "disclosures.csv", [_row(**{"Property Name": "Updated Tower"})])
    ingest_bronze(spark, tmp_path / "disclosures.csv", bronze_path)
    second = transform_silver(spark, bronze_path, silver_path)

    assert second["skipped"] is False
    assert second["fingerprint"] != first["fingerprint"]
