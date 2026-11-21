"""MCP Server: mcp-erratum-note, hosted on Databricks Apps.

Exposes the Erratum Annotator functions as MCP tools over streamable HTTP.
Endpoint: https://<app-url>/mcp
Demo page for librarians: https://<app-url>/ (same code, read-only).
"""
import asyncio
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


# ---- Demo web page for librarians and sponsors (same app; Databricks Apps handles the sign-in) ----
# GET  /                  page: pick a saved correction notice (or paste SRU XML) and see the annotated title
# GET  /api/examples      saved notices: [{file_name, row, correction_id, correction_title}]
# POST /api/annotate      {"file_name": "..."} or {"xml": "...", "search_title": "", "correction_id": ""}
# GET  /api/annotate-all  every saved notice, annotated (about a second in total)
# The page calls the same code as the MCP tools; nothing is written anywhere.
import json
import secrets
import threading
import time

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

MAX_XML_CHARS = 2_000_000
SRU_RECORD_URL = (
    "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve"
    "&recordSchema=mods&query=alma.mms_id%3D"
)
_cache = {"examples": None, "xml": {}}
_cache_lock = threading.Lock()


def _row_number(name: str) -> int:
    m = re.search(r"Row(\d+)", name)
    return int(m.group(1)) if m else 10_000


def _load_examples() -> list:
    """Read every saved SRU response once and keep it in memory (48 small files)."""
    with _cache_lock:
        if _cache["examples"] is not None:
            return _cache["examples"]
        names = sorted(
            (e.name for e in _client().files.list_directory_contents(SRU_DIR)
             if not e.is_directory and e.name.lower().endswith(".xml")),
            key=lambda n: (_row_number(n), n),
        )
        examples = []
        for name in names:
            xml = _read_volume_file(_safe_path(name))
            _cache["xml"][name] = xml
            m = re.search(r"(\d{16})\.xml$", name, re.I)
            cid = m.group(1) if m else ""
            recs = _parse(xml)
            corr = next((r for r in recs if r.is_correction and r.record_id == cid), None) or next(
                (r for r in recs if r.is_correction), None)
            examples.append({"file_name": name, "row": _row_number(name), "correction_id": cid,
                             "correction_title": corr.title if corr else ""})
        _cache["examples"] = examples
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
        result = await asyncio.to_thread(_explain, xml, search_title.strip(), correction_id.strip())
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
            rows.append({"row": ex["row"], "file_name": ex["file_name"], "status": r["status"],
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
    <button type="button" data-row="43">Typical correction</button>
    <button type="button" data-row="41">Two corrections in one response</button>
    <button type="button" data-row="40">Title with a curly apostrophe</button>
    <button type="button" data-row="4">No original article in Alma</button>
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
      var tbl = el("table"); var h = el("tr"); ["Row", "Status", "Correction notice", "Annotated title"].forEach(function (x) { h.append(el("th", null, x)); }); tbl.append(h);
      d.rows.forEach(function (r) {
        var tr = el("tr"); tr.append(el("td", null, String(r.row)));
        var st = el("td"); st.append(el("span", "badge b-" + r.status, (LABELS[r.status] || r.status).split(":")[0])); tr.append(st);
        tr.append(el("td", null, r.correction_title)); tr.append(el("td", null, r.status === "no_original" ? "(none)" : r.annotated_title)); tbl.append(tr);
      });
      box.replaceChildren(el("p", null, summary), tbl);
    } catch (e) { box.replaceChildren(el("p", "error", e.message)); }
  });
  call("api/examples").then(function (d) {
    pick.replaceChildren(el("option", null, "Choose a saved notice (" + d.examples.length + ")")); pick.firstChild.value = "";
    d.examples.forEach(function (x) {
      var o = el("option", null, "Row " + x.row + " - " + (x.correction_title || x.file_name).slice(0, 110)); o.value = x.file_name;
      pick.append(o); byRow[String(x.row)] = x.file_name;
    });
  }).catch(function (e) { pick.replaceChildren(el("option", null, "Could not load saved notices")); statusEl.textContent = e.message; });
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    threading.Thread(target=_warm_cache, daemon=True).start()
    mcp.run(transport="streamable-http")
