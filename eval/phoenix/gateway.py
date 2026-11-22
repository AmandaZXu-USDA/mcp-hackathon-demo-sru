"""Databricks serving endpoints as an OpenAI-compatible model gateway.

The agent-under-test and the LLM judges call Databricks Foundation Model endpoints at
``<workspace>/serving-endpoints`` with an OpenAI client. Credentials come from the
environment (the repo-root ``.env``), resolved by the Databricks SDK in this order of
preference: ``DATABRICKS_HOST`` + ``DATABRICKS_TOKEN``, ``DATABRICKS_HOST`` +
``DATABRICKS_CLIENT_ID`` + ``DATABRICKS_CLIENT_SECRET`` (OAuth M2M), or
``DATABRICKS_CONFIG_PROFILE``.
"""

from __future__ import annotations

import os
from functools import lru_cache

from databricks.sdk.core import Config

DEFAULT_AGENT_MODEL = "databricks-gpt-5-6-luna"
DEFAULT_JUDGE_MODEL = "databricks-claude-sonnet-4-6"

# Variables that select Databricks credentials. If none is set, the parent process got
# its credentials some other way (for example a notebook's runtime auth) and the server
# subprocess is given a host and a token explicitly.
_CREDENTIAL_VARS = (
    "DATABRICKS_TOKEN",
    "DATABRICKS_CLIENT_ID",
    "DATABRICKS_CONFIG_PROFILE",
)


@lru_cache(maxsize=1)
def _config() -> Config:
    return Config()


def base_url() -> str:
    """OpenAI-compatible base URL of the workspace's serving endpoints."""
    return _config().host.rstrip("/") + "/serving-endpoints"


def api_key() -> str:
    """A bearer token for the serving endpoints (OAuth tokens last about an hour)."""
    header = _config().authenticate()["Authorization"]
    return header.split(" ", 1)[1]


def agent_model() -> str:
    """Serving endpoint that drives the agent-under-test."""
    return os.getenv("AGENT_MODEL") or DEFAULT_AGENT_MODEL


def judge_model() -> str:
    """Serving endpoint the LLM judges use (keep it different from the agent's)."""
    return os.getenv("JUDGE_MODEL") or DEFAULT_JUDGE_MODEL


def reasoning_effort(model: str) -> str | None:
    """Reasoning effort to send with the agent's requests, or None to send none.

    GPT-5 endpoints reject function tools on chat completions unless reasoning is
    off, and only accept ``temperature=0`` with ``reasoning_effort="none"``.
    ``AGENT_REASONING_EFFORT`` overrides the default; set it empty to send nothing.
    """
    value = os.getenv("AGENT_REASONING_EFFORT")
    if value is not None:
        return value or None
    return "none" if "gpt-5" in model else None


def server_env(setting_names: set[str]) -> dict[str, str]:
    """Environment for the MCP server subprocess.

    The MCP stdio transport gives a server only a few "safe" variables (PATH, HOME,
    ...) unless ``env`` is set, so the server would start without credentials. Pass
    the Databricks credentials and the server's own settings (``setting_names``,
    upper case), and nothing else: in particular not the harness's AGENT_MODEL,
    which the deployed app also uses.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("DATABRICKS_") or key in setting_names
    }
    if not any(key in env for key in _CREDENTIAL_VARS):
        env["DATABRICKS_HOST"] = _config().host
        env["DATABRICKS_TOKEN"] = api_key()
    return env
