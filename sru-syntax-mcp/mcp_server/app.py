"""Custom MCP server (streamable HTTP at /mcp) with one tool, build_sru_search_url.

Function first, agent second: the tool and the page first run the governed Unity Catalog function
users.amanda_xu.build_sru_url on a SQL warehouse (usually 3-5 s). Only if that call fails do they ask the
Agent Bricks Supervisor Agent "agent-sru-syntax" (serving endpoint mas-c8629507-endpoint, 15-90 s).

The same app also hosts the SRU syntax agent (agent.py), which uses this MCP server:
  POST /invocations and POST /responses  - OpenAI Responses-style request: {"input": [...] or "text"}
  GET  /health                           - liveness check
and a browser page for librarians:
  GET  /                                 - paste one correction title, get the SRU URL as a link
  POST /api/sru-url                      - JSON {"title": "..."} -> {"text": ..., "urls": [...]}
"""
import asyncio
import logging
import os
import re
import secrets
import threading
import time
import uuid

import requests
import uvicorn
from databricks.sdk import WorkspaceClient
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

ENDPOINT = os.environ.get("SERVING_ENDPOINT", "mas-c8629507-endpoint")
TIMEOUT_S = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "300"))
MAX_TITLE_CHARS = 1000
SQL_FUNCTION = "users.amanda_xu.build_sru_url"
WAREHOUSE_ID = os.environ.get("SQL_WAREHOUSE_ID", "")
FUNCTION_WAIT = os.environ.get("FUNCTION_WAIT_TIMEOUT", "40s")  # SQL API wait, 5s-50s; then fall back to the agent
NO_URL_TEXT = (
    "No SRU URL: this notice does not name one original article (for example a bare 'Correction' or "
    "'Erratum', or a notice for a whole issue), so there is nothing to search. Check it by hand."
)
SRU_PREFIX = "https://nal.alma.exlibrisgroup.com/view/sru/"
RETRY_DEFAULT_WAIT_S = 2.0  # wait before retrying a busy (429) or unavailable agent
RETRY_MAX_WAIT_S = 10.0  # cap on a Retry-After header, so the one retry stays short
OTHER_LINK_NOTE = (
    "Note from mcp-sru-syntax: this reply contains a link that is not a NAL Alma "
    f"SRU search URL. Do not use it; use only URLs that start with {SRU_PREFIX}"
)
_LINK_RE = re.compile(r"https?://[^\s<>\"'`]+")
_sleep = time.sleep  # tests replace this to skip the wait

_ws = WorkspaceClient()  # app service principal credentials from the Apps environment

# Server-side logs carry only allowlisted fields (error id, category, status code, exception class).
# Upstream bodies, headers, URLs, titles and exception text are never logged or returned to clients.
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines include request URLs
log = logging.getLogger("mcp_sru_syntax")


class UpstreamError(Exception):
    """A failed request, with a stable category that is safe to show clients.

    Covers bad input, failures calling the Supervisor Agent, and empty replies. Each message says what
    happened and what to do. Messages never include upstream bodies, URLs, titles or exception text.
    """

    MESSAGES = {
        "invalid_input": f"Send one correction notice title as plain text (1 to {MAX_TITLE_CHARS:,} characters).",
        "timeout": (
            f"The SRU syntax agent did not answer within {TIMEOUT_S} seconds. Try again in a few minutes, "
            f"or use the SQL function {SQL_FUNCTION} for this title."
        ),
        "unavailable": (
            "The SRU syntax agent is unavailable right now; it may be starting up or restarting. "
            "Try again in a few minutes."
        ),
        "rate_limited": (
            "The SRU syntax agent is busy. Wait a minute and send one title at a time; for long lists, "
            f"use the SQL function {SQL_FUNCTION}."
        ),
        "permission_denied": (
            "This app is not allowed to call the SRU syntax agent. Contact the app owner and include this error id."
        ),
        "not_found": (
            "The SRU syntax agent endpoint was not found, so the app is misconfigured. "
            "Contact the app owner and include this error id."
        ),
        "bad_request": (
            "The SRU syntax agent rejected the request. Check that the title is plain text of at most "
            f"{MAX_TITLE_CHARS:,} characters; if it is, contact the app owner and include this error id."
        ),
        "bad_response": (
            "The SRU syntax agent sent a reply the app could not read. This usually means the app's service "
            f"principal is missing a permission (CAN QUERY on the agent endpoint, or EXECUTE on {SQL_FUNCTION}). "
            "Contact the app owner and include this error id."
        ),
        "empty_reply": (
            "The SRU syntax agent returned an empty reply for this title, also after one retry. For a few "
            f"titles this happens every time, so trying again is unlikely to help. Use the SQL function "
            f"{SQL_FUNCTION} for this title, or send the title and this error id to the app owner."
        ),
        "internal": (
            "Something went wrong inside the app. Try again; if it keeps happening, contact the app owner "
            "and include this error id."
        ),
    }
    # Fast, temporary failures worth one more try. Timeouts are not retried (a slow failure would double
    # the wait); configuration errors would fail again.
    RETRYABLE = frozenset({"unavailable", "rate_limited"})

    def __init__(self, category: str, status_code: int | None = None, retry_after: float | None = None):
        self.category = category
        self.status_code = status_code
        self.retry_after = retry_after  # seconds, from a Retry-After header
        self.retried = False  # True when this error came from the one retry
        self.error_id = uuid.uuid4().hex[:12]
        super().__init__(category)

    def client_message(self) -> str:
        message = self.MESSAGES[self.category]
        if self.retried and self.category != "empty_reply":
            message += " The app already retried once."
        return f"{message} (error {self.category}, id {self.error_id})"


