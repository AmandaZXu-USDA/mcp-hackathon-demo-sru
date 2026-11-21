"""Error-handling tests for the mcp-erratum-note MCP tools.

Run from the erratum-annotator folder:  python -m pytest tests -q
Needs the app's requirements (mcp<2, databricks-sdk) and pytest. No workspace access: the Files API is faked.
"""
import asyncio
import io
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from databricks.sdk import errors as dberr
from mcp.server.fastmcp.exceptions import ToolError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mcp_server"))
import app  # noqa: E402

FIXTURE = "Sample1-Row43-9917175550407426.xml"
XML = (HERE / "fixtures" / FIXTURE).read_text(encoding="utf-8")
CID = "9917175550407426"
ERROR_TAIL = re.compile(r"\[error (\w+), id [0-9a-f]{8}\]$")


def call(name, **args):
    """Call a tool the way an MCP client does; return its result as a dict or str."""
    out = asyncio.run(app.mcp.call_tool(name, args))
    blocks = out[0] if isinstance(out, tuple) else out
    text = blocks[0].text if blocks else ""
    try:
        return json.loads(text)
    except ValueError:
        return text


def error_of(name, **args):
    with pytest.raises(ToolError) as e:
        call(name, **args)
    msg = str(e.value)
    m = ERROR_TAIL.search(msg)
    assert m, msg
    return m.group(1), msg


class FakeFiles:
    def __init__(self, files=None, fail=None, fail_times=1):
        self.files, self.fail, self.left, self.calls = files or {}, fail, fail_times, 0

    def _maybe_fail(self):
        self.calls += 1
        if self.fail and self.left > 0:
            self.left -= 1
            raise self.fail("simulated")

    def download(self, path):
        self._maybe_fail()
        name = path.rsplit("/", 1)[-1]
        if name not in self.files:
            raise dberr.NotFound("The file being accessed is not found.")
        return SimpleNamespace(contents=io.BytesIO(self.files[name]))

    def list_directory_contents(self, folder):
        self._maybe_fail()
        return [SimpleNamespace(name=n, is_directory=False) for n in self.files]


@pytest.fixture
def files(monkeypatch):
    def use(**kw):
        fake = FakeFiles(**kw)
        monkeypatch.setattr(app, "_client", lambda: SimpleNamespace(files=fake))
        monkeypatch.setattr(app.time, "sleep", lambda s: None)
        return fake
    return use


# ---- happy path is unchanged, plus status and warnings ----
def test_process_sru_response_ok():
    r = call("process_sru_response", xml=XML, correction_id=CID)
    assert r["annotated_title"].endswith("[Erratum: Dec. 2026, v. 53, no. 1, 1310, 10.1007/s11033-026-12468-5]")
    assert r["original_id"] == "9917168304707426" and r["status"] == "ready" and r["warnings"] == []


def test_process_sru_file_ok(files):
    files(files={FIXTURE: XML.encode("utf-8")})
    r = call("process_sru_file", file_name=FIXTURE)
    assert r["correction_id_requested"] == CID and r["status"] == "ready"


def test_unknown_correction_id_is_a_warning():
    r = call("process_sru_response", xml=XML, correction_id="1234567890123456")
    assert r["correction_id"] == CID and "not in this response" in r["warnings"][0]


def test_sru_response_with_no_records():
    empty = '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><numberOfRecords>0</numberOfRecords></searchRetrieveResponse>'
    assert call("process_sru_response", xml=empty)["status"] == "no_records"


# ---- input errors ----
@pytest.mark.parametrize("xml,category", [
    ("", "invalid_input"),
    ("   ", "invalid_input"),
    ("not xml at all", "not_well_formed"),
    ("<a><b></a>", "not_well_formed"),
    ("<x/>", "not_sru"),
    ("<a>" + "x" * 2_000_001 + "</a>", "invalid_input"),
])
def test_bad_xml(xml, category):
    for tool in ("parse_sru_response", "process_sru_response"):
        assert error_of(tool, xml=xml)[0] == category


def test_not_well_formed_names_line_and_column():
    assert "(line 1, column 8)" in error_of("parse_sru_response", xml="<a><b></a>")[1]


def test_sru_diagnostic():
    diag = ('<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><diagnostics>'
            '<diagnostic xmlns="http://www.loc.gov/zing/srw/diagnostic/"><message>Query syntax error</message>'
            '</diagnostic></diagnostics></searchRetrieveResponse>')
    cat, msg = error_of("process_sru_response", xml=diag)
    assert cat == "sru_diagnostic" and "Query syntax error" in msg


@pytest.mark.parametrize("cid", ["abc", "123", "99171755504074261"])
def test_bad_correction_id(cid):
    assert error_of("process_sru_response", xml=XML, correction_id=cid)[0] == "invalid_input"


@pytest.mark.parametrize("name", ["../secrets.xml", "a.txt", "", "dir/x.xml"])
def test_bad_file_name(files, name):
    files()
    cat, msg = error_of("process_sru_file", file_name=name)
    assert cat == "invalid_input" and "/Volumes" not in msg


def test_long_text_inputs():
    assert error_of("enhance_title", original_title="t" * 2001, erratum_note="")[0] == "invalid_input"
    assert error_of("extract_erratum_note", part_text="p" * 501, doi="")[0] == "invalid_input"
    assert error_of("list_sru_files", contains="c" * 201)[0] == "invalid_input"


# ---- volume errors ----
def test_missing_file(files):
    files(files={FIXTURE: XML.encode()})
    cat, msg = error_of("process_sru_file", file_name="Sample1-Row99-0000000000000000.xml")
    assert cat == "not_found" and "list_sru_files" in msg


def test_file_not_utf8(files):
    files(files={"bad.xml": b"\xff\xfe\x00<"})
    assert error_of("process_sru_file", file_name="bad.xml")[0] == "bad_file"


def test_saved_file_not_sru(files):
    files(files={"x.xml": b"<x/>"})
    cat, msg = error_of("process_sru_file", file_name="x.xml")
    assert cat == "bad_file" and "not an SRU searchRetrieveResponse" in msg


def test_permission_denied(files):
    files(fail=dberr.PermissionDenied, fail_times=5)
    assert error_of("list_sru_files")[0] == "permission_denied"


def test_temporary_error_is_retried_once(files):
    fake = files(files={FIXTURE: XML.encode()}, fail=dberr.TemporarilyUnavailable, fail_times=1)
    assert call("list_sru_files")["count"] == 1 and fake.calls == 2


def test_temporary_error_twice_is_unavailable(files):
    files(fail=dberr.TemporarilyUnavailable, fail_times=2)
    assert error_of("list_sru_files")[0] == "unavailable"


def test_unexpected_error_hides_details(files, monkeypatch):
    files()
    monkeypatch.setattr(app, "_process", lambda *a: (_ for _ in ()).throw(RuntimeError("secret detail")))
    cat, msg = error_of("process_sru_response", xml=XML)
    assert cat == "internal" and "secret detail" not in msg


def test_health_reports_volume_problems(files):
    files(files={FIXTURE: XML.encode()})
    assert "1 saved SRU responses are readable" in call("health")
    files(fail=dberr.PermissionDenied, fail_times=5)
    assert "cannot read the saved SRU responses" in call("health")
