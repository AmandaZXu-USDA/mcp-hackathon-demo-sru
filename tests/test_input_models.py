"""Tests for the Pydantic input model of build_sru_search_url (sru_server.models).

No Databricks credentials or network access: invalid titles are rejected before any
function or agent call, and the schema test only lists tools.
"""

from __future__ import annotations

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from sru_server.app import mcp
from sru_server.models import MAX_TITLE_CHARS, BuildSruSearchUrlInput, is_valid_title
from sru_server.tools import build_sru_url as tool


def test_model_accepts_a_title_and_keeps_it_exactly():
    title = "  Correction to \u201cA title\u201d  "
    assert BuildSruSearchUrlInput(correction_title=title).correction_title == title


def test_model_accepts_a_title_at_the_limit():
    assert is_valid_title("x" * MAX_TITLE_CHARS)


@pytest.mark.parametrize(
    "value",
    ["", "   ", "x" * (MAX_TITLE_CHARS + 1), None, 42, ["Correction: a"]],
)
def test_model_rejects_blank_long_or_non_text(value):
    with pytest.raises(ValidationError):
        BuildSruSearchUrlInput(correction_title=value)
    assert not is_valid_title(value)


def test_model_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        BuildSruSearchUrlInput(correction_title="Correction: a", url="https://x")


async def test_schema_shows_description_and_limits():
    tools = {t.name: t for t in await mcp.list_tools()}
    schema = tools["build_sru_search_url"].inputSchema
    prop = schema["properties"]["correction_title"]
    assert schema["required"] == ["correction_title"]
    assert prop["type"] == "string"
    assert prop["minLength"] == 1 and prop["maxLength"] == MAX_TITLE_CHARS
    assert "exactly as given" in prop["description"]


@pytest.mark.parametrize("title", ["   ", "x" * (MAX_TITLE_CHARS + 1)])
async def test_tool_maps_model_errors_to_invalid_input(monkeypatch, title):
    def must_not_run(*args, **kwargs):
        raise AssertionError("no lookup for an invalid title")

    monkeypatch.setattr(tool, "_sru_lookup", must_not_run)
    with pytest.raises(ToolError, match=r"\(error invalid_input, id [0-9a-f]{12}\)$"):
        await mcp.call_tool("build_sru_search_url", {"correction_title": title})