def _category_for_status(status: int) -> str:
    if status in (401, 403):
        return "permission_denied"
    if status == 404:
        return "not_found"
    if status in (400, 413, 422):
        return "bad_request"
    if status == 429:
        return "rate_limited"
    if status in (408, 504):
        return "timeout"
    return "unavailable"


def _retry_after_seconds(value: object) -> float | None:
    """Seconds from a numeric Retry-After header; None if absent or not a number."""
    if not isinstance(value, str):
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None

mcp = FastMCP(
    "mcp-sru-syntax",
    instructions="Converts erratum/correction notice titles into NAL Alma production SRU search URLs "
    "for the original article, using the agent-sru-syntax agent.",
    host="0.0.0.0",  # behind the Apps proxy; avoids localhost-only Host-header checks
    stateless_http=True,
    json_response=True,
)


def _final_text(resp: dict) -> str:
    texts = []
    for item in resp.get("output") or []:
        for c in item.get("content") or []:
            if isinstance(c, dict) and c.get("text"):
                texts.append(c["text"])
    return texts[-1].strip() if texts else ""


def _call_agent(title: str) -> str:
    headers = _ws.config.authenticate()
    headers["Content-Type"] = "application/json"
    try:
        r = requests.post(
            f"{_ws.config.host}/serving-endpoints/{ENDPOINT}/invocations",
            headers=headers,
            json={"input": [{"role": "user", "content": title}]},  # title passed through unchanged
            timeout=TIMEOUT_S,
            allow_redirects=False,
        )
    except requests.Timeout:
        raise UpstreamError("timeout") from None
    except requests.RequestException:
        raise UpstreamError("unavailable") from None
    if r.status_code != 200:
        headers = getattr(r, "headers", None) or {}
        raise UpstreamError(
            _category_for_status(r.status_code),
            r.status_code,
            retry_after=_retry_after_seconds(headers.get("Retry-After")),
        )
    try:
        return _final_text(r.json())
    except ValueError:
        raise UpstreamError("bad_response", r.status_code) from None


def _call_agent_with_retry(title: str) -> str:
    """Call the agent, retrying at most once; return a non-empty reply or raise.

    Retried once: an empty reply (these come back in a few seconds), a busy agent (429) and a temporary
    outage (502/503, connection error), after the agent's Retry-After or 2 s, capped at 10 s. Not
    retried: timeouts, so a slow failure never doubles the wait, and permission or configuration
    errors, which would fail again. In testing (2026-11-19) the retry recovered none of the 10 titles
    that got empty replies, so an empty reply after the retry raises empty_reply.
    """
    try:
        text = _call_agent(title)
    except UpstreamError as e:
        if e.category not in UpstreamError.RETRYABLE:
            raise
        wait = min(RETRY_MAX_WAIT_S, RETRY_DEFAULT_WAIT_S if e.retry_after is None else e.retry_after)
        log.info("upstream_retry reason=%s status=%s wait_s=%.1f", e.category, e.status_code, wait)
        _sleep(wait)
        reason = "upstream_retry"
    else:
        if text.strip():
            return text
        log.info("empty_agent_reply retrying=1")
        reason = "empty_agent_reply"
    try:
        text = _call_agent(title)
    except UpstreamError as e:
        e.retried = True
        log.info("%s retry_result=%s", reason, e.category)
        raise
    log.info("%s retry_result=%s", reason, "ok" if text.strip() else "empty")
    if not text.strip():
        err = UpstreamError("empty_reply")
        err.retried = True
        raise err
    return text


