from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    embed_model_hf_id: str = "nomic-ai/nomic-embed-text-v1"
    embed_dim: int = 768
    embed_max_tokens: int = 8192
