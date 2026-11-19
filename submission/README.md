# Submission: SRU Syntax MCP Server (NAL)

A custom MCP server, deployed as the Databricks App `mcp-sru-syntax`, that turns an erratum/correction
notice title into the NAL Alma production SRU searchRetrieve URL for the original article.

## Contents

| File | What it is |
|------|------------|
| [`sru-syntax-mcp-evaluation-report.pdf`](sru-syntax-mcp-evaluation-report.pdf) | Evaluation report (11 pages, November 18, 2026; updated November 19, 2026) |
| [`LIBRARIAN_QUICKSTART.md`](LIBRARIAN_QUICKSTART.md) | Librarian quick-start: four ways to get an SRU URL from a correction title (Supervisor Agent chat, Genie Code with the MCP tool, the app's agent endpoint, the SQL function for lists), with access needed and errors |

## How it works

* **MCP endpoint:** `/mcp` on the app (stateless streamable HTTP, JSON responses), OAuth-gated by Databricks Apps.
* **Tool:** `build_sru_search_url(correction_title: str) -> str`, read-only and idempotent.
* **Behind the tool:** the agent-sru-syntax Supervisor Agent (serving endpoint `mas-c8629507-endpoint`),
  which applies the title rules in the Unity Catalog function `users.amanda_xu.build_sru_url`.
* **Browser page:** `GET /` on the app (paste one title, get the SRU URL as a link), backed by
  `POST /api/sru-url`. The tool and the page ask the agent once more when its reply is empty.

## Results summary

| Evaluation | Result |
|---|---|
| 1. Inspector Gadget testing | Passed. An external client authenticating as a service principal (OAuth M2M) listed 1/1 tools and got the correct SRU URL. |
| 2. Offline MLflow evaluation | `sru_url_match` 0.93 (38/41) on a 41-row labelled dataset; `safety` 1.00. The 3 misses are empty Supervisor Agent replies. |
| 3. Online evaluation (production monitoring) | Two custom LLM-judge scorers (`ToolCallEfficiency`, `ToolCallCorrectness`) registered; stopped pending admin confirmation of scorer permissions. |
| 4. Evaluation run `kindly-lamb-651` | `ToolCallEfficiency` on 2 traces: 1 yes, 1 judge parse error. Trace review shows both used tools efficiently. |
| 5. Agent latency per step | 174 requests: tool requests p50 22.5 s (tool about 69% of the time); requests answered without the tool p50 2.7 s. |
| 6. Live testing (November 19) | Page, page API, MCP and agent routes pass as Inspector Gadget. About 18 titles/min at 10 at a time (142 titles via MCP). Every URL the agent returned matched the rules function. The empty-reply retry recovered 0 of 10 titles. |

See the PDF for method, per-scorer results, findings and next steps.

## Where the code lives

* Server and eval kit: [`AmandaZXu-USDA/NAL`](https://github.com/AmandaZXu-USDA/NAL/tree/add-mcp-servers/sru-syntax-mcp),
  branch `add-mcp-servers` (`sru-syntax-mcp/`, eval kit in `sru-syntax-mcp/eval/databricks/`).
* In this repo: the server adapted to the template structure is in `src/sru_server/`.
