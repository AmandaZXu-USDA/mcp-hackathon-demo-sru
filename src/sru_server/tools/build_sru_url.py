"""MCP tool: build_sru_search_url.

Sends an erratum/correction notice title to the agent-sru-syntax Supervisor
Agent and returns the NAL Alma production SRU searchRetrieve URL for the
original article.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import requests
from databricks.sdk import WorkspaceClient
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from sru_server.config import settings

log = logging.getLogger("mcp_sru_syntax")

ENDPOINT = settings.serving_endpoint
TIMEOUT_S = settings.agent_timeout_seconds
EMPTY_MSG = (
    "agent-sru-syntax returned an empty reply for this title. This happens for some "
    "titles (for example, ones about inhibiting virus replication). Use the Unity "
    "Catalog function users.amanda_xu.build_sru_url directly for this title."
)

# App service principal credentials from the Apps environment. Created on first use,
# not at import, so the server and its tests load without Databricks credentials.
# Tests replace _ws with a mock.
_ws: WorkspaceClient | None = None


def _client() -> WorkspaceClient:
    global _ws
    if _ws is None:
        _ws = WorkspaceClient()
    return _ws


class UpstreamError(Exception):
    """Failure calling the Supervisor Agent.

    Carries a stable category that is safe to show clients.
    """

    MESSAGES = {
        "timeout": "The SRU syntax agent did not respond in time. Try again later.",
        "unavailable": "The SRU syntax agent is unavailable. Try again later.",
        "rate_limited": "The SRU syntax agent is busy. Wait a moment and try again.",
        "permission_denied": (
            "This app is not allowed to call the SRU syntax agent. Contact the app "
            "owner."
        ),
        "bad_response": (
            "The SRU syntax agent returned an unexpected response. Try again later."
        ),
    }

    def __init__(self, category: str, status_code: int | None = None):
        self.category = category
        self.status_code = status_code
        self.error_id = uuid.uuid4().hex[:12]
        super().__init__(category)

    def client_message(self) -> str:
        return (
            f"{self.MESSAGES[self.category]} "
            f"(error {self.category}, id {self.error_id})"
        )


def _category_for_status(status: int) -> str:
    if status in (401, 403):
        return "permission_denied"
    if status == 429:
        return "rate_limited"
    if status in (408, 504):
        return "timeout"
    return "unavailable"


def _final_text(resp: dict) -> str:
    texts = []
    for item in resp.get("output") or []:
        for c in item.get("content") or []:
            if isinstance(c, dict) and c.get("text"):
                texts.append(c["text"])
    return texts[-1].strip() if texts else ""


def _call_agent(title: str) -> str:
    ws = _client()
    headers = ws.config.authenticate()
    headers["Content-Type"] = "application/json"
    try:
        r = requests.post(
            f"{ws.config.host}/serving-endpoints/{ENDPOINT}/invocations",
            headers=headers,
            json={"input": [{"role": "user", "content": title}]},
            timeout=TIMEOUT_S,
            allow_redirects=False,
        )
    except requests.Timeout:
        raise UpstreamError("timeout") from None
    except requests.RequestException:
        raise UpstreamError("unavailable") from None
    if r.status_code != 200:
        raise UpstreamError(_category_for_status(r.status_code), r.status_code)
    try:
        return _final_text(r.json())
    except ValueError:
        raise UpstreamError("bad_response", r.status_code) from None


def _call_agent_retry_empty(title: str) -> str:
    """Call the agent; if the reply is empty, ask once more.

    Empty replies come back within a few seconds, so the retry costs little. In
    testing (2026-11-19) the 3 titles that got empty replies were empty on every
    try, so this only helps titles whose empty reply is intermittent. Errors
    (timeouts etc.) are not retried, so a slow failure never doubles the wait.
    """
    text = _call_agent(title)
    if not text.strip():
        log.info("empty_agent_reply retrying=1")
        text = _call_agent(title)
        result = "ok" if text.strip() else "empty"
        log.info("empty_agent_reply retry_result=%s", result)
    return text


def register(mcp) -> None:
    """Register the build_sru_search_url tool with the MCP server."""

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Build NAL Alma SRU search URL",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def build_sru_search_url(correction_title: str) -> str:
        """Send an erratum/correction notice title (e.g. 'Correction: <title>',
        'Correction to \u201c<title>\u201d', 'Corrigendum: ...') to the agent-sru-syntax
        agent and return its reply, which contains the NAL Alma production SRU
        searchRetrieve URL for the original article. Pass the full title exactly as
        given. Replies can take 60-90 seconds.

        Errors are returned as a short message with a stable category (timeout,
        unavailable, rate_limited, permission_denied, bad_response) and an error id for
        the app owner."""
        try:
            text = await asyncio.to_thread(_call_agent_retry_empty, correction_title)
        except UpstreamError as e:
            log.warning(
                "tool_error error_id=%s category=%s status=%s",
                e.error_id,
                e.category,
                e.status_code,
            )
            raise ToolError(e.client_message()) from None
        except Exception as e:
            err = UpstreamError("unavailable")
            log.warning(
                "tool_error error_id=%s category=unexpected exception=%s",
                err.error_id,
                type(e).__name__,
            )
            raise ToolError(err.client_message()) from None
        return text or EMPTY_MSG
