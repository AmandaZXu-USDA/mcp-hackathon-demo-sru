"""Two corrections + one original in one SRU response: both notes go into the single original title.

Rule (the user, 2026-11-22): when the SRU response holds two or more correction records and one
original article, record every correction note in the original title, ordered by date, then volume,
issue and page.

Fixtures:
* Sample 4, row 4 (correction 9917012079207426): original 9917011947507426 plus corrections
  9917011723907426 ('2025 Dec., v. 82, no. 1, 429') and 9917012079207426 ('2025 Dec., v. 82, no. 1, 416').
  Same date, so page decides: 416 then 429.
* Sample 1, row 41 (correction 9917175655407426): original 9916848606207426 plus corrections
  9917006526107426 ('2025 Nov. 13, v. 124') and 9917175655407426 ('2026 June 18, v. 134 p. 247-248').
  Date decides: Nov. 13, 2025 then June 18, 2026.
Run from the erratum-annotator folder:  python -m pytest tests -q
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mcp_server"))
import app  # noqa: E402
import erratum_annotator as ea  # noqa: E402

ROW4 = (HERE / "fixtures" / "Sample4-Row4-9917012079207426-TwoCorrectionsInOneOriginalTitle.xml").read_text(
    encoding="utf-8")
ROW4_TITLE = ("Characterization of the role of the antioxidant proteins metallothioneins 1 and 2 "
              "in an animal model of Alzheimer\u2019s disease")
ROW4_NOTES = ["[Erratum: Dec. 2025, v. 82, no. 1, 416, 10.1007/s00018-025-05965-6]",
              "[Erratum: Dec. 2025, v. 82, no. 1, 429, 10.1007/s00018-025-05953-w]"]

ROW41 = (HERE / "fixtures" / "Sample1-Row41-9917175655407426.xml").read_text(encoding="utf-8-sig")
ROW41_TITLE = ("Paracorymbiglomus gen. nov., Diversispora conica sp. nov., and new combinations "
               "in Diversisporaceae (Glomeromycota)")
ROW41_NOTES = ["[Erratum: Nov. 13, 2025, v. 124, 10.3897/mycokeys.124.171105]",
               "[Erratum: June 18, 2026, v. 134, 247-248, 10.3897/mycokeys.134.198487]"]


def call(name, **args):
    out = asyncio.run(app.mcp.call_tool(name, args))
    blocks = out[0] if isinstance(out, tuple) else out
    return json.loads(blocks[0].text)


@pytest.mark.parametrize("cid", ["9917012079207426", "9917011723907426", ""])
def test_row4_both_notes_in_page_order(cid):
    r = ea.process_sru_response(ROW4, "", cid)
    assert (r["num_records"], r["num_corrections"], r["original_id"]) == (3, 2, "9917011947507426")
    assert r["erratum_notes"] == ROW4_NOTES
    assert r["note_correction_ids"] == ["9917012079207426", "9917011723907426"]
    assert r["annotated_title"] == f"{ROW4_TITLE} {ROW4_NOTES[0]} {ROW4_NOTES[1]}"
    assert r["needs_review"] is False


def test_row41_both_notes_in_date_order():
    r = ea.process_sru_response(ROW41, "", "9917175655407426")
    assert r["original_id"] == "9916848606207426"
    assert r["erratum_notes"] == ROW41_NOTES
    assert r["annotated_title"] == f"{ROW41_TITLE} {ROW41_NOTES[0]} {ROW41_NOTES[1]}"


def test_mcp_tool_row4_ready_without_warning():
    r = call("process_sru_response", xml=ROW4, correction_id="9917012079207426")
    assert r["status"] == "ready" and r["warnings"] == []
    assert r["erratum_note"] == " ".join(ROW4_NOTES)
    assert r["annotated_title"] == f"{ROW4_TITLE} {' '.join(ROW4_NOTES)}"


def test_already_annotated_title_unchanged():
    xml = ROW4.replace(f"<title>{ROW4_TITLE}</title>", f"<title>{ROW4_TITLE} {ROW4_NOTES[0]}</title>")
    r = ea.process_sru_response(xml, "", "9917012079207426")
    assert r["already_annotated"] is True
    assert r["annotated_title"] == f"{ROW4_TITLE} {ROW4_NOTES[0]}"


def test_single_correction_unchanged():
    xml = (HERE / "fixtures" / "Sample1-Row43-9917175550407426.xml").read_text(encoding="utf-8-sig")
    r = ea.process_sru_response(xml, "", "9917175550407426")
    assert len(r["erratum_notes"]) == 1 and r["erratum_note"] == r["erratum_notes"][0]


@pytest.mark.parametrize("part,expected", [
    ("2025 Dec., v. 82, no. 1, 416", (2025, 12, 0, 82, 1, 416)),
    ("2026 June 18, v. 134 p. 247-248", (2026, 6, 18, 134, 0, 247)),
    ("2025 Nov. 13, v. 124", (2025, 11, 13, 124, 0, 0)),
    ("2024 Sept., v. 60, no. 10 p. 1150-1150", (2024, 9, 0, 60, 10, 1150)),
])
def test_note_sort_key(part, expected):
    rec = ea.ModsRecord("Correction", "1", part, "10.1/x", True)
    assert ea.note_sort_key(rec)[:6] == expected
