"""Configuration settings for Auto PR Control Plane."""

from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration settings."""

    model_config = SettingsConfigDict(
        env_prefix="AUTO_PR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./auto_pr.db",
        description="Async SQLAlchemy database URL (SQLite or PostgreSQL)",
    )
    db_echo: bool = Field(
        default=False,
        description="Echo SQL queries for debugging",
    )

    # Workflow & Retries
    max_retries: int = Field(
        default=3,
        description="Maximum retry attempts before human escalation",
    )
    workflow_timeout_seconds: int = Field(
        default=900,
        description="Global timeout for an entire workflow run in seconds",
    )

    # Sandbox Configuration
    sandbox_type: Literal["worktree", "docker"] = Field(
        default="worktree",
        description="Preferred sandbox execution engine: docker or worktree",
    )
    worktree_root: Path = Field(
        default=Path(".auto_pr_worktrees"),
        description="Base directory for isolated git worktrees",
    )
    execution_timeout_seconds: int = Field(
        default=120,
        description="Timeout for individual subprocess/container validation commands",
    )

    # Security & Redaction
    redact_secrets: bool = Field(
        default=True,
        description="Whether to redact detected secrets from logs, prompts, and audit records",
    )
    extra_secret_keys: list[str] = Field(
        default_factory=lambda: [
            "TOKEN",
            "SECRET",
            "PASSWORD",
            "API_KEY",
            "PRIVATE_KEY",
            "AUTH",
            "ACCESS_KEY",
        ],
        description="Key name fragments to automatically redact in payloads",
    )

    # Model Provider
    llm_provider: Literal["mock", "gemini", "openai"] = Field(
        default="mock",
        description="Model provider implementation to use",
    )
    gemini_api_key: str | None = Field(
        default=None,
        description="Google Gemini API key",
    )
    model_name: str = Field(
        default="gemini-2.5-flash",
        description="Default LLM model name",
    )


settings = Settings()
