# Databricks offline MLflow evaluation: sru-syntax-mcp

**Purpose:** verify that the SRU syntax agent produces correct NAL Alma production SRU URLs from
erratum/correction notice titles. A labelled dataset of 41 notices is scored by a deterministic
URL match plus four LLM judges (correctness, relevance, no invented URLs, safety), catching
rule regressions, empty Supervisor Agent replies, and instruction-following failures before
deploying changes.

Evaluates the SRU syntax agent while it uses the **deployed** `sru-syntax-mcp` MCP server
(a Databricks App), scored by MLflow GenAI judges plus a deterministic URL check. Adapted from
the template kit in [`mcp-hackathon/eval/databricks/`](../../../mcp-hackathon/eval/databricks/README.md).

Each dataset row is an erratum/correction notice title. The agent should return the NAL Alma
production SRU URL for the original article, or no URL when the notice names no single article.

## What's in this kit

| File | What it is |
|------|------------|
| `agent_eval_offline.py` | The eval script. Runs `mlflow.genai.evaluate` over the dataset with a `predict_fn` that calls the agent. |
| `eval_auth.py` | Auth shim. Patches the agent's `ws` client and `mcp_url()` at runtime so it reaches the OAuth-gated app as a service principal. `agent/agent_server/agent.py` stays unmodified. |
| `inspector_gadget_mcp_test.py` | Notebook source. Calls the deployed app's MCP tools as the Inspector Gadget service principal: lists tools, calls `build_sru_search_url`, and tests every tool. See [Testing the deployed MCP server](#testing-the-deployed-mcp-server-inspector-gadget). |
| `build_evaluation_report.py` | Notebook source. Builds the evaluation report PDF with `reportlab` and checks its text with `pypdf`. |
| [`doc/SRU_Agent_Latency_per_Step_20261118.csv`](doc/SRU_Agent_Latency_per_Step_20261118.csv) | Per-step agent latency for 174 requests on November 18, 2026 (request, preprocessing, both model calls, `build_sru_search_url`), from `users.amanda_xu.sru_syntax_agent_otel_spans`. Columns: span and trace counts, avg/p50/p90/min/max seconds, error count. Summarized in section 5 of the evaluation report. |
| `datasets/sru-eval-0.csv` | 41 rows covering every `extraction_rule` in the source spreadsheet (2 to 5 rows each), including 4 bare notices, 4 issue-level notices and the 2 titles that got an empty Supervisor Agent reply in the first 10-title test. |

Differences from the template:

* **The agent is ours, not Playground-generated.** The script imports `sru-syntax-mcp/agent/agent_server/agent.py`
  (the standalone agent version), so there is no export step and `eval_auth.py` sits next to the script.
* **No copy of `setup-eval-sp.sh`.** Use the template script with this app's names (Step 1).
* **Scorers fit the task:** a deterministic `sru_url_match` is the primary metric; the built-in
  `RelevanceToQuery` is replaced by a domain-aware guideline (it reads "Correction to: <title>" as a
  request to correct the article).
* **No `mlflow.tracing.set_destination(...)`.** The experiment stores traces in Unity Catalog; setting
  an experiment destination bypasses those tables, so assessments are not logged. A SQL warehouse ID
  is set instead, which UC trace reads require.

## Why a service principal is required

The app is OAuth-gated. An offline notebook eval cannot reach it with the notebook's identity: runtime
auth cannot mint an OAuth token, and personal access tokens are rejected. A **service principal using
OAuth M2M** with `CAN_USE` on the app is the identity that works. See the template README for the full
explanation and diagram.

## Step 1 — Provision the service principal (one time)

You must be a workspace admin. From a machine with the Databricks CLI and `jq`, at the repo root:

```bash
bash mcp-hackathon/eval/databricks/setup-eval-sp.sh \
  --app-name sru-syntax-mcp \
  --sp-name sp-sru-syntax-eval \
  --scope sru-syntax-eval-secrets
```

The script creates the SP, grants `workspace-access` and `CAN_USE` on the app, and stores `sp_id` and
`sp_secret` in the secret scope. Minting the OAuth secret is an **account-level** action; if the script
cannot do it, it prints the account console step, then re-run it with `--oauth-secret '<value>'`.

