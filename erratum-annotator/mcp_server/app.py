"""MCP Server: mcp-erratum-note, hosted on Databricks Apps.

Exposes the Erratum Annotator functions as MCP tools over streamable HTTP.
Endpoint: https://<app-url>/mcp
Demo page for librarians: https://<app-url>/ (same code, read-only).
"""
import asyncio
import contextlib
import functools
import inspect
import os
import posixpath
import re
import secrets
import time
import xml.etree.ElementTree as ET

from databricks.sdk import WorkspaceClient
from databricks.sdk import errors as dberr
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from erratum_annotator import (
    ModsRecord,
    clean_xml,
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


# ---- Error handling (MCP tools and demo page) ----
# Every tool error comes back as a short message that says what to do, ending with
# "[error <category>, id <error id>]". Categories: invalid_input, not_well_formed, not_sru, sru_diagnostic,
# not_found, permission_denied, unavailable, bad_file, internal. Logs carry the error id, category, tool and
# exception type only, never XML, titles or file contents. Temporary volume errors are retried once.
MAX_XML_CHARS = 2_000_000
MAX_TEXT_CHARS = 2_000
SRW_DIAG = "{http://www.loc.gov/zing/srw/diagnostic/}"
_TEMPORARY = (dberr.TemporarilyUnavailable, dberr.DeadlineExceeded, dberr.InternalError, dberr.TooManyRequests,
              dberr.ResourceExhausted, ConnectionError, TimeoutError)


class ErratumError(Exception):
    """An error with a stable category and a message the caller can act on."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category, self.message, self.error_id = category, message, secrets.token_hex(4)

    def client_message(self) -> str:
        return f"{self.message} [error {self.category}, id {self.error_id}]"


def _log_error(err: ErratumError, where: str, exc: BaseException | None = None) -> None:
    print(f"tool_error error_id={err.error_id} category={err.category} where={where}"
          + (f" exception={type(exc).__name__}" if exc is not None else ""), flush=True)


def _check_text(name: str, value, limit: int = MAX_TEXT_CHARS, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ErratumError("invalid_input", f"{name} must be text.")
    if required and not value.strip():
        raise ErratumError("invalid_input", f"{name} is empty.")
    if len(value) > limit:
        raise ErratumError("invalid_input", f"{name} is too long (limit {limit:,} characters).")
    return value


def _check_correction_id(correction_id) -> str:
    cid = _check_text("correction_id", correction_id, 50).strip()
    if cid and not re.fullmatch(r"\d{16}", cid):
        raise ErratumError("invalid_input", "correction_id must be the 16-digit erratum MMS ID, or empty.")
    return cid


def _check_xml(xml) -> str:
    """Reject input that is not a well-formed SRU searchRetrieveResponse, with a message saying why."""
    xml = _check_text("xml", xml, MAX_XML_CHARS, required=True)
    try:
        root = ET.fromstring(clean_xml(xml))
    except ET.ParseError as e:
        line, col = getattr(e, "position", (0, 0))
        raise ErratumError("not_well_formed", f"The XML is not well-formed (line {line}, column {col}). Paste the "
                           "complete SRU searchRetrieveResponse, from its first line to its last.") from None
    if not root.tag.endswith("searchRetrieveResponse"):
        tag = root.tag.rsplit("}", 1)[-1][:60]
        raise ErratumError("not_sru", f"This XML is not an SRU searchRetrieveResponse (its root element is <{tag}>). "
                           "Use the response of an NAL Alma SRU searchRetrieve request with recordSchema=mods.")
    diag = root.find(f".//{SRW_DIAG}diagnostic")
    if diag is not None and not list(root.iter("{http://www.loc.gov/zing/srw/}record")):
        text = " ".join(t.strip() for t in (diag.findtext(f"{SRW_DIAG}message") or "",
                                             diag.findtext(f"{SRW_DIAG}details") or "") if t.strip())
        raise ErratumError("sru_diagnostic", "The SRU response reports an error instead of records"
                           + (f": {text[:200]}" if text else "") + ". Check the SRU search URL and run it again.")
    return xml


def _volume_call(fn, *args):
    """Call the Files API; retry once after a temporary error; map errors to categories."""
    for attempt in (1, 2):
        try:
            return fn(*args)
        except _TEMPORARY:
            if attempt == 2:
                raise ErratumError("unavailable", "The saved SRU responses could not be read just now (tried twice). "
                                   "Try again in a minute.") from None
            time.sleep(1)
        except (dberr.PermissionDenied, dberr.Unauthenticated):
            raise ErratumError("permission_denied", "The app cannot read the saved SRU responses (permission denied). "
                               "Ask the app owner to grant the app READ VOLUME on users.amanda_xu.erratum_files.") from None


def _read_volume_file(path: str) -> str:
    try:
        data = _volume_call(lambda p: _client().files.download(p).contents.read(), path)
    except dberr.NotFound:
        raise ErratumError("not_found", f"No saved SRU response named '{posixpath.basename(path)}'. Call "
                           "list_sru_files to see the saved file names.") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ErratumError("bad_file", f"The saved file '{posixpath.basename(path)}' is not UTF-8 text. "
                           "Save the SRU response again as UTF-8 XML.") from None


def _list_xml_names() -> list:
    try:
        entries = _volume_call(lambda d: list(_client().files.list_directory_contents(d)), SRU_DIR)
    except dberr.NotFound:
        raise ErratumError("not_found", "The saved SRU responses folder does not exist. Ask the app owner to check "
                           "SRU_VOLUME_DIR in app.yaml.") from None
    return [e.name for e in entries if not e.is_directory and e.name.lower().endswith(".xml")]


# ---- MLflow tracing of every tool call (for online evaluation) ----
# Each tool call becomes one trace in the experiment MLFLOW_EXPERIMENT_ID (app.yaml), with the tool's
# arguments as inputs, its result as outputs, and tags app and tool. Strings longer than MAX_TRACE_CHARS
# (an SRU XML response can be 2 MB) are cut, with their full length noted. A failed call records only the
# ToolError message the client also gets, never internal exception text. Tracing is best effort: it is set
# up only when the app starts (not on import, so tests stay offline), and if MLflow cannot be set up the
# app runs untraced. MCP_TRACING=off turns it off.
TRACE_EXPERIMENT_ID = os.environ.get("MLFLOW_EXPERIMENT_ID", "").strip()
MAX_TRACE_CHARS = 4_000
_mlflow = None  # the mlflow module once tracing is on


def _init_tracing() -> None:
    global _mlflow
    if not TRACE_EXPERIMENT_ID or os.environ.get("MCP_TRACING", "on").strip().lower() == "off":
        print("tracing_off reason=not_configured", flush=True)
        return
    try:
        import mlflow

        mlflow.set_tracking_uri("databricks")
        mlflow.set_experiment(experiment_id=TRACE_EXPERIMENT_ID)
        _mlflow = mlflow
        print("tracing_on", flush=True)
    except Exception as exc:  # never stop the app because tracing could not start
        print(f"tracing_off exception={type(exc).__name__}", flush=True)


def _short(value):
    """A copy of value for a trace, with long strings cut to MAX_TRACE_CHARS."""
    if isinstance(value, str) and len(value) > MAX_TRACE_CHARS:
        return f"{value[:MAX_TRACE_CHARS]}... [cut; {len(value):,} characters in total]"
    if isinstance(value, dict):
        return {k: _short(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_short(v) for v in value]
    return value


@contextlib.contextmanager
def _tool_span(fn, args, kwargs):
    """One MLflow trace for a tool call; yields the span, or None when tracing is off."""
    if _mlflow is None:
        yield None
        return
    with _mlflow.start_span(name=fn.__name__, span_type="TOOL") as span:
        try:
            inputs = dict(inspect.signature(fn).bind_partial(*args, **kwargs).arguments)
        except TypeError:
            inputs = dict(kwargs)
        span.set_inputs(_short(inputs))
        _mlflow.update_current_trace(tags={"app": "mcp-erratum-note", "tool": fn.__name__})
        yield span


def _handled(fn):
    """Turn any error in a tool into a clear, categorized ToolError; never expose internal exception text.
    Each call is also traced to MLflow when tracing is on."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _tool_span(fn, args, kwargs) as span:
            try:
                result = fn(*args, **kwargs)
            except ErratumError as err:
                _log_error(err, fn.__name__)
                raise ToolError(err.client_message()) from None
            except Exception as exc:
                err = ErratumError("internal", "Unexpected error in mcp-erratum-note. Try again; if it repeats, send "
                                   "the error id to the app owner.")
                _log_error(err, fn.__name__, exc)
                raise ToolError(err.client_message()) from None
            if span is not None:
                span.set_outputs(_short(result))
            return result
    return wrapper


def _with_status(result: dict, correction_id: str) -> dict:
    """Add status and warnings, so a caller can tell a usable annotation from an empty one."""
    warnings = []
    if not result.get("num_records"):
        status = "no_records"
    elif not result.get("num_corrections"):
        status = "no_correction"
    elif result.get("already_annotated"):
        status = "already_annotated"
    elif not result.get("erratum_note"):
        status = "no_note"
        warnings.append("The correction record has no part text or DOI, so no erratum note could be made.")
    else:
        status = _status(result)
    used = result.get("correction_id")
    if correction_id and used and used != correction_id:
        warnings.append(f"correction_id {correction_id} is not in this response; used the first correction record "
                        f"({used}) instead.")
    elif not correction_id and (result.get("num_corrections") or 0) > 1:
        warnings.append(f"This response has {result['num_corrections']} correction records; used the first ({used}). "
                        "Pass correction_id to choose another.")
    return {**result, "status": status, "warnings": warnings}


def _read_only(title: str) -> ToolAnnotations:
    """MCP annotations for every tool here: each one only reads (saved SRU responses or XML it is given),
    creates or changes nothing, gives the same result for the same input, and calls no outside service."""
    return ToolAnnotations(title=title, readOnlyHint=True, destructiveHint=False,
                           idempotentHint=True, openWorldHint=False)


@mcp.tool(annotations=_read_only("Check the erratum annotator"))
@_handled
def health() -> str:
    """Check that the erratum annotator server is running and can read the saved SRU responses."""
    try:
        count = len(_list_xml_names())
    except ErratumError as err:
        _log_error(err, "health")
        return f"mcp-erratum-note is running, but it cannot read the saved SRU responses: {err.client_message()}"
    return f"mcp-erratum-note is running; {count} saved SRU responses are readable."


@mcp.tool(annotations=_read_only("Parse an SRU response"))
@_handled
def parse_sru_response(xml: str) -> dict:
    """Parse an SRU searchRetrieveResponse XML string into classified records.

    Returns {num_records, records: [{title, record_id, part_text, doi, is_correction}]}.
    Errors (bad or non-SRU XML) end with [error <category>, id <id>].
    """
    records = _parse(_check_xml(xml))
    return {
        "num_records": len(records),
        "records": [
            {"title": r.title, "record_id": r.record_id, "part_text": r.part_text,
             "doi": r.doi, "is_correction": r.is_correction}
            for r in records
        ],
    }


@mcp.tool(annotations=_read_only("Format an erratum note"))
@_handled
def extract_erratum_note(part_text: str, doi: str) -> str:
    """Format an erratum note from a correction record's <part><text> and DOI.

    Returns '[Erratum: Mon. YYYY, v. V, no. N, page, doi]' or '' if inputs are missing.
    """
    part_text = _check_text("part_text", part_text, 500)
    doi = _check_text("doi", doi, 500)
    rec = ModsRecord(title="Correction", record_id="", part_text=part_text,
                     doi=doi, is_correction=True)
    return _extract_note(rec) or ""


@mcp.tool(annotations=_read_only("Append an erratum note to a title"))
@_handled
def enhance_title(original_title: str, erratum_note: str) -> dict:
    """Append an erratum note to the end of the original title.

    Skips if the title already contains '[Erratum:'.
    Returns {annotated_title, already_annotated}.
    """
    original_title = _check_text("original_title", original_title)
    erratum_note = _check_text("erratum_note", erratum_note)
    already = "[Erratum:" in (original_title or "")
    return {"annotated_title": _enhance(original_title, erratum_note),
            "already_annotated": already}


@mcp.tool(annotations=_read_only("Annotate a title from SRU XML"))
@_handled
def process_sru_response(xml: str, search_title: str = "", correction_id: str = "") -> dict:
    """Full pipeline: parse SRU XML, match correction to original, annotate the title.

    Uses search_title as the fallback when no original record is in the response.
    Pass correction_id (the 16-digit erratum MMS ID) when a response may contain several
    correction records, so the right one supplies the note.
    Returns {annotated_title, erratum_note, correction_id, original_id, original_source,
             already_annotated, num_records, num_corrections, status, warnings}.
    status: ready, needs_review, no_original, already_annotated, no_records, no_correction or no_note.
    Errors (bad or non-SRU XML, bad correction_id) end with [error <category>, id <id>].
    """
    search_title = _check_text("search_title", search_title).strip()
    correction_id = _check_correction_id(correction_id)
    return _with_status(_process(_check_xml(xml), search_title, correction_id), correction_id)


@mcp.tool(annotations=_read_only("List saved SRU responses"))
@_handled
def list_sru_files(contains: str = "") -> dict:
    """List saved SRU response XML files in the erratum volume folder.

    Optional `contains` filters file names by substring (case-insensitive),
    e.g. 'Row41' or an MMS ID. Returns {folder, count, files}.
    """
    contains = _check_text("contains", contains, 200).strip()
    names = sorted(n for n in _list_xml_names() if contains.lower() in n.lower())
    return {"folder": SRU_DIR, "count": len(names), "files": names}


@mcp.tool(annotations=_read_only("Annotate a title from a saved SRU response"))
@_handled
def process_sru_file(file_name: str, search_title: str = "", correction_id: str = "") -> dict:
    """Read a saved SRU response from the erratum volume folder and annotate the title.

    file_name is a bare name from list_sru_files, e.g. 'Sample1-Row43-9917175550407426.xml'.
    If correction_id is empty, the 16-digit MMS ID at the end of the file name is used
    (falls back to the first correction record if it does not match any record).
    Returns the same fields as process_sru_response plus {file_name, correction_id_requested}.
    Errors (no such file, unreadable file, bad XML) end with [error <category>, id <id>].
    """
    file_name = _check_text("file_name", file_name, 200, required=True)
    try:
        path = _safe_path(file_name)
    except ValueError:
        raise ErratumError("invalid_input", "file_name must be a bare .xml file name from list_sru_files, "
                           "with no folder.") from None
    search_title = _check_text("search_title", search_title).strip()
    correction_id = _check_correction_id(correction_id)
    if not correction_id:
        m = re.search(r"(\d{16})\.xml$", file_name, re.I)
        correction_id = m.group(1) if m else ""
    xml = _read_volume_file(path)
    try:
        xml = _check_xml(xml)
    except ErratumError as err:
        raise ErratumError("bad_file", f"The saved file '{file_name}' is not a usable SRU response: {err.message}") from None
    result = _with_status(_process(xml, search_title, correction_id), correction_id)
    return {"file_name": file_name, "correction_id_requested": correction_id, **result}


# ---- Demo web page for librarians and sponsors (same app; Databricks Apps handles the sign-in) ----
# GET  /                  page: pick a saved correction notice (or paste SRU XML) and see the annotated title
# GET  /api/examples      saved notices: [{file_name, row, correction_id, correction_title}]
# POST /api/annotate      {"file_name": "..."} or {"xml": "...", "search_title": "", "correction_id": ""}
# GET  /api/annotate-all  every saved notice, annotated (about a second in total)
# The page calls the same code as the MCP tools; nothing is written anywhere.
import json
import threading

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

SRU_RECORD_URL = (
    "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve"
    "&recordSchema=mods&query=alma.mms_id%3D"
)
_cache = {"examples": None, "xml": {}}
_cache_lock = threading.Lock()


def _row_number(name: str) -> int:
    m = re.search(r"Row(\d+)", name)
    return int(m.group(1)) if m else 10_000


def _sample_number(name: str) -> int:
    """Sample spreadsheet a saved response comes from: 'Sample2-Row3-...' -> 2 (default 1)."""
    m = re.match(r"Sample(\d+)-", name)
    return int(m.group(1)) if m else 1


def _load_examples() -> list:
    """Saved SRU responses, kept in memory (about 50 small files). The folder is listed on every call, so a newly
    saved response appears without restarting the app; only files not read before are downloaded."""
    with _cache_lock:
        names = sorted(_list_xml_names(), key=lambda n: (_sample_number(n), _row_number(n), n))
        if _cache["examples"] is not None and _cache.get("names") == names:
            return _cache["examples"]
        old = {e["file_name"]: e for e in (_cache["examples"] or [])}
        _cache["xml"] = {n: x for n, x in _cache["xml"].items() if n in names}
        examples = []
        for name in names:
            if name in old and name in _cache["xml"]:
                examples.append(old[name])
                continue
            xml = _read_volume_file(_safe_path(name))
            _cache["xml"][name] = xml
            m = re.search(r"(\d{16})\.xml$", name, re.I)
            cid = m.group(1) if m else ""
            recs = _parse(xml)
            corr = next((r for r in recs if r.is_correction and r.record_id == cid), None) or next(
                (r for r in recs if r.is_correction), None)
            sample, row = _sample_number(name), _row_number(name)
            examples.append({"file_name": name, "sample": sample, "row": row, "label": f"Sample {sample}, row {row}",
                             "correction_id": cid, "correction_title": corr.title if corr else ""})
        _cache["examples"], _cache["names"] = examples, names
        return examples


def _status(result: dict) -> str:
    if result.get("already_annotated"):
        return "already_annotated"
    if not result.get("original_id"):
        return "no_original"
    if result.get("needs_review"):
        return "needs_review"
    return "ready"


def _explain(xml: str, search_title: str, correction_id: str) -> dict:
    """Annotate, and add the correction and original records so the page can show before and after."""
    started = time.perf_counter()
    result = _process(xml, search_title, correction_id)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    recs = {r.record_id: r for r in _parse(xml)}
    corr = recs.get(str(result.get("correction_id") or ""))
    orig = recs.get(str(result.get("original_id") or ""))
    return {
        **result,
        "status": _status(result),
        "elapsed_ms": elapsed_ms,
        "correction_title": corr.title if corr else "",
        "original_title": orig.title if orig else "",
        "correction_doi": corr.doi if corr else "",
    }


async def _json_body(request: Request):
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        return None, JSONResponse({"error": "Send JSON."}, status_code=415)
    try:
        body = await request.json()
    except Exception:
        return None, JSONResponse({"error": "Request body must be JSON."}, status_code=400)
    if not isinstance(body, dict):
        return None, JSONResponse({"error": "Request body must be a JSON object."}, status_code=400)
    return body, None


def _err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


@mcp.custom_route("/api/examples", methods=["GET"])
async def api_examples(request: Request) -> JSONResponse:
    try:
        return JSONResponse({"folder": SRU_DIR, "examples": await asyncio.to_thread(_load_examples)})
    except ErratumError as err:
        _log_error(err, "page_examples")
        return _err(f"{err.message} (error id {err.error_id})", 502)
    except Exception as e:
        print(f"demo_error where=examples exception={type(e).__name__}")
        return _err("Could not read the saved SRU responses. Try again in a minute.", 502)


@mcp.custom_route("/api/annotate", methods=["POST"])
async def api_annotate(request: Request) -> JSONResponse:
    body, error = await _json_body(request)
    if error:
        return error
    search_title = body.get("search_title") or ""
    correction_id = body.get("correction_id") or ""
    if not isinstance(search_title, str) or not isinstance(correction_id, str) or len(search_title) > 2000:
        return _err("search_title and correction_id must be short text.")
    if correction_id and not re.fullmatch(r"\d{16}", correction_id.strip()):
        return _err("correction_id must be a 16-digit MMS ID.")
    try:
        if body.get("file_name"):
            name = body["file_name"]
            if not isinstance(name, str):
                return _err("file_name must be text.")
            _safe_path(name)  # bare .xml name inside the folder, or ValueError
            await asyncio.to_thread(_load_examples)
            xml = _cache["xml"].get(name)
            if xml is None:
                return _err("No saved SRU response with that file name.", 404)
            if not correction_id:
                m = re.search(r"(\d{16})\.xml$", name, re.I)
                correction_id = m.group(1) if m else ""
        else:
            xml = body.get("xml")
            if not isinstance(xml, str) or not xml.strip():
                return _err("Pick a saved notice, or paste an SRU response (XML).")
            if len(xml) > MAX_XML_CHARS:
                return _err("The XML is too long (limit 2 MB).")
            xml = _check_xml(xml)  # well-formed SRU searchRetrieveResponse, or a clear ErratumError
        result = await asyncio.to_thread(_explain, xml, search_title.strip(), correction_id.strip())
    except ErratumError as err:
        _log_error(err, "page_annotate")
        server_side = err.category in ("permission_denied", "unavailable", "internal")
        return _err(f"{err.message} (error id {err.error_id})", 502 if server_side else 400)
    except (ValueError, SyntaxError):  # bad file name, or XML that does not parse (ParseError)
        return _err("That does not look like an SRU response, or the file name is not allowed.")
    except Exception as e:
        print(f"demo_error where=annotate exception={type(e).__name__}")
        return _err("Something went wrong while reading the SRU response.", 502)
    return JSONResponse(result)


@mcp.custom_route("/api/annotate-all", methods=["GET"])
async def api_annotate_all(request: Request) -> JSONResponse:
    try:
        examples = await asyncio.to_thread(_load_examples)
        started = time.perf_counter()
        rows = []
        for ex in examples:
            r = _explain(_cache["xml"][ex["file_name"]], "", ex["correction_id"])
            rows.append({"sample": ex["sample"], "row": ex["row"], "label": ex["label"], "file_name": ex["file_name"],
                         "status": r["status"],
                         "correction_title": r["correction_title"], "annotated_title": r["annotated_title"],
                         "original_id": r.get("original_id") or "", "correction_id": r.get("correction_id") or ""})
        return JSONResponse({"count": len(rows), "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                             "rows": rows})
    except Exception as e:
        print(f"demo_error where=annotate_all exception={type(e).__name__}")
        return _err("Could not annotate the saved notices. Try again in a minute.", 502)


@mcp.custom_route("/", methods=["GET"])
async def demo_page(request: Request) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    html = DEMO_PAGE.replace("__NONCE__", nonce).replace("__RECORD_URL__", json.dumps(SRU_RECORD_URL))
    return HTMLResponse(html, headers={
        "Content-Security-Policy": (
            f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "connect-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    })


def _warm_cache() -> None:
    try:
        _load_examples()
        print("demo_cache ok")
    except Exception as e:
        print(f"demo_cache failed exception={type(e).__name__}")


DEMO_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Erratum Annotator demo - NAL</title>
<style nonce="__NONCE__">
  :root { --green:#2e8b22; --blue:#058dc7; --teal:#158158; --panel:#f3f6f9; --ink:#1b1b1b; --muted:#555; }
  body { font-family: system-ui, -apple-system, "Segoe UI", Arial, sans-serif; max-width: 60rem; margin: 0 auto; padding: 1rem 1rem 3rem; color: var(--ink); line-height: 1.5; }
  header { border-bottom: 4px solid var(--green); margin-bottom: 1rem; }
  h1 { font-size: 1.6rem; margin: .5rem 0 .25rem; }
  h2 { font-size: 1.15rem; margin: 1.5rem 0 .5rem; }
  .lead { font-size: 1.05rem; color: var(--muted); margin-top: 0; }
  .card { background: var(--panel); border-radius: 8px; padding: 1rem; margin: .75rem 0; }
  .picks button, .primary, .secondary { font: inherit; border-radius: 6px; cursor: pointer; padding: .45rem .9rem; margin: .25rem .4rem .25rem 0; }
  .primary { background: var(--green); color: #fff; border: 0; font-weight: 600; }
  .secondary, .picks button { background: #fff; border: 1px solid #b8c4ce; }
  select, textarea, input { font: inherit; width: 100%; box-sizing: border-box; padding: .45rem; margin: .25rem 0; }
  textarea { min-height: 8rem; font-family: ui-monospace, Consolas, monospace; font-size: .85rem; }
  .steps { display: grid; grid-template-columns: 1fr; gap: .5rem; }
  .step { background: #fff; border-left: 5px solid var(--blue); border-radius: 6px; padding: .6rem .8rem; }
  .step.final { border-left-color: var(--green); }
  .step .k { font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
  .step .v { font-size: 1.02rem; word-break: break-word; }
  .note { background: #e4f3e1; color: #145a10; font-weight: 600; padding: 0 .2rem; border-radius: 3px; }
  .meta { color: var(--muted); font-size: .9rem; }
  .badge { display: inline-block; padding: .15rem .6rem; border-radius: 999px; font-weight: 600; font-size: .9rem; }
  .b-ready { background: #e4f3e1; color: #145a10; } .b-needs_review { background: #fff1d6; color: #7a4b00; }
  .b-no_original { background: #fde4e4; color: #8a1414; } .b-already_annotated { background: #e3eef8; color: #0b4a75; }
  .error { color: #b50909; font-weight: 600; }
  details { margin: .75rem 0; } summary { cursor: pointer; font-weight: 600; }
  table { border-collapse: collapse; width: 100%; font-size: .88rem; background: #fff; }
  th, td { border-bottom: 1px solid #dde3e8; padding: .35rem .4rem; text-align: left; vertical-align: top; }
  th { background: #e9eef2; }
  a { color: #0b5fa5; }
  .row { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  .grow { flex: 1 1 20rem; }
</style>
</head>
<body>
<header>
  <h1>Erratum Annotator</h1>
  <p class="lead">USDA National Agricultural Library. When a publisher corrects an article, the catalog record of the
  <strong>original article</strong> should say so. This demo reads the Alma SRU response, finds the original
  article, and adds an erratum note to its title, in about a second.</p>
</header>

<h2>1. Pick a correction notice</h2>
<div class="card">
  <div class="picks" id="picks">Quick examples:
    <button type="button" data-row="1-43">Typical correction</button>
    <button type="button" data-row="1-41">Two corrections in one response</button>
    <button type="button" data-row="1-40">Title with a curly apostrophe</button>
    <button type="button" data-row="2-3">Correction title in curly double quotes</button>
    <button type="button" data-row="1-4">No original article in Alma</button>
  </div>
  <label for="pick">Or choose any of the saved notices:</label>
  <div class="row"><div class="grow"><select id="pick"><option value="">Loading saved notices...</option></select></div>
  <button type="button" class="primary" id="go">Annotate this notice</button></div>
</div>

<h2>2. See the result</h2>
<div id="status" class="meta" role="status" aria-live="polite">Pick a notice above.</div>
<div id="result"></div>

<details>
  <summary>Paste your own SRU response (for staff who have one)</summary>
  <div class="card">
    <label for="xml">SRU searchRetrieve response (MODS XML)</label>
    <textarea id="xml" spellcheck="false" placeholder="&lt;searchRetrieveResponse ...&gt;"></textarea>
    <label for="cid">Correction (erratum) MMS ID, optional</label>
    <input id="cid" inputmode="numeric" maxlength="16" placeholder="16 digits, e.g. 9917175550407426">
    <button type="button" class="primary" id="goxml">Annotate pasted XML</button>
  </div>
</details>

<details>
  <summary>See all saved notices at once</summary>
  <div class="card"><button type="button" class="secondary" id="all">Annotate all saved notices</button>
  <div id="allout"></div></div>
</details>

<details>
  <summary>How it works</summary>
  <div class="card">
    <ol>
      <li><strong>Find:</strong> the SRU search for the notice (built by the companion tool, mcp-sru-syntax) returns
      the correction notice and the original article.</li>
      <li><strong>Match:</strong> the original is the record whose DOI the notice cites; otherwise the most similar
      title. Uncertain matches are flagged for review, never guessed.</li>
      <li><strong>Annotate:</strong> the date, volume, issue, pages and DOI of the correction become the note
      <span class="note">[Erratum: ...]</span> at the end of the original title. Titles that already have a note are
      left alone.</li>
    </ol>
    <p class="meta">Same rules everywhere: this page, the MCP server <code>mcp-erratum-note</code> (7 read-only tools
    at <code>/mcp</code>, for Genie Code and other AI clients), the Supervisor Agent <code>agent-erratum-annotator</code>
    (chat), and the Unity Catalog function <code>users.amanda_xu.process_sru_response</code> (SQL, for long lists).
    Evaluation on 53 librarian-checked notices: 50/53 exact annotated titles from the agent; 0 errors and 48/48
    original MMS IDs from the MCP server.</p>
  </div>
</details>

<script nonce="__NONCE__">
(function () {
  var RECORD_URL = __RECORD_URL__;
  var LABELS = { ready: "Ready for the catalog", needs_review: "Needs review: original match is uncertain",
    no_original: "No original article in Alma: correction notice only", already_annotated: "Already annotated: no change needed" };
  var pick = document.getElementById("pick"), statusEl = document.getElementById("status"), out = document.getElementById("result");
  var byRow = {};
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function link(id) {
    if (!/^[0-9]{16}$/.test(id || "")) return el("span", "meta", "");
    var a = el("a", null, "View record " + id); a.href = RECORD_URL + id; a.target = "_blank"; a.rel = "noopener noreferrer"; return a;
  }
  function step(key, value, extra, cls) {
    var s = el("div", "step" + (cls ? " " + cls : "")); s.append(el("div", "k", key));
    var v = el("div", "v"); if (value instanceof Node) v.append(value); else v.textContent = value || "(none)"; s.append(v);
    if (extra) { var m = el("div", "meta"); m.append(extra); s.append(m); }
    return s;
  }
  function annotated(title, note) {
    var span = el("span"); var i = note ? title.lastIndexOf(note) : -1;
    if (i < 0) { span.textContent = title; return span; }
    span.append(document.createTextNode(title.slice(0, i))); span.append(el("span", "note", note)); return span;
  }
  async function call(url, opts) {
    var r = await fetch(url, Object.assign({ credentials: "same-origin" }, opts || {}));
    var data = null; try { data = await r.json(); } catch (e) { data = null; }
    if (!data) throw new Error("Your sign-in may have expired. Reload the page and try again.");
    if (!r.ok) throw new Error(data.error || ("Request failed (HTTP " + r.status + ")."));
    return data;
  }
  function show(d) {
    out.replaceChildren();
    var card = el("div", "card");
    var b = el("span", "badge b-" + d.status, LABELS[d.status] || d.status); card.append(b);
    var steps = el("div", "steps");
    steps.append(step("Correction notice in Alma", d.correction_title, link(d.correction_id)));
    steps.append(step("Original article found", d.original_id ? d.original_title : "Not in this SRU response",
      d.original_id ? link(d.original_id) : null));
    steps.append(step("Erratum note", d.erratum_note));
    if (d.status === "no_original") {
      steps.append(step("Annotated title", "None: there is no original article record to annotate.", null, "final"));
    } else {
      var actions = el("span"); var c = el("button", "secondary", "Copy annotated title"); c.type = "button";
      c.addEventListener("click", function () { navigator.clipboard.writeText(d.annotated_title).then(function () { c.textContent = "Copied"; }); });
      actions.append(c);
      steps.append(step("Annotated title for the original record", annotated(d.annotated_title, d.erratum_note), actions, "final"));
    }
    card.append(steps);
    card.append(el("p", "meta", "Done in " + d.elapsed_ms + " ms by the same code as the MCP server and the SQL function. Records in this response: "
      + d.num_records + " (" + d.num_corrections + " correction" + (d.num_corrections === 1 ? "" : "s") + ")."));
    out.append(card);
  }
  async function annotate(body, label) {
    statusEl.textContent = "Working on " + label + "..."; out.replaceChildren();
    var t = Date.now();
    try {
      var d = await call("api/annotate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      show(d); statusEl.textContent = label + ": done in " + ((Date.now() - t) / 1000).toFixed(1) + " s (including the network).";
    } catch (e) { statusEl.textContent = ""; out.append(el("p", "error", e.message)); }
  }
  function annotateSelected() {
    var f = pick.value; if (!f) return;
    annotate({ file_name: f }, pick.options[pick.selectedIndex].textContent.split(" - ")[0]);
  }
  document.getElementById("go").addEventListener("click", annotateSelected);
  document.getElementById("picks").addEventListener("click", function (ev) {
    var row = ev.target && ev.target.getAttribute && ev.target.getAttribute("data-row"); if (!row) return;
    var f = byRow[row]; if (!f) { statusEl.textContent = "That example is not in the saved notices."; return; }
    pick.value = f; annotateSelected();
  });
  document.getElementById("goxml").addEventListener("click", function () {
    var xml = document.getElementById("xml").value, cid = document.getElementById("cid").value.trim();
    if (!xml.trim()) { statusEl.textContent = "Paste an SRU response first."; return; }
    annotate({ xml: xml, correction_id: cid }, "Pasted SRU response");
  });
  document.getElementById("all").addEventListener("click", async function () {
    var box = document.getElementById("allout"); box.replaceChildren(el("p", "meta", "Working..."));
    try {
      var d = await call("api/annotate-all");
      var counts = {}; d.rows.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
      var summary = d.count + " notices in " + d.elapsed_ms + " ms: " + Object.keys(counts).map(function (k) { return counts[k] + " " + (LABELS[k] || k).split(":")[0].toLowerCase(); }).join(", ") + ".";
      var tbl = el("table"); var h = el("tr"); ["Notice", "Status", "Correction notice", "Annotated title"].forEach(function (x) { h.append(el("th", null, x)); }); tbl.append(h);
      d.rows.forEach(function (r) {
        var tr = el("tr"); tr.append(el("td", null, r.label || String(r.row)));
        var st = el("td"); st.append(el("span", "badge b-" + r.status, (LABELS[r.status] || r.status).split(":")[0])); tr.append(st);
        tr.append(el("td", null, r.correction_title)); tr.append(el("td", null, r.status === "no_original" ? "(none)" : r.annotated_title)); tbl.append(tr);
      });
      box.replaceChildren(el("p", null, summary), tbl);
    } catch (e) { box.replaceChildren(el("p", "error", e.message)); }
  });
  call("api/examples").then(function (d) {
    pick.replaceChildren(el("option", null, "Choose a saved notice (" + d.examples.length + ")")); pick.firstChild.value = "";
    d.examples.forEach(function (x) {
      var o = el("option", null, (x.label || ("Row " + x.row)) + " - " + (x.correction_title || x.file_name).slice(0, 110)); o.value = x.file_name;
      pick.append(o); byRow[(x.sample || 1) + "-" + x.row] = x.file_name;
    });
  }).catch(function (e) { pick.replaceChildren(el("option", null, "Could not load saved notices")); statusEl.textContent = e.message; });
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    _init_tracing()
    threading.Thread(target=_warm_cache, daemon=True).start()
    mcp.run(transport="streamable-http")
