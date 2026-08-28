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
        .config("spark.jars.packages", "org.postgresql:postgresql:42.7.4")
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark
