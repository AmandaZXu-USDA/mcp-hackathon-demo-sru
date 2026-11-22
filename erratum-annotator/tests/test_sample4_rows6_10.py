"""Sample 4, rows 6 to 10: one correction and one original each; row 10 has a MODS subTitle.

Row 10's original is a parallel title split by MARC-to-MODS into <title>MÚLT-JELEN-JÖVŐ ... =</title>
and <subTitle>PAST-PRESENT-FUTURE in Hungarian soil analyses</subTitle>. Before 2026-11-22 only <title>
was read, so the annotated title ended in a dangling '=' and lost the English half.
Run from the erratum-annotator folder:  python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mcp_server"))
import erratum_annotator as ea  # noqa: E402

FIX = HERE / "fixtures"

# file, status, original MMS ID, annotated title (checked against the live app on 2026-11-22)
ROWS = [
    ("Sample4-Row6-9916208075707426.xml", "ready", "9915837933107426",
     "Stairway Plot 2: demographic history inference with folded SNP frequency spectra "
     "[Erratum: Dec. 2020, v. 21, no. 1, 305, 10.1186/s13059-020-02243-5]"),
    ("Sample4-Row7-9915622432007426.xml", "already_annotated", "9915622429307426",
     "PM2.5 exposure inducing ATP alteration links with NLRP3 inflammasome activation "
     "[Erratum: April 2022, v.29(17); p.24457]"),
    ("Sample4-Row8-9916177053207426.xml", "ready", "9916127477307426",
     "547 transcriptomes from 44 brain areas reveal features of the aging brain in non-human primates "
     "[Erratum: Dec. 2020, v. 21, no. 1, 46, 10.1186/s13059-020-01962-z]"),
    ("Sample4-Row9-9916175063907426.xml", "ready", "9915827859007426",
     "SMURF-seq: efficient copy number profiling on long-read sequencers "
     "[Erratum: Dec. 2020, v. 21, no. 1, 214, 10.1186/s13059-020-02149-2]"),
    ("Sample4-Row10-9916197269207426.xml", "ready", "9917152597007426",
     "MÚLT-JELEN-JÖVŐ a hazai mezőgazdasági talajvizsgálatokban = PAST-PRESENT-FUTURE in Hungarian soil "
     "analyses [Erratum: May 31, 2021, v. 70, no. 1, 85-85, 10.1556/0088.2021.00087]"),
]


@pytest.mark.parametrize("file_name,status,original_id,annotated", ROWS, ids=[r[0].split("-")[1] for r in ROWS])
def test_sample4_rows6_10(file_name, status, original_id, annotated):
    cid = file_name.split("-")[2][:16]
    res = ea.process_sru_response((FIX / file_name).read_text(encoding="utf-8"), "", cid)
    assert res["correction_id"] == cid
    assert res["original_id"] == original_id
    assert res["annotated_title"] == annotated
    assert res["already_annotated"] is (status == "already_annotated")
    assert res["needs_review"] is False
    assert res["note_correction_ids"] == [cid]


def _mods(title_info: str) -> str:
    return ('<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><records><record><recordData>'
            '<mods xmlns="http://www.loc.gov/mods/v3">' + title_info +
            '<recordInfo><recordIdentifier>1234567890123456</recordIdentifier></recordInfo>'
            '</mods></recordData></record></records></searchRetrieveResponse>')


@pytest.mark.parametrize("title_info,expected", [
    ("<titleInfo><title>Cím =</title><subTitle>Title</subTitle></titleInfo>", "Cím = Title"),
    ("<titleInfo><title>Main</title><subTitle>a subtitle</subTitle></titleInfo>", "Main: a subtitle"),
    ("<titleInfo><nonSort>The</nonSort><title>Main</title><subTitle>sub</subTitle></titleInfo>", "The Main: sub"),
    ("<titleInfo type=\"alternative\"><title>Alt</title></titleInfo><titleInfo><title>Main</title></titleInfo>",
     "Main"),
    ("<titleInfo><title>Only a title</title></titleInfo>", "Only a title"),
], ids=["parallel", "colon", "nonsort", "skip-alternative", "no-subtitle"])
def test_title_with_subtitle(title_info, expected):
    (rec,) = ea.parse_sru_response(_mods(title_info))
    assert rec.title == expected
