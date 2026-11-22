"""url_exact_match: deterministic check of the SRU URL, no LLM.

The gold answers are exact URLs (mcp-builder: answers verifiable by direct string
comparison), so this code evaluator checks them exactly. It also cross-checks the LLM
correctness judge, which is weaker at comparing long encoded strings.
"""

from __future__ import annotations

import re
from typing import Any

NAME = "url_exact_match"
NO_URL = "No SRU URL"
SRU_URL_RE = re.compile(
    r"https://nal\.alma\.exlibrisgroup\.com/view/sru/[^\s<>\"'`)\]]+"
)


def sru_urls(text: str) -> set[str]:
    """The distinct NAL Alma SRU URLs in a text (trailing punctuation removed)."""
    return {url.rstrip(".,;:") for url in SRU_URL_RE.findall(text or "")}


def url_exact_match(output: Any, expected: dict) -> dict:
    """1 if the answer has exactly the reference URL (or none when there is none).

    Rows whose reference describes behaviour ("Decline: ...") are not URL questions:
    the score is None and the label ``not_applicable``.
    """
    reference = expected["responses"].strip()
    text = output.get("response", "") if isinstance(output, dict) else str(output or "")
    urls = sru_urls(text)
    if reference.startswith("https://"):
        ok = urls == {reference}
        reason = (
            "exact URL" if ok else f"found {len(urls)} SRU URL(s), not the reference"
        )
    elif reference == NO_URL:
        ok = not urls
        reason = "no URL, as expected" if ok else "gave an SRU URL; expected none"
    else:
        return {
            "label": "not_applicable",
            "score": None,
            "explanation": "not a URL question",
        }
    return {
        "label": "match" if ok else "mismatch",
        "score": int(ok),
        "explanation": reason,
    }
