"""Eval-time auth shim for the SRU syntax agent (sru-syntax-mcp/agent/agent_server/agent.py).

Adapted from mcp-hackathon/eval/databricks/agent_server/eval_auth.py.

WHY THIS FILE EXISTS
--------------------
The agent connects to the sru-syntax-mcp Databricks App with a module-level
``ws = WorkspaceClient()``. Inside the deployed app that is the app's service
principal. In an offline notebook eval it would be the notebook identity, which
cannot mint the OAuth token a Databricks App requires ("OAuth tokens are not
available for runtime authentication"), so the MCP connection fails.

The only identity that reliably reaches a deployed app from an offline eval is a
SERVICE PRINCIPAL using OAuth machine-to-machine (M2M) with ``CAN_USE`` on the app.

WHAT THIS FILE DOES
-------------------
It leaves agent.py UNTOUCHED and patches two module attributes at runtime:

* ``agent.ws``      -> an authenticated service-principal WorkspaceClient, used by
                       ``McpServer(workspace_client=ws)`` on every request.
* ``agent.mcp_url`` -> returns the configured MCP URL directly, so the eval does not
                       need permission to look the app up by name.

USAGE
-----
    import agent_server.agent as agent
    from eval_auth import patch_agent_with_service_principal

    patch_agent_with_service_principal(agent, mcp_url="https://<app>/mcp", host=..., client_id=..., client_secret=...)
"""

from __future__ import annotations

from databricks.sdk import WorkspaceClient


def build_service_principal_client(host: str, client_id: str, client_secret: str) -> WorkspaceClient:
    """Return an OAuth M2M service-principal client (needs CAN_USE on the app + workspace-access)."""
    return WorkspaceClient(host=host, client_id=client_id, client_secret=client_secret, auth_type="oauth-m2m")


def patch_agent(agent_module, mcp_url: str, workspace_client: WorkspaceClient) -> WorkspaceClient:
    """Point the agent at ``mcp_url`` and authenticate MCP calls with ``workspace_client``."""
    agent_module.ws = workspace_client
    agent_module.mcp_url = lambda: mcp_url
    return workspace_client


def patch_agent_with_service_principal(
    agent_module, mcp_url: str, host: str, client_id: str, client_secret: str
) -> WorkspaceClient:
    """Patch the agent to reach the deployed app as the eval service principal."""
    if not client_id or not client_secret:
        raise ValueError(
            "Service-principal credentials are missing. Run setup-eval-sp.sh (see README) "
            "and check SECRET_SCOPE / SECRET_KEY_* in the CONFIG block."
        )
    return patch_agent(agent_module, mcp_url, build_service_principal_client(host, client_id, client_secret))
