"""Sample 4, rows 17, 18, 21, 23 and 24.

Row 17 (-NoOriginalTitle): only the correction notice, so annotated_title is blank.
Row 21: the original comes first in the response and the correction second.
Row 24: the correction title carries a bracketed citation '[Taxon 59: 896\u2013904. 2010]', which is not an
'[Erratum:' note, so the original is annotated normally.
Run from the erratum-annotator folder:  python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mcp_server"))
import app  # noqa: E402
import erratum_annotator as ea  # noqa: E402

FIX = HERE / "fixtures"

# file, original MMS ID (None: not in Alma), erratum note, annotated title (checked against the live app)
ROWS = [
    ("Sample4-Row17-9917166931307426-NoOriginalTitle.xml", None,
     "[Erratum: Apr. 2026, v. 73, no. 2, 295, 10.1007/s10228-026-01071-0]", ""),
    ("Sample4-Row18-9917166980707426.xml", "9915788769007426",
     "[Erratum: Oct. 2012, v. 249, no. 4, 1183, 10.1007/s00709-012-0376-8]",
     "Probing and tracking organelles in living plant cells "
     "[Erratum: Oct. 2012, v. 249, no. 4, 1183, 10.1007/s00709-012-0376-8]"),
    ("Sample4-Row21-9917162379507426.xml", "9917035108507426",
     "[Erratum: May 2026, v. 113, no. 5, e70209, 10.1002/ajb2.70209]",
     "Disentangling complex relationships and disjunctions in western Camassia: Integrating multiple criteria "
     "to resolve taxonomic boundaries [Erratum: May 2026, v. 113, no. 5, e70209, 10.1002/ajb2.70209]"),
    ("Sample4-Row23-9917162387507426.xml", "9917138970307426",
     "[Erratum: May 2026, v. 50, no. 3, e70224, 10.1111/ijcs.70224]",
     "Revisiting Masstige Marketing: A Structured Literature Review and Future Research Agenda Using "
     "SPAR\u20104\u2010SLR and S\u2010O\u2010R Model [Erratum: May 2026, v. 50, no. 3, e70224, 10.1111/ijcs.70224]"),
    ("Sample4-Row24-9917162403807426.xml", "9917162105907426",
     "[Erratum: Aug. 2013, v. 62, no. 4, 847, 10.12705/624.32]",
     "Taxonomic revision of Sargassum sect. Acanthocarpicae (Fucales, Phaeophyceae) "
     "[Erratum: Aug. 2013, v. 62, no. 4, 847, 10.12705/624.32]"),
]


@pytest.mark.parametrize("file_name,original_id,note,annotated", ROWS, ids=[r[0].split("-")[1] for r in ROWS])
def test_sample4_rows17_24(file_name, original_id, note, annotated):
    cid = file_name.split("-")[2][:16]
    res = ea.process_sru_response((FIX / file_name).read_text(encoding="utf-8"), "", cid)
    assert res["correction_id"] == cid
    assert res["original_id"] == original_id
    assert res["erratum_note"] == note
    assert res["annotated_title"] == annotated
    assert res["needs_review"] is False
    assert res["already_annotated"] is False
    assert app._status(res) == ("ready" if original_id else "no_original")
