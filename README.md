# NAL Metadata Support: automating PubAg correction processing

Databricks MCP Hackathon project from the USDA National Agricultural Library (NAL).

Publishers issue correction notices (errata, corrigenda, addenda) for articles indexed in PubAg. Each notice
has its own catalog record, and staff must find the **original article** it corrects. Today that means
reading the notice title, working out the original article title by hand, and searching NAL's Alma catalog.

This project is the initial stage of automating that workflow:

1. **Part 1, spreadsheet processing:** extract the original article title from each correction notice title
   and build an Alma SRU search URL for it.
2. **Part 2, agents, MCP and governance on Databricks:** make the same logic available to people and AI
   agents as a governed Unity Catalog function, a Supervisor Agent and an MCP server, with tracing and
   evaluation.

```
Correction notice title
  "Correction to: Effects of a Mixture of Humulus japonicus ... by Kim et al. J Med Food 2021;24(5):497-504"
        |
        v  title extraction rules (Part 1)
Original article title
  "Effects of a Mixture of Humulus japonicus on Longitudinal Bone Growth in Hypophysectomized Rats"
        |
        v  SRU URL builder
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve
  &recordSchema=mods&query=alma.title%3D%22Effects%20of%20a%20Mixture...%22%20and%20alma.local_field_912%3D%22Article%22
```

## Repository layout

| Folder | What it is |
| --- | --- |
| [`src/sru_server/`](src/sru_server/) | Part 2: the MCP server and agent code, adapted to the GSA MCP hackathon template structure (`app.py`, `agent.py`, `tools/build_sru_url.py`, `config.py`). |
| [`title-extraction/`](title-extraction/README.md) | Part 1: `erratum_title_extractor.py`, the spreadsheet processing script. |
| [`deploy/databricks/`](deploy/databricks/README.md) | Deployment runbook: how to deploy the MCP server as a Databricks App using a Declarative Automation Bundle. |
| [`eval/databricks/`](eval/databricks/README.md) | Offline evaluation: MLflow GenAI evaluation over labelled notices with the `ToolCallEfficiency` scorer. |
| [`tests/`](tests/) | Smoke tests and SSRF hardening regression tests for the MCP server. |
| [`.agents/skills/agent-sru-syntax/`](.agents/skills/agent-sru-syntax/SKILL.md) | Coding-agent skill: instructions and SRU URL rules for agents working on this project. |
| [`databricks.yml`](databricks.yml) | Declarative Automation Bundle: defines the app, its resources, and variables. |
| [`setup/`](setup/create_uc_backed_experiment.py) | One-time setup: create a Unity Catalog-backed MLflow experiment for trace storage. |
| [`mcp_server/`](mcp_server/) | App runtime config (`app.yaml`, `requirements.txt`) used by the bundle deploy. |

## Part 1: Spreadsheet processing

**Input:** an Alma export of correction notice records. The main sample,
`Correction-Sample2-1494-20261021.xlsx`, has 1,494 records with `Title` and `MMS ID` columns.

**Code:** [`title-extraction/erratum_title_extractor.py`](title-extraction/README.md)
(`python erratum_title_extractor.py INPUT.xlsx`; needs `pandas` and `openpyxl`).

**Output:** the same records with these columns, as a downloadable Excel workbook:

| Column | Name | Contents |
| --- | --- | --- |
| A | `erratumn_article_title` | Correction notice title, as exported |
| B | `extracted_title` | Original article title after the extraction rules |
| C | `erratum_MMSID` | MMS ID of the correction notice record |
| D | `extracted_title_clean` | Extracted title after normalisation (dashes, quotes, spaces) |
| E | `SRU_Query_Syntax` | CQL query: `alma.title="<title>" and alma.local_field_912="Article"` |
| F | `SRU_Full_URL` | Full SRU searchRetrieve URL |
| G | `extraction_rule` | QA column: which rule produced the title |

The column name `erratumn_article_title` is kept as-is for compatibility with existing files.

### Title extraction rules

The rules were built up iteratively on real notices:

1. Remove notice prefixes such as `Correction:`, `Correction to:` and `Publisher Correction:`.
2. Parse the embedded article title out of bibliographic `Corrigendum:` and `Corrigenda:` notices of the form
   `Corrigendum: Author1, Author2, ... (2026) Original article title. Journal Title 123: 45-67. https://doi.org/...`.
   Remove the prefix, author list, year, journal title, volume/issue/page information and DOI, and keep only
   the original article title.
3. Handle the other notice patterns found in the data: quoted titles, cited authors
   (`Correction for Kuo and Chang, <title>`), quoted full citations, trailing citations
   (`... by Lee et al. Journal 2024;27(6):488-501; doi: ...`), notice suffixes (`<title>/Correction`), and
   titles with no notice wording.
