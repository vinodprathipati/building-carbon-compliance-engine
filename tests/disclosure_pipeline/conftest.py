from __future__ import annotations

import pytest

from disclosure_pipeline.config import Settings
from disclosure_pipeline.spark_session import get_spark_session


@pytest.fixture(scope="session")
def spark():
    settings = Settings(database_url="postgresql://unused:unused@localhost:5432/unused")
    session = get_spark_session(settings)
    yield session
    session.stop()
