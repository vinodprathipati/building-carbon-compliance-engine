from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

# Portfolio Manager's standard null sentinel — appears across dozens of
# columns, not just the ones Silver types, so it's normalized generically
# rather than column by column.
_NULL_SENTINEL = "Not Available"

_BBL_COLUMN = "NYC_Borough_Block_and_Lot_BBL"

# Columns actually needed downstream (LL97 emissions/cap math in Gold —
# see the ll97-disclosure-csv-columns and ll97-emissions-calc-methodology
# notes). Everything else stays raw-only in Bronze; Silver is a narrow,
# typed, analysis-ready slice, not a full retype of all 253 columns.
_NUMERIC_COLUMNS = [
    "Property_GFA_Self_Reported_ft",
    "Largest_Property_Use_Type_Gross_Floor_Area_ft",
    "2nd_Largest_Property_Use_Gross_Floor_Area_ft",
    "3rd_Largest_Property_Use_Type_Gross_Floor_Area_ft",
    "Total_GHG_Emissions_Metric_Tons_CO2e",
    "Direct_GHG_Emissions_Metric_Tons_CO2e",
    "Indirect_GHG_Emissions_Metric_Tons_CO2e",
    "Electricity_Use_Grid_Purchase_kWh",
    "Natural_Gas_Use_kBtu",
    "Fuel_Oil_1_Use_kBtu",
    "Fuel_Oil_2_Use_kBtu",
    "Fuel_Oil_4_Use_kBtu",
    "Fuel_Oil_5_6_Use_kBtu",
    "Diesel_2_Use_kBtu",
    "Propane_Use_kBtu",
    "District_Steam_Use_kBtu",
]

# original bronze column -> clean, business-friendly Silver column name
_COLUMN_RENAMES = {
    "Property_Id": "property_id",
    "Property_Name": "property_name",
    "Parent_Property_Id": "parent_property_id",
    "Parent_Property_Name": "parent_property_name",
    "NYC_Building_Identification_Number_BIN": "bin",
    "Address_1": "address",
    "City": "city",
    "Postal_Code": "postal_code",
    "Borough": "borough",
    "Primary_Property_Type_Self_Selected": "primary_property_type",
    "List_of_All_Property_Use_Types_at_Property": "all_property_use_types",
    "Largest_Property_Use_Type": "largest_use_type",
    "Largest_Property_Use_Type_Gross_Floor_Area_ft": "largest_use_gfa_ft",
    "2nd_Largest_Property_Use_Type": "second_largest_use_type",
    "2nd_Largest_Property_Use_Gross_Floor_Area_ft": "second_largest_use_gfa_ft",
    "3rd_Largest_Property_Use_Type": "third_largest_use_type",
    "3rd_Largest_Property_Use_Type_Gross_Floor_Area_ft": "third_largest_use_gfa_ft",
    "Property_GFA_Self_Reported_ft": "gross_floor_area_ft",
    "Total_GHG_Emissions_Metric_Tons_CO2e": "total_ghg_emissions_tons",
    "Direct_GHG_Emissions_Metric_Tons_CO2e": "direct_ghg_emissions_tons",
    "Indirect_GHG_Emissions_Metric_Tons_CO2e": "indirect_ghg_emissions_tons",
    "Electricity_Use_Grid_Purchase_kWh": "electricity_use_kwh",
    "Natural_Gas_Use_kBtu": "natural_gas_use_kbtu",
    "Fuel_Oil_1_Use_kBtu": "fuel_oil_1_use_kbtu",
    "Fuel_Oil_2_Use_kBtu": "fuel_oil_2_use_kbtu",
    "Fuel_Oil_4_Use_kBtu": "fuel_oil_4_use_kbtu",
    "Fuel_Oil_5_6_Use_kBtu": "fuel_oil_5_6_use_kbtu",
    "Diesel_2_Use_kBtu": "diesel_2_use_kbtu",
    "Propane_Use_kBtu": "propane_use_kbtu",
    "District_Steam_Use_kBtu": "district_steam_use_kbtu",
    "year_ending": "year_ending",
}


