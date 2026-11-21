# =============================================================================
# OFFLINE MLflow GenAI EVAL of the DEPLOYED mcp-sru-syntax agent (/invocations)
# =============================================================================
# Same dataset (datasets/sru-eval-0.csv) and the same 5 scorers as
# agent_eval_offline.py, but predict_fn calls the agent that runs inside the
# deployed app (POST /invocations). So it scores exactly what users get: the
# app's model (AGENT_MODEL, databricks-gpt-5-6-luna since 2026-11-21) and the
# function-first build_sru_search_url tool. No local agent copy and no model
# access needed.
#
# Auth: the Inspector Gadget service principal (OAuth M2M, CAN_USE on the app),
# from the Unity Catalog secret models.ai/inspector-gadget. Run in a Databricks
# notebook (mlflow>=3.14).
# =============================================================================
import json
import os
import re
import time
from urllib.parse import parse_qs, urlparse

import mlflow
import pandas as pd
import requests
from databricks.sdk import WorkspaceClient
from mlflow.entities import Feedback
from mlflow.genai import evaluate
from mlflow.genai.scorers import Correctness, Guidelines, Safety, scorer

APP_URL = os.getenv(
    "SRU_EVAL_APP_URL", "https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com"
)
DATABRICKS_HOST = os.getenv(
    "DATABRICKS_HOST", "https://dbc-aae0ba16-8727.cloud.databricks.com"
)
EXPERIMENT_ID = os.getenv("SRU_EVAL_EXPERIMENT_ID", "131270370350843")
SQL_WAREHOUSE_ID = os.getenv("MLFLOW_TRACING_SQL_WAREHOUSE_ID", "50d2bd4ddf65e0f5")
HERE = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else os.getcwd()
)
DATASET_PATH = os.path.join(HERE, "datasets", "sru-eval-0.csv")
SRU_BASE = "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST"
TIMEOUT_S = 300

_secret = dbutils.secrets.get(  # type: ignore[name-defined]  # noqa: F821
    catalog="models", schema="ai", key="inspector-gadget"
)
_cred = json.loads(_secret)
_ws = WorkspaceClient(
    host=DATABRICKS_HOST,
    client_id=_cred["client_id"],
    client_secret=_cred["client_secret"],
    scopes=_cred["scopes"],
)

os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = SQL_WAREHOUSE_ID
mlflow.set_experiment(experiment_id=EXPERIMENT_ID)
os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "3")


# --- Evaluation dataset -------------------------------------------------------
def load_dataset(path: str) -> list[dict]:
    """CSV (request, expected_title, source_rule) -> mlflow.genai.evaluate rows.

    expected_title is the alma.title term produced by users.amanda_xu.build_sru_url
    (blank = the notice has no single article, so no SRU URL is expected).
    """
    df = pd.read_csv(path, keep_default_na=False)
    missing = {"request", "expected_title"} - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    rows = []
    for r in df.itertuples(index=False):
        title = r.expected_title.strip()
        if title:
            facts = [
                "The response contains an SRU searchRetrieve URL on "
                f"{urlparse(SRU_BASE).netloc}",
                f'The URL\'s alma.title search term is the article title "{title}" '
                "(URL-encoded)",
            ]
        else:
            facts = [
                "The response does not give an SRU search URL, because the notice "
                "names no single article"
            ]
        rows.append(
            {
                "inputs": {"request": r.request},
                "expectations": {"expected_title": title, "expected_facts": facts},
                "tags": {"source_rule": getattr(r, "source_rule", "")},
            }
        )
    return rows


# --- Scorers ------------------------------------------------------------------
def _sru_titles(text: str) -> list[tuple[str, str]]:
    """Return (url, decoded alma.title) for every SRU URL in the response."""
    found = []
    for url in re.findall(r"https://[^\s<>\"'`\]\)]+", text or ""):
        if "/view/sru/" not in url:
            continue
        query = parse_qs(urlparse(url).query).get("query", [""])[0]
        m = re.search(r'alma\.title="(.*)" and alma\.local_field_912="Article"', query)
        found.append((url, m.group(1) if m else ""))
    return found


@scorer
def sru_url_match(outputs, expectations) -> Feedback:
    """Deterministic check: right base URL and exactly the expected alma.title term."""
    expected = expectations.get("expected_title", "")
    urls = _sru_titles(outputs)
    if not expected:
        return Feedback(
            value=not urls,
            rationale="No SRU URL expected; "
            + (f"got {len(urls)}" if urls else "none given"),
        )
    if not urls:
        return Feedback(
            value=False, rationale="Expected an SRU URL; none in the response"
        )
    good = [u for u, t in urls if t == expected and u.startswith(SRU_BASE + "?")]
    if good:
        return Feedback(value=True, rationale="Base URL and alma.title match")
    url, title = urls[0]
    why = (
        "wrong base URL"
        if not url.startswith(SRU_BASE + "?")
        else f'alma.title was "{title}"'
    )
    return Feedback(value=False, rationale=f'Expected alma.title "{expected}"; {why}')


SCORERS = [
    sru_url_match,  # primary, deterministic
    Correctness(),  # LLM judge on expected_facts
    # Domain-aware relevance. The built-in RelevanceToQuery judge reads a bare notice
    # title such as "Correction to: <title>" as a request to correct the article, and
    # marks the SRU URL irrelevant.
    Guidelines(
        name="relevant_to_notice",
        guidelines=(
            "The user message is an erratum or correction notice title from a library "
            "catalog. NAL staff send it to find the original article being corrected. "
            "A "
            "relevant response gives the NAL Alma SRU search URL for that original "
            "article, or explains that the notice names no single article to search "
            "for."
        ),
    ),
    Safety(),
    Guidelines(
        name="no_invented_urls",
        guidelines=(
            "The response must only give SRU URLs that came from the "
            "build_sru_search_url tool and must not add unrelated commentary. If the "
            "tool reported an empty reply or an error, the response says so instead of "
            "inventing a URL."
        ),
    ),
]


LATENCY: dict[str, float] = {}


def predict(request: str) -> str:
    """POST the title to the deployed app's agent and return its reply text."""
    headers = {**_ws.config.authenticate(), "Content-Type": "application/json"}
    started = time.monotonic()
    r = requests.post(
        f"{APP_URL}/invocations",
        headers=headers,
        timeout=TIMEOUT_S,
        json={"input": [{"role": "user", "content": request}]},
    )
    LATENCY[request] = time.monotonic() - started
    if r.status_code != 200:
        return f"ERROR HTTP {r.status_code}: {r.text[:300]}"
    return r.json()["output"][0]["content"][0]["text"] or ""


eval_dataset = load_dataset(DATASET_PATH)

if __name__ == "__main__":
    results = evaluate(data=eval_dataset, predict_fn=predict, scorers=SCORERS)
    print(results.metrics)
