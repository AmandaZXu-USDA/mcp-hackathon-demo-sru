"""Tool registration aggregator. One file per tool."""

from sru_server.tools.build_sru_url import register as register_build_sru_url


def register_tools(mcp) -> None:
    """Register all MCP tools with the server."""
    register_build_sru_url(mcp)
