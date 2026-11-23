# sru-syntax-mcp (deployed source)

Copy of the source the live `mcp-sru-syntax` app is deployed from (AmandaZXu-USDA/NAL, `sru-syntax-mcp/`),
kept byte-identical for the code deposit. Change code in the NAL repo first and copy it here with
`scripts/sync_to_fork.py`. Since 2026-11-22 the live app is deployed from this folder by this repo's `prod`
bundle target (see [`../deploy/databricks/README.md`](../deploy/databricks/README.md#production-target-prod)).

**Librarians:** see [`LIBRARIAN_QUICKSTART.md`](LIBRARIAN_QUICKSTART.md) for the four ways to get a URL
from a title (Supervisor Agent chat, Genie Code with the MCP tool, the app's agent endpoint, and the
`build_sru_url` SQL function for lists), with the access each needs.

| Path | What it is |
| --- | --- |
| `mcp_server/app.py` | MCP server: tool `build_sru_search_url` at `/mcp`, browser page `GET /`, `POST /api/sru-url`, agent routes `/invocations` and `/responses`, `GET /health` |
| `mcp_server/agent.py` | The app's agent (model `AGENT_MODEL`), which calls the MCP tool |
| `mcp_server/app.yaml`, `requirements.txt` | Databricks Apps config and dependencies |
| `LIBRARIAN_QUICKSTART.md` | Librarian quick-start (same file as in the NAL repo) |
| `uc_functions/build_sru_url.sql` | Unity Catalog function `users.amanda_xu.build_sru_url`, the rules the tool runs |

Tools, functions and deployment: [`deploy/databricks/README.md`](../deploy/databricks/README.md#tools-and-functions).
`src/sru_server/` is the same server adapted to the GSA hackathon template, with the tests in `tests/`.

**Playground demo:** the two demo prompts (MMS ID 9917175652607426, both MCP apps) are in the root README under
[Playground demo: both MCP apps on one correction notice](../README.md#playground-demo-both-mcp-apps-on-one-correction-notice).
