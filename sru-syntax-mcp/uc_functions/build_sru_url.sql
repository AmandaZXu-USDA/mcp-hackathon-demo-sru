-- Unity Catalog function users.amanda_xu.build_sru_url
-- Rules behind the SRU MCP tool build_sru_search_url (mcp-sru-syntax), the agent-sru-syntax
-- Supervisor Agent and the SQL option in the librarian quick-start.
-- Exported from Unity Catalog on 2026-11-21; recreating it from this file gives the same definition.
-- To recreate: run this file in the SQL editor (change users.amanda_xu if you use another schema), then
-- GRANT EXECUTE ON FUNCTION users.amanda_xu.build_sru_url TO the principals that call it.

CREATE OR REPLACE FUNCTION users.amanda_xu.build_sru_url(
  correction_title STRING
)
RETURNS STRING
LANGUAGE PYTHON
DETERMINISTIC
COMMENT 'Builds the NAL Alma PRODUCTION SRU searchRetrieve URL (https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST, Article filter) from a correction title. Removes Correction/Corrigendum/Erratum etc. prefixes; blank for bare/issue notices. space=%20, no maximumRecords. Base switched from sandbox (nal-psb) 2026-11-18.'
AS $$
import re, unicodedata
from urllib.parse import urlencode, quote

BASE = "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST"