def _call_function(title: str) -> str:
    """Run the governed UC function on the SQL warehouse; return its URL ('' = no single original article).

    The title is a bound parameter, never part of the SQL text. Raises on any failure, so the caller can
    fall back to the agent.
    """
    if not WAREHOUSE_ID:
        raise RuntimeError("SQL_WAREHOUSE_ID is not set")
    from databricks.sdk.service.sql import (
        ExecuteStatementRequestOnWaitTimeout,
        StatementParameterListItem,
        StatementState,
    )

    r = _ws.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=f"SELECT {SQL_FUNCTION}(:title) AS url",
        parameters=[StatementParameterListItem(name="title", value=title)],
        wait_timeout=FUNCTION_WAIT,
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
    )
    if r.status is None or r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"statement state {getattr(r.status, 'state', None)}")
    rows = (r.result.data_array if r.result else None) or [[None]]
    url = (rows[0][0] or "").strip()
    if url and not url.startswith(SRU_PREFIX):
        raise RuntimeError("function returned a non-SRU URL")
    return url


def _function_text(url: str) -> str:
    return f"NAL Alma SRU search URL for the original article:\n{url}" if url else NO_URL_TEXT


def _sru_lookup(title: str, use_agent: bool = False) -> dict:
    """Function first; the agent only if the function call fails (or when use_agent is asked for).

    An empty URL from the function is a real answer (no single original article). The agent calls the same
    function, so asking it as well would only add a minute of waiting.
    """
    if not use_agent:
        started = time.monotonic()
        try:
            url = _call_function(title)
            log.info("function_ok seconds=%.1f has_url=%s", time.monotonic() - started, bool(url))
            return {"source": "function", "text": _function_text(url)}
        except Exception as e:  # any failure: fall back to the agent; never expose the exception text
            log.warning("function_failed_fallback_to_agent exception=%s", type(e).__name__)
    return {"source": "agent", "text": _call_agent_with_retry(title)}


# ---- MLflow tracing of every tool and page lookup (for online evaluation) ----
# Each lookup becomes one trace in the app's experiment (MLFLOW_EXPERIMENT_ID, the app-experiment resource),
# with the title as input, the reply text as output, and tags channel (mcp or page) and answered_by
# (function or agent). Calls from the app's own agent (/invocations) reach the tool over /mcp, so they are
# traced here too, as channel mcp, in addition to the agent's own trace. Tracing is best effort: it is set up
# only when the app starts (not on import, so tests stay offline), and if MLflow cannot be set up the app
# runs untraced. MCP_TRACING=off turns it off.
TRACE_EXPERIMENT_ID = os.environ.get("MLFLOW_EXPERIMENT_ID", "").strip()
_mlflow = None  # the mlflow module once tracing is on


def _init_tracing() -> None:
    global _mlflow
    if not TRACE_EXPERIMENT_ID or os.environ.get("MCP_TRACING", "on").strip().lower() == "off":
        log.info("tracing_off reason=not_configured")
        return
    try:
        import mlflow

        mlflow.set_tracking_uri("databricks")
        mlflow.set_experiment(experiment_id=TRACE_EXPERIMENT_ID)
        _mlflow = mlflow
        log.info("tracing_on")
    except Exception as e:  # never stop the app because tracing could not start
        log.warning("tracing_off exception=%s", type(e).__name__)


def _traced_lookup(title: str, use_agent: bool, channel: str) -> dict:
    """_sru_lookup, recorded as one MLflow trace when tracing is on."""
    if _mlflow is None:
        return _sru_lookup(title, use_agent)
    with _mlflow.start_span(name="build_sru_search_url", span_type="TOOL") as span:
        span.set_inputs({"correction_title": title, "use_agent": use_agent})
        _mlflow.update_current_trace(tags={"app": "mcp-sru-syntax", "channel": channel})
        found = _sru_lookup(title, use_agent)  # an UpstreamError is recorded on the span, then re-raised
        text = _checked_reply(found["text"])
        span.set_outputs({"text": text, "answered_by": found["source"]})
        _mlflow.update_current_trace(tags={"answered_by": found["source"]})
        return found


