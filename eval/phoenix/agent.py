"""SRUSyntaxAgent: a LangChain agent that can use only the mcp-sru-syntax MCP server.

Launches the server (``src/sru_server``) over stdio, gives its tools to a LangChain
agent driven by ``AGENT_MODEL`` on Databricks serving endpoints, and traces each run
to Phoenix.

Smoke test, from ``eval/phoenix/`` with Phoenix running::

    uv run agent.py "Correction for Kuo and Chang, GATA-1 and Gfi-1B Interplay To ..."
    uv run agent.py --no-trace "..."   # without Phoenix
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable

import gateway
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

load_dotenv()

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
PROMPTS_DIR = HERE / "prompts"
SERVER_KEY = "sru_syntax_server"
DEFAULT_PROJECT = "mcp-sru-syntax-eval"
DEFAULT_PHOENIX_ENDPOINT = "http://localhost:6006"
RECURSION_LIMIT = 12  # model and tool steps per question; one question needs about 3
SAMPLE_QUERY = (
    "What is the NAL Alma SRU search URL for the original article corrected by "
    "'Correction for Kuo and Chang, GATA-1 and Gfi-1B Interplay To Regulate Bcl-xL "
    "Transcription'? Reply with the URL only."
)


def prompt_versions() -> list[str]:
    """Prompt versions that exist in prompts/ (system_prompt_<version>.txt)."""
    names = (p.stem for p in PROMPTS_DIR.glob("system_prompt_v*.txt"))
    return sorted(name.removeprefix("system_prompt_") for name in names)


def server_setting_names() -> set[str]:
    """Environment variable names the server reads (its Settings fields)."""
    from sru_server.config import Settings

    return {name.upper() for name in Settings.model_fields}


def server_connection() -> dict[str, Any]:
    """Stdio launch config for the server; works from any working directory.

    Uses this interpreter (the harness's environment, where ``uv sync`` installed
    ``sru_server``) instead of a nested ``uv run``.
    """
    env = gateway.server_env(server_setting_names())
    env["MCP_TRANSPORT"] = "stdio"
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "sru_server.app"],
        "cwd": str(REPO_ROOT),
        "env": env,
    }
    # Alternative, the deployed app (needs an OAuth token for Databricks Apps):
    # {"transport": "streamable_http", "url": "https://<app>/mcp", "headers": {...}}


def _text(message: Any) -> str:
    """Plain text of a LangChain message (content may be a list of blocks)."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


class SRUSyntaxAgent:
    """The agent-under-test: one LLM, the server's tools, a versioned system prompt."""

    def __init__(
        self,
        system_prompt_version: str = "v1",
        project_name: str = DEFAULT_PROJECT,
        phoenix_endpoint: str | None = None,
        model: str | None = None,
    ) -> None:
        self.system_prompt_version = system_prompt_version
        self.project_name = project_name
        self.phoenix_endpoint = (
            phoenix_endpoint
            or os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
            or DEFAULT_PHOENIX_ENDPOINT
        ).rstrip("/")
        self.model = model or gateway.agent_model()
        self.system_prompt = self._load_system_prompt()
        self.client: MultiServerMCPClient | None = None
        self.tools: list | None = None
        self.tracer_provider = None

    def _load_system_prompt(self) -> str:
        path = PROMPTS_DIR / f"system_prompt_{self.system_prompt_version}.txt"
        if not path.is_file():
            raise ValueError(
                f"No prompt {path.name}; available: {', '.join(prompt_versions())}"
            )
        return path.read_text(encoding="utf-8").strip()

    def initialize(self, trace: bool = True) -> SRUSyntaxAgent:
        """Instrument LangChain for Phoenix (once) and load the server's tools."""
        if trace and self.tracer_provider is None:
            from openinference.instrumentation.langchain import LangChainInstrumentor
            from phoenix.otel import register

            self.tracer_provider = register(
                project_name=self.project_name,
                endpoint=f"{self.phoenix_endpoint}/v1/traces",
                verbose=False,
            )
            LangChainInstrumentor().instrument(tracer_provider=self.tracer_provider)
        self.client = MultiServerMCPClient({SERVER_KEY: server_connection()})
        # Each tool call opens its own stdio session, so the tools are not tied to
        # this event loop and can be reused by later asyncio.run() calls.
        self.tools = asyncio.run(self.client.get_tools())
        return self

    def _chat_model(self) -> ChatOpenAI:
        # Built per run: its async HTTP client belongs to the event loop of the run.
        return ChatOpenAI(
            model=self.model,
            base_url=gateway.base_url(),
            api_key=gateway.api_key(),
            temperature=0,
            reasoning_effort=gateway.reasoning_effort(self.model),
            timeout=120,
            max_retries=2,
        )

    async def run(self, query: str) -> dict[str, Any]:
        """Answer one question; return the final text and the tools it called."""
        if self.tools is None:
            raise RuntimeError("Call initialize() before run().")
        agent = create_agent(
            model=self._chat_model(),
            tools=self.tools,
            system_prompt=self.system_prompt,
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"recursion_limit": RECURSION_LIMIT},
        )
        messages = result["messages"]
        tool_calls = [
            call["name"]
            for message in messages
            for call in (getattr(message, "tool_calls", None) or [])
        ]
        return {"response": _text(messages[-1]), "tool_calls": tool_calls}

    def create_experiment_task(self) -> Callable[[dict], dict[str, Any]]:
        """A synchronous Phoenix task: Phoenix passes the example's ``input`` dict."""

        def task(input: dict) -> dict[str, Any]:
            return asyncio.run(self.run(input["query"]))

        return task


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("query", nargs="?", default=SAMPLE_QUERY)
    parser.add_argument(
        "--system-prompt-version", default="v1", choices=prompt_versions()
    )
    parser.add_argument(
        "--no-trace", action="store_true", help="do not send traces to Phoenix"
    )
    args = parser.parse_args()
    agent = SRUSyntaxAgent(system_prompt_version=args.system_prompt_version)
    agent.initialize(trace=not args.no_trace)
    print(f"tools: {[tool.name for tool in agent.tools]}")
    answer = asyncio.run(agent.run(args.query))
    print(f"tool calls: {answer['tool_calls']}")
    print(answer["response"])


if __name__ == "__main__":
    main()
