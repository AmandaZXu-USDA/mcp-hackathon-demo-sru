"""Regression tests for the sru_server outbound request boundary.

These tests verify that the build_sru_search_url tool hardens against SSRF
and does not leak sensitive upstream data to clients or logs. They mock the
Databricks WorkspaceClient and requests.post so no real network calls happen.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sru_server.tools.build_sru_url import (
    UpstreamError,
    _call_agent,
    _category_for_status,
    _final_text,
)

# ── _category_for_status ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "permission_denied"),
        (403, "permission_denied"),
        (429, "rate_limited"),
        (408, "timeout"),
        (504, "timeout"),
        (500, "unavailable"),
        (502, "unavailable"),
        (404, "unavailable"),
    ],
)
def test_category_for_status(status: int, expected: str) -> None:
    assert _category_for_status(status) == expected


# ── UpstreamError sanitization ──────────────────────────────────────────────


def test_upstream_error_client_message_is_safe() -> None:
    """The client-facing message must not include status codes or response details."""
    err = UpstreamError("timeout", status_code=504)
    msg = err.client_message()
    assert "504" not in msg
    assert "timeout" in msg
    assert err.error_id  # has a unique id for support


def test_upstream_error_categories_have_messages() -> None:
    """Every defined category must have a safe client message."""
    for category in UpstreamError.MESSAGES:
        err = UpstreamError(category)
        assert err.client_message()


# ── _final_text extraction ───────────────────────────────────────────────────


def test_final_text_extracts_last_text_content() -> None:
    resp = {
        "output": [
            {"content": [{"type": "output_text", "text": "first"}]},
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": "https://nal.alma.exlibrisgroup.com/...",
                    }
                ]
            },
        ]
    }
    assert _final_text(resp) == "https://nal.alma.exlibrisgroup.com/..."


def test_final_text_returns_empty_on_no_content() -> None:
    assert _final_text({}) == ""
    assert _final_text({"output": []}) == ""
    assert _final_text({"output": [{"content": []}]}) == ""


def test_final_text_ignores_non_text_content() -> None:
    resp = {"output": [{"content": [{"type": "image", "image_url": "secret"}]}]}
    assert _final_text(resp) == ""


# ── _call_agent security ────────────────────────────────────────────────────


def _mock_ws(host="https://dbc-test.cloud.databricks.com"):
    ws = MagicMock()
    ws.config.host = host
    ws.config.authenticate.return_value = {"Authorization": "Bearer test-token"}
    return ws


@pytest.mark.asyncio
async def test_call_agent_uses_allow_redirects_false() -> None:
    """Requests must use allow_redirects=False to prevent SSRF via redirects."""
    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch("sru_server.tools.build_sru_url.requests.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"output": [{"content": [{"text": "https://nal.alma..."}]}]},
        )
        await _async_call_agent("Correction: Test Title")
        _, kwargs = mock_post.call_args
        assert kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_call_agent_sends_json_content_type() -> None:
    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch("sru_server.tools.build_sru_url.requests.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"output": [{"content": [{"text": "url"}]}]},
        )
        await _async_call_agent("Correction: Title")
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert "Bearer" in kwargs["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_call_agent_url_is_fixed_not_user_controlled() -> None:
    """The endpoint URL must be built from config, not from user input."""
    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch("sru_server.tools.build_sru_url.requests.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"output": [{"content": [{"text": "url"}]}]},
        )
        # A crafted title must not change the destination URL
        await _async_call_agent("http://169.254.169.254/latest/meta-data")
        args, _ = mock_post.call_args
        assert (
            args[0]
            == "https://dbc-test.cloud.databricks.com/serving-endpoints/mas-c8629507-endpoint/invocations"
        )


@pytest.mark.asyncio
async def test_call_agent_title_is_passed_in_json_body_not_url() -> None:
    """User input goes in the JSON body, never in the URL."""
    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch("sru_server.tools.build_sru_url.requests.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"output": [{"content": [{"text": "url"}]}]},
        )
        await _async_call_agent("http://evil.com")
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["input"][0]["content"] == "http://evil.com"
        # URL must not contain the user input
        url = mock_post.call_args[0][0]
        assert "evil.com" not in url


@pytest.mark.asyncio
async def test_call_agent_timeout_raises_upstream_error() -> None:
    import requests as req

    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch(
            "sru_server.tools.build_sru_url.requests.post",
            side_effect=req.Timeout("timed out"),
        ),
    ):
        with pytest.raises(UpstreamError) as exc:
            await _async_call_agent("Title")
        assert exc.value.category == "timeout"


@pytest.mark.asyncio
async def test_call_agent_connection_error_raises_unavailable() -> None:
    import requests as req

    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch(
            "sru_server.tools.build_sru_url.requests.post",
            side_effect=req.ConnectionError("refused"),
        ),
    ):
        with pytest.raises(UpstreamError) as exc:
            await _async_call_agent("Title")
        assert exc.value.category == "unavailable"


@pytest.mark.asyncio
async def test_call_agent_non_200_raises_upstream_error() -> None:
    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch("sru_server.tools.build_sru_url.requests.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(status_code=403)
        with pytest.raises(UpstreamError) as exc:
            await _async_call_agent("Title")
        assert exc.value.category == "permission_denied"
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_call_agent_sensitive_response_not_in_error(caplog) -> None:
    """When the upstream returns non-200, sensitive response data must not leak."""
    sensitive = "SSN 123-45-6789 token=secret"
    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch("sru_server.tools.build_sru_url.requests.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(status_code=500, text=sensitive)
        with pytest.raises(UpstreamError) as exc:
            await _async_call_agent("Title")
        msg = exc.value.client_message()
        assert sensitive not in msg
        assert "500" not in msg
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_call_agent_invalid_json_raises_bad_response() -> None:
    sensitive = "not-json SSN 123-45-6789"
    with (
        patch("sru_server.tools.build_sru_url._ws", _mock_ws()),
        patch("sru_server.tools.build_sru_url.requests.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.side_effect = ValueError(sensitive)
        with pytest.raises(UpstreamError) as exc:
            await _async_call_agent("Title")
        assert exc.value.category == "bad_response"
        assert sensitive not in exc.value.client_message()


# ── Helper ──────────────────────────────────────────────────────────────────


async def _async_call_agent(title: str) -> str:
    """Run _call_agent in a thread (as the tool does via asyncio.to_thread)."""
    import asyncio

    return await asyncio.to_thread(_call_agent, title)
