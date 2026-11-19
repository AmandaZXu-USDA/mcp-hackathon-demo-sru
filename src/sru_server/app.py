"""MCP server entry point for the NAL SRU Syntax MCP server.

Creates a FastMCP instance (mcp 1.x, stateless HTTP), registers the
build_sru_search_url tool, and serves the MCP endpoint at /mcp. Also hosts
the SRU syntax agent at /invocations and /responses, plus /health.

Genie Code calls /mcp from the browser, so the app allows CORS from the
workspace URL (DATABRICKS_HOST, set by Databricks Apps) plus any origins in
ALLOWED_ORIGINS, and answers GET /mcp with 405 (no standalone SSE stream in
stateless mode).
"""

from __future__ import annotations

import logging
import os
import uuid

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from sru_server.config import settings
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


app.add_route("/health", health, methods=["GET"])
app.add_route("/invocations", invocations, methods=["POST"])
app.add_route("/responses", invocations, methods=["POST"])


def main() -> None:
    platform_port = os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT")
    if platform_port:
        uvicorn.run(app, host="0.0.0.0", port=int(platform_port))
    elif settings.mcp_transport == "streamable-http":
        uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