def clean(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


# --- Leading notice prefix: Correction:, Correction to, Publisher/Author Correction:, Corrigendum (to),
#     Corrigenda, Errata, Addendum, Addition to, Editorial expression of concern, Correction for/of, ...
PREFIX = re.compile(r"""^
    (?:(?:first|second|third)\s+)?
    (?:(?:publisher(?:'s|’s)?|authors?(?:'|’)?)\s+)?
    (?P<kind>corrections?|corrigend(?:um|a)|errat(?:um|a)|addend(?:um|a)|addition|
       (?:editorial\s+)?expression\s+of\s+concern|corrected\s+and\s+republished|correspondence)
    (?:\s+(?P<conn>to|of|for|in|on|from))?
    (?:\s+supplement(?=\s*:))?
    (?P<sep>\s*:\s*|\s+[-–—]\s+|\s+|(?=[“"‘'\[])|$)
""", re.I | re.X)
# Trailing notice suffix: "Title: Correction", "Title/Correction"
SUFFIX = re.compile(r"\s*[:/]\s*corrections?\s*$", re.I)
# Notices that cover a whole issue / batch of papers rather than one article
ISSUE = re.compile(r"""^(?:(?:(?:errata|addend(?:um|a)|corrections?)\s+(?:to|in|for)\s+)?taxon\s+\d+\s*\(\s*\d+\s*\)\.?$
    |(?:errata|corrections?)\s+for\s+articles\b
    |data\s+(?:papers?|articles?)(?:\s*/\s*data\s+(?:papers?|articles?))?\s+published\b)""", re.I | re.X)
# "Correction for Smith et al., “Title”" / "Correction for Kuo and Chang, Title"
FOR_AUTHORS = re.compile(r"^[^,“\"‘]{1,80}?(?:\bet\s+al\.?|\s+and\s+[\w'’\-]+)\s*,\s*", re.I)
QUOTES = {"“": "”", '"': '"', "‘": "’", "'": "'", "«": "»"}
# Quoted full citation: “A B, C D, and E F. Title. Journal. Date. pages.”
QUOTED_AUTHORS = re.compile(r"^(?:[A-Z][^,]{1,40},\s+){2,}and\s+(?:[A-Z][\w'’\-]*\.?\s+)*[A-Z][\w'’\-]+\.\s*(?=[A-Z])")
# Bibliographic corrigendum: Authors (YYYY) Title. Journal 123(4): 45-67. https://doi.org/...
BIB = re.compile(r"^(?P<auth>[^()]{1,400}?)\s*\((?:19|20)\d{2}[a-z]?\)\s*(?P<rest>.+)$")
AUTHORS = re.compile(r"^[\w'’.\-]+(?:\s+[\w'’.\-]+)*(?:\s*,\s*[\w'’.\-]+(?:\s+[\w'’.\-]+)*)*$")
INITIALS = re.compile(r"\b[A-Z]{1,3}\b|\b[A-Z]\.")
DOI = re.compile(r"\s*(?:https?://(?:dx\.)?doi\.org/\S+|doi:\s*\S+)\s*$", re.I)
JOURNAL = re.compile(r"\.\s+(?:(?!\.\s)[^:])+?\s+\d+\s*(?:\(\s*[\w\-–]+\s*\))?\s*:\s*[A-Za-z]?\d[\w\-–]*\.?\s*$")
# Other trailing citation noise
BY_PUBLISHED = re.compile(r"\s+by\s+[A-Z][^,]*(?:,\s*[A-Z][^,]*)*?,?\s+(?i:published\s+in)\b.*$")
# "Title by Lee et al. Journal of Medicinal Food 2024;27(6):488-501" / ", by Danielson and McKay Ind Biotechnol 2023;19(4)"
BY_CITATION = re.compile(r",?\s+by\s+[A-Z][\w'’\-]+.{0,60}?(?:\bet\s+al\.?|\band\s+[A-Z][\w'’\-]+)"
                         r"(?=.*\b(?:19|20)\d{2}\b)(?=.*\d+\s*\(\s*\w+\s*\)).*$")
CITE_TAIL = re.compile(r"\.\s+[A-Z][\w.&\- ]{2,80},\s*\d+\s*\([^)]*\)\s*,\s*[\w‐\-–]+\.?\s*$")
BRACKET_TAIL = re.compile(r"\s*\[[^\]]*\]\s*$")


def _unquote(rest):
    """Return the text inside a leading quote (handles nested apostrophes and a missing/odd closer)."""
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
    """Authors (YYYY) Title. Journal 123(4): 45-67. DOI  ->  Title   (journal-name agnostic)."""
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
        rest = s[m.end():].strip()
        sep, conn = m["sep"], (m["conn"] or "").lower()
        # Accept the prefix only if it is clearly a notice (avoids real titles like "Correction of hypocalcemia...")
        if not (rest == "" or ":" in sep or sep.strip() in "-–—" and sep.strip()
                or rest[:1] in QUOTES or rest[:1] == "[" or conn in ("to", "for")):
            m = None
    if not m:
        t = SUFFIX.sub("", s)
        if t != s:
            return clean(t), "notice suffix removed"
        return s, "no correction prefix (kept as is)"
    while True:  # repeated prefixes, e.g. "Correction: Correction: Title"
        m2 = PREFIX.match(rest)
        if not (m2 and ":" in m2["sep"] and rest[m2.end():].strip()):
            break
        rest = rest[m2.end():].strip()
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
            title = re.split(r"\.\s*(?=[A-Z])", inner[a.end():], maxsplit=1)[0]
            return clean(title).rstrip(" ."), "quoted citation: authors/journal removed"
        return inner.rstrip(" ."), rule + " + quotes/citation removed"
    t = DOI.sub("", rest)
    t = BY_PUBLISHED.sub("", t)
    t = BY_CITATION.sub("", t)
    if t == DOI.sub("", rest):  # no "by <authors> ..." tail: try Authors (YYYY) Title. Journal ...
        b = _bibliographic(rest)
        if b is not None:
            return b, "bibliographic: authors/year/journal/DOI removed"
    t = CITE_TAIL.sub("", t)
    t = BRACKET_TAIL.sub("", t)
    if t != rest:
        rule += " + trailing citation removed"
    t = re.sub(r"[’'”\"]{2,}$", "", clean(t).rstrip(" .;,"))  # stray doubled closing quotes
    return clean(t).rstrip(" .;,"), rule


def extract(s):
    return extract_with_rule(s)[0]


# --- Normalisation for SRU matching ---------------------------------------
TRANS = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u2032": "'", "\u00b4": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
    "\u00a0": " ", "\u2009": " ", "\u202f": " ",
    "\u00ac": "", "\u00ad": "", "\u200b": "",
})


def clean_title(t):
    t = clean(unicodedata.normalize("NFC", t or "").translate(TRANS))
    return t.strip('"').strip().rstrip(" .")



def sru_url_from_title(title):
    term = re.sub(r'["\\]', " ", title or "")   # a quote/backslash would end the CQL quoted term
    term = re.sub(r"\s+", " ", term).strip()
    if not term:
        return ""
    q = f'alma.title="{term}" and alma.local_field_912="Article"'
    return BASE + "?" + urlencode({"version": "1.2", "operation": "searchRetrieve", "recordSchema": "mods",
                                   "query": q}, quote_via=quote, safe="")

if correction_title is None:
    return ""
return sru_url_from_title(clean_title(extract(correction_title)))
$$;
