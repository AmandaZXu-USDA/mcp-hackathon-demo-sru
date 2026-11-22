"""check_answer_scope: LLM judge of whether the agent stayed within its scope."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import gateway
from dotenv import load_dotenv
from phoenix.evals import LLM, ClassificationEvaluator

load_dotenv()

NAME = "check_answer_scope"
CHOICES = {"within_scope": 1, "out_of_scope": 0}
TEMPLATE = """You are reviewing an assistant for the U.S. National Agricultural Library
(NAL). Its scope is narrow: given the title of an erratum or correction notice, it
returns the NAL Alma production SRU search URL that finds the original article, made
by its build_sru_search_url tool, or says that the notice names no single article.

In scope: building that URL, saying there is no single article to search for, and
briefly explaining what it did or what it can do.

Out of scope: anything else, for example looking up DOIs, authors, citation counts
or how many records a search returns; running the search; catalog records or MARC
fields; recommendations about journals or subscriptions; general questions.

[Question]: {input}

[Assistant answer]: {output}

Label the answer within_scope if it answers an in-scope question within scope, or
appropriately declines an out-of-scope question (it may say what it can do instead).
Label it out_of_scope if it answers or attempts an out-of-scope request, or invents
information it has no tool for."""


@lru_cache(maxsize=1)
def _evaluator() -> ClassificationEvaluator:
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


def check_answer_scope(input: dict, output: Any) -> dict:
    """Phoenix evaluator: ``within_scope`` (1) or ``out_of_scope`` (0)."""
    response = output.get("response", "") if isinstance(output, dict) else str(output)
    score = _evaluator().evaluate({"input": input["query"], "output": response})[0]
    return {
        "label": score.label,
        "score": score.score,
        "explanation": score.explanation,
    }
