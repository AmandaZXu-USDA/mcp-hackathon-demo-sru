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
3. **Part 3, erratum annotation:** from the SRU response, find the original article's record and append an
   erratum note to its title, with a second MCP server and agent ([`erratum-annotator/`](erratum-annotator/README.md)).

## At a glance: two MCP apps, two agents

| | Project 1: SRU syntax (Parts 1 and 2) | Project 2: Erratum annotator (Part 3) |
| --- | --- | --- |
| What it does | Correction notice title -> NAL Alma SRU search URL | SRU response (MODS XML) -> original title with `[Erratum: ...]` note |
| MCP server (Databricks App) | `mcp-sru-syntax`: 1 tool, `build_sru_search_url` | `mcp-erratum-note`: 7 tools, e.g. `list_sru_files`, `process_sru_file` |
| Agent | Supervisor Agent `agent-sru-syntax` (`mas-c8629507-endpoint`); the app also serves an OpenAI Agents SDK agent at `/invocations` | Supervisor Agent `agent-erratum-annotator` (`mas-c341c0aa-endpoint`), [configuration](erratum-annotator/agent/README.md) |
| Deterministic rules | UC function `users.amanda_xu.build_sru_url` | UC function `users.amanda_xu.process_sru_response` |
| Code | Repo root: [`src/sru_server/`](src/sru_server/), [`databricks.yml`](databricks.yml) | [`erratum-annotator/`](erratum-annotator/README.md) |
| Evaluation | [`eval/databricks/`](eval/databricks/README.md), [report PDF](submission/sru-syntax-mcp-evaluation-report.pdf) | [`erratum-annotator/eval/databricks/`](erratum-annotator/eval/databricks/README.md), [report PDF](erratum-annotator/eval/databricks/doc/agent-erratum-annotator-evaluation-report.pdf) |
| Headline result | 135/142 correct replies via MCP, 0 wrong URLs | Agent: 50/53 exact annotated titles; MCP server alone: 0 errors, 48/48 original MMS IDs |
| Deploy | Declarative Automation Bundle `sru_syntax` | `databricks apps deploy` from `erratum-annotator/mcp_server` |

