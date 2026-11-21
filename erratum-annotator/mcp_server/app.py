"""MCP Server: mcp-erratum-note, hosted on Databricks Apps.

Exposes the Erratum Annotator functions as MCP tools over streamable HTTP.
Endpoint: https://<app-url>/mcp
"""
import os
import posixpath
import re

from databricks.sdk import WorkspaceClient
from mcp.server.fastmcp import FastMCP

from erratum_annotator import (
    ModsRecord,
    enhance_title as _enhance,
    extract_erratum_note as _extract_note,
    parse_sru_response as _parse,
    process_sru_response as _process,
)

# Databricks Apps routes traffic to DATABRICKS_APP_PORT; bind on all interfaces.
PORT = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
mcp = FastMCP("mcp-erratum-note", host="0.0.0.0", port=PORT)

# UC volume folder holding saved SRU responses. Reads are restricted to this folder.
SRU_DIR = os.environ.get("SRU_VOLUME_DIR", "/Volumes/users/amanda_xu/erratum_files/sru_responses").rstrip("/")
_ws = None


def _client() -> WorkspaceClient:
    """Workspace client authenticated as the app's service principal."""
    global _ws
    if _ws is None:
        _ws = WorkspaceClient()
    return _ws


def _safe_path(file_name: str) -> str:
    """Resolve a bare .xml file name inside SRU_DIR; reject paths and other extensions."""
    name = posixpath.basename((file_name or "").strip())
    if not name or name != (file_name or "").strip() or not name.lower().endswith(".xml"):
        raise ValueError(f"file_name must be a bare .xml file name in {SRU_DIR}, got {file_name!r}")
    return f"{SRU_DIR}/{name}"


def _read_volume_file(path: str) -> str:
    resp = _client().files.download(path)
    return resp.contents.read().decode("utf-8")


@mcp.tool()
def health() -> str:
    """Check that the erratum annotator server is running."""
    return "mcp-erratum-note is running"


@mcp.tool()
def parse_sru_response(xml: str) -> dict:
    """Parse an SRU searchRetrieveResponse XML string into classified records.

    Returns {num_records, records: [{title, record_id, part_text, doi, is_correction}]}.
    """
    records = _parse(xml)
    return {
        "num_records": len(records),
        "records": [
            {"title": r.title, "record_id": r.record_id, "part_text": r.part_text,
             "doi": r.doi, "is_correction": r.is_correction}
            for r in records
        ],
    }


@mcp.tool()
def extract_erratum_note(part_text: str, doi: str) -> str:
    """Format an erratum note from a correction record's <part><text> and DOI.

    Returns '[Erratum: Mon. YYYY, v. V, no. N, page, doi]' or '' if inputs are missing.
    """
    rec = ModsRecord(title="Correction", record_id="", part_text=part_text,
                     doi=doi, is_correction=True)
    return _extract_note(rec) or ""


@mcp.tool()
def enhance_title(original_title: str, erratum_note: str) -> dict:
    """Append an erratum note to the end of the original title.

    Skips if the title already contains '[Erratum:'.
    Returns {annotated_title, already_annotated}.
    """
    already = "[Erratum:" in (original_title or "")
    return {"annotated_title": _enhance(original_title, erratum_note),
            "already_annotated": already}


@mcp.tool()
def process_sru_response(xml: str, search_title: str = "", correction_id: str = "") -> dict:
    """Full pipeline: parse SRU XML, match correction to original, annotate the title.

    Uses search_title as the fallback when no original record is in the response.
    Pass correction_id (the erratum MMS ID) when a response may contain several
    correction records, so the right one supplies the note.
    Returns {annotated_title, erratum_note, correction_id, original_id,
             original_source, already_annotated, num_records, num_corrections}.
    """
    return _process(xml, search_title, correction_id)


@mcp.tool()
def list_sru_files(contains: str = "") -> dict:
    """List saved SRU response XML files in the erratum volume folder.

    Optional `contains` filters file names by substring (case-insensitive),
    e.g. 'Row41' or an MMS ID. Returns {folder, count, files}.
    """
    names = sorted(
        e.name for e in _client().files.list_directory_contents(SRU_DIR)
        if not e.is_directory and e.name.lower().endswith(".xml")
        and contains.lower() in e.name.lower()
    )
    return {"folder": SRU_DIR, "count": len(names), "files": names}


@mcp.tool()
def process_sru_file(file_name: str, search_title: str = "", correction_id: str = "") -> dict:
    """Read a saved SRU response from the erratum volume folder and annotate the title.

    file_name is a bare name from list_sru_files, e.g. 'Sample1-Row43-9917175550407426.xml'.
    If correction_id is empty, the 16-digit MMS ID at the end of the file name is used
    (falls back to the first correction record if it does not match any record).
    Returns the same fields as process_sru_response plus {file_name, correction_id_requested}.
    """
    path = _safe_path(file_name)
    if not correction_id:
        m = re.search(r"(\d{16})\.xml$", file_name, re.I)
        correction_id = m.group(1) if m else ""
    result = _process(_read_volume_file(path), search_title, correction_id)
    return {"file_name": file_name, "correction_id_requested": correction_id, **result}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
