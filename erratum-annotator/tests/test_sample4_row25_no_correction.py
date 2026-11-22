"""Sample 4, row 25: only the original article is in Alma; the corrigendum is not catalogued.

The SRU response holds one record, the original (9917162191107426). The row's correction MMS ID
(9917162397207426) is not in it, so there is no erratum note to add: status no_correction, annotated_title
blank and a manual-review warning (project owner's use case, 2026-11-22).
Sample 4 rows 16, 19, 20 and 22 have no SRU response at all (their titles only carry a correction keyword such
as erratum, addendum or ERRATA); they need manual review and are not tested here.
Run from the erratum-annotator folder:  python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mcp_server"))
import app  # noqa: E402
import erratum_annotator as ea  # noqa: E402

FILE = "Sample4-Row25-9917162397207426-OnlyOriginalTitle.xml"
XML = (HERE / "fixtures" / FILE).read_text(encoding="utf-8")
CID, OID = "9917162397207426", "9917162191107426"


@pytest.mark.parametrize("correction_id", [CID, ""])
def test_only_original_gives_no_correction_and_blank_title(correction_id):
    res = app._with_status(ea.process_sru_response(XML, "", correction_id), correction_id)
    assert res["num_records"] == 1 and res["num_corrections"] == 0
    assert res["correction_id"] is None
    assert res["original_id"] == OID
    assert res["erratum_note"] is None
    assert res["annotated_title"] == ""
    assert res["status"] == "no_correction"
    (warning,) = res["warnings"]
    assert OID in warning and "Manual review" in warning
    assert (CID in warning) == bool(correction_id)


def test_file_name_suffix_keeps_correction_id():
    # the app reads the 16-digit correction ID before '-OnlyOriginalTitle'
    import re

    m = re.search(r"(\d{16})(?:-[A-Za-z][A-Za-z0-9]*)*\.xml$", FILE, re.I)
    assert m and m.group(1) == CID
