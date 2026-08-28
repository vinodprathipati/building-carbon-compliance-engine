"""Run the full disclosure_pipeline: Bronze -> Silver -> Gold, for the NYC
LL97 disclosure CSV.

    python scripts/run_disclosure_pipeline.py

Requires regulation_pipeline's extraction tables (fuel_coefficients,
emissions_factors, penalty_rules, covered_building_rules) and
covered_buildings to already be populated — run
scripts/run_regulation_pipeline.py and scripts/load_covered_buildings_list.py
first.
"""

from __future__ import annotations

from pathlib import Path

from disclosure_pipeline.bronze import ingest_bronze
from disclosure_pipeline.config import Settings
from disclosure_pipeline.gold import run_gold
from disclosure_pipeline.silver import transform_silver
from disclosure_pipeline.spark_session import get_spark_session

CSV_PATH = Path("data/disclosures/nyc_ll97_building_disclosure.csv")


def main() -> None:
    settings = Settings()
    spark = get_spark_session(settings)

    bronze_path = f"{settings.lake_root}/bronze/nyc_ll97_disclosures"
    silver_path = f"{settings.lake_root}/silver/nyc_ll97_disclosures"

    print("=== Bronze ===")
    print(ingest_bronze(spark, CSV_PATH, bronze_path))

    print("\n=== Silver ===")
    print(transform_silver(spark, bronze_path, silver_path))

    print("\n=== Gold ===")
    print(run_gold(spark, settings))

    spark.stop()
    print("\nDone.")


if __name__ == "__main__":
    main()