4. Leave the title blank, so no URL is built, when the notice names no single article: bare notices
   (`Correction`, `ERRATA`) and issue-level notices (`Taxon 61(6)`, `Correction for Data Papers Published in 2020`).
5. Guard against false positives: a real title such as `Correction of hypocalcemia in dairy cows` is kept.

The full rule table, with an example and rule name for each case, is in
[`.agents/skills/agent-sru-syntax/references/sru_url_rules.md`](.agents/skills/agent-sru-syntax/references/sru_url_rules.md).

### SRU URL format

```
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods
  &query=alma.title%3D%22<title>%22%20and%20alma.local_field_912%3D%22Article%22
```

* Production Alma (`nal.alma...`). The sandbox (`nal-psb.alma...`) does not hold the production records.
* The whole query is percent-encoded (spaces as `%20`, not `+`); there is no `maximumRecords` parameter.
* `"` and `\` inside a title are replaced with spaces so they cannot end the CQL quoted term.

### Results on the 1,494-record sample

* 1,384 records get an SRU URL; 110 are bare or issue-level notices with no single article, so no URL is built.
* The Unity Catalog function (below) reproduces the extractor's output for all 1,494 records.
* A URL that returns a valid SRU response with 0 records means the article was not found in Alma, not a
  syntax problem.

## Part 2: Agents, MCP and governance on Databricks

### Components

| Component | What it does |
| --- | --- |
| Unity Catalog function `users.amanda_xu.build_sru_url(correction_title)` | Python UDF with the Part 1 rules. Deterministic; the source of truth for SRU URLs. Use it for bulk processing in SQL. |
| Supervisor Agent `agent-sru-syntax` (endpoint `mas-c8629507-endpoint`) | Agent Bricks agent that calls the function as a tool. |
| Databricks App `mcp-sru-syntax` | Custom MCP server with one read-only tool, `build_sru_search_url`, that calls the Supervisor Agent. The same app serves an OpenAI Agents SDK agent at `/invocations` that uses the tool. See [`deploy/databricks/README.md`](deploy/databricks/README.md). |
| Agent skill `agent-sru-syntax` | Instructions and rules for coding agents working on this project ([`SKILL.md`](.agents/skills/agent-sru-syntax/SKILL.md)). |
| Offline evaluation | MLflow GenAI evaluation over labelled notices ([`eval/databricks/`](eval/databricks/README.md)). |

For bulk work, call the function from SQL. The agent takes about 20 seconds per title, so it suits
interactive use rather than thousands of rows.

### The MCP server (`src/sru_server/`)

The server is built on MCP 1.x (`mcp.server.fastmcp`) and serves stateless streamable-HTTP. The workspace
is at its 100-app limit, so the MCP server and the agent share the `mcp-sru-syntax` app:

| Endpoint | Code | What it does |
| --- | --- | --- |
| `/mcp` | `src/sru_server/app.py` | MCP server (streamable HTTP) with one tool, `build_sru_search_url`, that calls the agent-sru-syntax Supervisor Agent endpoint `mas-c8629507-endpoint` |
| `POST /invocations`, `POST /responses` | `src/sru_server/agent.py` | OpenAI Agents SDK agent that uses the `/mcp` tool over localhost |
| `GET /health` | `src/sru_server/app.py` | Liveness check |

The tool implementation is in [`src/sru_server/tools/build_sru_url.py`](src/sru_server/tools/build_sru_url.py).
It sends the correction title to the Supervisor Agent, returns the SRU URL, and handles errors with stable
categories (`timeout`, `unavailable`, `rate_limited`, `permission_denied`, `bad_response`) and an error ID
instead of leaking upstream response bodies.

### Two ways to reach the logic over MCP

**1. Databricks-managed MCP server for Unity Catalog functions (no hosting).** Databricks exposes Unity
Catalog functions as MCP tools at:

* `https://<workspace-host>/api/2.0/mcp/functions/{catalog}/{schema}`: every function in the schema
* `https://<workspace-host>/api/2.0/mcp/functions/{catalog}/{schema}/{function_name}`: one function

A workspace admin must enable Managed MCP Servers on the workspace Previews page. Clients request the
`unity-catalog` OAuth scope.

**2. Custom MCP server on Databricks Apps (`mcp-sru-syntax`).** Managed MCP has no endpoint for
Supervisor Agents, so the app wraps the agent in an MCP tool:
`https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/mcp`. Databricks Apps require an OAuth token;
personal access tokens are rejected. See [`deploy/databricks/README.md`](deploy/databricks/README.md) for
full deployment instructions.

### Deploy

Run from the repo root (the bundle root):

```bash
databricks bundle validate --strict -t dev

# One time: the mcp-sru-syntax app already exists, so let the bundle manage it
databricks bundle deployment bind sru_syntax_mcp mcp-sru-syntax -t dev

databricks bundle deploy -t dev
databricks bundle run sru_syntax_mcp -t dev
```

