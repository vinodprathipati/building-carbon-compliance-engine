from disclosure_pipeline.config import Settings


def _settings(database_url: str = "postgresql://postgres:postgres@localhost:5432/cra_dev") -> Settings:
    return Settings(database_url=database_url)


def test_jdbc_url_derived_from_database_url():
    assert _settings().jdbc_url == "jdbc:postgresql://localhost:5432/cra_dev"


def test_jdbc_user_and_password_derived_from_database_url():
    settings = _settings()
    assert settings.jdbc_user == "postgres"
    assert settings.jdbc_password == "postgres"


def test_jdbc_url_with_different_host_and_db_name():
    settings = _settings("postgresql://alice:secret@db.internal:5433/warehouse")
    assert settings.jdbc_url == "jdbc:postgresql://db.internal:5433/warehouse"
    assert settings.jdbc_user == "alice"
    assert settings.jdbc_password == "secret"
