"""Sample 4, rows 11 to 15.

Rows 11 to 13: one correction and one original each (row 12 keeps the catalog's U+2010 hyphen; row 13
matches although the correction writes 'acetylbrowniine' and the original 'Acetylbrowniine').
Rows 14 and 15 (file names end in -NoOriginalTitle): the response holds only the correction notice, so
there is no original to annotate and annotated_title is blank (since 2026-11-22).
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
    ("Sample4-Row11-9917172119507426.xml", "9917011787407426",
     "[Erratum: July 2026, v. 28, no. 7, e70363, 10.1111/1462-2920.70363]",
     "Initially Coexisting Endosymbionts Migrate Into Different Tissues During Ontogeny of Host Cicadas "
     "[Erratum: July 2026, v. 28, no. 7, e70363, 10.1111/1462-2920.70363]"),
    ("Sample4-Row12-9917172306307426.xml", "9917162209407426",
     "[Erratum: July 2026, v. 113, no. 7, e70228, 10.1002/ajb2.70228]",
     "Phylogenomics resolves the evolutionary histories and taxonomy of the long\u2010associated North American "
     "legume genera Psorodendron and Psorothamnus [Erratum: July 2026, v. 113, no. 7, e70228, 10.1002/ajb2.70228]"),
    ("Sample4-Row13-9917172378907426.xml", "9917167473907426",
     "[Erratum: May 2026, v. 62, no. 3, 643, 10.1007/s10600-026-05032-x]",
     "New C\u2081\u2089-Diterpenoid Alkaloid 19-Oxo-14-Acetylbrowniine with Antioxidant Activity from "
     "Delphinium oreophilum [Erratum: May 2026, v. 62, no. 3, 643, 10.1007/s10600-026-05032-x]"),
    ("Sample4-Row14-9917167033407426-NoOriginalTitle.xml", None,
     "[Erratum: Sept. 2021, v. 44, no. 9, 2001, 10.1007/s00449-021-02575-x]", ""),
    ("Sample4-Row15-9917167031307426-NoOriginalTitle.xml", None,
     "[Erratum: Oct. 2012, v. 249, no. 4, 1181, 10.1007/s00709-012-0420-8]", ""),
]


@pytest.mark.parametrize("file_name,original_id,note,annotated", ROWS, ids=[r[0].split("-")[1] for r in ROWS])
def test_sample4_rows11_15(file_name, original_id, note, annotated):
    cid = file_name.split("-")[2][:16]
    res = ea.process_sru_response((FIX / file_name).read_text(encoding="utf-8"), "", cid)
    assert res["correction_id"] == cid
    assert res["original_id"] == original_id
    assert res["erratum_note"] == note
    assert res["annotated_title"] == annotated
    assert res["needs_review"] is False
    assert app._status(res) == ("ready" if original_id else "no_original")
