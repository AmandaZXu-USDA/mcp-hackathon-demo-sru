"""Smoke tests for the NAL SRU Syntax MCP server.

These verify the server imports and every submodule registers without error.
"""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from sru_server.app import mcp
from sru_server.config import settings


def test_server_is_importable():
    assert mcp is not None


def test_server_has_name():
    assert mcp.name == "mcp-sru-syntax"


def test_default_transport_is_stdio():
    """Guard against accidentally shipping with a non-stdio default."""
    assert settings.mcp_transport == "stdio"


def test_tools_register_without_error():
    from sru_server.tools import register_tools

    register_tools(FastMCP("test"))  # must not raise


def test_routes_register_without_error():
    from sru_server.routes import register_routes

    register_routes(FastMCP("test"))  # must not raise


@pytest.mark.asyncio
async def test_build_sru_search_url_is_discoverable():
    """The build_sru_search_url tool should be registered and discoverable."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert "build_sru_search_url" in tool_names


def test_allowed_origins_from_env(monkeypatch):
    """Genie Code calls /mcp from the workspace URL, so it must be allowed."""
    from sru_server.app import _allowed_origins

    monkeypatch.setenv("DATABRICKS_HOST", "dbc-example.cloud.databricks.com/")
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://a.example.com/ ,")
    assert _allowed_origins() == [
        "https://dbc-example.cloud.databricks.com",
        "https://a.example.com",
    ]
    monkeypatch.delenv("DATABRICKS_HOST")
    monkeypatch.delenv("ALLOWED_ORIGINS")
    assert _allowed_origins() == []


def test_get_mcp_returns_405_immediately():
    """Stateless mode has no SSE stream; GET /mcp must not hang."""
    from starlette.testclient import TestClient

    from sru_server.app import app

    # No `with`: middleware answers before the MCP session manager, whose
    # lifespan can only run once per process.
    client = TestClient(app)
    response = client.get("/mcp", headers={"Accept": "text/event-stream"})
    assert response.status_code == 405


def test_cors_preflight_refuses_unknown_origin():
    from starlette.testclient import TestClient

    from sru_server.app import app

    client = TestClient(app)  # no lifespan needed; CORS middleware answers
    response = client.options(
        "/mcp",
        headers={
            "Origin": "https://not-allowed.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in response.headers
