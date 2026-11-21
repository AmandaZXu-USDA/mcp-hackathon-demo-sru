"""SRU syntax agent: an OpenAI Agents SDK agent that uses this app's own MCP server.

The agent runs in the same Databricks App as the MCP server (app.py) and connects to it over
localhost, so it needs no extra app, URL lookup, or app-to-app permission.
"""
import os

import mlflow
from agents import Agent, Runner, set_default_openai_api, set_default_openai_client
from agents.mcp import MCPServerStreamableHttp
from agents.tracing import set_trace_processors
from databricks_openai import AsyncDatabricksOpenAI

# Environment variables injected from the app resources declared in databricks.yml
MODEL_SERVICE = os.environ["MODEL_SERVICE"]
# AGENT_MODEL, if set, is a Databricks-hosted foundation model serving endpoint (for example
# databricks-gpt-5-6-luna) used instead of the Unity Gateway model service. Added 2026-11-21 because
# the OpenAI API key behind the models.ai model services expired (401 on every call).
AGENT_MODEL = os.environ.get("AGENT_MODEL", "").strip()
MODEL = AGENT_MODEL or MODEL_SERVICE

# Point the OpenAI Agents SDK at Databricks: a serving endpoint, or a model through Unity Gateway
set_default_openai_client(AsyncDatabricksOpenAI(use_ai_gateway=not AGENT_MODEL))
set_default_openai_api("responses")

# Send traces to MLflow instead of OpenAI
set_trace_processors([])
mlflow.set_tracking_uri("databricks")
mlflow.openai.autolog()  # automatic tracing of every model and tool call

mlflow.set_experiment(experiment_id=os.environ["MLFLOW_EXPERIMENT_ID"])

# This app's own MCP endpoint (same process, served by app.py)
PORT = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
LOCAL_MCP_URL = f"http://127.0.0.1:{PORT}/mcp"
# The agent-sru-syntax endpoint can take 60-90 seconds per title, so allow a long timeout
MCP_TIMEOUT_S = float(os.environ.get("AGENT_TIMEOUT_SECONDS", "300"))

INSTRUCTIONS = (
    "You help National Agricultural Library (NAL) staff find the original article behind "
    "erratum and correction notices. When the user gives one or more correction notice titles "
    "(for example 'Correction: <title>', 'Correction to \u201c<title>\u201d', 'Corrigendum: ...', "
    "'Erratum: ...'), call the build_sru_search_url tool once per title, passing the full title "
    "exactly as given. Return the NAL Alma production SRU searchRetrieve URL for each title. "
    "A bare notice is only a notice word with no article title, such as 'Correction', 'Corrigendum', "
    "'Erratum', 'Errata', 'Addendum' or 'Correction notice'. For a bare notice, do not call the tool and "
    "do not ask for more details: reply that the notice names no article, so there is no SRU URL to build. "
    "An issue-level notice covers a whole journal issue or several articles rather than one article, "
    "for example a journal name with volume(issue) such as 'Taxon 72(3)' or 'Errata to Brittonia 70(2)', "
    "or 'Correction for Data Papers Published in <years>' or 'Errata for articles published in ...'. "
    "For an issue-level notice, do not call the tool and do not ask "
    "questions: reply that the notice covers a journal issue or several articles, not a single article, so "
    "there is no SRU URL to build. "
    "Some notices repeat only the article title, with no notice wording; call the tool for those too. "
    "If you are unsure whether the text names a single article, call the tool. "
    "If the tool says it returned an empty reply, relay that message to the user. "
    "Do not invent SRU URLs yourself. For other questions, answer clearly and concisely."
)


def preprocess(messages: list[dict] | str) -> list[dict]:
    """Normalize the request into Responses-style input items with trimmed text."""
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    cleaned = []
    for m in messages:
        if isinstance(m.get("content"), str):
            m = {**m, "content": m["content"].strip()}
        cleaned.append(m)
    return cleaned


@mlflow.trace(name="sru_syntax_agent_run", span_type="AGENT")
async def run_agent(messages: list[dict] | str) -> str:
    """Run the agent with this app's MCP tools and return the final reply."""
    mlflow.update_current_trace(tags={"agent_name": "SRU Syntax Agent", "model_service": MODEL})

    # Custom span: trace our own preprocessing in the same trace
    with mlflow.start_span(name="preprocessing") as span:
        span.set_inputs({"raw": messages})
        cleaned = preprocess(messages)
        span.set_outputs({"cleaned": cleaned})

    # Connect to the local MCP server for this request; leaving the block closes the connection
    async with MCPServerStreamableHttp(
        params={"url": LOCAL_MCP_URL, "timeout": MCP_TIMEOUT_S, "sse_read_timeout": MCP_TIMEOUT_S},
        name="mcp-sru-syntax",
        client_session_timeout_seconds=MCP_TIMEOUT_S,
    ) as mcp_server:
        agent = Agent(
            name="SRU Syntax Agent",
            instructions=INSTRUCTIONS,
            model=MODEL,
            mcp_servers=[mcp_server],
        )
        result = await Runner.run(agent, cleaned)
    return result.final_output
