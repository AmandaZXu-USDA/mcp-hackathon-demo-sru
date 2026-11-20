"""Tests for the browser page (GET /, POST /api/sru-url), retries and error messages.

The agent call (_call_agent) is replaced with a stub, so no Databricks credentials
or network access are needed.
"""

from __future__ import annotations

import re

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from sru_server.app import app, mcp
from sru_server.tools import build_sru_url as tool

SRU_URL = (
    "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2"
    "&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22X%22"
)


def stub_agent(monkeypatch, *replies):
    """Make _call_agent return (or raise) each reply in turn; return the call log."""
    calls: list[str] = []

    def fake(title: str) -> str:
        calls.append(title)
        reply = replies[len(calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(tool, "_call_agent", fake)
    return calls


@pytest.fixture(autouse=True)
def retry_waits(monkeypatch):
    """Record retry waits instead of sleeping."""
    waits: list[float] = []
    monkeypatch.setattr(tool, "_sleep", waits.append)
    return waits


async def call_tool_text(title: str) -> str:
    result = await mcp.call_tool("build_sru_search_url", {"correction_title": title})
    content = result[0] if isinstance(result, tuple) else result
    return content[0].text


# ---- page ----


def test_page_is_served_with_strict_csp():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    csp = r.headers["content-security-policy"]
    nonce = re.search(r"script-src 'nonce-([\w-]+)'", csp).group(1)
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert r.text.count(f'nonce="{nonce}"') == 2  # the page's own script and style
    for placeholder in ("__NONCE__", "__PREFIX__", "__MAX__"):
        assert placeholder not in r.text
    assert 'maxlength="1000"' in r.text
    assert r.headers["x-content-type-options"] == "nosniff"


def test_page_nonce_changes_per_request():
    client = TestClient(app)
    first = client.get("/").headers["content-security-policy"]
    assert client.get("/").headers["content-security-policy"] != first


# ---- /api/sru-url ----


def test_api_returns_only_sru_urls(monkeypatch):
    reply = f"Here: {SRU_URL}. See also https://evil.example/x and <b>x</b>"
    calls = stub_agent(monkeypatch, reply)
    r = TestClient(app).post("/api/sru-url", json={"title": "  Correction: X  "})
    assert r.status_code == 200
    assert r.json()["urls"] == [SRU_URL]
    assert calls == ["Correction: X"]  # surrounding whitespace trimmed


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"data": {"title": "x"}}, 415),  # plain form post
        ({"json": {"title": "   "}}, 400),
        ({"json": {"title": 5}}, 400),
        ({"json": {"title": "x" * 1001}}, 400),
        ({"json": ["x"]}, 400),
    ],
)
def test_api_rejects_bad_input(monkeypatch, kwargs, status):
    calls = stub_agent(monkeypatch)
    assert TestClient(app).post("/api/sru-url", **kwargs).status_code == status
    assert calls == []  # the agent is never called


def test_api_timeout_is_504(monkeypatch):
    stub_agent(monkeypatch, tool.UpstreamError("timeout"))
    r = TestClient(app).post("/api/sru-url", json={"title": "x"})
    assert r.status_code == 504
    assert "error timeout" in r.json()["error"]


def test_api_hides_unexpected_error_text(monkeypatch):
    stub_agent(monkeypatch, RuntimeError("secret internal detail"))
    r = TestClient(app).post("/api/sru-url", json={"title": "x"})
    assert r.status_code == 502
    assert "secret" not in r.text


# ---- retries ----


@pytest.mark.parametrize(
    ("replies", "expected_calls"),
    [((SRU_URL,), 1), (("", SRU_URL), 2), ((" \n", SRU_URL), 2)],
)
async def test_tool_retries_once_on_empty_reply(monkeypatch, replies, expected_calls):
    calls = stub_agent(monkeypatch, *replies)
    assert await call_tool_text("Correction: X") == SRU_URL
    assert len(calls) == expected_calls


@pytest.mark.parametrize("category", ["unavailable", "rate_limited"])
async def test_tool_retries_once_on_temporary_error(monkeypatch, retry_waits, category):
    calls = stub_agent(monkeypatch, tool.UpstreamError(category), SRU_URL)
    assert await call_tool_text("Correction: X") == SRU_URL
    assert len(calls) == 2
    assert retry_waits == [tool.RETRY_DEFAULT_WAIT_S]


@pytest.mark.parametrize(
    ("retry_after", "wait"), [(3.0, 3.0), (60.0, 10.0), (0.0, 0.0)]
)
async def test_retry_waits_for_retry_after_capped(
    monkeypatch, retry_waits, retry_after, wait
):
    busy = tool.UpstreamError("rate_limited", 429, retry_after=retry_after)
    stub_agent(monkeypatch, busy, SRU_URL)
    assert await call_tool_text("x") == SRU_URL
    assert retry_waits == [wait]


