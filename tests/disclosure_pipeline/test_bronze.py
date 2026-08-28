from __future__ import annotations

from pathlib import Path

from disclosure_pipeline.bronze import ingest_bronze

CSV_HEADER = "Property Id,Property Name,Year Ending,NYC Borough (BBL),Notes\n"


def _write_csv(path: Path, rows: list[str]) -> Path:
    path.write_text(CSV_HEADER + "\n".join(rows) + "\n")
    return path


def test_ingest_bronze_reads_all_columns_as_string_with_lineage_columns(spark, tmp_path):
    csv_path = _write_csv(
        tmp_path / "disclosures.csv",
        ['1001,Test Tower,12/31/2021,1-00123,"line one' + "\n" + 'line two, still notes"'],
    )
    bronze_path = str(tmp_path / "bronze" / "disclosures")

    result = ingest_bronze(spark, csv_path, bronze_path)

    assert result == {
        "skipped": False,
        "row_count": 1,
        "years_ingested": ["12/31/2021"],
        "source_hash": result["source_hash"],
    }
    df = spark.read.format("delta").load(bronze_path)
    row = df.collect()[0]
    assert row["Property_Id"] == "1001"
    assert row["year_ending"] == "12/31/2021"
    assert row["Notes"] == "line one\nline two, still notes"
    assert row["_source_file"] == "disclosures.csv"
    assert row["_source_file_hash"] == result["source_hash"]
    assert row["_ingested_at"] is not None


def test_ingest_bronze_sanitizes_column_names_with_spaces_and_special_chars(spark, tmp_path):
    csv_path = _write_csv(tmp_path / "disclosures.csv", ["1001,Test Tower,12/31/2021,1-00123,no notes"])
    bronze_path = str(tmp_path / "bronze" / "disclosures")

    ingest_bronze(spark, csv_path, bronze_path)

    df = spark.read.format("delta").load(bronze_path)
    assert "NYC_Borough_BBL" in df.columns
    for column in df.columns:
        assert " " not in column
        assert "(" not in column and ")" not in column


def test_ingest_bronze_skips_unchanged_source_file(spark, tmp_path):
    csv_path = _write_csv(tmp_path / "disclosures.csv", ["1001,Test Tower,12/31/2021,1-00123,no notes"])
    bronze_path = str(tmp_path / "bronze" / "disclosures")

    first = ingest_bronze(spark, csv_path, bronze_path)
    second = ingest_bronze(spark, csv_path, bronze_path)

    assert first["skipped"] is False
    assert second == {"skipped": True, "reason": "unchanged source file"}


def test_ingest_bronze_reingests_when_source_file_changes(spark, tmp_path):
    csv_path = _write_csv(tmp_path / "disclosures.csv", ["1001,Test Tower,12/31/2021,1-00123,no notes"])
    bronze_path = str(tmp_path / "bronze" / "disclosures")
    first = ingest_bronze(spark, csv_path, bronze_path)

    _write_csv(csv_path, ["1001,Test Tower,12/31/2021,1-00123,updated notes"])
    second = ingest_bronze(spark, csv_path, bronze_path)

    assert second["skipped"] is False
    assert second["source_hash"] != first["source_hash"]
    df = spark.read.format("delta").load(bronze_path)
    assert df.count() == 1
    assert df.collect()[0]["Notes"] == "updated notes"


def test_ingest_bronze_replaces_only_the_matching_year_partition(spark, tmp_path):
    csv_path_2021 = _write_csv(tmp_path / "disclosures_2021.csv", ["1001,Tower A,12/31/2021,1-001,n"])
    csv_path_2022 = _write_csv(tmp_path / "disclosures_2022.csv", ["2002,Tower B,12/31/2022,1-002,n"])
    bronze_path = str(tmp_path / "bronze" / "disclosures")

    ingest_bronze(spark, csv_path_2021, bronze_path)
    ingest_bronze(spark, csv_path_2022, bronze_path)

    df = spark.read.format("delta").load(bronze_path)
    years = sorted(r["year_ending"] for r in df.select("year_ending").distinct().collect())
    assert years == ["12/31/2021", "12/31/2022"]
    assert df.count() == 2
