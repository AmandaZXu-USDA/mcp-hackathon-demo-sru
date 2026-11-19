# =============================================================================
# OFFLINE MLflow GenAI EVAL for the mcp-sru-syntax Databricks App
# =============================================================================
# Adapted from mcp-hackathon/eval/databricks/agent_eval_offline.py.
#
# Evaluates the SRU syntax agent (sru-syntax-mcp/agent/agent_server/agent.py,
# used UNMODIFIED) while it calls the DEPLOYED mcp-sru-syntax MCP server. Each
# row is an erratum/correction notice title; the agent should return the NAL
# Alma production SRU URL for the original article (or no URL for bare and
# issue-level notices).
#
# Run it in a Databricks notebook opened in THIS folder (eval/databricks/).
#
# !!! FIRST, run this in a SEPARATE notebook cell ABOVE this one, on its own:
# !!!
# !!!     %pip install openai-agents>=0.25 databricks-openai>=0.17 "mlflow[databricks]>=3.14"
# !!!     %restart_python
#
# Auth: a SERVICE PRINCIPAL (OAuth M2M) with CAN_USE on the app. See README and
# eval_auth.py for why the notebook's own identity cannot reach the app.
# =============================================================================
import asyncio
import atexit
import concurrent.futures
import contextvars
import os
import re
import sys
import threading
from urllib.parse import parse_qs, urlparse

import mlflow
import pandas as pd
from mlflow.entities import Feedback
from mlflow.genai import evaluate
from mlflow.genai.scorers import Correctness, Guidelines, Safety, scorer

# --- CONFIG: the things you edit --------------------------------------------
# 1) The deployed MCP server's /mcp URL.
MCP_SERVER_URL = os.getenv("SRU_EVAL_MCP_URL", "https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/mcp")

# 2) The model service the agent drives (same as the app's model-service resource).
MODEL = os.getenv("SRU_EVAL_MODEL", "models.ai.gpt-5-6-luna")

# 3) Workspace host + an experiment you can write to (UC-backed SRU agent experiment).
DATABRICKS_HOST = os.getenv("DATABRICKS_HOST", "https://dbc-aae0ba16-8727.cloud.databricks.com")
EXPERIMENT_ID = os.getenv("SRU_EVAL_EXPERIMENT_ID", "131270370350843")
# The experiment stores traces in Unity Catalog, so reading them back needs a SQL warehouse you can use.
SQL_WAREHOUSE_ID = os.getenv("MLFLOW_TRACING_SQL_WAREHOUSE_ID", "50d2bd4ddf65e0f5")  # Serverless Starter Warehouse

# 4) Secret scope + keys holding the eval service principal's credentials
#    (created by mcp-hackathon/eval/databricks/setup-eval-sp.sh; see README).
SECRET_SCOPE = "sru-syntax-eval-secrets"
SECRET_KEY_CLIENT_ID = "sp_id"
SECRET_KEY_CLIENT_SECRET = "sp_secret"

# 5) How the agent authenticates to the MCP server:
#    "service_principal" (default, required for the deployed app) or
#    "current_user" (only for a local, unauthenticated dev copy of the server).
AUTH_MODE = os.getenv("SRU_EVAL_AUTH", "service_principal")

# 6) Dataset: one row per title-extraction rule (see README.md).
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
DATASET_PATH = os.path.join(HERE, "datasets", "sru-eval-0.csv")

SRU_BASE = "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST"
# -----------------------------------------------------------------------------

# NOTE: do NOT call nest_asyncio.apply() (it breaks the shared-loop design below).

# --- Import the (unmodified) agent ---------------------------------------------
# agent.py reads these at import time.
os.environ["MODEL_SERVICE"] = MODEL
os.environ["MLFLOW_EXPERIMENT_ID"] = EXPERIMENT_ID
os.environ["MCP_SERVER_APP"] = MCP_SERVER_URL
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "agent")))  # sru-syntax-mcp/agent
sys.path.insert(0, HERE)

import agent_server.agent as agent  # noqa: E402
from eval_auth import patch_agent, patch_agent_with_service_principal  # noqa: E402

if AUTH_MODE == "service_principal":
    try:
        _sp_client_id = dbutils.secrets.get(SECRET_SCOPE, SECRET_KEY_CLIENT_ID)  # type: ignore[name-defined]
        _sp_client_secret = dbutils.secrets.get(SECRET_SCOPE, SECRET_KEY_CLIENT_SECRET)  # type: ignore[name-defined]
    except NameError:  # outside a Databricks notebook
        _sp_client_id = os.getenv("DATABRICKS_CLIENT_ID", "")
        _sp_client_secret = os.getenv("DATABRICKS_CLIENT_SECRET", "")
    patch_agent_with_service_principal(
        agent, mcp_url=MCP_SERVER_URL, host=DATABRICKS_HOST,
        client_id=_sp_client_id, client_secret=_sp_client_secret,
    )
