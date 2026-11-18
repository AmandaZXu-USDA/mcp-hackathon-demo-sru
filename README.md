# sru-syntax-mcp

Converts erratum/correction notice titles into NAL Alma production SRU search URLs for the original article.

This folder is a Declarative Automation Bundle with one Databricks App and one MLflow experiment.
The workspace is at its 100-app limit, so the MCP server and the agent share the `sru-syntax-mcp` app:

| Endpoint | Code | What it does |
| --- | --- | --- |
| `/mcp` | `mcp_server/app.py` | MCP server (streamable HTTP) with one tool, `build_sru_search_url`, that calls the agent-sru-syntax Supervisor Agent endpoint `mas-c8629507-endpoint` |
| `POST /invocations`, `POST /responses` | `mcp_server/agent.py` | OpenAI Agents SDK agent that uses the `/mcp` tool over localhost |
| `GET /health` | `mcp_server/app.py` | Liveness check |

Agent traces go to the experiment `/Users/amanda.xu@usda.gov/sru-syntax-agent-uc-experiment`
(ID `131270370350843`), which stores them in Unity Catalog tables `users.amanda_xu.sru_syntax_agent_*`.

## Layout

```
sru-syntax-mcp/
  databricks.yml                     bundle: app, experiment, variables
  mcp_server/                        the deployed app
    app.py                           MCP server + agent HTTP routes
    agent.py                         agent, local MCP connection, MLflow tracing
    app.yaml, requirements.txt       env from app resources; dependencies
  agent/                             standalone agent app version (not deployed; use if app capacity frees up)
  setup/create_uc_backed_experiment.py  optional: experiment with traces in Unity Catalog
```

## App resources

The app gets these through `valueFrom` in `mcp_server/app.yaml`:

* `serving-endpoint` -> `SERVING_ENDPOINT`: Supervisor Agent endpoint, `CAN_QUERY`
* `model-service` -> `MODEL_SERVICE`: Unity Gateway model service (default `models.ai.gpt-5-6-luna`), `EXECUTE`
* `app-experiment` -> `MLFLOW_EXPERIMENT_ID`: Unity Catalog-backed experiment (`var.trace_experiment_id`), `CAN_EDIT`
* `trace-annotations`, `trace-logs`, `trace-metrics`, `trace-spans`: the four `users.amanda_xu.sru_syntax_agent_otel_*` tables, `MODIFY` (includes `SELECT`)

## Deploy

Run from this folder (the bundle root):

```bash
databricks bundle validate --strict -t dev

# One time: the sru-syntax-mcp app already exists, so let the bundle manage it
databricks bundle deployment bind sru_syntax_mcp sru-syntax-mcp -t dev

databricks bundle deploy -t dev
databricks bundle run sru_syntax_mcp -t dev
```

Override any variable with `--var`, for example `--var model_service=models.ai.gpt-5-6-sol`.

## Test the agent

```bash
curl -X POST "https://sru-syntax-mcp-7474654188777746.aws.databricksapps.com/invocations" \
  -H "Authorization: Bearer <OAUTH_TOKEN>" -H "Content-Type: application/json" \
  -d '{"input": [{"role": "user", "content": "Correction: <article title>"}]}'
```

Apps require an OAuth token (`databricks auth token`); personal access tokens are not accepted.
Each title can take 60-90 seconds because the Supervisor Agent does the lookup.

## Tracing

`mlflow.openai.autolog()` traces every model and MCP tool call automatically. `run_agent` adds an
`AGENT` span plus a `preprocessing` child span.

Traces are stored in Unity Catalog under `users.amanda_xu`:

* `sru_syntax_agent_otel_spans`, `_otel_logs`, `_otel_metrics`, `_otel_annotations` (tables)
* `sru_syntax_agent_trace_unified`, `sru_syntax_agent_trace_metadata` (views)

`setup/create_uc_backed_experiment.py` created the experiment and tables (already run once). To use a
different location, run it with new names and set `trace_experiment_id` / `trace_table_prefix` in
`databricks.yml`. The original workspace-backed `sru-syntax-agent-experiment` is kept for its earlier trace.
