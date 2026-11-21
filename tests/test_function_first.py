"""Function first, agent second: build_sru_search_url and the page.

The SQL warehouse and the agent are replaced with stubs, so no Databricks
credentials are needed.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.sql import StatementState
from starlette.testclient import TestClient

import sru_server.tools.build_sru_url as tool
from sru_server.app import app
from sru_server.config import settings

SRU_URL = (
    "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2"
    "&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22Maize%22"
)


def _statement(url, state=StatementState.SUCCEEDED):
    return SimpleNamespace(
        status=SimpleNamespace(state=state),
        result=SimpleNamespace(data_array=[[url]]),
    )


@pytest.fixture
def warehouse(monkeypatch):
    """Stub workspace client whose SQL call returns SRU_URL; returns the mock."""
    monkeypatch.setattr(settings, "sql_warehouse_id", "wh-test")
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = _statement(SRU_URL)
    monkeypatch.setattr(tool, "_ws", ws)
    return ws


@pytest.fixture
def agent(monkeypatch):
    """Stub agent; returns the list of titles it was asked about."""
    calls = []

    def fake(title):
        calls.append(title)
        return f"Agent reply: {SRU_URL}"

    monkeypatch.setattr(tool, "_call_agent_with_retry", fake)
    return calls


def test_function_answers_without_the_agent(warehouse, agent):
    found = tool._sru_lookup("Correction: Maize")
    assert found["source"] == "function"
    assert SRU_URL in found["text"]
    assert agent == []


def test_title_is_a_bound_parameter_not_sql_text(warehouse, agent):
    title = "Correction: x') OR 1=1 --"
    tool._sru_lookup(title)
    kwargs = warehouse.statement_execution.execute_statement.call_args.kwargs
    assert title not in kwargs["statement"]
    assert kwargs["statement"] == f"SELECT {tool.SQL_FUNCTION}(:title) AS url"
    assert kwargs["parameters"][0].value == title
    assert kwargs["warehouse_id"] == "wh-test"


def test_empty_url_is_an_answer_not_a_failure(warehouse, agent):
    warehouse.statement_execution.execute_statement.return_value = _statement("")
    found = tool._sru_lookup("Correction")
    assert found == {"source": "function", "text": tool.NO_URL_TEXT}
    assert agent == []


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("warehouse down"),
        _statement(SRU_URL, state=StatementState.FAILED),
        _statement("https://example.com/not-sru"),
    ],
)
def test_function_failure_falls_back_to_the_agent(warehouse, agent, failure):
    call = warehouse.statement_execution.execute_statement
    if isinstance(failure, Exception):
        call.side_effect = failure
    else:
        call.return_value = failure
    found = tool._sru_lookup("Correction: Maize")
    assert found["source"] == "agent"
    assert agent == ["Correction: Maize"]


def test_no_warehouse_configured_uses_the_agent(monkeypatch, agent):
    monkeypatch.setattr(settings, "sql_warehouse_id", "")
    assert tool._sru_lookup("Correction: Maize")["source"] == "agent"
    assert agent == ["Correction: Maize"]


def test_use_agent_skips_the_function(warehouse, agent):
    found = tool._sru_lookup("Correction: Maize", use_agent=True)
    assert found["source"] == "agent"
    warehouse.statement_execution.execute_statement.assert_not_called()


async def test_tool_uses_the_function(warehouse, agent):
    from sru_server.app import mcp

    result = await mcp.call_tool(
        "build_sru_search_url", {"correction_title": "Correction: Maize"}
    )
    assert SRU_URL in str(result)
    assert agent == []


def test_page_reports_the_source(warehouse, agent):
    client = TestClient(app)
    r = client.post("/api/sru-url", json={"title": "Correction: Maize"})
    assert r.status_code == 200
    assert r.json()["source"] == "function"
    assert r.json()["urls"] == [SRU_URL]
    r = client.post(
        "/api/sru-url", json={"title": "Correction: Maize", "use_agent": True}
    )
    assert r.json()["source"] == "agent"
    assert agent == ["Correction: Maize"]


def test_warm_up_never_raises(monkeypatch):
    monkeypatch.setattr(settings, "sql_warehouse_id", "wh-test")
    ws = MagicMock()
    ws.statement_execution.execute_statement.side_effect = RuntimeError("down")
    monkeypatch.setattr(tool, "_ws", ws)
    tool.warm_up()