else:
    from databricks.sdk import WorkspaceClient

    patch_agent(agent, MCP_SERVER_URL, WorkspaceClient())

# --- MLflow experiment + trace destination -----------------------------------
os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = SQL_WAREHOUSE_ID
mlflow.set_experiment(experiment_id=EXPERIMENT_ID)
# The template also calls mlflow.tracing.set_destination(MlflowExperimentLocation(...)). Do NOT do
# that for a Unity Catalog-backed experiment: it bypasses the experiment's UC trace tables, so the
# harness cannot read the traces back and assessments are not logged.

# Each row takes ~20 s (the Supervisor Agent behind the tool is the slow step).
# Keep parallelism low so the app is not hammered.
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
                f"The response contains an SRU searchRetrieve URL on {urlparse(SRU_BASE).netloc}",
                f'The URL\'s alma.title search term is the article title "{title}" (URL-encoded)',
            ]
        else:
            facts = ["The response does not give an SRU search URL, because the notice names no single article"]
        rows.append({
            "inputs": {"request": r.request},
            "expectations": {"expected_title": title, "expected_facts": facts},
            "tags": {"source_rule": getattr(r, "source_rule", "")},
        })
    return rows


eval_dataset = load_dataset(DATASET_PATH)


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
        return Feedback(value=not urls, rationale="No SRU URL expected; " + (f"got {len(urls)}" if urls else "none given"))
    if not urls:
        return Feedback(value=False, rationale="Expected an SRU URL; none in the response")
    good = [u for u, t in urls if t == expected and u.startswith(SRU_BASE + "?")]
    if good:
        return Feedback(value=True, rationale="Base URL and alma.title match")
    url, title = urls[0]
    why = "wrong base URL" if not url.startswith(SRU_BASE + "?") else f'alma.title was "{title}"'
    return Feedback(value=False, rationale=f'Expected alma.title "{expected}"; {why}')


SCORERS = [
    sru_url_match,  # primary, deterministic
    Correctness(),  # LLM judge on expected_facts
    # Domain-aware relevance. The built-in RelevanceToQuery judge reads a bare notice title such as
    # "Correction to: <title>" as a request to correct the article, and marks the SRU URL irrelevant.
    Guidelines(
        name="relevant_to_notice",
        guidelines=(
            "The user message is an erratum or correction notice title from a library catalog. NAL staff send it "
            "to find the original article being corrected. A relevant response gives the NAL Alma SRU search URL "
            "for that original article, or explains that the notice names no single article to search for."
        ),
    ),
    Safety(),
    Guidelines(
        name="no_invented_urls",
        guidelines=(
            "The response must only give SRU URLs that came from the build_sru_search_url tool and must not "
            "add unrelated commentary. If the tool reported an empty reply or an error, the response says so "
            "instead of inventing a URL."
        ),
    ),
]


# --- Async plumbing -----------------------------------------------------------
# agent.py creates ONE AsyncDatabricksOpenAI client at import; its connection pool
# binds to the first event loop that uses it. Run ONE persistent loop on a
# background thread and submit every call onto it. Each call runs in a copy of the
# caller's context, so the agent's spans join the trace that evaluate() opened for the row.
_LOOP = asyncio.new_event_loop()


def _loop_runner():
    asyncio.set_event_loop(_LOOP)
    _LOOP.run_forever()


_LOOP_THREAD = threading.Thread(target=_loop_runner, daemon=True, name="eval-async-loop")
_LOOP_THREAD.start()
atexit.register(lambda: _LOOP.call_soon_threadsafe(_LOOP.stop))


def _run_async(coro):
    ctx = contextvars.copy_context()
    result: concurrent.futures.Future = concurrent.futures.Future()

    def _done(task: asyncio.Task) -> None:
        if task.cancelled():
            result.set_exception(concurrent.futures.CancelledError())
        elif task.exception() is not None:
            result.set_exception(task.exception())
        else:
            result.set_result(task.result())

    def _start() -> None:  # runs on the loop thread inside ctx; the task inherits ctx
        _LOOP.create_task(coro).add_done_callback(_done)

    _LOOP.call_soon_threadsafe(_start, context=ctx)
    return result.result()


def predict(request: str) -> str:
    # run_agent is already traced (sru_syntax_agent_run), so no extra @mlflow.trace here.
    return _run_async(agent.run_agent([{"role": "user", "content": request}])) or ""


# --- Run evaluation -----------------------------------------------------------
if __name__ == "__main__":
    results = evaluate(data=eval_dataset, predict_fn=predict, scorers=SCORERS)
    print(results.metrics)
    # Per-row results and traces are in the MLflow experiment UI (Evaluations tab).