See [Deploying the two apps safely](#deploying-the-two-apps-safely) and [`submission/`](submission/README.md).

```
Correction notice title
  "Correction to: Effects of a Mixture of Humulus japonicus ... by Kim et al. J Med Food 2021;24(5):497-504"
        |
        v  title extraction rules (Part 1)
Original article title
  "Effects of a Mixture of Humulus japonicus on Longitudinal Bone Growth in Hypophysectomized Rats"
        |
        v  SRU URL builder (Part 2, mcp-sru-syntax)
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve
  &recordSchema=mods&query=alma.title%3D%22Effects%20of%20a%20Mixture...%22%20and%20alma.local_field_912%3D%22Article%22
        |
        v  run the SRU search in Alma; save the response (MODS XML) to the volume, or paste it
SRU searchRetrieveResponse (MODS XML)
  correction notice record + original article record
        |
        v  erratum annotation (Part 3, mcp-erratum-note)
        |    list_sru_files / process_sru_file   saved file    (or process_sru_response for pasted XML)
        |    1. parse_sru_response    records: title, MMS ID, <part><text>, DOI, is_correction
        |    2. match                 correction record (erratum MMS ID) -> original article
        |                             (cited DOI first, then title similarity; else needs_review)
        |    3. extract_erratum_note  "[Erratum: Mon. YYYY, v. V, no. N, page, DOI]"
        |    4. enhance_title         append the note; titles that already have "[Erratum:" stay unchanged
        v
Annotated original title + original MMS ID
  "Effects of a Mixture of Humulus japonicus on Longitudinal Bone Growth in Hypophysectomized Rats
   [Erratum: Mon. YYYY, v. V, no. N, page, DOI]"
  plus status, warnings and needs_review flags for the librarian
```

## Repository layout

| Folder | What it is |
| --- | --- |
| [`src/sru_server/`](src/sru_server/) | Part 2: the MCP server and agent code, adapted to the GSA MCP hackathon template structure (`app.py`, `agent.py`, `tools/build_sru_url.py`, `config.py`). |
| [`sru-syntax-mcp/`](sru-syntax-mcp/README.md) | Part 2, as deployed: byte-identical copy of the live `mcp-sru-syntax` source (`mcp_server/`) and the UC function `build_sru_url` (`uc_functions/`). Tools and functions are listed in [`deploy/databricks/README.md`](deploy/databricks/README.md#tools-and-functions). |
| [`title-extraction/`](title-extraction/README.md) | Part 1: `erratum_title_extractor.py`, the spreadsheet processing script. |
| [`deploy/databricks/`](deploy/databricks/README.md) | Deployment runbook: how to deploy the MCP server as a Databricks App using a Declarative Automation Bundle. |
| [`eval/databricks/`](eval/databricks/README.md) | Offline evaluation: MLflow GenAI evaluation over labelled notices with the `ToolCallEfficiency` scorer. |
| [`tests/`](tests/) | Smoke tests and SSRF hardening regression tests for the MCP server. |
| [`.agents/skills/agent-sru-syntax/`](.agents/skills/agent-sru-syntax/SKILL.md) | Coding-agent skill: instructions and SRU URL rules for agents working on this project. |
| [`databricks.yml`](databricks.yml) | Declarative Automation Bundle: defines the app, its resources, and variables. |
| [`setup/`](setup/create_uc_backed_experiment.py) | One-time setup: create a Unity Catalog-backed MLflow experiment for trace storage. |
| [`mcp_server/`](mcp_server/) | App runtime config (`app.yaml`, `requirements.txt`) used by the bundle deploy. |
| [`erratum-annotator/`](erratum-annotator/README.md) | Part 3, self-contained: MCP server `mcp-erratum-note` (`mcp_server/`), agent `agent-erratum-annotator` configuration (`agent/`), UC function definitions (`uc_functions/`), evaluation, Inspector Gadget test and report (`eval/databricks/`). |
| [`submission/`](submission/README.md) | Hackathon deck, both evaluation reports and the librarian quick-start. |

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
| Databricks App `mcp-sru-syntax` | Custom MCP server with one read-only tool, `build_sru_search_url`, that runs the function on a SQL warehouse first (about 4 s) and asks the Supervisor Agent only if that call fails. The same app serves an OpenAI Agents SDK agent at `/invocations` that uses the tool. See [`deploy/databricks/README.md`](deploy/databricks/README.md). |
| Agent skill `agent-sru-syntax` | Instructions and rules for coding agents working on this project ([`SKILL.md`](.agents/skills/agent-sru-syntax/SKILL.md)). |
| Offline evaluation | MLflow GenAI evaluation over labelled notices ([`eval/databricks/`](eval/databricks/README.md)). |

For bulk work, call the function from SQL. The MCP tool and the browser page answer in about 4 seconds
per title (live test 2026-11-21: 3.9-4.7 s), because they run the function first; the Supervisor Agent
(about 20 seconds per title) is only the fallback. Either way they suit interactive use rather than
thousands of rows.

### The MCP server (`src/sru_server/`)

The server is built on MCP 1.x (`mcp.server.fastmcp`) and serves stateless streamable-HTTP. The workspace
is at its 100-app limit, so the MCP server and the agent share the `mcp-sru-syntax` app:

| Endpoint | Code | What it does |
| --- | --- | --- |
| `/mcp` | `src/sru_server/app.py` | MCP server (streamable HTTP) with one tool, `build_sru_search_url`: runs `users.amanda_xu.build_sru_url` on a SQL warehouse first (about 4 s) and falls back to the agent-sru-syntax Supervisor Agent endpoint `mas-c8629507-endpoint` |
| `POST /invocations`, `POST /responses` | `src/sru_server/agent.py` | OpenAI Agents SDK agent that uses the `/mcp` tool over localhost |
| `GET /health` | `src/sru_server/app.py` | Liveness check |

The tool implementation is in [`src/sru_server/tools/build_sru_url.py`](src/sru_server/tools/build_sru_url.py).
It runs the governed function `users.amanda_xu.build_sru_url` on the SQL warehouse in `SQL_WAREHOUSE_ID`
first (title as a bound parameter; about 4 s). If the function finds no single original article, the tool
says so at once. Only if the function call fails does it send the title to the Supervisor Agent. It returns
the SRU URL and handles agent errors with stable
categories (`invalid_input`, `timeout`, `unavailable`, `rate_limited`, `permission_denied`, `not_found`,
`bad_request`, `bad_response`, `empty_reply`, `internal`) and an error ID instead of leaking upstream response
bodies. Each message says what to do next. An empty reply, a busy agent (429) or a temporary outage
(502/503, connection error) is retried once, after the agent's Retry-After or 2 s (at most 10 s); timeouts and
permission or configuration errors are not retried. If the reply is still empty after the retry, the tool
returns the `empty_reply` error, which points to the SQL function for that title.

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

# Only if this bundle does not track the app yet (e.g. a different user or a fresh bundle state):
# the mcp-sru-syntax app already exists, so bind it instead of creating it
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
The tool itself answers in about 4 seconds (SQL function first); with the agent's own model calls a title
takes about 7-10 seconds (live test 2026-11-21: 6.6-10.1 s), and a bare or issue-level notice about 1 second.
The agent uses the Databricks-hosted model endpoint `databricks-gpt-5-6-luna` (`AGENT_MODEL` in `app.yaml`).

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

## Part 3: Erratum annotation

Once the SRU search returns the original article and its correction notice, [`erratum-annotator/`](erratum-annotator/README.md)
picks the original record (cited DOI first, then title similarity), builds the erratum note from the correction
record and appends it to the original title, for example
`<original title> [Erratum: Aug. 2026, v. 52, no. 4, 134, 10.1007/s10695-026-01767-0]`. Titles that already carry
a note are returned unchanged; uncertain matches are flagged `needs_review`.

* **MCP server `mcp-erratum-note`** ([`erratum-annotator/mcp_server/`](erratum-annotator/mcp_server/)): 7 read-only
  tools; `process_sru_file` reads saved SRU responses from a Unity Catalog volume.
* **Agent `agent-erratum-annotator`**: Supervisor Agent with the MCP server and the UC function
  `process_sru_response` (generated from the same Python file) as tools.
* **Evaluation** ([`erratum-annotator/eval/databricks/`](erratum-annotator/eval/databricks/README.md)): MLflow
  evaluation of the agent on the 53-row Sample1 set (annotated_title_exact 50/53, erratum_note_exact 52/53,
  original MMS ID 45/46) and a direct Inspector Gadget test of the MCP server (48 files, 0 errors, 46/48 titles
  with the 2 expected differences, 48/48 MMS IDs, median 0.28 s per call).

The live `mcp-erratum-note` app is deployed from the same folder in NAL's repository; this copy is kept
byte-identical.

## Deploying the two apps safely

The two projects deploy independently: neither deploy touches the other app, agent or permissions.

| | `mcp-sru-syntax` | `mcp-erratum-note` |
| --- | --- | --- |
| How | Bundle `sru_syntax` from the repo root (see [Deploy](#deploy)) | `databricks apps deploy mcp-erratum-note --source-code-path <repo>/erratum-annotator/mcp_server` |
| App service principal gets | `CAN_QUERY` on `mas-c8629507-endpoint`, `EXECUTE` on the model service, `CAN_EDIT` on the experiment, `MODIFY` on the trace tables | `READ VOLUME` on `users.amanda_xu.erratum_files` only |
| Check after deploy | [`eval/databricks/inspector_gadget_mcp_test.py`](eval/databricks/inspector_gadget_mcp_test.py) | `erratum-annotator/eval/databricks/mcp-erratum-note Inspector Gadget Test` (expect 0 errors, 46/48, 48/48) |

* **Update in place, never recreate.** The workspace is at its 100-app limit and both apps already exist. Run
  `databricks bundle validate` first; if the bundle state does not track `mcp-sru-syntax`, bind it
  (`bundle deployment bind`) instead of creating it. Never rename the bundle resource key `sru_syntax_mcp`
  without unbinding and rebinding, or the next deploy would delete the app.
* **Callers need CAN USE.** Both apps are OAuth-gated by Databricks Apps. The test service principal
  (Inspector Gadget) has CAN USE on both; its credentials stay in the Unity Catalog secret
  `models.ai/inspector-gadget`, never in Git.
* **Supervisor Agents are configured in Agent Bricks**, not in a bundle, so redeploying an app never changes
  an agent. The `agent-erratum-annotator` tools and instructions are in
  [`erratum-annotator/agent/README.md`](erratum-annotator/agent/README.md) so it can be recreated.
* **Keep one source of rules.** Each project's deterministic rules are a governed UC function, and the agents
  call tools instead of writing answers themselves. For Project 2, `process_sru_response` is generated from
  `erratum-annotator/mcp_server/erratum_annotator.py`: regenerate it whenever that file changes
  (`erratum-annotator/uc_functions/build_uc_functions.py`), then rerun the evaluation. Both projects' function
  definitions are in Git (`sru-syntax-mcp/uc_functions/`, `erratum-annotator/uc_functions/`).

## Tests

* [`tests/test_server.py`](tests/test_server.py) -- smoke tests: server import, name, default transport, tool registration, `build_sru_search_url` discoverability.
* [`tests/test_http_security.py`](tests/test_http_security.py) -- SSRF hardening: `allow_redirects=False`, fixed endpoint URL (not user-controlled), user input in JSON body (not URL), error sanitization, stable error categories.

## Status and next steps

* Done: extraction rules, Unity Catalog function, Supervisor Agent, MCP server app, Unity Catalog tracing,
  offline evaluation; Part 3 erratum annotation (second MCP server and agent) on saved SRU responses.
* Known issue: the Supervisor Agent sometimes returns an empty reply for a title (3 of 41 eval rows). Use the
  function directly for those titles.
* Next: run the SRU searches against Alma live (needs USDA eAuth; Part 3 currently reads saved responses) to
  retrieve the original article's MMS ID and link it to the correction record; provision the evaluation service principal so the eval can run against the deployed app.

## Acknowledgements

This project is built on the [GSA MCP Hackathon template](https://github.com/GSA-TTS/mcp-hackathon-template),
adapted for the NAL SRU Syntax MCP server. The template's `src/`, `tests/`, `deploy/`, and `eval/` structure
is preserved; the example server code is replaced with the mcp-sru-syntax server, agent, and tools.
