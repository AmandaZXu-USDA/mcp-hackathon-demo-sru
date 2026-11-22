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

## Tools and functions

All code for this app is in Git, at the same paths in both repos
([AmandaZXu-USDA/NAL](https://github.com/AmandaZXu-USDA/NAL/tree/add-mcp-servers/sru-syntax-mcp), branch
`add-mcp-servers`, and [AmandaZXu-USDA/mcp-hackathon-demo-sru](https://github.com/AmandaZXu-USDA/mcp-hackathon-demo-sru/tree/main/sru-syntax-mcp)).
Paths below are from the repo root. The live app is deployed from the NAL copy.

### MCP tool (at `/mcp`)

| Tool | Input | What it does | Code |
| --- | --- | --- | --- |
| `build_sru_search_url` | `correction_title` (string, 1 to 1,000 characters) | Turns an erratum or correction notice title into the NAL Alma production SRU searchRetrieve URL for the original article. Runs the UC function `users.amanda_xu.build_sru_url` on the SQL warehouse in `SQL_WAREHOUSE_ID` first (about 4 s); only if that call fails, asks the `agent-sru-syntax` Supervisor Agent (`SERVING_ENDPOINT`). A notice that names no single article (bare `Correction`, an issue-level notice) gets a short no-URL message. Errors come back as a short message with a category (`invalid_input`, `timeout`, `unavailable`, `rate_limited`, `permission_denied`, `not_found`, `bad_request`, `bad_response`, `empty_reply`, `internal`) and an error id. Annotations: read-only, not destructive, idempotent, closed world. | `sru-syntax-mcp/mcp_server/app.py` |

### Other routes on the same app

| Route | What it does | Code |
| --- | --- | --- |
| `GET /` | Browser page: paste one title, get the SRU URL as a link | `sru-syntax-mcp/mcp_server/app.py` |
| `POST /api/sru-url` | `{"title": "..."}` returns `{"text", "urls", "source"}`; same lookup as the tool (`source` is `function` or `agent`); `"use_agent": true` asks the agent directly | `sru-syntax-mcp/mcp_server/app.py` |
| `POST /invocations`, `POST /responses` | The app's agent (OpenAI Responses-style input; model `AGENT_MODEL`, `databricks-gpt-5-6-luna`), which calls the MCP tool | `sru-syntax-mcp/mcp_server/agent.py` |
| `GET /health` | Liveness check | `sru-syntax-mcp/mcp_server/app.py` |

### Unity Catalog function

| Function | What it does | Used by | Definition |
| --- | --- | --- | --- |
| `users.amanda_xu.build_sru_url(correction_title STRING) RETURNS STRING` | Python, deterministic. Removes the Correction, Corrigendum, Erratum and similar prefixes and builds the production SRU URL (`https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST`, `alma.title` plus the Article filter, spaces as `%20`, no `maximumRecords`). Returns an empty string for bare and issue-level notices. | The MCP tool and page (first), the `agent-sru-syntax` Supervisor Agent (its tool), and SQL users (librarian quick-start, option 4) | `sru-syntax-mcp/uc_functions/build_sru_url.sql` |

To recreate the function, run `build_sru_url.sql` in the SQL editor (change `users.amanda_xu` for another schema),
then grant it as in [1.4](#14-unity-catalog-permissions). The file was exported from Unity Catalog on
November 21, 2026; recreating a copy from it gave the same definition and the same URL for all 142 Sample3 titles.

The fork also has `src/sru_server/`, the same tool adapted to the GSA hackathon template (`tools/build_sru_url.py`),
with its tests in `tests/`.

---

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
| `AGENT_MODEL` | (literal) | Model the app's agent uses: `databricks-gpt-5-6-luna`, a Databricks-hosted endpoint. While it is set, `MODEL_SERVICE` is not used (its OpenAI key expired November 20, 2026) |
| `SQL_WAREHOUSE_ID` | (literal) | SQL warehouse (`50d2bd4ddf65e0f5`) the tool and page run `users.amanda_xu.build_sru_url` on; the app's service principal needs `CAN USE` on it |

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

The MCP server's tool (`build_sru_search_url`) runs the Unity Catalog function
`users.amanda_xu.build_sru_url` directly on a SQL warehouse, and the Agent Bricks Supervisor Agent
(the fallback) uses the same function as its tool. Ensure the app's service principal (or your user,
in development) has `CAN USE` on the SQL warehouse in `SQL_WAREHOUSE_ID`, and:

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

> **For the live app, use the `prod` target**, not the steps below: see
> [Production target](#production-target-prod). Since 2026-11-22 only this repo's `prod`
> target manages `mcp-sru-syntax`; the `dev` target does not track it, so
> `bundle deploy -t dev` would try to create a second app. The steps below show how the
> app was first deployed and are kept for reference.

Run from the repo root (the bundle root):

```bash
# 1. Validate the bundle configuration
databricks bundle validate --strict -t dev

# 2. One time: bind the existing app to the bundle resource
#    (only if this bundle does not track the existing mcp-sru-syntax app yet,
#    e.g. a different user or a fresh bundle state; skip it otherwise)
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

### Production target (`prod`)

`-t dev` (the default) is development mode: jobs get a `[dev <user>]` prefix and their
schedules are paused. `-t prod` is production mode:

* one fixed copy at `/Workspace/Users/amanda.xu@usda.gov/.bundle/sru_syntax/prod`;
* deploys only from the `main` branch;
* runs as amanda.xu@usda.gov, who has CAN_MANAGE on every resource;
* real resource names, with the `check_live` job's schedule active (07:00 US Eastern).

Two resources it defines already existed and were managed elsewhere, so a first
`bundle deploy -t prod` would have tried to create duplicates:

| Bundle resource | Existing resource | Managed before the binding by |
| --- | --- | --- |
| `sru_syntax_mcp` (app) | `mcp-sru-syntax` | the `sru_syntax` bundle in AmandaZXu-USDA/NAL (`sru-syntax-mcp/`) |
| `check_live` (job) | "NAL MCP apps daily live check", job 531572408825586 | created in the UI; runs `scripts/check_live.py` from the NAL clone |

To make this repo's prod target the owner, bind both, then deploy:

```bash
databricks bundle validate --strict -t prod
databricks bundle deployment bind sru_syntax_mcp mcp-sru-syntax -t prod
databricks bundle deployment bind check_live 531572408825586 -t prod
databricks bundle deploy -t prod
```

Status (2026-11-22): both are bound and `prod` is deployed (commit `f9813a4`), followed by
`databricks bundle run sru_syntax_mcp -t prod` to deploy the app code:

* app `mcp-sru-syntax`: deployment `01f1e61881a013a9a6bbc8f30764bc2d` from
  `.bundle/sru_syntax/prod/files/sru-syntax-mcp/mcp_server` (the same files as the earlier
  deployment from NAL); resources `sql-warehouse` and `sru-function` added, as declared;
  ACL amanda.xu@usda.gov CAN_MANAGE, Inspector Gadget CAN_USE;
* job 531572408825586: script from `.bundle/sru_syntax/prod/files/scripts/check_live.py`,
  07:00 US Eastern, UI-locked (change it here and redeploy);
* experiment `/Users/amanda.xu@usda.gov/sru-syntax-agent-experiment` created (empty; the
  app writes traces to the Unity Catalog-backed experiment `131270370350843`).

Checked after the deploy: Inspector Gadget suite 55/55 (`mcp-sru-syntax`) and 89/89
(`mcp-erratum-note`); a manual job run passed 5/5.

The app and job now come from this repo's `main`. The prod target overrides the app's
`source_code_path` with `./sru-syntax-mcp/mcp_server`, because `./mcp_server` has only
`app.yaml` and `requirements.txt` and cannot run alone. The app was then unbound from
NAL's bundle (`dev`), so this `prod` target is the only bundle that manages it. To ship
a change: edit in AmandaZXu-USDA/NAL, copy it here with `scripts/sync_to_fork.py`, commit
to `main`, then `bundle plan -t prod` (must say `update`, not `create`, for the app),
`bundle deploy -t prod` and `bundle run sru_syntax_mcp -t prod`.

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
are not accepted. A title takes about 7-10 seconds: about 4 seconds for the
tool (SQL function first) plus the agent's own model calls. The agent uses the
Databricks-hosted endpoint `databricks-gpt-5-6-luna` (`AGENT_MODEL` in app.yaml).

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
| `warehouse_id` | `50d2bd4ddf65e0f5` | SQL warehouse for `build_sru_url` and the `check_live` job |
| `sru_function` | `users.amanda_xu.build_sru_url` | Governed Unity Catalog function with the title rules |
| `check_live_secret` | `models.ai.inspector-gadget` | UC secret with the Inspector Gadget OAuth credentials for the `check_live` job |

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
