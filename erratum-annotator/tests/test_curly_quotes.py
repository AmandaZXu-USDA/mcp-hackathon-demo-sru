"""Curly double quotes (“ ”) in correction and original titles, and saved responses from other samples.

Fixture: Sample 2, row 3, the saved SRU response for correction 9917226153507426, whose title is
Correction to “Developing epidemiological preparedness ...”. Expected values were read from its MODS records:
record 2 (9916961039907426) is the original; the correction's <part><text> is '2026 Nov., v. 8, no. 6 p. 2306-2312'.
Run from the erratum-annotator folder:  python -m pytest tests -q
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mcp_server"))
import app  # noqa: E402

FIXTURE = "Sample2-Row3-9917226153507426.xml"
XML = (HERE / "fixtures" / FIXTURE).read_text(encoding="utf-8")
CID, OID = "9917226153507426", "9916961039907426"
ORIGINAL = ("Developing epidemiological preparedness for a plant disease invasion: "
            "Modelling citrus huánglóngbìng in the European Union")
NOTE = "[Erratum: Nov. 2026, v. 8, no. 6, 2306-2312, 10.1002/ppp3.70207]"


def call(name, **args):
    out = asyncio.run(app.mcp.call_tool(name, args))
    blocks = out[0] if isinstance(out, tuple) else out
    return json.loads(blocks[0].text)


def test_correction_title_in_curly_double_quotes():
    corr = next(r for r in call("parse_sru_response", xml=XML)["records"] if r["is_correction"])
    assert corr["title"].startswith("Correction to \u201c") and corr["title"].endswith("\u201d")
    r = call("process_sru_response", xml=XML, correction_id=CID)
    assert (r["status"], r["original_id"], r["correction_id"]) == ("ready", OID, CID)
    assert r["erratum_note"] == NOTE
    assert r["annotated_title"] == f"{ORIGINAL} {NOTE}"  # accents kept exactly


def test_search_title_with_curly_or_straight_quotes():
    for st in (f"\u201c{ORIGINAL}\u201d", f'"{ORIGINAL}"'):
        assert call("process_sru_response", xml=XML, search_title=st, correction_id=CID)["original_id"] == OID


def test_curly_quotes_inside_original_title_are_kept():
    quoted = "The \u201cone health\u201d approach to citrus huánglóngbìng"
    xml = XML.replace(f"<title>{ORIGINAL}</title>", f"<title>{quoted}</title>").replace(
        f"\u201c{ORIGINAL}\u201d", f"\u201c{quoted}\u201d")
    r = call("process_sru_response", xml=xml, correction_id=CID)
    assert r["original_id"] == OID and r["annotated_title"] == f"{quoted} {NOTE}"


def test_other_sample_files_get_their_own_label(monkeypatch):
    names = {"Sample1-Row3-9916000000000000.xml": XML, FIXTURE: XML}

    class Files:
        def list_directory_contents(self, folder):
            return [SimpleNamespace(name=n, is_directory=False) for n in names]

        def download(self, path):
            import io
            return SimpleNamespace(contents=io.BytesIO(names[path.rsplit("/", 1)[-1]].encode()))

    monkeypatch.setattr(app, "_client", lambda: SimpleNamespace(files=Files()))
    monkeypatch.setitem(app._cache, "examples", None)
    ex = app._load_examples()
    assert [(e["sample"], e["row"], e["label"]) for e in ex] == [(1, 3, "Sample 1, row 3"), (2, 3, "Sample 2, row 3")]
    r = call("process_sru_file", file_name=FIXTURE)
    assert r["correction_id_requested"] == CID and r["original_id"] == OID
