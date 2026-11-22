-- Unity Catalog function users.amanda_xu.enhance_title
-- Body: ../mcp_server/erratum_annotator.py plus the UDF entry at the end. Do not edit the body here;
-- change erratum_annotator.py and run build_uc_functions.py.
-- To recreate: run this file in the SQL editor (change users.amanda_xu if you use another schema), then
-- GRANT EXECUTE ON FUNCTION users.amanda_xu.enhance_title TO the principals that call it.

CREATE OR REPLACE FUNCTION users.amanda_xu.enhance_title(
  original_title STRING COMMENT 'Original article title',
  erratum_note STRING COMMENT 'Erratum note, e.g. from extract_erratum_note'
)
RETURNS STRING
LANGUAGE PYTHON
NOT DETERMINISTIC
COMMENT 'Erratum Annotator: append an erratum note to the end of an original article title. Returns the title unchanged if it already contains [Erratum: or the note is empty.'
AS $$"""
Erratum Annotator core module.

Parses SRU MODS XML responses from the NAL Alma catalog, extracts erratum
notes from correction records, and appends them to original article titles.

Validated on 22 SRU XML files covering: dual/single-record responses,
already-annotated titles (skip rule), malformed XML (unescaped &, raw <),
and variant part-text formats.
"""
import re
import difflib
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

SRW = "{http://www.loc.gov/zing/srw/}"
MODS = "{http://www.loc.gov/mods/v3}"
CORRECTION_PREFIXES = ("correction", "corrigendum", "corrigenda", "erratum", "errata")
# Qualifier words that may precede a correction word, e.g. 'Publisher Correction:'
CORRECTION_QUALIFIERS = ("publisher", "publishers", "author", "authors")


@dataclass
class ModsRecord:
    """A single MODS record from an SRU response."""
    title: str
    record_id: str
    part_text: str
    doi: Optional[str]
    is_correction: bool
    notes: tuple = ()  # untyped MODS <note> values, e.g. ('ERRATUM',), ('JOURNAL ARTICLE',)

    def erratum_note(self) -> Optional[str]:
        if not self.is_correction or not self.part_text or not self.doi:
            return None
        return f"[Erratum: {parse_part(self.part_text)}, {self.doi}]"


def _text(el) -> str:
    # Strip whitespace and stray byte-order marks (seen in some MycoKeys titles)
    return (el.text or "").replace("\ufeff", "").strip() if el is not None else ""


def is_correction_title(title: str) -> bool:
    """Classify a title as correction/erratum by its first word(s)."""
    if not title:
        return False
    words = [re.sub(r"[^a-z]", "", w.lower()) for w in title.split()]
    if not words:
        return False
    if words[0] in CORRECTION_PREFIXES:  # also covers 'Correction to:'
        return True
    # 'Publisher Correction:', 'Author Correction:'
    return len(words) > 1 and words[0] in CORRECTION_QUALIFIERS and words[1] in CORRECTION_PREFIXES