The workspace already has an `sp-mcp-eval` SP and `mcp-eval-secrets` scope, but you cannot read that scope,
so create a dedicated SP for this app.

## Step 2 — Run the eval in a notebook

Open a notebook in this folder (`sru-syntax-mcp/eval/databricks/`).

**Cell 1** (run alone, first):

```python
%pip install "openai-agents>=0.25" "databricks-openai>=0.17" "mlflow[databricks]>=3.14"
%restart_python
```

**Cell 2:** paste the contents of `agent_eval_offline.py` and run it. The `CONFIG` block already
points at this app; each value can also be set with an environment variable:

| Setting | Default | Env var |
|---|---|---|
| `MCP_SERVER_URL` | `https://sru-syntax-mcp-7474654188777746.aws.databricksapps.com/mcp` | `SRU_EVAL_MCP_URL` |
| `MODEL` | `models.ai.gpt-5-6-luna` | `SRU_EVAL_MODEL` |
| `EXPERIMENT_ID` | `131270370350843` (UC-backed SRU agent experiment) | `SRU_EVAL_EXPERIMENT_ID` |
| `SQL_WAREHOUSE_ID` | `50d2bd4ddf65e0f5` (Serverless Starter Warehouse) | `MLFLOW_TRACING_SQL_WAREHOUSE_ID` |
| `SECRET_SCOPE` | `sru-syntax-eval-secrets` | none |
| `AUTH_MODE` | `service_principal` | `SRU_EVAL_AUTH` |

A run takes about 7 minutes (41 rows, 3 at a time; the Supervisor Agent behind the tool takes about
20 seconds per title). Metrics print at the end; per-row results and traces are in the experiment's
**Evaluations** tab.

### Local dev copy of the server

To evaluate code changes before deploying, run `mcp_server/app.py` locally and point the eval at it with
`SRU_EVAL_MCP_URL=http://127.0.0.1:<port>/mcp` and `SRU_EVAL_AUTH=current_user`. The local server has no
Apps OAuth gate, so the current identity is enough.

## Scorers

| Scorer | Kind | Passes when |
|---|---|---|
| `sru_url_match` | Deterministic (primary) | The reply has an SRU URL on the production base whose decoded `alma.title` equals `expected_title`; or, when `expected_title` is blank, the reply has no SRU URL. |
| `correctness` | LLM judge | The reply contains the row's `expected_facts`. |
| `relevant_to_notice` | LLM guideline | The reply gives the SRU URL for the original article, or explains there is no single article. |
| `no_invented_urls` | LLM guideline | Only tool-produced URLs, no unrelated commentary, and errors are relayed rather than papered over. |
| `safety` | LLM judge | No harmful content. |

Results against a local copy of the server (2026-11-18), before and after the agent instructions were
changed to handle bare notices (two runs after):

| Metric | Before | After (run 1) | After (run 2) |
|---|---|---|---|
| `sru_url_match` | 1.00 | 1.00 | 1.00 |
| `correctness` | 0.91 | 1.00 | 1.00 |
| `relevant_to_notice` | 0.91 | 1.00 | 0.91 |
| `no_invented_urls` | 0.82 | 0.91 | 0.91 |
| `safety` | 1.00 | 1.00 | 1.00 |

* Before, the bare `Correction` row failed: the agent asked for the full title. It now replies that the
  notice names no article, without calling the tool.
* The remaining `no_invented_urls` failure is the issue-level row: the judge counts the agent's explanation
  of why there is no URL as "unrelated commentary". This is the guideline's wording, not an agent error.
* The Supervisor Agent's occasional empty replies would show up as `sru_url_match` failures (none occurred
  in these runs).

After the dataset grew to 41 rows, before and after the instructions were changed to answer issue-level
notices directly (one run each, 2026-11-18):

| Metric | Before | After |
|---|---|---|
| `sru_url_match` | 0.93 (38/41) | 0.93 (38/41) |
| `correctness` | 0.93 | 0.90 |
| `no_invented_urls` | 0.93 | 0.93 |
| `relevant_to_notice` | 0.83 | 0.85 |
| `safety` | 1.00 | 1.00 |

What the new rows exposed (before the change):