def _warm_up() -> None:
    """Run the function once at start-up, so the first librarian does not wait for a cold Python UDF."""
    try:
        _call_function("Correction: warm up")
        log.info("function_warm_up ok")
    except Exception as e:
        log.warning("function_warm_up failed exception=%s", type(e).__name__)


def _check_title(title: object) -> None:
    """Reject empty or over-long titles before calling the agent."""
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE_CHARS:
        raise UpstreamError("invalid_input")


def _checked_reply(text: str) -> str:
    """Flag links in the reply that are not NAL Alma SRU URLs (not seen in testing)."""
    other = [u for u in _LINK_RE.findall(text) if not u.startswith(SRU_PREFIX)]
    if not other:
        return text
    log.warning("reply_has_other_links count=%d", len(other))
    return f"{text}\n\n{OTHER_LINK_NOTE}"


@mcp.tool(
    annotations=ToolAnnotations(
        title="Build NAL Alma SRU search URL",
        readOnlyHint=True,  # only reads; creates or changes nothing
        destructiveHint=False,
        idempotentHint=True,  # same title, same intent; safe to retry
        openWorldHint=False,  # calls only this workspace's Supervisor Agent endpoint
    )
)
async def build_sru_search_url(correction_title: str) -> str:
    """Turn an erratum/correction notice title (e.g. 'Correction: <title>', 'Correction to “<title>”',
    'Corrigendum: ...') into the NAL Alma production SRU searchRetrieve URL for the original article.
    Pass the full title exactly as given. Runs the governed SQL function users.amanda_xu.build_sru_url
    first (usually 3-5 seconds); only if that fails, asks the agent-sru-syntax agent (15-90 seconds).
    If the notice names no single original article, says so and returns no URL.

    Errors are returned as a short message that says what to do, with a stable category (invalid_input,
    timeout, unavailable, rate_limited, permission_denied, not_found, bad_request, bad_response,
    empty_reply, internal) and an error id for the app owner. An empty reply, a busy agent or a
    temporary outage is retried once; timeouts are not."""
    try:
        _check_title(correction_title)
        text = (await asyncio.to_thread(_traced_lookup, correction_title, False, "mcp"))["text"]
    except UpstreamError as e:
        log.warning(
            "tool_error error_id=%s category=%s status=%s retried=%s", e.error_id, e.category, e.status_code, e.retried
        )
        raise ToolError(e.client_message()) from None
    except Exception as e:  # anything unexpected (e.g. auth setup): never expose its text
        err = UpstreamError("internal")
        log.warning("tool_error error_id=%s category=unexpected exception=%s", err.error_id, type(e).__name__)
        raise ToolError(err.client_message()) from None
    return _checked_reply(text)


app = mcp.streamable_http_app()  # serves the MCP endpoint at /mcp


