"""MCP tool: build_sru_search_url.

Turns an erratum/correction notice title into the NAL Alma production SRU
searchRetrieve URL for the original article. Function first, agent second: it
runs the governed Unity Catalog function users.amanda_xu.build_sru_url on a SQL
warehouse (usually 3-5 s), and asks the agent-sru-syntax Supervisor Agent
(15-90 s) only if that call fails.
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
from sru_server.models import MAX_TITLE_CHARS, CorrectionTitleArg, is_valid_title

log = logging.getLogger("mcp_sru_syntax")

ENDPOINT = settings.serving_endpoint
TIMEOUT_S = settings.agent_timeout_seconds
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
NO_URL_TEXT = (
    "No SRU URL: this notice does not name one original article (for example a "
    "bare 'Correction' or 'Erratum', or a notice for a whole issue), so there is "
    "nothing to search. Check it by hand."
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


def _call_function(title: str) -> str:
    """Run the UC function on the SQL warehouse; return its URL ('' = no URL).

    The title is a bound parameter, never part of the SQL text. Raises on any
    failure, so the caller can fall back to the agent.
    """
    if not settings.sql_warehouse_id:
        raise RuntimeError("SQL_WAREHOUSE_ID is not set")
    from databricks.sdk.service.sql import (
        ExecuteStatementRequestOnWaitTimeout,
        StatementParameterListItem,
        StatementState,
    )

    r = _client().statement_execution.execute_statement(
        warehouse_id=settings.sql_warehouse_id,
        statement=f"SELECT {SQL_FUNCTION}(:title) AS url",
        parameters=[StatementParameterListItem(name="title", value=title)],
        wait_timeout=settings.function_wait_timeout,
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
    if url:
        return f"NAL Alma SRU search URL for the original article:\n{url}"
    return NO_URL_TEXT


def _sru_lookup(title: str, use_agent: bool = False) -> dict:
    """Function first; the agent only if the function call fails or is asked for.

    An empty URL from the function is a real answer (no single original
    article). The agent calls the same function, so asking it as well would only
    add a minute of waiting. Returns {"source": "function" | "agent", "text"}.
    """
    if not use_agent:
        started = time.monotonic()
        try:
            url = _call_function(title)
            log.info(
                "function_ok seconds=%.1f has_url=%s",
                time.monotonic() - started,
                bool(url),
            )
            return {"source": "function", "text": _function_text(url)}
        except Exception as e:  # fall back; never expose the exception text
            log.warning(
                "function_failed_fallback_to_agent exception=%s", type(e).__name__
            )
    return {"source": "agent", "text": _call_agent_with_retry(title)}


def warm_up() -> None:
    """Run the function once at start-up, so the first user skips the cold start."""
    try:
        _call_function("Correction: warm up")
        log.info("function_warm_up ok")
    except Exception as e:
        log.warning("function_warm_up failed exception=%s", type(e).__name__)


def _check_title(title: object) -> None:
    """Reject titles the Pydantic input model (models.BuildSruSearchUrlInput) does
    not accept: not text, empty or over-long. Checked before any function or agent
    call."""
    if not is_valid_title(title):
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
    async def build_sru_search_url(correction_title: CorrectionTitleArg) -> str:
        """Turn an erratum/correction notice title (e.g. 'Correction: <title>',
        'Correction to \u201c<title>\u201d', 'Corrigendum: ...') into the NAL Alma
        production SRU searchRetrieve URL for the original article. Pass the full
        title exactly as given. Runs the governed SQL function
        users.amanda_xu.build_sru_url first (usually 3-5 seconds); only if that
        fails, asks the agent-sru-syntax agent (15-90 seconds). If the notice names
        no single original article, says so and returns no URL.

        Errors are returned as a short message that says what to do, with a stable
        category (invalid_input, timeout, unavailable, rate_limited,
        permission_denied, not_found, bad_request, bad_response, empty_reply,
        internal) and an error id for the app owner. An empty reply, a busy agent
        or a temporary outage is retried once; timeouts are not."""
        try:
            _check_title(correction_title)
            found = await asyncio.to_thread(_sru_lookup, correction_title)
            text = found["text"]
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
