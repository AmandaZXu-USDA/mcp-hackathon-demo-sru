"""Sample 4, rows 26 to 30.

Row 26: the correction title carries a bracketed citation '[Taxon 63: 1112\u20131113. 2014]' (not an '[Erratum:' note).
Rows 28 to 30: article numbers (165, 369, 135) instead of page ranges.
Row 30: the original comes first in the response and the correction second.
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

# file, original MMS ID, erratum note, annotated title (checked against the live app)
ROWS = [
    ("Sample4-Row26-9917162200107426.xml", "9917162169107426",
     "[Erratum: Mar. 2015, v. 64, no. 1, 183, 10.12705/641.18]",
     "Holotype specimens and type citations: General issues "
     "[Erratum: Mar. 2015, v. 64, no. 1, 183, 10.12705/641.18]"),
    ("Sample4-Row27-9917164112007426.xml", "9916836293907426",
     "[Erratum: Dec. 2025, v. 80, no. 14, 2309, 10.1134/S1061934825020042]",
     "Extraction of Microplastics from River Water in a Rotating Coiled Column Using a Water\u2013Oil System "
     "[Erratum: Dec. 2025, v. 80, no. 14, 2309, 10.1134/S1061934825020042]"),
    ("Sample4-Row28-9917163838107426.xml", "9917163931807426",
     "[Erratum: June 2026, v. 68, no. 3, 165, 10.1007/s10341-026-01878-1]",
     "Socioeconomic and Perceptual Drivers of Climate Change Impact Perceptions Among Peach Farmers: "
     "Evidence from \u00c7anakkale, T\u00fcrkiye [Erratum: June 2026, v. 68, no. 3, 165, 10.1007/s10341-026-01878-1]"),
    ("Sample4-Row29-9916991253207426.xml", "9916945788907426",
     "[Erratum: Dec. 2025, v. 18, no. 1, 369, 10.1186/s13071-025-07023-3]",
     "Ecological drivers of malaria vector habitat and transmission over 1 year of long-lasting insecticidal "
     "net intervention in C\u00f4te d\u2019Ivoire [Erratum: Dec. 2025, v. 18, no. 1, 369, 10.1186/s13071-025-07023-3]"),
    ("Sample4-Row30-9917155273707426.xml", "9915614049107426",
     "[Erratum: Dec. 2016, v. 13, no. 1, 135, 10.1186/s12985-016-0582-7]",
     "Classical swine fever virus NS5A protein changed inflammatory cytokine secretion in porcine alveolar "
     "macrophages by inhibiting the NF-\u03baB signaling pathway "
     "[Erratum: Dec. 2016, v. 13, no. 1, 135, 10.1186/s12985-016-0582-7]"),
]


@pytest.mark.parametrize("file_name,original_id,note,annotated", ROWS, ids=[r[0].split("-")[1] for r in ROWS])
def test_sample4_rows26_30(file_name, original_id, note, annotated):
    cid = file_name.split("-")[2][:16]
    res = ea.process_sru_response((FIX / file_name).read_text(encoding="utf-8"), "", cid)
    assert res["correction_id"] == cid
    assert res["original_id"] == original_id
    assert res["erratum_note"] == note
    assert res["annotated_title"] == annotated
    assert res["needs_review"] is False
    assert res["already_annotated"] is False
    assert app._status(res) == "ready"
