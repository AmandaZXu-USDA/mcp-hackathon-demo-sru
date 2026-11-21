#!/usr/bin/env python3
"""Extract original article titles from erratum/correction titles; build SRU queries.

Usage:
    python erratum_title_extractor.py INPUT.xlsx [-o OUTPUT.xlsx] [--sheet SHEET]

Input : Alma "Digital titles export" workbook with columns "Title" and "MMS ID".
Output: workbook with columns
    A erratumn_article_title   B extracted_title      C erratum_MMSID
    D extracted_title_clean    E SRU_Query_Syntax     F SRU_Full_URL
    G extraction_rule  (QA column: which rule produced the title)
Requires: pandas, openpyxl  (pip install pandas openpyxl)
"""

import argparse
import io
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlencode

import pandas as pd

BASE = "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST"  # NAL Alma production


def clean(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


# --- Leading notice prefix: Correction:, Correction to, Publisher/Author Correction:,
#     Corrigendum (to), Corrigenda, Errata, Addendum, Addition to, Editorial expression
#     of concern, Correction for/of, ...
PREFIX = re.compile(
    r"""^
    (?:(?:first|second|third)\s+)?
    (?:(?:publisher(?:'s|’s)?|authors?(?:'|’)?)\s+)?
    (?P<kind>corrections?|corrigend(?:um|a)|errat(?:um|a)|addend(?:um|a)|addition|
       (?:editorial\s+)?expression\s+of\s+concern|corrected\s+and\s+republished|correspondence)
    (?:\s+(?P<conn>to|of|for|in|on|from))?
    (?:\s+supplement(?=\s*:))?
    (?P<sep>\s*:\s*|\s+[-–—]\s+|\s+|(?=[“"‘'\[])|$)
""",
    re.I | re.X,
)
# Trailing notice suffix: "Title: Correction", "Title/Correction"
SUFFIX = re.compile(r"\s*[:/]\s*corrections?\s*$", re.I)
# Notices that cover a whole issue / batch of papers rather than one article
ISSUE = re.compile(
    r"""^(?:(?:(?:errata|addend(?:um|a)|corrections?)\s+(?:to|in|for)\s+)?taxon\s+\d+\s*\(\s*\d+\s*\)\.?$
    |(?:errata|corrections?)\s+for\s+articles\b
    |data\s+(?:papers?|articles?)(?:\s*/\s*data\s+(?:papers?|articles?))?\s+published\b)""",
    re.I | re.X,
)
# "Correction for Smith et al., “Title”" / "Correction for Kuo and Chang, Title"
FOR_AUTHORS = re.compile(
    r"^[^,“\"‘]{1,80}?(?:\bet\s+al\.?|\s+and\s+[\w'’\-]+)\s*,\s*", re.I
)
QUOTES = {"“": "”", '"': '"', "‘": "’", "'": "'", "«": "»"}
# Quoted full citation: “A B, C D, and E F. Title. Journal. Date. pages.”
QUOTED_AUTHORS = re.compile(
    r"^(?:[A-Z][^,]{1,40},\s+){2,}and\s+(?:[A-Z][\w'’\-]*\.?\s+)*[A-Z][\w'’\-]+\.\s*(?=[A-Z])"
)
# Bibliographic corrigendum: Authors (YYYY) Title. Journal 123(4): 45-67.
# https://doi.org/...
BIB = re.compile(r"^(?P<auth>[^()]{1,400}?)\s*\((?:19|20)\d{2}[a-z]?\)\s*(?P<rest>.+)$")
AUTHORS = re.compile(
    r"^[\w'’.\-]+(?:\s+[\w'’.\-]+)*(?:\s*,\s*[\w'’.\-]+(?:\s+[\w'’.\-]+)*)*$"
)
INITIALS = re.compile(r"\b[A-Z]{1,3}\b|\b[A-Z]\.")
DOI = re.compile(r"\s*(?:https?://(?:dx\.)?doi\.org/\S+|doi:\s*\S+)\s*$", re.I)
JOURNAL = re.compile(
    r"\.\s+(?:(?!\.\s)[^:])+?\s+\d+\s*(?:\(\s*[\w\-–]+\s*\))?\s*:\s*[A-Za-z]?\d[\w\-–]*\.?\s*$"
)
# Other trailing citation noise
BY_PUBLISHED = re.compile(
    r"\s+by\s+[A-Z][^,]*(?:,\s*[A-Z][^,]*)*?,?\s+(?i:published\s+in)\b.*$"
)
# "Title by Lee et al. Journal of Medicinal Food 2024;27(6):488-501" / ", by Danielson
# and McKay Ind Biotechnol 2023;19(4)"
BY_CITATION = re.compile(
    r",?\s+by\s+[A-Z][\w'’\-]+.{0,60}?(?:\bet\s+al\.?|\band\s+[A-Z][\w'’\-]+)"
    r"(?=.*\b(?:19|20)\d{2}\b)(?=.*\d+\s*\(\s*\w+\s*\)).*$"
)
CITE_TAIL = re.compile(
    r"\.\s+[A-Z][\w.&\- ]{2,80},\s*\d+\s*\([^)]*\)\s*,\s*[\w‐\-–]+\.?\s*$"
)
BRACKET_TAIL = re.compile(r"\s*\[[^\]]*\]\s*$")


def _unquote(rest):
    """Return the text inside a leading quote.

    Handles nested apostrophes and a missing or odd closing quote.
    """
    close = QUOTES[rest[0]]
    body = rest[1:]
    j = body.rfind(close)
    if j < 0 and rest[0] == "“":
        j = max(body.rfind("“"), body.rfind('"'))
    inner = body[:j] if j >= 0 else body
    inner = clean(inner).strip("“”\"'’")
    # Remove orphaned nesting artifacts: e.g. ‘Steak Dry Aging’”: -> ‘Steak Dry Aging’:
    inner = re.sub(r"([\u2019\u2018'])\s*[\u201c\u201d\"]", r"\1", inner)
    inner = re.sub(r"[\u201c\u201d\"]\s*([\u2019\u2018'])", r"\1", inner)
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return clean(inner)


def _bibliographic(rest):
    """Authors (YYYY) Title. Journal 123(4): 45-67. DOI  ->  Title.

    Journal-name agnostic.
    """
    m = BIB.match(rest)
    if not m or not AUTHORS.match(m["auth"].strip()) or not INITIALS.search(m["auth"]):
        return None
    t = JOURNAL.sub("", DOI.sub("", m["rest"]))
    return clean(t).rstrip(" .")


def extract_with_rule(s):
    """Return (original_article_title, rule_name)."""
    s = clean(s)
    if not s:
        return "", "empty"
    if ISSUE.match(s):
        return "", "issue-level notice (no single article)"
    m = PREFIX.match(s)
    if m:
        rest = s[m.end() :].strip()
        sep, conn = m["sep"], (m["conn"] or "").lower()
        # Accept the prefix only if it is clearly a notice (avoids real titles like
        # "Correction of hypocalcemia...")
        if not (
            rest == ""
            or ":" in sep
            or sep.strip() in "-–—"
            and sep.strip()
            or rest[:1] in QUOTES
            or rest[:1] == "["
            or conn in ("to", "for")
        ):
            m = None
    if not m:
        t = SUFFIX.sub("", s)
        if t != s:
            return clean(t), "notice suffix removed"
        return s, "no correction prefix (kept as is)"
    # repeated prefixes: "Correction: Correction: T",
    # "Correction to Correction to" + quoted T
    while True:
        m2 = PREFIX.match(rest)
        after = rest[m2.end() :].strip() if m2 else ""
        if not (
            m2
            and after
            and (
                ":" in m2["sep"]
                or after[:1] in QUOTES
                or after[:1] == "["
                or (m2["conn"] or "").lower() in ("to", "for")
            )
        ):
            break
        rest, conn = after, (m2["conn"] or "").lower()
    if not rest:
        return "", "bare notice (no title)"
    if ISSUE.match(rest):
        return "", "issue-level notice (no single article)"
    rule = "prefix removed"
    if conn == "for":
        t = FOR_AUTHORS.sub("", rest, count=1)
        if t != rest:
            rest, rule = t, "prefix + cited authors removed"
    if rest[:1] in QUOTES:
        inner = _unquote(rest)
        a = QUOTED_AUTHORS.match(inner)
        if a:
            title = re.split(r"\.\s*(?=[A-Z])", inner[a.end() :], maxsplit=1)[0]
            return clean(title).rstrip(" ."), "quoted citation: authors/journal removed"
        return inner.rstrip(" ."), rule + " + quotes/citation removed"
    t = DOI.sub("", rest)
    t = BY_PUBLISHED.sub("", t)
    t = BY_CITATION.sub("", t)
    if t == DOI.sub(
        "", rest
    ):  # no "by <authors> ..." tail: try Authors (YYYY) Title. Journal ...
        b = _bibliographic(rest)
        if b is not None:
            return b, "bibliographic: authors/year/journal/DOI removed"
    t = CITE_TAIL.sub("", t)
    t = BRACKET_TAIL.sub("", t)
    if t != rest:
        rule += " + trailing citation removed"
    t = re.sub(
        r"[’'”\"]{2,}$", "", clean(t).rstrip(" .;,")
    )  # stray doubled closing quotes
    return clean(t).rstrip(" .;,"), rule


def extract(s):
    return extract_with_rule(s)[0]


# --- Normalisation for SRU matching ---------------------------------------
TRANS = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u2032": "'",
        "\u00b4": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2033": '"',
        "\u00a0": " ",
        "\u2009": " ",
        "\u202f": " ",
        "\u00ac": "",
        "\u00ad": "",
        "\u200b": "",
    }
)


