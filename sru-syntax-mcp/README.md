# sru-syntax-mcp (deployed source)

Copy of the source the live `mcp-sru-syntax` app is deployed from (AmandaZXu-USDA/NAL, `sru-syntax-mcp/`),
kept byte-identical for the code deposit. The live app is deployed from the NAL repo; change code there first.

| Path | What it is |
| --- | --- |
| `mcp_server/app.py` | MCP server: tool `build_sru_search_url` at `/mcp`, browser page `GET /`, `POST /api/sru-url`, agent routes `/invocations` and `/responses`, `GET /health` |
| `mcp_server/agent.py` | The app's agent (model `AGENT_MODEL`), which calls the MCP tool |
| `mcp_server/app.yaml`, `requirements.txt` | Databricks Apps config and dependencies |
| `uc_functions/build_sru_url.sql` | Unity Catalog function `users.amanda_xu.build_sru_url`, the rules the tool runs |

Tools, functions and deployment: [`deploy/databricks/README.md`](../deploy/databricks/README.md#tools-and-functions).
`src/sru_server/` is the same server adapted to the GSA hackathon template, with the tests in `tests/`.