* **Empty Supervisor Agent replies (agent error):** 3 titles got no URL: "Overexpression of FBR41 ...",
  "Structure–Function Parameters ..." and "Homologous promoter derived ...". These are the only
  `sru_url_match` failures.
* **Issue-level notices without notice wording (agent error):** for `Taxon 61(6)` and
  `Errata to taxon 59(5)` the agent asked a clarifying question instead of saying the notice names no single
  article. No URL was given, so `sru_url_match` passes, but both LLM guidelines fail.
  **Fixed:** all 4 issue-level rows, and the 9 issue-level notices in the spreadsheet that are not in the
  dataset, now get "covers a journal issue or several articles, ... no SRU URL" with no question, in 2 to
  6 seconds (a tool call takes about 17). The prompt's examples are made up (e.g. `Taxon 72(3)`) so they do not leak dataset rows. The
  remaining LLM-judge failures on these rows (`correctness` and `relevant_to_notice` on
  `Errata to taxon 59(5)`, `no_invented_urls` on the two Data Papers rows) are judge strictness: the
  replies are correct.
* **Judge false negatives:** `relevant_to_notice` failed two correct URL answers for title-only notices
  ("AAFP and ISFM Guidelines ...", "p21-Activated Kinase 1 ..."), apparently because the request has no
  notice wording.

## Dataset

`datasets/sru-eval-0.csv` columns: `request` (the notice title, sent as-is), `expected_title` (the
`alma.title` term from `users.amanda_xu.build_sru_url`, blank when no URL is expected) and `source_rule`
(the extraction rule, logged as a tag). Every `request` is an `erratumn_article_title` from
`Correction-Sample2-1494-Extracted-Titles-FINAL.xlsx`. The first 11 rows are one per `extraction_rule`
(random_state=7); the next 30 add up to 3 more per rule (random_state=11) plus the known empty-reply titles.

To add rows, append to the CSV and fill `expected_title` from the UC function (blank result = no URL expected):

```sql
SELECT coalesce(regexp_extract(url_decode(users.amanda_xu.build_sru_url(:title)),
                'alma.title="(.*)" and alma.local_field_912', 1), '') AS expected_title
```

If the title rules change, regenerate every `expected_title` the same way.

## Online evaluation (production monitoring)

**Purpose:** continuously monitor live agent traces for tool-call efficiency and correctness as
the agent handles real correction titles in production. Two custom LLM judges score each trace
when started, catching regressions in tool usage and URL output quality without running a
separate eval script.

In addition to the offline evaluation above, two custom scorers are registered to the MLflow experiment
(`1096079759943475`) for **online (production) monitoring**. When started, they automatically score
new traces as they are logged to the experiment, without running a separate eval script.

| Scorer | Type | What it checks | Sample rate |
|---|---|---|---|
| `ToolCallEfficiency` | Custom (LLM judge) | Whether the agent used tools efficiently: no redundant calls, repeated parameters, or calls that should have been consolidated. Returns `yes` or `no`. | 0.0% (stopped) |
| `ToolCallCorrectness` | Custom (LLM judge) | Whether the tool call produced a correct SRU URL for the given correction title. | 0.0% (stopped) |

Both monitoring jobs are currently **turned off** (0% sample rate). To start them:

```python
import mlflow
from mlflow.genai.scorers import get_scorer, ScorerSamplingConfig

mlflow.set_experiment(experiment_id="1096079759943475")

efficiency = get_scorer(name="ToolCallEfficiency")
efficiency = efficiency.start(sampling_config=ScorerSamplingConfig(sample_rate=0.1))

correctness = get_scorer(name="ToolCallCorrectness")
correctness = correctness.start(sampling_config=ScorerSamplingConfig(sample_rate=0.1))
```

To stop them:

```python
efficiency.stop()
correctness.stop()
```

### Service principal and authentication for online evaluation

Online scorers are LLM judges that call the Unity Gateway model service (e.g.
`models.ai.gpt-5-6-luna`) to evaluate each trace. The model service requires `EXECUTE`
permission plus `USE CATALOG` and `USE SCHEMA` on its parent catalog and schema.

**Questions for the workspace admin:**

1. What identity do scheduled scorers run as? (Experiment owner, system service principal,
   or a dedicated service principal?)
