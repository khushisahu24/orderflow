"""Application settings read from environment variables.

Every variable uses the ORDERFLOW_ prefix. A local `.env` file is read when
present; see `.env.example`. Real values never belong in the repository.
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORDERFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        description="SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@host:5432/orderflow",
    )
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=30, ge=1, le=24 * 60)
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
