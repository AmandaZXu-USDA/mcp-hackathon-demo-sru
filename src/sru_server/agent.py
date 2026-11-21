"""SRU syntax agent using the OpenAI Agents SDK and this app\'s own MCP server."""

from __future__ import annotations

import os

import mlflow
from agents import Agent, Runner, set_default_openai_api, set_default_openai_client
from agents.mcp import MCPServerStreamableHttp
from agents.tracing import set_trace_processors
from databricks_openai import AsyncDatabricksOpenAI

MODEL_SERVICE = os.environ.get("MODEL_SERVICE", "")
# AGENT_MODEL, if set, is a Databricks-hosted foundation model serving endpoint (for
# example databricks-gpt-5-6-luna) used instead of the Unity Gateway model service.
# Added 2026-11-21: the OpenAI key behind the models.ai model services expired.
AGENT_MODEL = os.environ.get("AGENT_MODEL", "").strip()
MODEL = AGENT_MODEL or MODEL_SERVICE

# A serving endpoint, or a model service through Unity Gateway
set_default_openai_client(AsyncDatabricksOpenAI(use_ai_gateway=not AGENT_MODEL))
set_default_openai_api("responses")
set_trace_processors([])
mlflow.set_tracking_uri("databricks")
mlflow.openai.autolog()

if os.environ.get("MLFLOW_EXPERIMENT_ID"):
    mlflow.set_experiment(experiment_id=os.environ["MLFLOW_EXPERIMENT_ID"])

PORT = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
LOCAL_MCP_URL = f"http://127.0.0.1:{PORT}/mcp"
MCP_TIMEOUT_S = float(os.environ.get("AGENT_TIMEOUT_SECONDS", "300"))

INSTRUCTIONS = (
    "You help NAL staff find the original article behind erratum and correction "
    "notices. Call the build_sru_search_url tool once per title, passing the full "
    "title exactly as given. Return the NAL Alma production SRU searchRetrieve URL. "
    "For bare notices (just a notice word like Correction), reply that no article is "
    "named. For issue-level notices, reply that the notice covers a journal issue, "
    "not a single article. Do not invent SRU URLs."
)


def preprocess(messages):
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    return [
        {**m, "content": m["content"].strip()}
        if isinstance(m.get("content"), str)
        else m
        for m in messages
    ]


@mlflow.trace(name="sru_syntax_agent_run", span_type="AGENT")
async def run_agent(messages):
    mlflow.update_current_trace(
        tags={"agent_name": "SRU Syntax Agent", "model_service": MODEL}
    )
    with mlflow.start_span(name="preprocessing") as span:
        span.set_inputs({"raw": messages})
        cleaned = preprocess(messages)
        span.set_outputs({"cleaned": cleaned})
    async with MCPServerStreamableHttp(
        params={
            "url": LOCAL_MCP_URL,
            "timeout": MCP_TIMEOUT_S,
            "sse_read_timeout": MCP_TIMEOUT_S,
        },
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
