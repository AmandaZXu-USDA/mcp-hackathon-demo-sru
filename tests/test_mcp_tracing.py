"""MLflow tracing in the two deployed MCP servers, offline.

Loads the deployed sources (sru-syntax-mcp/mcp_server/app.py and
erratum-annotator/mcp_server/app.py, byte-identical to NAL) with dummy Databricks
credentials and a fake mlflow module, so no network, workspace or model is used.
"""

from __future__ import annotations

import contextlib
import importlib.util
import sys
import types
from pathlib import Path

import databricks.sdk
import pytest
from mcp.server.fastmcp.exceptions import ToolError

ROOT = Path(__file__).resolve().parent.parent
SRU_APP = ROOT / "sru-syntax-mcp" / "mcp_server" / "app.py"
ERRATUM_DIR = ROOT / "erratum-annotator" / "mcp_server"
SRU_URL = "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?query=x"


class FakeSpan:
    def __init__(self, name: str, span_type: str) -> None:
        self.name, self.span_type = name, span_type
        self.inputs = self.outputs = self.error = None

    def set_inputs(self, value) -> None:
        self.inputs = value

    def set_outputs(self, value) -> None:
        self.outputs = value


class FakeMlflow:
    """Records spans and trace tags the way the servers use mlflow."""

    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []
        self.tags: dict[str, str] = {}

    @contextlib.contextmanager
    def start_span(self, name: str, span_type: str):
        span = FakeSpan(name, span_type)
        self.spans.append(span)
        try:
            yield span
        except Exception as exc:
            span.error = exc
            raise

    def update_current_trace(self, tags: dict) -> None:
        self.tags.update(tags)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sru(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dummy")
    monkeypatch.delenv("MLFLOW_EXPERIMENT_ID", raising=False)
    # app.py creates a WorkspaceClient on import. A real one fetches host
    # metadata over the network and keeps retrying when the dummy host does
    # not answer (this hung CI for 15 minutes), so use a stand-in.
    config = types.SimpleNamespace(host="https://example.cloud.databricks.com")
    monkeypatch.setattr(
        databricks.sdk,
        "WorkspaceClient",
        lambda *a, **k: types.SimpleNamespace(config=config),
    )
    return _load("deployed_sru_app", SRU_APP)


@pytest.fixture
def erratum(monkeypatch):
    monkeypatch.delenv("MLFLOW_EXPERIMENT_ID", raising=False)
    monkeypatch.syspath_prepend(str(ERRATUM_DIR))
    monkeypatch.delitem(sys.modules, "erratum_annotator", raising=False)
    return _load("deployed_erratum_app", ERRATUM_DIR / "app.py")


def _found(title, use_agent=False):
    return {"source": "function", "text": f"SRU URL:\n{SRU_URL}"}


@pytest.mark.parametrize("name", ["sru", "erratum"])
def test_tracing_is_off_on_import_and_without_an_experiment(name, request):
    module = request.getfixturevalue(name)
    assert module._mlflow is None
    module._init_tracing()  # no MLFLOW_EXPERIMENT_ID: stays off, does not raise
    assert module._mlflow is None


@pytest.mark.parametrize("name", ["sru", "erratum"])
def test_tracing_stays_off_if_mlflow_cannot_start(name, request, monkeypatch):
    module = request.getfixturevalue(name)
    monkeypatch.setattr(module, "TRACE_EXPERIMENT_ID", "123")
    monkeypatch.setitem(sys.modules, "mlflow", None)  # import mlflow fails
    module._init_tracing()
    assert module._mlflow is None


@pytest.mark.parametrize("name", ["sru", "erratum"])
def test_mcp_tracing_off_turns_tracing_off(name, request, monkeypatch):
    module = request.getfixturevalue(name)
    monkeypatch.setattr(module, "TRACE_EXPERIMENT_ID", "123")
    monkeypatch.setenv("MCP_TRACING", "off")
    module._init_tracing()
    assert module._mlflow is None


async def test_sru_tool_untraced_when_off(sru, monkeypatch):
    monkeypatch.setattr(sru, "_sru_lookup", _found)
    assert SRU_URL in await sru.build_sru_search_url("Correction: A title")


async def test_sru_tool_call_is_one_trace(sru, monkeypatch):
    fake = FakeMlflow()
    monkeypatch.setattr(sru, "_mlflow", fake)
    monkeypatch.setattr(sru, "_sru_lookup", _found)
    reply = await sru.build_sru_search_url("Correction: A title")
    assert SRU_URL in reply
    (span,) = fake.spans
    assert (span.name, span.span_type) == ("build_sru_search_url", "TOOL")
    assert span.inputs == {
        "correction_title": "Correction: A title",
        "use_agent": False,
    }
    assert span.outputs == {"text": reply, "answered_by": "function"}
    assert fake.tags == {
        "app": "mcp-sru-syntax",
        "channel": "mcp",
        "answered_by": "function",
    }


async def test_sru_tool_error_records_only_the_category(sru, monkeypatch):
    fake = FakeMlflow()
    monkeypatch.setattr(sru, "_mlflow", fake)

    def slow(title, use_agent=False):
        raise sru.UpstreamError("timeout")

    monkeypatch.setattr(sru, "_sru_lookup", slow)
    with pytest.raises(ToolError, match="error timeout"):
        await sru.build_sru_search_url("Correction: A title")
    (span,) = fake.spans
    assert str(span.error) == "timeout" and span.outputs is None


def test_sru_page_lookup_is_tagged_page(sru, monkeypatch):
    fake = FakeMlflow()
    monkeypatch.setattr(sru, "_mlflow", fake)
    monkeypatch.setattr(sru, "_sru_lookup", _found)
    assert sru._traced_lookup("Correction: A title", True, "page") == _found("")
    assert fake.tags["channel"] == "page"
    assert fake.spans[0].inputs["use_agent"] is True


def test_erratum_tool_call_is_one_trace(erratum, monkeypatch):
    fake = FakeMlflow()
    monkeypatch.setattr(erratum, "_mlflow", fake)
    result = erratum.enhance_title("Some title", "[Erratum: x]")
    (span,) = fake.spans
    assert (span.name, span.span_type) == ("enhance_title", "TOOL")
    assert span.inputs == {
        "original_title": "Some title",
        "erratum_note": "[Erratum: x]",
    }
    assert span.outputs == result
    assert fake.tags == {"app": "mcp-erratum-note", "tool": "enhance_title"}


def test_erratum_long_inputs_are_cut(erratum, monkeypatch):
    fake = FakeMlflow()
    monkeypatch.setattr(erratum, "_mlflow", fake)
    xml = "<bad" + "x" * 10_000
    with pytest.raises(ToolError):
        erratum.parse_sru_response(xml)
    cut = fake.spans[0].inputs["xml"]
    assert cut.startswith(xml[: erratum.MAX_TRACE_CHARS])
    assert cut.endswith(f"[cut; {len(xml):,} characters in total]")


def test_erratum_error_records_only_the_client_message(erratum, monkeypatch):
    fake = FakeMlflow()
    monkeypatch.setattr(erratum, "_mlflow", fake)

    def broken():
        raise RuntimeError("secret internal detail")

    tool = erratum._handled(broken)
    with pytest.raises(ToolError) as info:
        tool()
    (span,) = fake.spans
    assert isinstance(span.error, ToolError)
    assert str(span.error) == str(info.value)
    assert "secret internal detail" not in str(span.error)


def test_erratum_short_keeps_structure(erratum):
    long = "y" * (erratum.MAX_TRACE_CHARS + 1)
    out = erratum._short({"a": [long, 1], "b": "ok"})
    assert out["b"] == "ok" and out["a"][1] == 1
    assert out["a"][0].endswith("characters in total]")
