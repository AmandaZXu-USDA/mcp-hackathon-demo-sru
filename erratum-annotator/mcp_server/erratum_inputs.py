"""Pydantic input models for the mcp-erratum-note tools: one model per tool.

Each model is the one place that states a tool's input rules (type, length, format). The tools in app.py
validate their arguments with these models through app._validated(), which turns a ValidationError into
an invalid_input error with a message naming the field, so clients keep getting stable error categories.

The tool signatures use the *Arg types below. They carry the same descriptions and limits into the MCP
input schema (tools/list), so an agent can see them before it calls a tool, but they leave enforcement to
the models: FastMCP would otherwise reject bad input with a generic Pydantic message, before the tool can
add its category and error id.
"""
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import PydanticCustomError

MAX_XML_CHARS = 2_000_000
MAX_TEXT_CHARS = 2_000
MAX_PART_CHARS = 500
MAX_NAME_CHARS = 200
MAX_ID_CHARS = 50
MMS_ID_PATTERN = r"[0-9]{16}"  # Alma MMS ID; ASCII digits only


def _arg(description: str, max_length: int, **schema) -> object:
    """A str argument whose description and limits are shown in the MCP input schema (not enforced here)."""
    return Annotated[str, Field(description=description, json_schema_extra={"maxLength": max_length, **schema})]


XmlArg = _arg("The complete SRU searchRetrieveResponse XML (recordSchema=mods), from its first line to its last.",
              MAX_XML_CHARS, minLength=1)
SearchTitleArg = _arg("Optional. The original article title the librarian searched for; only used to rank the "
                      "original records in the response.", MAX_TEXT_CHARS)
CorrectionIdArg = _arg("Optional. The 16-digit MMS ID of the correction notice, to choose its record when the "
                       "response has several. Empty uses the first correction record.", MAX_ID_CHARS,
                       pattern=rf"^({MMS_ID_PATTERN})?$")
FileNameArg = _arg("A bare .xml file name returned by list_sru_files, with no folder, e.g. "
                   "'Sample1-Row43-9917175550407426.xml'.", MAX_NAME_CHARS, minLength=1, pattern=r"^[^/\\]+\.xml$")
ContainsArg = _arg("Optional. Case-insensitive text the file name must contain, e.g. 'Row41' or an MMS ID.",
                   MAX_NAME_CHARS)
PartTextArg = _arg("The correction record's MODS <part><text>, e.g. 'Aug. 2026, v. 52, no. 4, 134'.", MAX_PART_CHARS)
DoiArg = _arg("The correction record's DOI, e.g. '10.1007/s10695-026-01767-0'. May be empty.", MAX_PART_CHARS)
OriginalTitleArg = _arg("The original article's title as it is in the catalog.", MAX_TEXT_CHARS)
ErratumNoteArg = _arg("An erratum note from extract_erratum_note, e.g. '[Erratum: Aug. 2026, v. 52, no. 4, ...]'.",
                      MAX_TEXT_CHARS)


class ToolInput(BaseModel):
    """Base for every tool input: no unknown fields, values are text, and None counts as empty text."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _none_is_empty(cls, value):
        return "" if value is None else value


def _not_blank(value: str, field: str) -> str:
    if not value.strip():
        raise PydanticCustomError("blank", "{field} is empty.", {"field": field})
    return value


class SruXmlInput(ToolInput):
    """parse_sru_response; also checks the XML of a saved file before it is parsed."""

    xml: str = Field(max_length=MAX_XML_CHARS)

    @field_validator("xml")
    @classmethod
    def _xml_not_blank(cls, value: str) -> str:
        return _not_blank(value, "xml")


class _CorrectionChoice(ToolInput):
    """Shared by the two annotate tools: an optional search title and correction MMS ID, both stripped."""

    search_title: str = Field(default="", max_length=MAX_TEXT_CHARS)
    correction_id: str = Field(default="", max_length=MAX_ID_CHARS)

    @field_validator("search_title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        return value.strip()

    @field_validator("correction_id")
    @classmethod
    def _mms_id_or_empty(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(MMS_ID_PATTERN, value):
            raise PydanticCustomError("mms_id", "correction_id must be the 16-digit erratum MMS ID, or empty.")
        return value


class ProcessSruResponseInput(SruXmlInput, _CorrectionChoice):
    """process_sru_response: SRU XML plus the optional search title and correction MMS ID."""


class ProcessSruFileInput(_CorrectionChoice):
    """process_sru_file: a saved file name plus the optional search title and correction MMS ID.
    The file name is only checked for length here; app._safe_path() makes sure it is a bare .xml name."""

    file_name: str = Field(max_length=MAX_NAME_CHARS)

    @field_validator("file_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _not_blank(value, "file_name")


class ListSruFilesInput(ToolInput):
    """list_sru_files: an optional file-name filter, stripped."""

    contains: str = Field(default="", max_length=MAX_NAME_CHARS)

    @field_validator("contains")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ExtractErratumNoteInput(ToolInput):
    """extract_erratum_note: the correction record's part text and DOI."""

    part_text: str = Field(max_length=MAX_PART_CHARS)
    doi: str = Field(max_length=MAX_PART_CHARS)


class EnhanceTitleInput(ToolInput):
    """enhance_title: the original title and the note to append."""

    original_title: str = Field(max_length=MAX_TEXT_CHARS)
    erratum_note: str = Field(max_length=MAX_TEXT_CHARS)


def input_error_message(err: ValidationError) -> str:
    """One short message for the first problem, naming the field, in the wording the tools have always used."""
    first = err.errors()[0]
    field = ".".join(str(p) for p in first.get("loc", ())) or "input"
    kind, ctx = first["type"], first.get("ctx") or {}
    if kind == "string_type":
        return f"{field} must be text."
    if kind == "string_too_long":
        return f"{field} is too long (limit {ctx['max_length']:,} characters)."
    if kind == "missing":
        return f"{field} is required."
    if kind == "extra_forbidden":
        return f"{field} is not an input of this tool."
    return first["msg"]  # the PydanticCustomError messages above
