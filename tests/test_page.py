"""Tests for the browser page (GET /, POST /api/sru-url) and the empty-reply retry.

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


# ---- retry on empty replies ----


@pytest.mark.parametrize(
    ("replies", "expected_calls", "gets_url"),
    [
        ((SRU_URL,), 1, True),
        (("", SRU_URL), 2, True),
        ((" \n", SRU_URL), 2, True),
        (("", ""), 2, False),
    ],
)
async def test_tool_retries_once_on_empty_reply(
    monkeypatch, replies, expected_calls, gets_url
):
    calls = stub_agent(monkeypatch, *replies)
    text = await call_tool_text("Correction: X")
    assert len(calls) == expected_calls
    assert text == (SRU_URL if gets_url else tool.EMPTY_MSG)


@pytest.mark.parametrize(
    ("replies", "expected_calls", "url_count"),
    [((SRU_URL,), 1, 1), (("", SRU_URL), 2, 1), (("", ""), 2, 0)],
)
def test_page_api_retries_once_on_empty_reply(
    monkeypatch, replies, expected_calls, url_count
):
    calls = stub_agent(monkeypatch, *replies)
    body = TestClient(app).post("/api/sru-url", json={"title": "x"}).json()
    assert len(calls) == expected_calls
    assert len(body["urls"]) == url_count
    if not url_count:
        assert body["text"] == tool.EMPTY_MSG


async def test_errors_are_not_retried(monkeypatch):
    calls = stub_agent(monkeypatch, tool.UpstreamError("timeout"), SRU_URL)
    with pytest.raises(ToolError, match="timeout"):
        await call_tool_text("x")
    assert len(calls) == 1
