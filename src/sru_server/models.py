"""Pydantic input model for the build_sru_search_url tool.

BuildSruSearchUrlInput is the one place that states the tool's input rules. The tool
validates its argument with it and turns any problem into the stable invalid_input
error (with an error id), so clients keep getting the same error category.

CorrectionTitleArg carries the same description and limits into the MCP input schema
(tools/list), so an agent sees them before it calls the tool. It does not enforce
them: FastMCP would otherwise reject bad input with a generic Pydantic message,
before the tool can add its category and error id.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import PydanticCustomError

MAX_TITLE_CHARS = 1000

CorrectionTitleArg = Annotated[
    str,
    Field(
        description=(
            "The full correction notice title exactly as given, e.g. 'Correction to: "
            "<original title>' or 'Corrigendum: <title>'. Do not shorten or clean it; "
            "the server removes prefixes, author lists and citations itself."
        ),
        json_schema_extra={"minLength": 1, "maxLength": MAX_TITLE_CHARS},
    ),
]


class BuildSruSearchUrlInput(BaseModel):
    """build_sru_search_url: one correction notice title, as text (strict: no
    numbers or lists), not blank, at most MAX_TITLE_CHARS characters. The title is
    kept exactly as given, because the extraction rules read its prefix and quotes."""

    model_config = ConfigDict(extra="forbid", strict=True)

    correction_title: str = Field(max_length=MAX_TITLE_CHARS)

    @field_validator("correction_title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("blank", "correction_title is empty.")
        return value


def is_valid_title(title: object) -> bool:
    """True if build_sru_search_url accepts this title (see BuildSruSearchUrlInput)."""
    try:
        BuildSruSearchUrlInput(correction_title=title)
    except ValidationError:
        return False
    return True