class NoGetStreamMiddleware:
    """Answer GET /mcp with 405 right away. In stateless mode the server offers no standalone SSE stream,
    so a GET would otherwise hang; the MCP spec allows 405 here, and clients then use POST only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"].rstrip("/") == "/mcp":
            response = JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Method Not Allowed"}},
                status_code=405,
                headers={"Allow": "POST, DELETE"},
            )
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def _allowed_origins() -> list[str]:
    """The workspace URL (Genie Code calls /mcp from the browser), plus any extra in ALLOWED_ORIGINS."""
    host = (_ws.config.host or os.environ.get("DATABRICKS_HOST", "")).rstrip("/")
    if host and not host.startswith("http"):
        host = f"https://{host}"
    extra = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return [o for o in [host, *extra] if o]


app.add_middleware(NoGetStreamMiddleware)
app.add_middleware(  # added last, so it runs first and answers CORS preflight (OPTIONS) requests
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["mcp-session-id", "mcp-protocol-version"],
)


# ---- SRU syntax agent endpoints (same app) ----

async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def invocations(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be JSON"}, status_code=400)
    messages = body.get("input") if isinstance(body, dict) else None
    if not isinstance(messages, (str, list)) or not messages:
        return JSONResponse({"error": "Body must include 'input' (a string or a list of messages)"}, status_code=400)
    try:
        from agent import run_agent  # imported lazily so the MCP tool keeps working if agent setup fails

        text = await run_agent(messages)
    except Exception as e:
        error_id = uuid.uuid4().hex[:12]
        log.warning("agent_error error_id=%s exception=%s", error_id, type(e).__name__)
        return JSONResponse(
            {"error": f"The SRU syntax agent could not complete the request. Try again later. (error agent_failed, id {error_id})"},
            status_code=502,
        )
    return JSONResponse(
        {
            "id": f"resp_{uuid.uuid4().hex}",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": f"msg_{uuid.uuid4().hex}",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text or "", "annotations": []}],
                }
            ],
        }
    )


# ---- Browser page for librarians (same app; Databricks Apps handles the login) ----

_SRU_URL_RE = re.compile(re.escape(SRU_PREFIX) + r"[^\s<>\"'`]+")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAL SRU search URL from a correction title</title>
<style nonce="__NONCE__">
  body { font-family: system-ui, -apple-system, "Segoe UI", Arial, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; color: #1b1b1b; line-height: 1.5; }
  h1 { font-size: 1.5rem; margin-bottom: .25rem; }
  label { font-weight: 600; display: block; margin: 1rem 0 .25rem; }
  textarea { width: 100%; box-sizing: border-box; font: inherit; padding: .5rem; min-height: 5rem; }
  button { font: inherit; padding: .45rem 1rem; margin-top: .5rem; cursor: pointer; }
  #status { margin-top: 1rem; color: #4a4a4a; }
  #result { margin-top: .5rem; }
  .url { word-break: break-all; display: block; margin: .25rem 0; }
  .error { color: #b50909; }
  .hint { color: #4a4a4a; font-size: .92rem; }
</style>
</head>
<body>
<h1>SRU search URL from a correction title</h1>
<p class="hint">Paste one erratum or correction notice title, for example
<em>Correction: Zinc Amendment Prompts Phytotoxic to Beneficial Effects in Safflower Growth and Physiological Functions Under Calcareous Soil and Saline Water Conditions</em>. You get the NAL Alma
production SRU searchRetrieve URL for the original article. Open it to see the matching Alma record.</p>
<p class="hint">Here are two more examples:</p>
<ul class="hint">
  <li><em>Correction to: From Concept to Curriculum and Competencies: Results of a Survey on Teaching of Integrative Forest Management at Higher Education Institutions Across Europe</em></li>
  <li><em>Correction: Comparison of manual and automated methods in the hematological evaluation of a frugivorous bat captured in urban green areas</em></li>
</ul>
<form id="f">
  <label for="title">Correction title</label>
  <textarea id="title" name="title" maxlength="__MAX__" required></textarea>
  <button type="submit" id="go">Get SRU URL</button>
</form>
<div id="status" role="status" aria-live="polite"></div>
<div id="result"></div>
<p class="hint">Answers usually take 3-5 seconds: the page runs the governed SQL function
<code>users.amanda_xu.build_sru_url</code> first and asks the AI agent (up to a minute) only if that fails.
One title per request; for long lists, call the SQL function directly. Copy URLs as they are; do not edit
the encoding.</p>
<script nonce="__NONCE__">
(function () {
  var PREFIX = "__PREFIX__";
  var form = document.getElementById("f"), btn = document.getElementById("go");
  var statusEl = document.getElementById("status"), out = document.getElementById("result");
  function para(text, cls) { var p = document.createElement("p"); p.textContent = text; if (cls) p.className = cls; return p; }
  var SOURCES = { "function": "Answered by the governed SQL function", "agent": "Answered by the AI agent" };
  form.addEventListener("submit", function (ev) { ev.preventDefault(); run(false); });
  async function run(useAgent) {
    var title = document.getElementById("title").value.trim();
    if (!title) return;
    btn.disabled = true; out.replaceChildren();
    statusEl.textContent = useAgent ? "Asking the AI agent... this can take up to a minute." : "Working... usually 3-5 seconds.";
    var source = "";
    var started = Date.now(), ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 300000);
    try {
      var r = await fetch("api/sru-url", { method: "POST", credentials: "same-origin", signal: ctrl.signal,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title, use_agent: useAgent }) });
      var data = null; try { data = await r.json(); } catch (e) { data = null; }
      if (!data) { out.append(para("Your sign-in may have expired. Reload the page and try again.", "error")); return; }
      if (!r.ok) { out.append(para(data.error || ("Request failed (HTTP " + r.status + ")."), "error")); return; }
      source = SOURCES[data.source] || "";
      var urls = (data.urls || []).filter(function (u) { return typeof u === "string" && u.indexOf(PREFIX) === 0; });
      if (urls.length) {
        urls.forEach(function (u) {
          var a = document.createElement("a"); a.href = u; a.textContent = u; a.className = "url";
          a.target = "_blank"; a.rel = "noopener noreferrer"; out.append(a);
          var c = document.createElement("button"); c.type = "button"; c.textContent = "Copy URL";
          c.addEventListener("click", function () { navigator.clipboard.writeText(u).then(function () { c.textContent = "Copied"; }); });
          out.append(c);
        });
      } else {
        out.append(para(data.text || "No SRU URL in the reply. Try again, or use the SQL function."));
        if (data.source === "function") {
          var ask = document.createElement("button"); ask.type = "button"; ask.textContent = "Ask the AI agent instead (up to a minute)";
          ask.addEventListener("click", function () { run(true); }); out.append(ask);
        }
      }
    } catch (e) {
      out.append(para(e && e.name === "AbortError" ? "No reply after 5 minutes. Try again later."
        : "Could not reach the app. Your sign-in may have expired; reload the page and try again.", "error"));
    } finally {
      clearTimeout(timer); btn.disabled = false;
      statusEl.textContent = "Done in " + Math.round((Date.now() - started) / 1000) + " s." + (source ? " " + source + "." : "");
    }
  }
})();
</script>
</body>
</html>
"""


