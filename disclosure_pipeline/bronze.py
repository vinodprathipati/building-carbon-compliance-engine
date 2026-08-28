from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

# Parquet/Delta column names must be storage-safe. Rather than denylisting
# characters one at a time as source columns turn up new ones (space, "()",
# "/", "²" have all shown up in this CSV), allowlist alphanumerics and
# collapse every run of anything else to a single underscore.
_INVALID_COL_CHARS = re.compile(r"[^A-Za-z0-9]+")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sanitize_columns(df: DataFrame) -> DataFrame:
    for original in df.columns:
        clean = _INVALID_COL_CHARS.sub("_", original).strip("_")
        if clean != original:
            df = df.withColumnRenamed(original, clean)
    return df


def _already_ingested(spark: SparkSession, bronze_path: str, source_hash: str) -> bool:
    if not DeltaTable.isDeltaTable(spark, bronze_path):
        return False
    existing = spark.read.format("delta").load(bronze_path)
    return existing.filter(F.col("_source_file_hash") == source_hash).limit(1).count() > 0


def ingest_bronze(spark: SparkSession, csv_path: Path, bronze_path: str) -> dict[str, Any]:
    """Read the raw disclosure CSV as-is — every column as string, no schema
    inference — into the Bronze Delta table. Bronze preserves source
    fidelity exactly; typing/cleanup belongs in Silver, not here.

    Partitioned by year_ending, taken from the CSV's own "Year Ending"
    column (source-faithful, not asserted by the caller). Idempotent: skips
    re-ingesting an unchanged source file; a changed file replaces just the
    partitions its rows belong to (other years' data is untouched).
    """
    source_hash = file_hash(csv_path)

    if _already_ingested(spark, bronze_path, source_hash):
        return {"skipped": True, "reason": "unchanged source file"}

    # multiLine + explicit escape: several free-text columns (contact notes,
    # explanations) contain embedded commas/newlines inside quoted fields.
    # Without multiLine, Spark's CSV reader splits those onto extra "rows"
    # and every column after the break shifts — Year Ending silently fills
    # with garbage from unrelated columns instead of erroring.
    df = (
        spark.read.option("header", True)
        .option("inferSchema", False)
        .option("multiLine", "true")
        .option("escape", '"')
        .csv(str(csv_path))
    )
    df = _sanitize_columns(df)
    df = (
        df.withColumnRenamed("Year_Ending", "year_ending")
        .withColumn("_source_file", F.lit(csv_path.name))
        .withColumn("_source_file_hash", F.lit(source_hash))
        .withColumn("_ingested_at", F.lit(datetime.now(timezone.utc).isoformat()))
        .withColumn("_source_row_number", F.monotonically_increasing_id())
    )

    distinct_years = [r["year_ending"] for r in df.select("year_ending").distinct().collect()]
    non_null_years = sorted(y for y in distinct_years if y is not None)
    has_null_year = any(y is None for y in distinct_years)

    predicate_parts = []
    if non_null_years:
        predicate_parts.append("year_ending IN ({})".format(", ".join(f"'{y}'" for y in non_null_years)))
    if has_null_year:
        predicate_parts.append("year_ending IS NULL")
    replace_predicate = " OR ".join(predicate_parts)
    years_present = non_null_years + (["<null>"] if has_null_year else [])

    row_count = df.count()

    (
        df.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", replace_predicate)
        .partitionBy("year_ending")
        .save(bronze_path)
    )

    return {
        "skipped": False,
        "row_count": row_count,
        "years_ingested": years_present,
        "source_hash": source_hash,
    }
