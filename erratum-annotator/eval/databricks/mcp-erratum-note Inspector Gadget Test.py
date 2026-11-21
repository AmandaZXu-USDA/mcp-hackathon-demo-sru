# Databricks notebook source
# DBTITLE 1,About this test
# MAGIC %md
# MAGIC # mcp-erratum-note: Inspector Gadget test
# MAGIC Live test of the Databricks App MCP server `mcp-erratum-note`, run as the **Inspector Gadget** service principal (application ID `f22c554b-c019-4511-8774-079d9891c7d5`, credentials in the UC secret `models.ai/inspector-gadget`).
# MAGIC
# MAGIC * Prerequisite: Inspector Gadget has **CAN_USE** on the app (granted 2026-11-21).
# MAGIC * The test lists the tools, calls `list_sru_files`, then calls `process_sru_file` on every saved Sample1 SRU response and compares `annotated_title` and `original_id` with `Correction-Sample1-53-annotated.csv`.
# MAGIC * Each run is **appended** to `users.amanda_xu.erratum_mcp_inspector_test` (one row per file, keyed by `run_ts`) and exported as a per-row CSV to `DOC`.
# MAGIC * Rows 4 and 24 are expected to differ: Alma has no original, so the ground-truth title is blank, while the tool still builds a title from the search title.

# COMMAND ----------

# DBTITLE 1,Install pinned MCP client packages
# Versions verified 2026-11-21; mcp 2.x uses snake_case fields (Tool.input_schema, CallToolResult.is_error)
%pip install -q databricks-mcp==0.9.2 databricks-sdk==0.168.0 mcp==2.3.0
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Configuration and Inspector Gadget client
import asyncio, json, re, time
from dataclasses import dataclass
import httpx2
import nest_asyncio
import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks_mcp import DatabricksOAuthClientProvider
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

nest_asyncio.apply()

SERVER_URL = 'https://mcp-erratum-note-7474654188777746.aws.databricksapps.com/mcp'
RESULT_TABLE = 'users.amanda_xu.erratum_mcp_inspector_test'
GT_CSV = '/Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv'
DOC = '/Workspace/Users/amanda.xu@usda.gov/erratum-annotator/eval/doc'  # per-row CSV export folder
TESTER = 'Inspector Gadget (f22c554b-c019-4511-8774-079d9891c7d5)'
TIMEOUT_S = 300  # DatabricksMCPClient's 5 s httpx default is too short for tool calls


@dataclass
class InspectorGadget:
    client_id: str
    client_secret: str
    scopes: list[str]

    @classmethod
    def from_uc(cls):
        return cls(**json.loads(dbutils.secrets.get(catalog='models', schema='ai', key='inspector-gadget')))

    def workspace_client(self) -> WorkspaceClient:
        # OAuth M2M must use the workspace URL as host, not the app URL
        host = f"https://{spark.conf.get('spark.databricks.workspaceUrl')}"
        return WorkspaceClient(host=host, client_id=self.client_id, client_secret=self.client_secret, scopes=self.scopes)


ig_wc = InspectorGadget.from_uc().workspace_client()


async def in_session(fn):
    async with httpx2.AsyncClient(auth=DatabricksOAuthClientProvider(ig_wc), follow_redirects=True,
                                  timeout=httpx2.Timeout(TIMEOUT_S)) as hc:
        async with Client(streamable_http_client(SERVER_URL, http_client=hc)) as s:
            return await fn(s)


# Ground truth: the CSV is Excel-formatted (UTF-8 BOM, IDs written as ="...")
gt = pd.read_csv(GT_CSV, encoding='utf-8-sig', dtype=str).fillna('')
for c in gt.columns:
    gt[c] = gt[c].str.replace(r'^="(.*)"$', r'\1', regex=True)
print(len(gt), 'ground-truth rows')

# COMMAND ----------

