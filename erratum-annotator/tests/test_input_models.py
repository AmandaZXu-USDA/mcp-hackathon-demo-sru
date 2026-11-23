"""Tests for the Pydantic input models of the mcp-erratum-note tools (mcp_server/erratum_inputs.py).

Run from the erratum-annotator folder:  python -m pytest tests -q
No workspace access: only model validation, tools/list and argument errors raised before any volume read.
"""
import asyncio
import re
import sys
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mcp_server"))
import app  # noqa: E402
import erratum_inputs as models  # noqa: E402

TOOLS = {t.name: t for t in asyncio.run(app.mcp.list_tools())}
ERROR_TAIL = re.compile(r"\[error invalid_input, id [0-9a-f]{8}\]$")


@pytest.mark.parametrize("name", sorted(set(TOOLS) - {"health"}))
def test_every_argument_has_a_description_and_a_length_limit(name):
    props = TOOLS[name].inputSchema["properties"]
    assert props
    for field, prop in props.items():
        assert prop["type"] == "string", field
        assert prop.get("description", "").strip(), field
        assert isinstance(prop.get("maxLength"), int), field


def test_schema_limits_match_the_models():
    schema = TOOLS["process_sru_file"].inputSchema["properties"]
    assert schema["file_name"]["maxLength"] == models.MAX_NAME_CHARS
    assert schema["correction_id"]["maxLength"] == models.MAX_ID_CHARS
    assert TOOLS["parse_sru_response"].inputSchema["properties"]["xml"]["maxLength"] == models.MAX_XML_CHARS
    assert re.fullmatch(schema["correction_id"]["pattern"], "9917175550407426")
    assert re.fullmatch(schema["correction_id"]["pattern"], "")
    assert not re.fullmatch(schema["correction_id"]["pattern"], "12345")


def test_models_strip_optional_text_and_keep_titles():
    args = models.ProcessSruFileInput(file_name="a.xml", search_title="  T  ", correction_id=" 9917175550407426 ")
    assert (args.search_title, args.correction_id) == ("T", "9917175550407426")
    assert models.EnhanceTitleInput(original_title=" T ", erratum_note="").original_title == " T "
    assert models.ListSruFilesInput(contains=None).contains == ""


@pytest.mark.parametrize("model, values, message", [
    (models.SruXmlInput, {"xml": "  "}, "xml is empty."),
    (models.SruXmlInput, {"xml": 5}, "xml must be text."),
    (models.ProcessSruFileInput, {"file_name": ""}, "file_name is empty."),
    (models.ProcessSruFileInput, {"file_name": "a.xml", "correction_id": "12345"},
     "correction_id must be the 16-digit erratum MMS ID, or empty."),
    (models.ProcessSruFileInput, {"file_name": "a.xml", "correction_id": "\u0661" * 16},
     "correction_id must be the 16-digit erratum MMS ID, or empty."),
    (models.ListSruFilesInput, {"contains": "c" * 201}, "contains is too long (limit 200 characters)."),
    (models.ListSruFilesInput, {"folder": "/Volumes"}, "folder is not an input of this tool."),
    (models.ExtractErratumNoteInput, {"doi": ""}, "part_text is required."),
])
def test_model_errors_have_a_clear_message(model, values, message):
    with pytest.raises(ValidationError) as e:
        model.model_validate(values)
    assert models.input_error_message(e.value) == message


def test_tool_turns_a_model_error_into_invalid_input():
    with pytest.raises(ToolError) as e:
        asyncio.run(app.mcp.call_tool("process_sru_file", {"file_name": "a.xml", "correction_id": "12345"}))
    text = str(e.value)
    assert ERROR_TAIL.search(text) and "16-digit" in text