def clean_title(t):
    t = clean(unicodedata.normalize("NFC", t or "").translate(TRANS))
    return t.strip('"').strip().rstrip(" .")


# --- SRU / CQL query building -----------------------------------------------
# Same rules as the Unity Catalog function users.amanda_xu.build_sru_url (the source of
# truth). Only " and \ are replaced (they would end the CQL quoted term); other
# punctuation such as ( ) is kept and percent-encoded.


def sru_query(t):
    """Clean title -> CQL query, or "" when there is no title."""
    term = clean(re.sub(r'["\\]', " ", t or ""))
    if not term:
        return ""
    return f'alma.title="{term}" and alma.local_field_912="Article"'


def sru_url(q):
    """Full SRU 1.2 searchRetrieve URL.

    The query is percent-encoded as UTF-8 (space=%20, "=%22, (=%28, )=%29) instead of
    form-encoding with '+'. No maximumRecords parameter.
    """
    if not q:
        return ""
    return (
        BASE
        + "?"
        + urlencode(
            {
                "version": "1.2",
                "operation": "searchRetrieve",
                "recordSchema": "mods",
                "query": q,
            },
            quote_via=quote,
            safe="",
        )
    )


def process(d):
    """d: DataFrame with 'Title' and 'MMS ID' columns -> output DataFrame (cols A-G)."""
    d = d.fillna("").astype(str)
    ex = d["Title"].map(extract_with_rule)
    o = pd.DataFrame(
        {
            "erratumn_article_title": d["Title"].map(clean),
            "extracted_title": ex.map(lambda x: x[0]),
            "erratum_MMSID": d["MMS ID"].map(clean),
        }
    )
    o["extracted_title_clean"] = o["extracted_title"].map(clean_title)
    o["SRU_Query_Syntax"] = o["extracted_title_clean"].map(sru_query)
    o["SRU_Full_URL"] = o["SRU_Query_Syntax"].map(sru_url)
    o["extraction_rule"] = ex.map(lambda x: x[1])
    return o


