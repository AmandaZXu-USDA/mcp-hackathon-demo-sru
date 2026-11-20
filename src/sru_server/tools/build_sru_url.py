"""MCP tool: build_sru_search_url.

Sends an erratum/correction notice title to the agent-sru-syntax Supervisor
Agent and returns the NAL Alma production SRU searchRetrieve URL for the
original article.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid

import requests
from databricks.sdk import WorkspaceClient
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from sru_server.config import settings

log = logging.getLogger("mcp_sru_syntax")

ENDPOINT = settings.serving_endpoint
TIMEOUT_S = settings.agent_timeout_seconds
MAX_TITLE_CHARS = 1000
SQL_FUNCTION = "users.amanda_xu.build_sru_url"
SRU_PREFIX = "https://nal.alma.exlibrisgroup.com/view/sru/"
RETRY_DEFAULT_WAIT_S = 2.0  # wait before retrying a busy (429) or unavailable agent
RETRY_MAX_WAIT_S = 10.0  # cap on a Retry-After header, so the one retry stays short
OTHER_LINK_NOTE = (
    "Note from mcp-sru-syntax: this reply contains a link that is not a NAL Alma "
    f"SRU search URL. Do not use it; use only URLs that start with {SRU_PREFIX}"
)
_LINK_RE = re.compile(r"https?://[^\s<>\"'`]+")
_sleep = time.sleep  # tests replace this to skip the wait

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
    """A failed request, with a stable category that is safe to show clients.

    Covers bad input, failures calling the Supervisor Agent, and empty replies.
    Each message says what happened and what to do. Messages never include
    upstream response bodies, URLs, titles or exception text.
    """

    MESSAGES = {
        "invalid_input": (
            "Send one correction notice title as plain text "
            f"(1 to {MAX_TITLE_CHARS:,} characters)."
        ),
        "timeout": (
            f"The SRU syntax agent did not answer within {TIMEOUT_S} seconds. Try "
            f"again in a few minutes, or use the SQL function {SQL_FUNCTION} for "
            "this title."
        ),
        "unavailable": (
            "The SRU syntax agent is unavailable right now; it may be starting up "
            "or restarting. Try again in a few minutes."
        ),
        "rate_limited": (
            "The SRU syntax agent is busy. Wait a minute and send one title at a "
            f"time; for long lists, use the SQL function {SQL_FUNCTION}."
        ),
        "permission_denied": (
            "This app is not allowed to call the SRU syntax agent. Contact the app "
            "owner and include this error id."
        ),
        "not_found": (
            "The SRU syntax agent endpoint was not found, so the app is "
            "misconfigured. Contact the app owner and include this error id."
        ),
        "bad_request": (
            "The SRU syntax agent rejected the request. Check that the title is "
            f"plain text of at most {MAX_TITLE_CHARS:,} characters; if it is, "
            "contact the app owner and include this error id."
        ),
        "bad_response": (
            "The SRU syntax agent sent a reply the app could not read. This usually "
            "means the app's service principal is missing a permission (CAN QUERY "
            f"on the agent endpoint, or EXECUTE on {SQL_FUNCTION}). Contact the "
            "app owner and include this error id."
        ),
        "empty_reply": (
            "The SRU syntax agent returned an empty reply for this title, also "
            "after one retry. For a few titles this happens every time, so trying "
            f"again is unlikely to help. Use the SQL function {SQL_FUNCTION} for "
            "this title, or send the title and this error id to the app owner."
        ),
        "internal": (
            "Something went wrong inside the app. Try again; if it keeps "
            "happening, contact the app owner and include this error id."
        ),
    }
    # Fast, temporary failures worth one more try. Timeouts are not retried (a
    # slow failure would double the wait); configuration errors would fail again.
    RETRYABLE = frozenset({"unavailable", "rate_limited"})

    def __init__(
        self,
        category: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
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

    Retried once: an empty reply (these come back in a few seconds), a busy agent
    (429) and a temporary outage (502/503, connection error), after the agent's
    Retry-After or 2 s, capped at 10 s. Not retried: timeouts, so a slow failure
    never doubles the wait, and permission or configuration errors, which would
    fail again. In testing (2026-11-19) the retry recovered none of the 10 titles
    that got empty replies, so an empty reply after the retry raises empty_reply.
    """
    try:
        text = _call_agent(title)
    except UpstreamError as e:
        if e.category not in UpstreamError.RETRYABLE:
            raise
        wait = min(
            RETRY_MAX_WAIT_S,
            RETRY_DEFAULT_WAIT_S if e.retry_after is None else e.retry_after,
        )
        log.info(
            "upstream_retry reason=%s status=%s wait_s=%.1f",
            e.category,
            e.status_code,
            wait,
        )
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

        Errors are returned as a short message that says what to do, with a stable
        category (invalid_input, timeout, unavailable, rate_limited,
        permission_denied, not_found, bad_request, bad_response, empty_reply,
        internal) and an error id for the app owner. An empty reply, a busy agent
        or a temporary outage is retried once; timeouts are not."""
        try:
            _check_title(correction_title)
            text = await asyncio.to_thread(_call_agent_with_retry, correction_title)
        except UpstreamError as e:
            log.warning(
                "tool_error error_id=%s category=%s status=%s retried=%s",
                e.error_id,
                e.category,
                e.status_code,
                e.retried,
            )
            raise ToolError(e.client_message()) from None
        except Exception as e:
            err = UpstreamError("internal")
            log.warning(
                "tool_error error_id=%s category=unexpected exception=%s",
                err.error_id,
                type(e).__name__,
            )
            raise ToolError(err.client_message()) from None
        return _checked_reply(text)
