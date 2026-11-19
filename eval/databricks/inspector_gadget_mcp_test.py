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

# COMMAND ----------

# DBTITLE 1,Test the browser page and /api/sru-url
import requests

# The browser page (GET /) and its JSON API, called as Inspector Gadget (needs CAN USE on the app).
app_url = mcp_server_url.rsplit('/mcp', 1)[0]
headers = workspace_client.config.authenticate()
checks = []
r = requests.get(f'{app_url}/', allow_redirects=False, timeout=30)
checks.append(('GET / without a token goes to the login page', r.status_code in (302, 303, 401), r.status_code))
r = requests.get(f'{app_url}/', headers=headers, timeout=30)
csp = r.headers.get('Content-Security-Policy', '')
checks.append(('GET / serves the page with a per-request CSP nonce', r.status_code == 200 and "script-src 'nonce-" in csp, r.status_code))
r = requests.post(f'{app_url}/api/sru-url', headers=headers, data={'title': 'x'}, timeout=30)
checks.append(('A plain form post to /api/sru-url is refused', r.status_code == 415, r.status_code))
start = time.time()
r = requests.post(f'{app_url}/api/sru-url', headers=headers, json={'title': sample_title}, timeout=300)
urls = r.json().get('urls', []) if r.ok else []
checks.append((f'POST /api/sru-url returns one SRU URL ({time.time() - start:.0f} s)', r.status_code == 200 and len(urls) == 1, r.status_code))
for name, ok, status in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name} (HTTP {status})")

# COMMAND ----------

# DBTITLE 1,Offline test: load Sample3 and expected URLs
# Offline regression test of the MCP server against the confirmed UC function users.amanda_xu.build_sru_url.
# INPUT is the Sample3 workbook copy in the erratum Volume.
INPUT = '/Volumes/users/amanda_xu/erratum_files/Correction-Sample3-142-20261016-20261030.xlsx'
RESULT_TABLE = 'users.amanda_xu.sample3_mcp_offline_test'

spark.sql("""SELECT * FROM read_files(:path, format => 'excel', headerRows => 1,
    dataAddress => '''Digital titles export''!A1:C143', schemaEvolutionMode => 'none')""",
    args={'path': INPUT}).createOrReplaceTempView('sample3_raw')

exp = spark.sql("""
SELECT row_number() OVER (ORDER BY `MMS ID`) AS row_num,
       Title AS erratum_title, `Record Number` AS record_number, `MMS ID` AS erratum_mms_id,
       users.amanda_xu.build_sru_url(Title) AS expected_url
FROM sample3_raw""").toPandas()
print(len(exp), 'titles;', (exp.expected_url.fillna('') == '').sum(), 'with blank expected URL')

# COMMAND ----------

# DBTITLE 1,Offline test: call MCP tool for every title
import asyncio, time, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from databricks_mcp import DatabricksOAuthClientProvider

async def _call_one(sem, title, timeout_s=300):
    async with sem:
        t0 = time.time()
        try:
            async with httpx2.AsyncClient(auth=DatabricksOAuthClientProvider(workspace_client),
                                          follow_redirects=True, timeout=httpx2.Timeout(timeout_s)) as hc:
                async with Client(streamable_http_client(server_url, http_client=hc)) as s:
                    r = await s.call_tool('build_sru_search_url', {'correction_title': title},
                                          read_timeout_seconds=timeout_s)
            text = ' '.join(getattr(c, 'text', '') for c in r.content).strip()
            status = 'TOOL_ERROR' if r.is_error else 'OK'
        except BaseException as e:
            errs = getattr(e, 'exceptions', None) or [e]
            text, status = '; '.join(f'{type(x).__name__}: {x}' for x in errs), 'EXCEPTION'
        return status, text, round(time.time() - t0, 1)

async def run_batch(titles, concurrency=10):
    sem = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*[_call_one(sem, t) for t in titles])

# ~8 minutes for 142 titles at concurrency 10
res = asyncio.run(run_batch(exp.erratum_title.tolist()))
exp['mcp_status'], exp['mcp_output'], exp['mcp_seconds'] = zip(*res)

# COMMAND ----------

# DBTITLE 1,Offline test: classify results and save
import pandas as pd

def classify(r):
    expected = r.expected_url or ''
    if r.mcp_status != 'OK':
        return 'ERROR'
    if r.mcp_output == expected:
        return 'EXACT'
    if not expected:
        return 'BARE_NOTICE_NO_URL'          # bare Correction/Erratum: agent asks for full title
    if r.mcp_output.startswith('agent-sru-syntax returned an empty reply'):
        return 'EMPTY_AGENT_REPLY'
    if expected in r.mcp_output:
        return 'CORRECT_URL_EXTRA_TEXT'
    return 'WRONG_URL'

exp['result'] = exp.apply(classify, axis=1)
exp['tested_at'] = pd.Timestamp.now(tz='UTC')
exp['run_id'] = exp['tested_at'].iloc[0].strftime('%Y%m%dT%H%M%S')
# Append so earlier runs are kept; compare with GROUP BY run_id, result
spark.createDataFrame(exp).write.mode('append').option('mergeSchema', 'true').saveAsTable(RESULT_TABLE)

print(exp.result.value_counts().to_string())
print(f"latency s: median {exp.mcp_seconds.median():.1f}, max {exp.mcp_seconds.max():.1f}")
display(spark.table(RESULT_TABLE).where(f"run_id = '{exp.run_id.iloc[0]}' AND result <> 'EXACT'").select('row_num', 'result', 'mcp_seconds', 'erratum_title', 'mcp_output'))