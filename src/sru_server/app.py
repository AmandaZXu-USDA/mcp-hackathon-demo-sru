"""MCP server entry point for the NAL SRU Syntax MCP server.

Creates a FastMCP instance (mcp 1.x, stateless HTTP), registers the
build_sru_search_url tool, and serves the MCP endpoint at /mcp. Also hosts
the SRU syntax agent at /invocations and /responses, plus /health, and a
browser page for librarians: GET / (paste one correction title, get the SRU URL
as a link) backed by POST /api/sru-url ({"title": "..."} -> {"text", "urls"}).

Genie Code calls /mcp from the browser, so the app allows CORS from the
workspace URL (DATABRICKS_HOST, set by Databricks Apps) plus any origins in
ALLOWED_ORIGINS, and answers GET /mcp with 405 (no standalone SSE stream in
stateless mode).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import threading
import uuid
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from sru_server.config import settings
from sru_server.tools import build_sru_url as agent_tool
from sru_server.tools import register_tools

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("mcp_sru_syntax")

mcp = FastMCP(
    "mcp-sru-syntax",
    instructions=(
        "Converts erratum/correction notice titles into NAL Alma production SRU "
        "search URLs for the original article, using the agent-sru-syntax agent."
    ),
    host="0.0.0.0",
    stateless_http=True,
    json_response=True,
)

register_tools(mcp)

app = mcp.streamable_http_app()


class NoGetStreamMiddleware:
    """Answer GET /mcp with 405 right away.

    In stateless mode the server offers no standalone SSE stream, so a GET would
    otherwise hang. The MCP spec allows 405 here; clients then use POST only.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        is_get_mcp = (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and scope["path"].rstrip("/") == "/mcp"
        )
        if is_get_mcp:
            response = JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Method Not Allowed"},
                },
                status_code=405,
                headers={"Allow": "POST, DELETE"},
            )
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def _allowed_origins() -> list[str]:
    """Workspace URL (DATABRICKS_HOST) plus any extra origins in ALLOWED_ORIGINS."""
    host = os.environ.get("DATABRICKS_HOST", "").strip().rstrip("/")
    if host and not host.startswith("http"):
        host = f"https://{host}"
    extra = os.environ.get("ALLOWED_ORIGINS", "").split(",")
    origins = [host, *(o.strip().rstrip("/") for o in extra)]
    return [o for o in origins if o]


app.add_middleware(NoGetStreamMiddleware)
app.add_middleware(  # added last, so it runs first and answers CORS preflight
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["mcp-session-id", "mcp-protocol-version"],
)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "mcp-sru-syntax"})


async def invocations(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be JSON"}, status_code=400)
    messages = body.get("input") if isinstance(body, dict) else None
    if not isinstance(messages, (str, list)) or not messages:
        return JSONResponse({"error": "Body must include input"}, status_code=400)
    try:
        from sru_server.agent import run_agent

        text = await run_agent(messages)
    except Exception as e:
        error_id = uuid.uuid4().hex[:12]
        log.warning("agent_error error_id=%s exception=%s", error_id, type(e).__name__)
        return JSONResponse({"error": f"Agent failed (id {error_id})"}, status_code=502)
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
                    "content": [
                        {"type": "output_text", "text": text or "", "annotations": []}
                    ],
                }
            ],
        }
    )


# ---- Browser page for librarians (Databricks Apps handles the login) ----

SRU_PREFIX = "https://nal.alma.exlibrisgroup.com/view/sru/"
MAX_TITLE_CHARS = 1000
_SRU_URL_RE = re.compile(re.escape(SRU_PREFIX) + r"[^\s<>\"'`]+")
PAGE = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


async def index(request: Request) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    html = (
        PAGE.replace("__NONCE__", nonce)
        .replace("__PREFIX__", SRU_PREFIX)
        .replace("__MAX__", str(MAX_TITLE_CHARS))
    )
    # only this page's own inline script and style may run; it may only call this app
    csp = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; "
        f"style-src 'nonce-{nonce}'; connect-src 'self'; img-src 'self'; "
        "form-action 'self'; base-uri 'none'"
    )
    headers = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }
    return HTMLResponse(html, headers=headers)


def _json_error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


_ERROR_STATUS = {"invalid_input": 400, "timeout": 504, "rate_limited": 429}


def _upstream_error(e: agent_tool.UpstreamError) -> JSONResponse:
    """Error reply for the page: the message, plus its category and error id."""
    return JSONResponse(
        {"error": e.client_message(), "category": e.category, "error_id": e.error_id},
        status_code=_ERROR_STATUS.get(e.category, 502),
    )


async def sru_url_api(request: Request) -> JSONResponse:
    """JSON API behind the page.

    {"title": "...", "use_agent": false} -> {"text", "urls", "source"}, where
    source is "function" or "agent".
    """
    content_type = request.headers.get("content-type", "").lower()
    if not content_type.startswith("application/json"):
        # also blocks plain cross-site HTML form posts, which cannot send JSON
        return _json_error('Send JSON: {"title": "..."}', 415)
    try:
        body = await request.json()
    except Exception:
        return _json_error("Request body must be JSON", 400)
    title = body.get("title") if isinstance(body, dict) else None
    use_agent = isinstance(body, dict) and body.get("use_agent") is True
    if not isinstance(title, str) or not title.strip():
        return _json_error("Body must include 'title' (the correction title)", 400)
    if len(title) > MAX_TITLE_CHARS:
        return _json_error(f"Title is longer than {MAX_TITLE_CHARS} characters", 400)
    try:
        found = await asyncio.to_thread(
            agent_tool._sru_lookup, title.strip(), use_agent
        )
    except agent_tool.UpstreamError as e:
        log.warning(
            "page_error error_id=%s category=%s status=%s retried=%s",
            e.error_id,
            e.category,
            e.status_code,
            e.retried,
        )
        return _upstream_error(e)
    except Exception as e:  # never expose unexpected exception text
        err = agent_tool.UpstreamError("internal")
        log.warning(
            "page_error error_id=%s category=unexpected exception=%s",
            err.error_id,
            type(e).__name__,
        )
        return _upstream_error(err)
    text = agent_tool._checked_reply(found["text"])
    urls = [u.rstrip(").,;") for u in _SRU_URL_RE.findall(text)]
    return JSONResponse(
        {"text": text, "urls": list(dict.fromkeys(urls)), "source": found["source"]}
    )


app.add_route("/", index, methods=["GET"])
app.add_route("/api/sru-url", sru_url_api, methods=["POST"])
app.add_route("/health", health, methods=["GET"])
app.add_route("/invocations", invocations, methods=["POST"])
app.add_route("/responses", invocations, methods=["POST"])


def main() -> None:
    platform_port = os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT")
    if settings.sql_warehouse_id and (
        platform_port or settings.mcp_transport == "streamable-http"
    ):
        threading.Thread(target=agent_tool.warm_up, daemon=True).start()
    if platform_port:
        uvicorn.run(app, host="0.0.0.0", port=int(platform_port))
    elif settings.mcp_transport == "streamable-http":
        uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
