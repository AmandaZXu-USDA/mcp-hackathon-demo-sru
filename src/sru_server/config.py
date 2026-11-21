"""Server configuration loaded from environment variables or a .env file.

On Databricks Apps, these values are injected from app resources declared in
databricks.yml via `valueFrom` in app.yaml.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MCP server settings. Override any field via environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Transport ─────────────────────────────────────────────────────────────
    mcp_transport: str = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    # ── SRU Syntax Agent ──────────────────────────────────────────────────────
    serving_endpoint: str = "mas-c8629507-endpoint"
    agent_timeout_seconds: int = 300
    model_service: str = ""
    mlflow_experiment_id: str = ""

    # ── Function first (SQL warehouse) ────────────────────────────────────────
    # The tool and page run the governed UC function on this warehouse first and
    # ask the agent only if that call fails. Empty: always ask the agent.
    sql_warehouse_id: str = ""
    function_wait_timeout: str = "40s"  # SQL API wait (5s-50s), then fall back


settings = Settings()
