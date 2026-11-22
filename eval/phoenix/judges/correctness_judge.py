"""match_expected_response: LLM judge comparing the agent's answer to ground truth."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import gateway
from dotenv import load_dotenv
from phoenix.evals import LLM, ClassificationEvaluator

load_dotenv()

NAME = "match_expected_response"
CHOICES = {"correct": 1, "incorrect": 0}
TEMPLATE = """You are grading an assistant for the U.S. National Agricultural Library
(NAL). Its only job: given the title of an erratum or correction notice, return the
NAL Alma production SRU search URL (it starts with
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?) that finds the original
article, or say that there is no single article to search for.

[Question]: {input}

[Assistant answer]: {output}

[Reference]: {reference}

The reference is one of three kinds:

1. An SRU URL. The answer is correct only if it contains this exact URL, character
   for character, including the percent-encoded title in the query. Surrounding
   prose, a short explanation, markdown link formatting or a trailing period do not
   matter. A different or shortened title, a different query, an added or missing
   field, or the same title decoded or encoded differently is incorrect.
2. "No SRU URL". The answer is correct if it says there is no single original
   article to search for (for example a bare notice or a notice for a whole issue)
   and gives no SRU URL.
3. Text that starts with "Decline:". It describes the expected behaviour. The answer
   is correct if it does what the description says and does not invent facts such as
   DOIs, record counts or citation data.

Is the assistant's answer correct or incorrect?"""


@lru_cache(maxsize=1)
def _evaluator() -> ClassificationEvaluator:
    # Built on first use, so importing this module needs no credentials.
    llm = LLM(
        provider="openai",
        model=gateway.judge_model(),
        base_url=gateway.base_url(),
        api_key=gateway.api_key(),
    )
    return ClassificationEvaluator(
        name=NAME,
        llm=llm,
        prompt_template=TEMPLATE,
        choices=CHOICES,
        temperature=0.0,
    )


def _response(output: Any) -> str:
    return output.get("response", "") if isinstance(output, dict) else str(output or "")


def match_expected_response(input: dict, output: Any, expected: dict) -> dict:
    """Phoenix evaluator: ``correct`` (1) or ``incorrect`` (0), with the reason."""
    score = _evaluator().evaluate(
        {
            "input": input["query"],
            "output": _response(output),
            "reference": expected["responses"],
        }
    )[0]
    return {
        "label": score.label,
        "score": score.score,
        "explanation": score.explanation,
    }