async def index(request: Request) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    html = (
        PAGE.replace("__NONCE__", nonce).replace("__PREFIX__", SRU_PREFIX).replace("__MAX__", str(MAX_TITLE_CHARS))
    )
    return HTMLResponse(
        html,
        headers={
            # only this page's own inline script and style may run; it may only call this app
            "Content-Security-Policy": (
                f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                "connect-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'"
            ),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        },
    )


async def sru_url_api(request: Request) -> JSONResponse:
    """JSON API behind the page: {"title": "..."} -> {"text": agent reply, "urls": [SRU URLs in it]}."""
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        # also blocks plain cross-site HTML form posts, which cannot send application/json
        return JSONResponse({"error": "Send JSON: {\"title\": \"...\"}"}, status_code=415)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be JSON"}, status_code=400)
    title = body.get("title") if isinstance(body, dict) else None
    use_agent = isinstance(body, dict) and body.get("use_agent") is True
    if not isinstance(title, str) or not title.strip():
        return JSONResponse({"error": "Body must include 'title' (the correction title)"}, status_code=400)
    if len(title) > MAX_TITLE_CHARS:
        return JSONResponse({"error": f"Title is longer than {MAX_TITLE_CHARS} characters"}, status_code=400)
    try:
        found = await asyncio.to_thread(_traced_lookup, title.strip(), use_agent, "page")
    except UpstreamError as e:
        log.warning(
            "page_error error_id=%s category=%s status=%s retried=%s", e.error_id, e.category, e.status_code, e.retried
        )
        return _upstream_error(e)
    except Exception as e:  # never expose unexpected exception text
        err = UpstreamError("internal")
        log.warning("page_error error_id=%s category=unexpected exception=%s", err.error_id, type(e).__name__)
        return _upstream_error(err)
    text = _checked_reply(found["text"])
    urls = [u.rstrip(").,;") for u in _SRU_URL_RE.findall(text)]
    return JSONResponse({"text": text, "urls": list(dict.fromkeys(urls)), "source": found["source"]})


_ERROR_STATUS = {"invalid_input": 400, "timeout": 504, "rate_limited": 429}


def _upstream_error(e: UpstreamError) -> JSONResponse:
    """Error reply for the page: the message, plus its category and error id."""
    return JSONResponse(
        {"error": e.client_message(), "category": e.category, "error_id": e.error_id},
        status_code=_ERROR_STATUS.get(e.category, 502),
    )


app.add_route("/", index, methods=["GET"])
app.add_route("/api/sru-url", sru_url_api, methods=["POST"])
app.add_route("/health", health, methods=["GET"])
app.add_route("/invocations", invocations, methods=["POST"])
app.add_route("/responses", invocations, methods=["POST"])

if __name__ == "__main__":
    _init_tracing()
    if WAREHOUSE_ID:
        threading.Thread(target=_warm_up, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
