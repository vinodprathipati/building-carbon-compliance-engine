from __future__ import annotations

import os

from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession

from disclosure_pipeline.config import Settings


def get_spark_session(settings: Settings) -> SparkSession:
    # PySpark reads JAVA_HOME when it launches the JVM subprocess, so this
    # must be set before SparkSession creation. Local machines with a very
    # new default JDK (23+) break Spark's bundled Hadoop code — see README.
    if settings.java_home:
        os.environ["JAVA_HOME"] = settings.java_home

    builder = (
        SparkSession.builder.appName(settings.spark_app_name)
        .master("local[*]")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    )
    # configure_spark_with_delta_pip sets spark.jars.packages itself (to
    # Delta's own Maven coordinate) and OVERWRITES any prior value rather
    # than merging with it — a bare .config("spark.jars.packages", ...)
    # call before this line is silently discarded. Its extra_packages
    # parameter is the correct way to add the Postgres JDBC driver
    # alongside Delta (confirmed live: without this, spark.jars.packages
    # only ever resolved to Delta's jar, and any JDBC write failed with
    # java.lang.ClassNotFoundException: org.postgresql.Driver).
    spark = configure_spark_with_delta_pip(
        builder, extra_packages=["org.postgresql:postgresql:42.7.4"]
    ).getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark
