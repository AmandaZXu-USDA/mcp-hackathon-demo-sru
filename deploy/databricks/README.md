# Databricks Apps Deployment

Deploy the NAL SRU Syntax MCP server as a [Databricks App](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/)
using a [Declarative Automation Bundle](https://docs.databricks.com/aws/en/dev-tools/bundles/).
Databricks builds a container from the synced source and `app.yaml`, runs it,
and exposes it behind your workspace's authentication.

- **Transport:** MCP over streamable-HTTP at `/mcp` (stateless); health at `/health`
- **Port:** Databricks injects `DATABRICKS_APP_PORT` (defaults to `8000`); `app.py`
  serves HTTP automatically — no code changes.
- **Bundle:** `databricks.yml` at the `sru-syntax-mcp/` root defines the app,
  its resources (serving endpoint, model service, MLflow experiment, trace tables),
  and variables you can override at deploy time.

> **How the app supports this:** `mcp_server/app.py` serves MCP over
> streamable-HTTP on the injected port. The bundle (`databricks.yml`) declares
> the app and wires its Unity Catalog resources so `app.yaml` can read them via
> `valueFrom` at runtime.

## What Databricks injects at runtime

| Variable | Purpose |
|---|---|
| `DATABRICKS_APP_PORT` | Port your server must listen on (default 8000) |
| `DATABRICKS_HOST` | Workspace URL |
| `DATABRICKS_CLIENT_ID` | Service principal client ID |
| `DATABRICKS_CLIENT_SECRET` | OAuth secret |

The app also receives these from the bundle's app resources (via `valueFrom` in
`mcp_server/app.yaml`):

| Env var | Resource | Purpose |
|---|---|---|
| `SERVING_ENDPOINT` | `serving-endpoint` | Agent Bricks Supervisor Agent endpoint (`mas-c8629507-endpoint`), `CAN_QUERY` |
| `MODEL_SERVICE` | `model-service` | Unity Gateway model service (default `models.ai.gpt-5-6-luna`), `EXECUTE` |
| `MLFLOW_EXPERIMENT_ID` | `app-experiment` | Unity Catalog-backed experiment for traces, `CAN_EDIT` |
| `AGENT_TIMEOUT_SECONDS` | (literal) | Timeout for agent calls (300s) |

---

## Part 1 — Prerequisites

### 1.1 Install the Databricks CLI (v0.205+)

```bash
# macOS
brew tap databricks/tap && brew install databricks
# or see: https://docs.databricks.com/dev-tools/cli/install.html
databricks --version
```

### 1.2 Authenticate

```bash
databricks auth login --host https://<your-workspace>.cloud.databricks.com
databricks current-user me      # confirm you're logged in
```

> **Profile name gotcha:** `databricks auth login` prompts for a profile name and
> defaults it to your workspace host (e.g. `dbc-xxxx`) — **not** `DEFAULT`. Note
> the name you choose; you may need `--profile <name>` on bundle commands if you
> are not using `DEFAULT`.

> Databricks **Apps** must be enabled on your workspace. If `apps` commands fail
> with a feature error, ask your workspace admin to enable Databricks Apps.

### 1.3 Clone the repository

```bash
git clone -b add-mcp-servers https://github.com/AmandaZXu-USDA/NAL.git
cd NAL/sru-syntax-mcp
```

### 1.4 Unity Catalog permissions

The MCP server's tool (`build_sru_search_url`) calls the Unity Catalog function
`users.amanda_xu.build_sru_url` through the Agent Bricks Supervisor Agent. Ensure
the app's service principal (or your user, in development) has:

```sql
GRANT USE CATALOG ON CATALOG users TO `<principal>`;
GRANT USE SCHEMA ON SCHEMA users.amanda_xu TO `<principal>`;
GRANT EXECUTE ON FUNCTION users.amanda_xu.build_sru_url TO `<principal>`;
```

---

## Part 2 — Deploy with the bundle

The `databricks.yml` bundle defines one app (`sru_syntax_mcp`) that hosts both the
MCP server (`/mcp`) and the SRU syntax agent (`/invocations`, `/responses`).
The workspace is at its 100-app limit, so the agent shares this app.

Run from the `sru-syntax-mcp/` folder (the bundle root):

```bash
# 1. Validate the bundle configuration
databricks bundle validate --strict -t dev

# 2. One time: bind the existing app to the bundle resource
#    (the mcp-sru-syntax app already exists in the workspace)
databricks bundle deployment bind sru_syntax_mcp mcp-sru-syntax -t dev

# 3. Deploy the app
databricks bundle deploy -t dev

# 4. Start the app
databricks bundle run sru_syntax_mcp -t dev
```

Override any variable with `--var`, for example:

```bash
databricks bundle deploy -t dev --var model_service=models.ai.gpt-5-6-sol
```

The first deploy builds the container and can take a few minutes.

### Smoke-test

```bash
# Private apps are auth-gated — an unauthenticated curl returns 302/401 (expected).
# Authenticated health check:
DATABRICKS_TOKEN="$(databricks auth token --output json | jq -r .access_token)"   curl -s -H "Authorization: Bearer $DATABRICKS_TOKEN"   https://<app-url>/health

# List MCP tools:
DATABRICKS_TOKEN="$(databricks auth token --output json | jq -r .access_token)"   curl -s -H "Authorization: Bearer $DATABRICKS_TOKEN"   -H 'Content-Type: application/json'   -H 'Accept: application/json, text/event-stream'   -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'   https://<app-url>/mcp
```

---

## Part 3 — Connect a client

Databricks Apps are gated by workspace auth, so an MCP client must present a
bearer token. For **Claude**, **Cursor**, **Codex**, or any MCP client that
supports HTTP + headers:

```json
{
  "mcpServers": {
    "mcp-sru-syntax": {
      "type": "http",
      "url": "https://<app-url>/mcp",
      "headers": { "Authorization": "Bearer <DATABRICKS_TOKEN>" }
    }
  }
}
```

> Token from `databricks auth token`. Tokens are short-lived; for a durable
> integration use a service principal with access to the app.

### Managed MCP endpoint (alternative)

The underlying Unity Catalog function is also available as a managed MCP server
endpoint, bypassing the app entirely:

```
https://<workspace-hostname>/api/2.0/mcp/functions/users/amanda_xu/build_sru_url
```

When authenticating with OAuth, request the `unity-catalog` scope. This endpoint
exposes the tool `users__amanda_xu__build_sru_url` directly.

---

## Part 4 — Test the agent

```bash
curl -X POST "https://<app-url>/invocations" \
  -H "Authorization: Bearer <OAUTH_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"input": [{"role": "user", "content": "Correction: <article title>"}]}'
```

Apps require an OAuth token (`databricks auth token`); personal access tokens
are not accepted. Each title can take 60-90 seconds because the Supervisor
Agent does the lookup.

---

## Teardown

```bash
# Stop and delete the app (the bundle can redeploy it later)
databricks apps delete mcp-sru-syntax

# Or destroy the bundle deployment entirely
databricks bundle destroy -t dev
```

---

## Bundle variables

| Variable | Default | Description |
|---|---|---|
| `mcp_app_name` | `mcp-sru-syntax` | Name of the Databricks App |
| `serving_endpoint` | `mas-c8629507-endpoint` | Agent Bricks Supervisor Agent endpoint |
| `model_service` | `models.ai.gpt-5-6-luna` | Unity Gateway model service |
| `trace_experiment_id` | `131270370350843` | Unity Catalog-backed MLflow experiment |
| `trace_table_prefix` | `users.amanda_xu.sru_syntax_agent` | Prefix for UC trace tables |

---

## Known gaps / notes

- **Auth-gated by default:** Databricks Apps sit behind workspace SSO/OAuth, so
  unauthenticated probes return 302/401 — that's expected, not a failure. Use a
  bearer token to reach the app programmatically.
- **App limit:** The workspace is at its 100-app limit, so the MCP server and the
  agent share one app (`mcp-sru-syntax`). The standalone agent in `agent/` is an
  alternative if app capacity frees up.
- **Stateless HTTP:** The server runs stateless streamable-HTTP, which scales
  cleanly on Apps (no sticky sessions required).
- **Tracing:** `mlflow.openai.autolog()` traces every model and MCP tool call
  automatically. Traces are stored in Unity Catalog tables
  `users.amanda_xu.sru_syntax_agent_otel_*`.
- **Dependencies:** `requirements.txt` pins `mcp>=1.10.0,<2` because MCP 2.x
  removed `mcp.server.fastmcp`.