def _normalize_null_sentinel(df: DataFrame) -> DataFrame:
    select_exprs = [
        F.when(F.col(c) == _NULL_SENTINEL, None).otherwise(F.col(c)).alias(c) for c in df.columns
    ]
    return df.select(*select_exprs)


def _dedup_latest_submission(df: DataFrame) -> DataFrame:
    # 283 Property Ids appear more than once in the source file — these are
    # amended filings (same building resubmitted later in the year), not
    # genuine duplicates. Empirically, the row with the later Submission
    # Date is always the corrected one, whether the earlier row was
    # "Not Available" or just an outdated real value. See
    # ll97-disclosure-csv-columns memory for the empirical breakdown.
    window = Window.partitionBy("Property_Id").orderBy(F.desc("submission_ts"))
    return (
        df.withColumn("submission_ts", F.to_timestamp("Submission_Date", "MM/dd/yyyy hh:mm:ss a"))
        .withColumn("_dedup_rank", F.row_number().over(window))
        .filter(F.col("_dedup_rank") == 1)
        .drop("_dedup_rank", "submission_ts")
    )


def _normalize_bbl(df: DataFrame) -> DataFrame:
    # A property can span multiple tax lots — the source column is then a
    # ";"-separated list of BBLs (e.g. "1-02235-0029;1-02235-0035"). Keep
    # the full normalized list plus a single `bbl` (first lot) for simple
    # one-column joins.
    segments = F.split(F.col(_BBL_COLUMN), ";")
    normalized_list = F.transform(segments, lambda x: F.regexp_replace(x, "-", ""))
    return df.withColumn("bbl_list", normalized_list).withColumn("bbl", F.element_at("bbl_list", 1))


def _cast_numeric_columns(df: DataFrame) -> DataFrame:
    # try_cast, not cast: beyond "Not Available" (already nulled out above),
    # Portfolio Manager fills unmeasurable numeric fields with other
    # free-text placeholders too (e.g. "Insufficient access" on utility
    # columns) — treat anything non-numeric as null rather than trying to
    # enumerate every placeholder string it might use.
    for column in _NUMERIC_COLUMNS:
        df = df.withColumn(column, F.expr(f"try_cast(`{column}` as double)"))
    return df


def _bronze_fingerprint(bronze_df: DataFrame) -> str:
    hashes = sorted(r["_source_file_hash"] for r in bronze_df.select("_source_file_hash").distinct().collect())
    return ",".join(hashes)


def _already_transformed(spark: SparkSession, silver_path: str, fingerprint: str) -> bool:
    if not DeltaTable.isDeltaTable(spark, silver_path):
        return False
    existing = spark.read.format("delta").load(silver_path)
    return existing.filter(F.col("_bronze_fingerprint") == fingerprint).limit(1).count() > 0


def transform_silver(spark: SparkSession, bronze_path: str, silver_path: str) -> dict[str, Any]:
    """Clean and type the Bronze disclosure table into an analysis-ready
    Silver table: null-sentinel normalization, dedup of amended filings,
    BBL normalization, and numeric casting for the columns Gold needs.

    Idempotent against the current Bronze snapshot: skips the transform if
    Silver already reflects the exact set of source files currently in
    Bronze (a `_bronze_fingerprint` — the sorted, joined set of Bronze's
    distinct `_source_file_hash` values).
    """
    bronze_df = spark.read.format("delta").load(bronze_path)
    fingerprint = _bronze_fingerprint(bronze_df)

    if _already_transformed(spark, silver_path, fingerprint):
        return {"skipped": True, "reason": "bronze unchanged since last transform"}

    df = _normalize_null_sentinel(bronze_df)
    df = _dedup_latest_submission(df)
    df = _normalize_bbl(df)
    df = _cast_numeric_columns(df)

    select_exprs = [F.col(original).alias(clean) for original, clean in _COLUMN_RENAMES.items()]
    df = df.select(*select_exprs, "bbl", "bbl_list")
    df = (
        df.withColumn("_bronze_fingerprint", F.lit(fingerprint))
        .withColumn("_silver_transformed_at", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    row_count = df.count()

    df.write.format("delta").mode("overwrite").partitionBy("year_ending").save(silver_path)

    return {"skipped": False, "row_count": row_count, "fingerprint": fingerprint}
