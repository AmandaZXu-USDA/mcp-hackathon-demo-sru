"""Regenerate the erratum annotator's Unity Catalog function definitions from mcp_server/erratum_annotator.py.

Each function body is the whole erratum_annotator.py module followed by a short "UDF entry" that calls it,
so the UC functions and the MCP tools run the same code. Run after changing erratum_annotator.py:

    python erratum-annotator/uc_functions/build_uc_functions.py

then run the changed .sql files in the SQL editor (CREATE OR REPLACE keeps grants).
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = (HERE.parent / "mcp_server" / "erratum_annotator.py").read_text(encoding="utf-8").rstrip()

HEADER = """-- Unity Catalog function users.amanda_xu.{name}
-- Body: ../mcp_server/erratum_annotator.py plus the UDF entry at the end. Do not edit the body here;
-- change erratum_annotator.py and run build_uc_functions.py.
-- To recreate: run this file in the SQL editor (change users.amanda_xu if you use another schema), then
-- GRANT EXECUTE ON FUNCTION users.amanda_xu.{name} TO the principals that call it.

"""

# name -> (CREATE ... COMMENT ... part before AS $$, UDF entry appended to the module)
FUNCTIONS = {
    'process_sru_response': (
        "CREATE OR REPLACE FUNCTION users.amanda_xu.process_sru_response(\n  xml STRING COMMENT 'Full NAL Alma SRU searchRetrieveResponse MODS XML',\n  search_title STRING COMMENT 'Original article title used to rank candidates (pass empty string if unknown)',\n  correction_id STRING COMMENT 'Erratum MMS ID (16 digits) selecting the correction record (pass empty string if unknown)'\n)\nRETURNS STRUCT<annotated_title: STRING, erratum_note: STRING, correction_id: STRING, original_id: STRING, original_source: STRING, original_candidates: INT, needs_review: BOOLEAN, already_annotated: BOOLEAN, num_records: INT, num_corrections: INT>\nLANGUAGE PYTHON\nNOT DETERMINISTIC\nCOMMENT 'Erratum Annotator: parse an NAL Alma SRU MODS XML response, match the correction record to its original article, and return the original title with an [Erratum: date, v., no., page, DOI] note appended. Titles already containing [Erratum: get no second note; the correction DOI is added to the existing note if missing. needs_review=true means the original match is uncertain.'\n",
        "\n\n\n# ---- UDF entry ----\nr = process_sru_response(xml or '', search_title or '', correction_id or '')\nreturn {k: r.get(k) for k in ['annotated_title','erratum_note','correction_id','original_id','original_source','original_candidates','needs_review','already_annotated','num_records','num_corrections']}\n",
    ),
    'parse_sru_response': (
        "CREATE OR REPLACE FUNCTION users.amanda_xu.parse_sru_response(\n  xml STRING COMMENT 'Full NAL Alma SRU searchRetrieveResponse MODS XML'\n)\nRETURNS ARRAY<STRUCT<title: STRING, record_id: STRING, part_text: STRING, doi: STRING, is_correction: BOOLEAN, notes: ARRAY<STRING>>>\nLANGUAGE PYTHON\nNOT DETERMINISTIC\nCOMMENT 'Erratum Annotator: parse an NAL Alma SRU MODS XML response into records (title, MMS ID, part text, DOI, correction flag, notes).'\n",
        "\n\n\n# ---- UDF entry ----\nreturn [{'title': r.title, 'record_id': r.record_id, 'part_text': r.part_text, 'doi': r.doi, 'is_correction': r.is_correction, 'notes': list(r.notes)} for r in parse_sru_response(xml or '')]\n",
    ),
    'extract_erratum_note': (
        "CREATE OR REPLACE FUNCTION users.amanda_xu.extract_erratum_note(\n  part_text STRING COMMENT 'MODS <part><text> of the correction record, e.g. 2024 Dec., v. 55, no. 1, 77',\n  doi STRING COMMENT 'DOI of the correction record'\n)\nRETURNS STRING\nLANGUAGE PYTHON\nNOT DETERMINISTIC\nCOMMENT 'Erratum Annotator: format an erratum note \\'[Erratum: Mon. YYYY, v. V, no. N, page, DOI]\\' from a correction record\\'s part text and DOI. Returns empty string if either input is missing.'\n",
        "\n\n\n# ---- UDF entry ----\nrec = ModsRecord(title='Correction', record_id='', part_text=part_text or '', doi=doi or None, is_correction=True)\nreturn extract_erratum_note(rec) or ''\n",
    ),
    'enhance_title': (
        "CREATE OR REPLACE FUNCTION users.amanda_xu.enhance_title(\n  original_title STRING COMMENT 'Original article title',\n  erratum_note STRING COMMENT 'Erratum note, e.g. from extract_erratum_note'\n)\nRETURNS STRING\nLANGUAGE PYTHON\nNOT DETERMINISTIC\nCOMMENT 'Erratum Annotator: append an erratum note to the end of an original article title. Returns the title unchanged if it already contains [Erratum: or the note is empty.'\n",
        "\n\n\n# ---- UDF entry ----\nreturn enhance_title(original_title or '', erratum_note or '')\n",
    ),
}


def render(name: str) -> str:
    head, entry = FUNCTIONS[name]
    return HEADER.format(name=name) + head + "AS $$" + CORE + entry + "$$;\n"


if __name__ == "__main__":
    for fn_name in FUNCTIONS:
        (HERE / f"{fn_name}.sql").write_text(render(fn_name), encoding="utf-8")
        print("wrote", fn_name + ".sql")