# --- File I/O: fall back to the Databricks SDK when /Volumes or /Workspace paths cannot
#     be opened directly (e.g. file-run sessions without filesystem access). Local paths
#     unchanged.
def _sdk_path(path, err):
    if not str(path).startswith(("/Volumes/", "/Workspace/")):
        raise err
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(), str(path)


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as err:
        w, p = _sdk_path(path, err)
        if p.startswith("/Volumes/"):
            return w.files.download(p).contents.read()
        from databricks.sdk.service.workspace import ExportFormat

        with w.workspace.download(
            p[len("/Workspace") :], format=ExportFormat.AUTO
        ) as f:
            return f.read()


def write_bytes(path, data):
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as err:
        w, p = _sdk_path(path, err)
        if p.startswith("/Volumes/"):
            w.files.upload(p, io.BytesIO(data), overwrite=True)
        else:
            from databricks.sdk.service.workspace import ImportFormat

            w.workspace.upload(
                p[len("/Workspace") :],
                io.BytesIO(data),
                format=ImportFormat.AUTO,
                overwrite=True,
            )


def write_xlsx(o, path):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        o.to_excel(w, sheet_name="Extracted Titles", index=False)
        ws = w.sheets["Extracted Titles"]
        for col, width in zip("ABCDEFG", [80, 70, 20, 70, 80, 100, 40]):
            ws.column_dimensions[col].width = width
        ws.freeze_panes = "A2"
    write_bytes(path, buf.getvalue())


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "xlsx", help="input workbook (local path, /Volumes/... or /Workspace/...)"
    )
    ap.add_argument(
        "-o",
        "--output",
        help="output workbook (default: <input>-Extracted-Titles.xlsx)",
    )
    ap.add_argument(
        "--sheet", default=0, help="sheet name or index (default: first sheet)"
    )
    a = ap.parse_known_args()[
        0
    ]  # parse_known_args: tolerate extra args injected by notebook kernels
    d = pd.read_excel(
        io.BytesIO(read_bytes(a.xlsx)), sheet_name=a.sheet, engine="openpyxl", dtype=str
    )
    missing = {"Title", "MMS ID"} - set(d.columns)
    if missing:
        raise SystemExit(f"Input is missing required column(s): {sorted(missing)}")
    o = process(d)
    out = a.output or str(
        Path(a.xlsx).with_name(Path(a.xlsx).stem + "-Extracted-Titles.xlsx")
    )
    write_xlsx(o, out)
    print(f"{len(o)} rows -> {out}")
    print(o["extraction_rule"].value_counts().to_string())


if __name__ == "__main__":
    main()
