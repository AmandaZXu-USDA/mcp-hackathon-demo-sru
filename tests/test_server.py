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
