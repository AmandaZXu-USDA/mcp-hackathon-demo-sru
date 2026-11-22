# Databricks offline MLflow evaluation: mcp-sru-syntax

**Purpose:** verify that the SRU syntax agent produces correct NAL Alma production SRU URLs from
erratum/correction notice titles. A labelled dataset of 41 notices is scored by a deterministic
URL match plus four LLM judges (correctness, relevance, no invented URLs, safety), catching
rule regressions, empty Supervisor Agent replies, and instruction-following failures before
deploying changes.

Evaluates the SRU syntax agent while it uses the **deployed** `mcp-sru-syntax` MCP server
(a Databricks App), scored by MLflow GenAI judges plus a deterministic URL check. Adapted from
the template kit in [`mcp-hackathon/eval/databricks/`](../../../mcp-hackathon/eval/databricks/README.md).

Each dataset row is an erratum/correction notice title. The agent should return the NAL Alma
production SRU URL for the original article, or no URL when the notice names no single article.

## What's in this kit

| File | What it is |
|------|------------|
| `agent_eval_offline.py` | The eval script. Runs `mlflow.genai.evaluate` over the dataset with a `predict_fn` that calls the agent. |
| `agent_eval_deployed.py` | Same dataset and scorers, but `predict_fn` calls the **deployed** app's agent (`POST /invocations`) as Inspector Gadget, so it scores what users get (the app's model and the function-first tool). Needs no agent copy and no model access. |
| `eval_auth.py` | Auth shim. Patches the agent's `ws` client and `mcp_url()` at runtime so it reaches the OAuth-gated app as a service principal. `agent/agent_server/agent.py` stays unmodified. |
| `inspector_gadget_mcp_test.py` | Notebook source. Calls the deployed app as the Inspector Gadget service principal: lists tools, calls `build_sru_search_url`, tests every tool, tests the browser page and `/api/sru-url`, and runs the 142-title MCP test. See [Testing the deployed MCP server](#testing-the-deployed-mcp-server-inspector-gadget). |
| `build_evaluation_report.py` | Notebook source. Builds the evaluation report PDF ([`doc/sru-syntax-mcp-evaluation-report.pdf`](doc/sru-syntax-mcp-evaluation-report.pdf), 16 pages: lessons learned and recommendations in section 7, the November 21, 2026 re-run in section 8, the November 22, 2026 Phoenix evaluation in section 9) with `reportlab` and checks its text with `pypdf`. |
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
  --app-name mcp-sru-syntax \
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
| `MCP_SERVER_URL` | `https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/mcp` | `SRU_EVAL_MCP_URL` |
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

### Deployed app agent on `databricks-gpt-5-6-luna`, function-first tool (2026-11-21)

`agent_eval_deployed.py`, 41 rows, 3 at a time, 212 s in total (MLflow run `3bd980fb57ec4b769ba66036c91091ee` in experiment
`131270370350843`). The app's agent had moved from `models.ai.gpt-5-6-luna`, whose OpenAI key expired, to the
Databricks-hosted `databricks-gpt-5-6-luna`; the tool now runs the SQL function first.

| Metric | 2026-11-18 (Supervisor Agent tool, `models.ai`) | 2026-11-21 (function first, `databricks-gpt-5-6-luna`) |
|---|---|---|
| `sru_url_match` | 0.93 (38/41) | **1.00 (41/41)** |
| `correctness` | 0.90 | 1.00 |
| `relevant_to_notice` | 0.85 | 0.90 |
| `no_invented_urls` | 0.93 | 0.90 |
| `safety` | 1.00 | 1.00 |

Per title: median 6.9 s, p90 7.3 s, max 7.5 s; bare and issue-level notices about 1 s.

* **All 41 replies are right.** The 3 titles that got empty Supervisor Agent replies on 2026-11-18 now get the
  correct URL, because the tool no longer goes through the Supervisor Agent.
* **The 7 judge failures are judge strictness, not agent errors** (each reply checked by hand):
  `relevant_to_notice` failed the issue-level rows `Errata to taxon 59(5)` and `Taxon 61(6)`, and two correct
  URL answers for title-only notices ("AAFP and ISFM Guidelines ...", "Monographic Revision of the American
  Genus Euphoria ..."), as before. `no_invented_urls` failed the two Data Papers rows (explanation counted as
  commentary, as before) and two correct URL answers, because this script sees only the HTTP reply: the judge
  cannot see the tool call, so it cannot confirm the URL came from the tool.

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
5. Tests the browser page: `GET /` without a token goes to the login page, `GET /` serves the page
   with a per-request CSP nonce, a plain form post to `/api/sru-url` is refused (415), and
   `POST /api/sru-url` returns one SRU URL.
6. **142-title MCP test** (last 3 cells): reads the Sample3 workbook from
   `/Volumes/users/amanda_xu/erratum_files/`, gets each expected URL from `users.amanda_xu.build_sru_url`,
   calls `build_sru_search_url` for every title (10 at a time, about 8 minutes), classifies each reply
   (`EXACT`, `EMPTY_AGENT_REPLY`, `BARE_NOTICE_NO_URL`, `CORRECT_URL_EXTRA_TEXT`, `WRONG_URL`, `ERROR`) and
   appends the results with a `run_id` to `users.amanda_xu.sample3_mcp_offline_test`.

Required permissions:

| Principal | Needs |
|---|---|
| Inspector Gadget service principal | `CAN USE` on the `mcp-sru-syntax` app |
| The app's own service principal | `CAN QUERY` on `mas-c8629507-endpoint`, `EXECUTE` on `users.amanda_xu.build_sru_url`, `USE SCHEMA` on `users.amanda_xu` |

| Symptom | Cause |
|---|---|
| `oauth-m2m: Invalid URL 'None'` | `WorkspaceClient` host is the app URL; use the workspace URL. |
| `ExceptionGroup` / `UnsupportedProtocol`, app logs show 401 | The service principal lacks `CAN USE` on the app. |
| Tool error `bad_response` | The app's service principal cannot run the UC function the Supervisor Agent calls. |
| `ReadTimeout` | The default 5 s client timeout; use `call_tool_with_timeout`. |

### Results on November 21, 2026 (function-first tool)

142-title MCP test, run `20261121T041852` in `users.amanda_xu.sample3_mcp_offline_test`, 10 at a time, as
Inspector Gadget: **142/142 correct** (138 `EXACT`, 4 `BARE_NOTICE_NO_URL`), 0 empty replies, 0 errors, all 142
answered by the rules function. Total 79 s for 142 titles, about 108 titles per minute (run time is now
recorded); per title median 5.2 s, max 9.2 s. On November 20 (run `20261120T025204`, agent path) the same test
had 126 `EXACT`, 7 `EMPTY_AGENT_REPLY` and 5 `CORRECT_URL_EXTRA_TEXT`; all 12 are `EXACT` now. A separate SQL
check found the URL in every reply equal to `users.amanda_xu.build_sru_url` recomputed for the title.

The classifier now compares the SRU URL in the reply (function-first replies label the URL) and records
`answered_by` (`function` or `agent`, from the reply's fixed wording), `run_seconds` and `concurrency`.

### Results on November 19, 2026

After the browser page and the empty-reply retry were deployed (section 6 of the evaluation report).

**Routes, as Inspector Gadget:** `GET /` without a token 302 to login; `GET /health` 200; `GET /` 200 with
a CSP nonce; `POST /api/sru-url` 200 with the correct URL (55 s first call, then 16 s and 20 s); form post 415;
MCP `tools/list` and `tools/call` 200 (14 s); `/invocations` 200 (21 s). The new page-test cell: 4/4 PASS.

**Titles per minute:**

| How titles were sent | Titles | At a time | Per-title time | Titles per minute |
|---|---|---|---|---|
| MCP tool (142-title test) | 142 | 10 | median 27.0 s, p90 58.2 s, max 70.4 s | about 18 at most (run took at least 7.8 min) |
| Supervisor Agent endpoint directly | 41 | 4 | median 15 s, p90 52 s, max 55 s | 10.6 (231 s) |
| MCP tool or page, one at a time | - | 1 | 14-21 s; 46-55 s for the first call after idle | about 3-4 |
| Rules function via the SQL Statement API | 41 | 1 | 3.3-3.6 s; 36 s for the first call | about 17 |

The 142-title run's total time was not recorded; its per-title times add up to 4,706 s across 10 parallel
calls, so about 18 a minute is an upper bound.

**Agent vs rules function:**

| Dataset | Agent | Rules function |
|---|---|---|
| 41 eval titles, agent called directly | Same URL on 30/33 article titles; 3 empty replies; 0 different URLs; no URL for 8/8 bare or issue-level notices | 41/41 |
| 142 Sample3 titles via the MCP tool | 130 exact; 7 empty replies; 4 bare notices with no URL; 1 correct URL with extra text; 0 wrong URLs | 142/142 |

The expected values come from the rules function, so its 100% shows only that it has not changed; the
useful result is that every URL the agent returned was the function's. The function was timed through the
SQL Statement API, not through MCP (the MCP tool always calls the agent). The agent-only path is kept for the
demo.

**Empty-reply retry:** the MCP tool and the page now ask the agent once more when its reply is empty; errors
are not retried. It recovered **0 of 10** titles that got empty replies: the 3 from the 41-row dataset were
empty on 9/9 extra calls before deploying and again after, and the 7 from the 142-title run were all still
empty through the deployed tool (7 retries in the app logs, all empty). Each empty reply now takes about
2-3 s longer. For these titles, use the rules function.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Service-principal credentials are missing` | The secret scope or keys are missing. Re-run Step 1, or check `SECRET_SCOPE` / `SECRET_KEY_*`. |
| Agent replies without a URL and logs a failed MCP connection, or tool calls return 401/403 | The SP is not reaching the app. Confirm it has `CAN_USE` on `mcp-sru-syntax` and `workspace-access`. |
| `INVALID_PARAMETER_VALUE: sql_warehouse_id is required` | Reading UC-stored traces needs `MLFLOW_TRACING_SQL_WAREHOUSE_ID` set to a warehouse you can use. |
| `no trace tagged with mlflow.eval.requestId was found` and missing assessments | Something set a trace destination other than the UC-backed experiment. Remove `set_destination` calls. |
| A tool error such as `(error unavailable, id ...)` in replies | The server's Supervisor Agent call failed. Search `databricks apps logs mcp-sru-syntax` for the id. |
| `bound to a different event loop` / `Event loop is closed` | Async plumbing. Do not add `nest_asyncio`; the script runs one persistent loop. |