2. Does that identity have `EXECUTE` on the model service the LLM judges call?
3. Does that identity have `USE CATALOG` and `USE SCHEMA` on the model service's catalog and schema?
4. Are there workspace-level settings required to allow scheduled scorers to call Unity Gateway
   model services?
5. Can the admin test by starting one scorer at a low sample rate (e.g. 0.1) and confirming new
   traces get scored?

### Online vs offline evaluation

| Aspect | Offline evaluation | Online evaluation (production monitoring) |
|---|---|---|
| How it runs | `mlflow.genai.evaluate()` in a notebook with a `predict_fn` that calls the agent | Scheduled scorers automatically score traces as they are logged to the experiment |
| Scorers | `sru_url_match`, `correctness`, `relevant_to_notice`, `no_invented_urls`, `safety` (5 scorers) | `ToolCallEfficiency`, `ToolCallCorrectness` (2 custom scorers) |
| Dataset | 41 labelled notices in `datasets/sru-eval-0.csv` | No dataset -- scores live traces from production traffic |
| Authentication | Service principal with OAuth M2M and `CAN_USE` on the app | Depends on the scorer's identity (see admin questions above) |
| When it runs | On demand (run the notebook) | Continuously when scorers are started (sample rate > 0) |
| Cost | ~7 minutes per run, 41 traces, 5 scorers | Per-trace LLM judge calls at the configured sample rate |

## Testing the deployed MCP server (Inspector Gadget)

`inspector_gadget_mcp_test.py` checks that an external client can reach the OAuth-gated app and call its
tools. Import it as a notebook and run the cells in order. It:

1. Loads the Inspector Gadget service principal's `client_id`, `client_secret` and `scopes` from the
   Unity Catalog secret `models.ai/inspector-gadget` (no credentials are stored in the file).
2. Builds a `WorkspaceClient` against the **workspace** URL (not the app URL; OAuth M2M needs the
   workspace to issue its token) and lists the app's tools with `DatabricksMCPClient`.
3. Calls `build_sru_search_url` on a sample title. The call opens the MCP session with an
   `httpx2.AsyncClient` and a 300 s timeout, because `DatabricksMCPClient.call_tool` uses the 5 s httpx
   default and the tool takes 15 to 90 s.
4. Calls every tool on the app (sample arguments in `sample_args`, placeholders for tools without an
   entry) and prints PASS, FAIL (tool returned an error) or ERROR (call failed) with timings.

Required permissions:

| Principal | Needs |
|---|---|
| Inspector Gadget service principal | `CAN USE` on the `sru-syntax-mcp` app |
| The app's own service principal | `CAN QUERY` on `mas-c8629507-endpoint`, `EXECUTE` on `users.amanda_xu.build_sru_url`, `USE SCHEMA` on `users.amanda_xu` |

| Symptom | Cause |
|---|---|
| `oauth-m2m: Invalid URL 'None'` | `WorkspaceClient` host is the app URL; use the workspace URL. |
| `ExceptionGroup` / `UnsupportedProtocol`, app logs show 401 | The service principal lacks `CAN USE` on the app. |
| Tool error `bad_response` | The app's service principal cannot run the UC function the Supervisor Agent calls. |
| `ReadTimeout` | The default 5 s client timeout; use `call_tool_with_timeout`. |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Service-principal credentials are missing` | The secret scope or keys are missing. Re-run Step 1, or check `SECRET_SCOPE` / `SECRET_KEY_*`. |
| Agent replies without a URL and logs a failed MCP connection, or tool calls return 401/403 | The SP is not reaching the app. Confirm it has `CAN_USE` on `sru-syntax-mcp` and `workspace-access`. |
| `INVALID_PARAMETER_VALUE: sql_warehouse_id is required` | Reading UC-stored traces needs `MLFLOW_TRACING_SQL_WAREHOUSE_ID` set to a warehouse you can use. |
| `no trace tagged with mlflow.eval.requestId was found` and missing assessments | Something set a trace destination other than the UC-backed experiment. Remove `set_destination` calls. |
| A tool error such as `(error unavailable, id ...)` in replies | The server's Supervisor Agent call failed. Search `databricks apps logs sru-syntax-mcp` for the id. |
| `bound to a different event loop` / `Event loop is closed` | Async plumbing. Do not add `nest_asyncio`; the script runs one persistent loop. |
