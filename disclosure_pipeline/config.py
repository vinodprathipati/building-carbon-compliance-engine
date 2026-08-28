from __future__ import annotations

from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    java_home: str = ""
    spark_app_name: str = "disclosure_pipeline"
    lake_root: str = "data/lake"

    @property
    def jdbc_url(self) -> str:
        parsed = urlparse(self.database_url)
        return f"jdbc:postgresql://{parsed.hostname}:{parsed.port}{parsed.path}"

    @property
    def jdbc_user(self) -> str:
        return urlparse(self.database_url).username or ""

    @property
    def jdbc_password(self) -> str:
        return urlparse(self.database_url).password or ""
