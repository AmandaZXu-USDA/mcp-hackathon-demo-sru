# Databricks notebook source


# COMMAND ----------

# This is provided as an example.  Prefer the use of Environment for dependency management!
%pip install --upgrade databricks-mcp databricks-sdk;
%restart_python

# COMMAND ----------

import json
from urllib.parse import urljoin
from dataclasses import dataclass
from databricks.sdk import WorkspaceClient
from databricks_mcp import DatabricksMCPClient

import nest_asyncio
nest_asyncio.apply()

# COMMAND ----------

# DBTITLE 1,Inspector Gadget class
@dataclass
class InspectorGadget:
    client_id: str
    client_secret: str
    scopes: list[str]

    @classmethod
    def from_uc(cls):
        params = dbutils.secrets.get(
            catalog='models',
            schema='ai',
            key='inspector-gadget'
        )
        return cls(**json.loads(params))
    
    def workspace_client(self, host: str | None = None) -> WorkspaceClient:
        if not host:
            netloc = spark.conf.get("spark.databricks.workspaceUrl")
            host = f'https://{netloc}'
        return WorkspaceClient(
            host = host,
            client_id = self.client_id,
            client_secret = self.client_secret,
            scopes = self.scopes
        )


# COMMAND ----------


# Provide the MCP server's network location (the host) without the path [/mcp]
mcp_server_url = 'https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/mcp'
server_url = urljoin(mcp_server_url, 'mcp')

# create an instance of Inspector Gadget and use to create a WorkspaceClient
ig = InspectorGadget.from_uc()
workspace_client = ig.workspace_client()

mcp_client = DatabricksMCPClient(
    server_url=server_url,
    workspace_client=workspace_client
)

print([
    tool.name 
    for tool in mcp_client.list_tools()
])

# COMMAND ----------

# DBTITLE 1,Call build_sru_search_url with sample title
import asyncio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from databricks_mcp import DatabricksOAuthClientProvider

# Replies can take 60-90 seconds; DatabricksMCPClient.call_tool uses httpx's 5s default timeout,
# so open the session directly with a longer timeout.
sample_title = 'Correction: Autogenic and climatic drivers of vegetation succession in a thermokarst lake-margin peatland, northern Greater Khingan Mountains'

async def call_tool_with_timeout(tool_name, arguments, timeout_s=300):
    async with httpx2.AsyncClient(
        auth=DatabricksOAuthClientProvider(workspace_client),
        follow_redirects=True,
        timeout=httpx2.Timeout(timeout_s),
    ) as http_client:
        async with Client(streamable_http_client(server_url, http_client=http_client)) as session:
            return await session.call_tool(tool_name, arguments, read_timeout_seconds=timeout_s)

response = asyncio.run(call_tool_with_timeout(
    'build_sru_search_url',
    {'correction_title': sample_title}
))

for item in response.content:
    print(item.text)

# COMMAND ----------

# DBTITLE 1,Test every tool on the app
import time

# Sample arguments per tool; add an entry here when the app gets a new tool.
# Tools without an entry get placeholder values built from their input schema.
sample_args = {
    'build_sru_search_url': {'correction_title': 'Correction to: Identification of JAZ1-MYC2 Complex in Lotus corniculatus'}
}

PLACEHOLDERS = {'string': 'test', 'integer': 1, 'number': 1.0, 'boolean': True, 'array': [], 'object': {}}

def placeholder_args(tool):
    schema = tool.input_schema or {}
    props = schema.get('properties', {})
    return {name: PLACEHOLDERS.get(props[name].get('type'), 'test') for name in schema.get('required', [])}

results = []
for tool in mcp_client.list_tools():
    args = sample_args.get(tool.name) or placeholder_args(tool)
    start = time.time()
    try:
        resp = asyncio.run(call_tool_with_timeout(tool.name, args))
        text = ' '.join(getattr(c, 'text', '') for c in resp.content)
        status = 'FAIL' if resp.is_error else 'PASS'
    except BaseException as e:
        errs = getattr(e, 'exceptions', None) or [e]
        text = '; '.join(f'{type(x).__name__}: {x}' for x in errs)
        status = 'ERROR'
    results.append({'tool': tool.name, 'status': status, 'seconds': round(time.time() - start, 1),
                    'args': json.dumps(args), 'output': text[:500]})

for r in results:
    print(f"[{r['status']}] {r['tool']} ({r['seconds']}s) args={r['args']}\n  {r['output']}\n")
print(f"{sum(r['status'] == 'PASS' for r in results)}/{len(results)} tools passed")