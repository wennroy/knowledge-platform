"""Application configuration via Pydantic Settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Reads from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Gateway / LLM
    GATEWAY_BASE_URL: str = "http://localhost:8080/v1"
    GATEWAY_API_KEY: str = ""

    # Models
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    CHAT_MODEL: str = "claude-sonnet-4-5"
    EMBEDDING_DIM: int = 1536

    # Local paths
    LANCEDB_PATH: str = "./data/lancedb"
    VAULT_PATH: str = "./vault"

    # Chunking
    CHUNK_TOKENS: int = 512
    CHUNK_OVERLAP: int = 64

    # Retrieval
    RETRIEVE_TOPK: int = 8

    # Logging
    LOG_LEVEL: str = "INFO"

    # Upload limits
    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024  # 50MB

    # Extension whitelist
    ALLOWED_EXTENSIONS: tuple[str, ...] = (
        ".pdf",
        ".docx",
        ".pptx",
        ".ppt",
        ".xlsx",
        ".xls",
        ".md",
        ".txt",
    )

    def lancedb_path(self) -> Path:
        return Path(self.LANCEDB_PATH).expanduser().resolve()

    def vault_path(self) -> Path:
        return Path(self.VAULT_PATH).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