@pytest.mark.parametrize(
    "category",
    ["timeout", "permission_denied", "not_found", "bad_request", "bad_response"],
)
async def test_slow_or_config_errors_are_not_retried(
    monkeypatch, retry_waits, category
):
    calls = stub_agent(monkeypatch, tool.UpstreamError(category), SRU_URL)
    with pytest.raises(ToolError, match=f"error {category}, id "):
        await call_tool_text("x")
    assert len(calls) == 1
    assert retry_waits == []


# ---- error messages when the retry fails ----


async def test_tool_empty_reply_after_retry_is_an_error(monkeypatch):
    calls = stub_agent(monkeypatch, "", "")
    with pytest.raises(ToolError) as exc:
        await call_tool_text("Correction: X")
    msg = str(exc.value)
    assert len(calls) == 2
    assert "also after one retry" in msg and tool.SQL_FUNCTION in msg
    assert re.search(r"\(error empty_reply, id [0-9a-f]{12}\)$", msg)
    assert "already retried" not in msg  # said once, in the message itself


async def test_tool_temporary_error_twice_says_it_retried(monkeypatch):
    calls = stub_agent(
        monkeypatch,
        tool.UpstreamError("unavailable"),
        tool.UpstreamError("unavailable"),
    )
    with pytest.raises(ToolError, match="The app already retried once."):
        await call_tool_text("x")
    assert len(calls) == 2


async def test_tool_temporary_error_then_empty_is_empty_reply(monkeypatch):
    stub_agent(monkeypatch, tool.UpstreamError("rate_limited"), "")
    with pytest.raises(ToolError, match="error empty_reply"):
        await call_tool_text("x")


def test_page_api_empty_reply_after_retry(monkeypatch):
    calls = stub_agent(monkeypatch, "", "")
    r = TestClient(app).post("/api/sru-url", json={"title": "x"})
    body = r.json()
    assert len(calls) == 2
    assert r.status_code == 502
    assert body["category"] == "empty_reply"
    assert re.fullmatch(r"[0-9a-f]{12}", body["error_id"])
    assert body["error_id"] in body["error"]


def test_page_api_retries_once_on_empty_reply(monkeypatch):
    calls = stub_agent(monkeypatch, "", SRU_URL)
    body = TestClient(app).post("/api/sru-url", json={"title": "x"}).json()
    assert len(calls) == 2
    assert body["urls"] == [SRU_URL]


@pytest.mark.parametrize(
    ("category", "status"),
    [("rate_limited", 429), ("not_found", 502), ("bad_response", 502)],
)
def test_page_api_error_status_and_category(monkeypatch, category, status):
    err = tool.UpstreamError(category)
    stub_agent(monkeypatch, err, err)
    r = TestClient(app).post("/api/sru-url", json={"title": "x"})
    assert r.status_code == status
    assert r.json()["category"] == category


# ---- input checks and reply checks ----


@pytest.mark.parametrize("title", ["", "   ", "x" * (tool.MAX_TITLE_CHARS + 1)])
async def test_tool_rejects_empty_or_long_title(monkeypatch, title):
    calls = stub_agent(monkeypatch, SRU_URL)
    with pytest.raises(ToolError, match="error invalid_input"):
        await call_tool_text(title)
    assert calls == []


async def test_tool_accepts_title_at_the_limit(monkeypatch):
    calls = stub_agent(monkeypatch, SRU_URL)
    assert await call_tool_text("x" * tool.MAX_TITLE_CHARS) == SRU_URL
    assert len(calls) == 1


async def test_tool_flags_links_that_are_not_sru_urls(monkeypatch):
    stub_agent(monkeypatch, f"Try {SRU_URL} or https://example.com/x")
    text = await call_tool_text("x")
    assert text.endswith(tool.OTHER_LINK_NOTE)


def test_page_api_flags_other_links_and_keeps_only_sru_urls(monkeypatch):
    stub_agent(monkeypatch, f"{SRU_URL} and https://example.com/x")
    body = TestClient(app).post("/api/sru-url", json={"title": "x"}).json()
    assert body["urls"] == [SRU_URL]
    assert body["text"].endswith(tool.OTHER_LINK_NOTE)


def test_every_error_message_says_what_to_do():
    for category, message in tool.UpstreamError.MESSAGES.items():
        assert message.endswith("."), category
        actions = ("try again", "use the sql", "contact the app owner", "send one")
        assert any(a in message.lower() for a in actions), category
