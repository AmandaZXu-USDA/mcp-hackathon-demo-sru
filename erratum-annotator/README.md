# erratum-annotator

Matches a correction (erratum) notice in the NAL Alma SRU catalog to its original article and appends an erratum
note to the original title, e.g. `<original title> [Erratum: Aug. 2026, v. 52, no. 4, 134, 10.1007/s10695-026-01767-0]`.
Titles that already carry an `[Erratum: ...]` note are returned unchanged.

This is **project 2** of the NAL MCP Hackathon submission. Project 1 (`mcp-sru-syntax` + `agent-sru-syntax`)
builds the SRU search URL for a correction notice; this project takes the SRU response and produces the annotated
catalog title.

| Component | Name |
| --- | --- |
| MCP server (Databricks App) | `mcp-erratum-note`, 7 tools, `https://mcp-erratum-note-7474654188777746.aws.databricksapps.com/mcp` |
| Agent (Agent Bricks Supervisor Agent) | `agent-erratum-annotator`, endpoint `mas-c341c0aa-endpoint` (see [`agent/README.md`](agent/README.md)) |
| Deterministic backend | UC function `users.amanda_xu.process_sru_response` (generated from `mcp_server/erratum_annotator.py`) |
| Data | Saved SRU responses in `/Volumes/users/amanda_xu/erratum_files/sru_responses` |

## Contents

| Path | Purpose |
| --- | --- |
| `mcp_server/erratum_annotator.py` | Core logic: parse SRU MODS XML, pick the original record, build the erratum note, enhance the title |
| `mcp_server/app.py` | MCP server `mcp-erratum-note` (FastMCP, streamable HTTP at `/mcp`) for Databricks Apps |
| `mcp_server/app.yaml`, `requirements.txt` | Databricks Apps config; `SRU_VOLUME_DIR` points at the saved SRU responses volume |
| `agent/README.md` | `agent-erratum-annotator` configuration: tools, endpoint and the instructions in use, with steps to recreate it |
| `eval/databricks/` | MLflow evaluation of the `agent-erratum-annotator` Supervisor Agent and the [PDF report](eval/databricks/doc/agent-erratum-annotator-evaluation-report.pdf) |

## MCP tools

`health`, `parse_sru_response`, `extract_erratum_note`, `enhance_title`, `process_sru_response`,
`list_sru_files`, `process_sru_file` (reads a saved response from `SRU_VOLUME_DIR`).

## Deploy

Deploy `mcp_server/` as a Databricks App named `mcp-erratum-note`. The app's service principal needs READ VOLUME on
the volume in `SRU_VOLUME_DIR`. The Supervisor Agent `agent-erratum-annotator` uses this MCP app plus the UC
function `users.amanda_xu.process_sru_response`.

The deployed app runs from this repo folder: `/Workspace/Users/amanda.xu@usda.gov/NAL/erratum-annotator/mcp_server`
(snapshot deployment, November 20, 2026). Redeploy after pulling changes:
`databricks apps deploy mcp-erratum-note --source-code-path <repo>/erratum-annotator/mcp_server`.

### Deploying safely

* **One deploy source.** The live app is deployed from the NAL repo folder above. The copy of this folder in
  [`AmandaZXu-USDA/mcp-hackathon-demo-sru`](https://github.com/AmandaZXu-USDA/mcp-hackathon-demo-sru/tree/main/erratum-annotator)
  is kept byte-identical for review; change the code in NAL first, then copy it.
* **Update, don't recreate.** The workspace is at its 100-app limit, so `apps deploy` updates the existing app.
  Never delete the app to redeploy it.
* **Least privilege.** The app's service principal needs only READ VOLUME on
  `users.amanda_xu.erratum_files`; callers need CAN USE on the app. Tools are read-only; `process_sru_file`
  accepts only a bare `.xml` file name inside `SRU_VOLUME_DIR` (no paths).
* **No secrets in Git.** Test credentials (Inspector Gadget) stay in the UC secret `models.ai/inspector-gadget`.
* **Check after every deploy.** Run `eval/databricks/mcp-erratum-note Inspector Gadget Test` (expect 0 errors,
  annotated_title 46/48, MMS ID 48/48) and, after changing `erratum_annotator.py`, regenerate the UC function.