# DBTITLE 1,Call every tool path and score each file
async def run_all(s):
    tools = [t.name for t in (await s.list_tools()).tools]
    listing = await s.call_tool('list_sru_files', {}, read_timeout_seconds=TIMEOUT_S)
    files = json.loads(listing.content[0].text)['files']
    fmap = {re.match(r'Sample1-Row(\d+)-', f).group(1): f for f in files}
    out = []
    for _, g in gt[gt.row_num.isin(fmap)].iterrows():
        t0 = time.time()
        try:
            r = await s.call_tool('process_sru_file', {'file_name': fmap[g.row_num], 'search_title': g.search_title,
                                                       'correction_id': g.erratum_mms_id}, read_timeout_seconds=TIMEOUT_S)
            text = r.content[0].text if r.content else ''
            is_error = bool(r.is_error)
            d = {} if is_error else json.loads(text)
        except Exception as e:  # record the failure and keep testing the other files
            text, is_error, d = f'{type(e).__name__}: {e}', True, {}
        out.append(dict(
            row_num=int(g.row_num), file_name=fmap[g.row_num], is_error=is_error,
            latency_sec=round(time.time() - t0, 2),
            # an errored call never counts as a match, even when the expected value is blank
            title_ok=not is_error and d.get('annotated_title', '') == g.annotated_title,
            mms_ok=not is_error and (d.get('original_id') or '') == g.original_mms_id,
            gt_erratum_status=g.erratum_status, needs_review=d.get('needs_review'),
            already_annotated=d.get('already_annotated'),
            got_original_mms_id=d.get('original_id'), gt_original_mms_id=g.original_mms_id,
            got_annotated_title=d.get('annotated_title'), gt_annotated_title=g.annotated_title,
            tool_output_json=text))
    return tools, len(files), out


tools, n_files, out = asyncio.run(in_session(run_all))
res = pd.DataFrame(out)
res['run_ts'] = pd.Timestamp.now(tz='UTC').floor('s')
res['tester'] = TESTER
res['server_url'] = SERVER_URL
spark.createDataFrame(res).write.mode('append').saveAsTable(RESULT_TABLE)

print(f"{len(tools)} tools: {tools}")
print(f"list_sru_files: {n_files} files")
print(f"{len(res)} files | errors {res.is_error.sum()} | title {res.title_ok.sum()}/{len(res)} | "
      f"MMS {res.mms_ok.sum()}/{len(res)} | median {res.latency_sec.median():.2f} s, max {res.latency_sec.max():.2f} s")

# COMMAND ----------

# DBTITLE 1,Rows that differ from the ground truth
EXPECTED_DIFF = {4, 24}  # no original in Alma: ground-truth title blank, tool builds one from the search title
bad = res[res.is_error | ~res.title_ok | ~res.mms_ok]
display(bad[['row_num', 'is_error', 'title_ok', 'mms_ok', 'gt_erratum_status', 'needs_review',
             'got_original_mms_id', 'got_annotated_title', 'tool_output_json']])
unexpected = set(bad.row_num) - EXPECTED_DIFF
assert not unexpected, f'Unexpected failures: {sorted(unexpected)}'
print('Only the expected rows differ:', sorted(set(bad.row_num)))

# COMMAND ----------

# DBTITLE 1,Export per-row results and run history
run_ts = res.run_ts.iloc[0]
csv_path = f"{DOC}/mcp-erratum-note-inspector-test-{run_ts:%Y%m%d}.csv"
res.assign(run_ts=run_ts.strftime('%Y-%m-%dT%H:%M:%SZ')).to_csv(csv_path, index=False)
print('Saved', csv_path, len(pd.read_csv(csv_path)), 'rows')

display(spark.sql(f"""
  SELECT run_ts, count(*) AS files, sum(cast(is_error AS int)) AS errors,
         sum(cast(title_ok AS int)) AS title_ok, sum(cast(mms_ok AS int)) AS mms_ok,
         round(percentile(latency_sec, 0.5), 2) AS median_sec, round(max(latency_sec), 2) AS max_sec
  FROM {RESULT_TABLE} GROUP BY run_ts ORDER BY run_ts DESC"""))