def is_correction_record(title: str, notes) -> bool:
    """A record is a correction if its title says so OR Alma tags it with <note>ERRATUM</note>."""
    return is_correction_title(title) or any(
        (n or "").strip().upper() in ("ERRATUM", "CORRIGENDUM", "CORRECTION") for n in notes)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = re.sub(r"\[erratum:.*?\]", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def title_similarity(a: str, b: str) -> float:
    """0-1 similarity of two titles; 1.0 when one normalized title contains the other."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def parse_part(part_text: str) -> str:
    """Parse MODS <part><text> into 'Mon. YYYY, v. V, no. N, page'.

    Handles variants such as:
      '2024 Dec., v. 55, no. 1, 77'
      '2024 Dec., v. 60, no. 10 p. 1150-1150'
      '2026 July, v. 524, no. 1 p. 373-373'   (unabbreviated month, no period)
      '2026 July 4, v. 21, no. 4 p. 1015-1015' (day included -> 'July 4, 2026')
      '2026 June 18, v. 134 p. 247-248'       (no issue -> 'June 18, 2026, v. 134, 247-248')
    Returns the input unchanged if it does not match.
    """
    s = (part_text or "").strip()
    m = re.match(r"(\d{4})\s+([A-Za-z]+\.?)(?:\s+(\d{1,2}))?,\s*v\.\s*(.+)$", s)
    if not m:
        return s
    year, month, day, rest = m.groups()
    date = f"{month} {day}, {year}" if day else f"{month} {year}"
    with_issue = re.match(r"([^,]+?),\s*no\.\s*(.+)$", rest)
    if not with_issue:
        # No issue number: 'V p. PAGES', 'V, PAGE' or just 'V'
        np = re.match(r"([^,\s]+)\s*,?\s*(?:p\.\s*)?(.*)$", rest)
        volume, page = np.group(1), np.group(2).strip()
        return f"{date}, v. {volume}, {page}" if page else f"{date}, v. {volume}"
    volume, remainder = with_issue.groups()
    if "," in remainder:
        issue, page = remainder.split(",", 1)
    else:
        mm = re.match(r"(\S+)\s*p\.?\s*(.+)", remainder)
        issue, page = (mm.group(1), mm.group(2)) if mm else (remainder, "")
    return f"{date}, v. {volume.strip()}, no. {issue.strip()}, {page.strip()}"


def clean_xml(xml: str) -> str:
    """Pre-clean XML for ElementTree: strip abstracts (may contain raw <), escape stray &."""
    xml = re.sub(r"<abstract\b[^>]*>.*?</abstract>", "", xml, flags=re.S)
    return re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#[xX][0-9a-fA-F]+;)", "&amp;", xml)


def parse_sru_response(xml: str) -> list[ModsRecord]:
    """Parse SRU searchRetrieveResponse XML into classified ModsRecords."""
    root = ET.fromstring(clean_xml(xml))
    records = []
    for rec in root.iter(f"{SRW}record"):
        rd = rec.find(f"{SRW}recordData")
        if rd is None:
            continue
        mods = rd.find(f"{MODS}mods")
        if mods is None:
            continue
        infos = mods.findall(f"{MODS}titleInfo")
        info = next((t for t in infos if not t.get("type")), infos[0] if infos else None)
        title = _text(info.find(f"{MODS}title")) if info is not None else None
        non_sort = _text(info.find(f"{MODS}nonSort")) if info is not None else None
        if non_sort:  # leading article stored separately, e.g. <nonSort>A</nonSort>
            title = f"{non_sort} {title}"
        sub = _text(info.find(f"{MODS}subTitle")) if info is not None else None
        if title and sub:  # MARC 245 $b; a parallel title keeps its ' =' (e.g. 'Cím = Title')
            title = f"{title} {sub}" if title.rstrip()[-1:] in "=:;/" else f"{title}: {sub}"
        rid = _text(mods.find(f"{MODS}recordInfo/{MODS}recordIdentifier"))
        part = _text(mods.find(f".//{MODS}part/{MODS}text"))
        doi = next((_text(i) for i in mods.findall(f"{MODS}identifier")
                    if i.get("type") == "doi"), None)
        notes = tuple(_text(n) for n in mods.findall(f"{MODS}note") if not n.get("type"))
        records.append(ModsRecord(title, rid, part, doi, is_correction_record(title, notes), notes))
    return records


def extract_erratum_note(correction: ModsRecord) -> Optional[str]:
    """Format '[Erratum: Mon. YYYY, v. V, no. N, page, doi]' from a correction record."""
    return correction.erratum_note()


def enhance_title(original_title: str, erratum_note: str) -> str:
    """Append erratum note to the end of the title; skip if already annotated."""
    if not erratum_note or "[Erratum:" in (original_title or ""):
        return original_title
    return f"{original_title} {erratum_note}"


_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _num(s) -> int:
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else 0


def note_sort_key(correction: ModsRecord) -> tuple:
    """Order correction records by date (year, month, day), then volume, issue and page.

    Reads the MODS <part><text>, e.g. '2025 Dec., v. 82, no. 1, 416' or '2026 June 18, v. 134 p. 247-248'.
    Unparsed parts sort last; the MMS ID breaks ties so the order is stable.
    """
    s = (correction.part_text or "").strip()
    m = re.match(r"(\d{4})(?:\s+([A-Za-z]+)\.?(?:\s+(\d{1,2}))?)?", s)
    if not m:
        return (9999, 99, 99, 0, 0, 0, correction.record_id)
    year, month, day = int(m.group(1)), _MONTHS.get((m.group(2) or "")[:3].lower(), 0), int(m.group(3) or 0)
    vol = re.search(r"(?<![A-Za-z])v\.\s*([^,\s]+)", s)  # not the 'v.' inside 'Nov.'
    issue = re.search(r"(?<![A-Za-z])no\.\s*([^,\s]+)", s)
    tail = s[vol.end():] if vol else s[m.end():]
    if issue:
        tail = s[issue.end():]
    return (year, month, day, _num(vol.group(1) if vol else ""), _num(issue.group(1) if issue else ""),
            _num(tail), correction.record_id)


def _same_article_corrections(corrections, correction, original, candidates: int):
    """Corrections whose notes all go into the original title, in date/page order.

    Rule (user, 2026-11-22, Sample4 Row4): when the SRU response holds two or more correction
    records and one original article, every correction of that article gets its note in the
    single original title, ordered by date, then volume, issue and page. A correction counts as
    'of that article' when its title matches the original title (similarity >= 0.6). Otherwise
    only the selected correction is used.
    """
    if correction is None:
        return []
    if original is None or candidates != 1 or len(corrections) < 2:
        return [correction]
    same = [c for c in corrections
            if c.record_id == correction.record_id or title_similarity(c.title, original.title) >= 0.6]
    return sorted(same, key=note_sort_key)


def _pick_original(records, correction, search_title: str = ""):
    """Choose the original article record; never an erratum/correction record.

    Candidates exclude every record classified as a correction (title prefix or
    <note>ERRATUM</note>) and the selected correction itself. When several remain,
    the one whose title best matches search_title (or the correction's title)
    wins. A candidate whose DOI is cited in the correction's title (Pensoft-style
    'Corrigendum: ... https://doi.org/<original DOI>') wins outright; JOURNAL
    ARTICLE/REVIEW records get a small bonus.
    Returns (record_or_None, num_candidates, needs_review).
    """
    cid = correction.record_id if correction else None
    cands = [r for r in records if not r.is_correction and r.record_id != cid]
    if not cands:
        return None, 0, False
    ref = search_title or (correction.title if correction else "")
    cited = {d.rstrip(".,;)").lower() for d in re.findall(r"10\.\d{4,9}/\S+", correction.title if correction else "")}
    def score(r):
        bonus = 0.05 if any(n.upper() in ("JOURNAL ARTICLE", "REVIEW") for n in r.notes) else 0.0
        if r.doi and r.doi.lower() in cited:
            bonus += 1.0
        return (title_similarity(r.title, ref) if ref else 0.0) + bonus
    ranked = sorted(cands, key=score, reverse=True)
    best = ranked[0]
    review = bool(ref) and score(best) < 0.6
    if len(ranked) > 1 and score(best) - score(ranked[1]) < 0.1:
        review = True
    return best, len(cands), review


def process_sru_response(xml: str, search_title: str = "", correction_id: str = "") -> dict:
    """Full pipeline: parse, match correction -> original, build annotated title.

    Falls back to search_title when the response has no original record.
    When a response holds several correction records, pass correction_id (the
    row's erratum MMS ID) to pick the right one; otherwise the first is used.
    When it holds two or more corrections of one original article, all their
    notes are appended in date/page order (erratum_note joins them with a space;
    erratum_notes lists them).
    """
    records = parse_sru_response(xml)
    corrections = [r for r in records if r.is_correction]
    correction = next((r for r in corrections if correction_id and r.record_id == str(correction_id)),
                      corrections[0] if corrections else None)
    original, candidates, review = _pick_original(records, correction, search_title)
    base = original.title if original else search_title
    used = _same_article_corrections(corrections, correction, original, candidates)
    notes = [n for n in (extract_erratum_note(c) for c in used) if n]
    note = " ".join(notes) or None
    already = "[Erratum:" in (base or "")
    annotated = enhance_title(base, note) if note else base
    return {
        "num_records": len(records),
        "num_corrections": len(corrections),
        "correction_id": correction.record_id if correction else None,
        "original_id": original.record_id if original else None,
        "original_source": "response" if original else "search_title",
        "original_candidates": candidates,
        "needs_review": review,
        "erratum_note": note,
        "erratum_notes": notes,
        "note_correction_ids": [c.record_id for c in used if extract_erratum_note(c)],
        "already_annotated": already,
        "annotated_title": annotated,
    }


# ---- UDF entry ----
return enhance_title(original_title or '', erratum_note or '')
$$;