Override any variable with `--var`, for example `--var model_service=models.ai.gpt-5-6-sol`.

### Test the agent

```bash
curl -X POST "https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/invocations" \\
  -H "Authorization: Bearer <OAUTH_TOKEN>" -H "Content-Type: application/json" \\
  -d '{"input": [{"role": "user", "content": "Correction: <article title>"}]}'
```

Apps require an OAuth token (`databricks auth token`); personal access tokens are not accepted.
Each title can take 60-90 seconds because the Supervisor Agent does the lookup.

### App resources

The app gets these through `valueFrom` in [`mcp_server/app.yaml`](mcp_server/app.yaml):

* `serving-endpoint` -> `SERVING_ENDPOINT`: Supervisor Agent endpoint, `CAN_QUERY`
* `model-service` -> `MODEL_SERVICE`: Unity Gateway model service (default `models.ai.gpt-5-6-luna`), `EXECUTE`
* `app-experiment` -> `MLFLOW_EXPERIMENT_ID`: Unity Catalog-backed experiment, `CAN_EDIT`
* `trace-annotations`, `trace-logs`, `trace-metrics`, `trace-spans`: the four `users.amanda_xu.sru_syntax_agent_otel_*` tables, `MODIFY` (includes `SELECT`)

### Governance

* **Unity Catalog permissions.** Callers need `USE CATALOG`, `USE SCHEMA` and `EXECUTE` on the function. The
  app's service principal gets only the resources declared in the bundle: `CAN_QUERY` on the Supervisor Agent
  endpoint, `EXECUTE` on the model service, `CAN_EDIT` on the experiment and `MODIFY` on the trace tables.
* **Deployment as code.** The app, its resources and permissions are defined in a Declarative Automation
  Bundle ([`databricks.yml`](databricks.yml)).
* **Tracing in Unity Catalog.** MLflow traces every agent, model and tool call into
  `users.amanda_xu.sru_syntax_agent_otel_*` tables, so traces are governed and queryable like any other table.
* **Safe tool behaviour.** The MCP tool is annotated read-only and idempotent, and returns stable error
  categories with an error ID instead of upstream error bodies. The outbound HTTP call uses
  `allow_redirects=False` to prevent SSRF via redirects.
* **Evaluation.** Offline MLflow GenAI evaluation checks URLs and agent behaviour over 41 labelled
  notices (5 scorers: `sru_url_match`, `correctness`, `relevant_to_notice`, `no_invented_urls`, `safety`).
  Online monitoring uses two registered custom scorers (`ToolCallEfficiency`, `ToolCallCorrectness`)
  that score live traces automatically when started. Both are currently stopped (0% sample rate).
  See [`eval/databricks/`](eval/databricks/README.md) and the
  [`eval/databricks/doc/`](eval/databricks/doc/) evaluation document.

### Tracing

`mlflow.openai.autolog()` traces every model and MCP tool call automatically. `run_agent` adds an
`AGENT` span plus a `preprocessing` child span.

Traces are stored in Unity Catalog under `users.amanda_xu`:

* `sru_syntax_agent_otel_spans`, `_otel_logs`, `_otel_metrics`, `_otel_annotations` (tables)
* `sru_syntax_agent_trace_unified`, `sru_syntax_agent_trace_metadata` (views)

[`setup/create_uc_backed_experiment.py`](setup/create_uc_backed_experiment.py) created the experiment and
tables (already run once). To use a different location, run it with new names and set
`trace_experiment_id` / `trace_table_prefix` in [`databricks.yml`](databricks.yml).

## Tests

* [`tests/test_server.py`](tests/test_server.py) -- smoke tests: server import, name, default transport, tool registration, `build_sru_search_url` discoverability.
* [`tests/test_http_security.py`](tests/test_http_security.py) -- SSRF hardening: `allow_redirects=False`, fixed endpoint URL (not user-controlled), user input in JSON body (not URL), error sanitization, stable error categories.

## Status and next steps

* Done: extraction rules, Unity Catalog function, Supervisor Agent, MCP server app, Unity Catalog tracing,
  offline evaluation.
* Known issue: the Supervisor Agent sometimes returns an empty reply for a title (3 of 41 eval rows). Use the
  function directly for those titles.
* Next: run the SRU searches against Alma to retrieve the original article's MMS ID and link it to the
  correction record; provision the evaluation service principal so the eval can run against the deployed app.

## Acknowledgements

This project is built on the [GSA MCP Hackathon template](https://github.com/GSA-TTS/mcp-hackathon-template),
adapted for the NAL SRU Syntax MCP server. The template's `src/`, `tests/`, `deploy/`, and `eval/` structure
is preserved; the example server code is replaced with the mcp-sru-syntax server, agent, and tools.
