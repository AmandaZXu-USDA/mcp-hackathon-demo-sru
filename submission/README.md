# Submission: NAL correction-notice MCP servers

Two custom MCP servers and two agents on Databricks, from the USDA National Agricultural Library (NAL), that
take a publisher's correction notice to the original article's catalog record:

| Step | MCP server (Databricks App) | Agent | What it does |
|---|---|---|---|
| 1 | `mcp-sru-syntax` (1 tool) | `agent-sru-syntax` (Supervisor Agent) | Correction notice title -> NAL Alma production SRU search URL for the original article |
| 2 | `mcp-erratum-note` (7 tools) | `agent-erratum-annotator` (Supervisor Agent) | SRU response -> original article title with an `[Erratum: ...]` note, ready for the catalog |

## Contents

| File | What it is |
|------|------------|
| [`GSA-MCP-Hackathon-mcp-sru-syntax.pptx`](GSA-MCP-Hackathon-mcp-sru-syntax.pptx) | Hackathon presentation (17 slides, with speaker notes): challenge, solution, `mcp-sru-syntax` design and key decisions, demo, evaluation, security, lessons learned, the second MCP server `mcp-erratum-note` and its evaluation (slides 13-14), how the MCP apps and two agents meet multi-agent system requirements (slide 15), and next steps |
| [`sru-syntax-mcp-evaluation-report.pdf`](sru-syntax-mcp-evaluation-report.pdf) | Step 1 evaluation report (16 pages, November 18, 2026; updated November 22, 2026), including lessons learned, recommendations, the November 21 re-run (41/41) and the November 22 Phoenix evaluation (section 9) |
| [`agent-erratum-annotator-evaluation-report.pdf`](agent-erratum-annotator-evaluation-report.pdf) | Step 2 evaluation report (4 pages, November 20, 2026; updated November 21, 2026): MLflow evaluation of `agent-erratum-annotator` and the Inspector Gadget test of `mcp-erratum-note` |
| [`LIBRARIAN_QUICKSTART.md`](LIBRARIAN_QUICKSTART.md) | Librarian quick-start: four ways to get an SRU URL from a correction title (Supervisor Agent chat, Genie Code with the MCP tool, the app's agent endpoint, the SQL function for lists), with access needed and errors |

## How it works: step 1, `mcp-sru-syntax`

* **MCP endpoint:** `/mcp` on the app (stateless streamable HTTP, JSON responses), OAuth-gated by Databricks Apps.
* **Tool:** `build_sru_search_url(correction_title: str) -> str`, read-only and idempotent.
* **Behind the tool:** the agent-sru-syntax Supervisor Agent (serving endpoint `mas-c8629507-endpoint`),
  which applies the title rules in the Unity Catalog function `users.amanda_xu.build_sru_url`.
* **Browser page:** `GET /` on the app (paste one title, get the SRU URL as a link), backed by
  `POST /api/sru-url`. The tool and the page ask the agent once more when its reply is empty.

## How it works: step 2, `mcp-erratum-note`

* **MCP endpoint:** `/mcp` on the app (FastMCP, streamable HTTP), OAuth-gated by Databricks Apps.
* **Tools (read-only):** `health`, `parse_sru_response`, `extract_erratum_note`, `enhance_title`,
  `process_sru_response`, `list_sru_files`, `process_sru_file` (reads a saved SRU response from a Unity Catalog
  volume; accepts only a bare `.xml` file name).
* **Logic:** picks the original record (cited DOI first, then title similarity), builds the erratum note from the
  correction record and appends it to the original title; titles that already carry a note are unchanged and
  uncertain matches are flagged `needs_review`.
* **Agent:** the `agent-erratum-annotator` Supervisor Agent (serving endpoint `mas-c341c0aa-endpoint`) calls the
  MCP server, or the Unity Catalog function `users.amanda_xu.process_sru_response` generated from the same
  Python file when the user pastes SRU XML.

## Results summary: step 1

| Evaluation | Result |
|---|---|
| 1. Inspector Gadget testing | Passed. An external client authenticating as a service principal (OAuth M2M) listed 1/1 tools and got the correct SRU URL. |
| 2. Offline MLflow evaluation | `sru_url_match` 0.93 (38/41) on a 41-row labelled dataset; `safety` 1.00. The 3 misses are empty Supervisor Agent replies. |
| 3. Online evaluation (production monitoring) | Two custom LLM-judge scorers (`ToolCallEfficiency`, `ToolCallCorrectness`) registered; stopped pending admin confirmation of scorer permissions. |
| 4. Evaluation run `kindly-lamb-651` | `ToolCallEfficiency` on 2 traces: 1 yes, 1 judge parse error. Trace review shows both used tools efficiently. |
| 5. Agent latency per step | 174 requests: tool requests p50 22.5 s (tool about 69% of the time); requests answered without the tool p50 2.7 s. |
| 6. Live testing (November 19) | Page, page API, MCP and agent routes pass as Inspector Gadget. About 18 titles/min at 10 at a time (142 titles via MCP). Every URL the agent returned matched the rules function. The empty-reply retry recovered 0 of 10 titles. |
| 7. Lessons learned and recommendations | 20 lessons (access, MCP naming and client, agent, evaluation, performance, engineering), including that a custom MCP server app must be named with the `mcp-` prefix to appear in the Genie Code connectors, and 10 recommendations, starting with an independent, librarian-confirmed ground truth. |

## Results summary: step 2

| Evaluation | Result |
|---|---|
| 1. Offline MLflow evaluation of `agent-erratum-annotator` (53 librarian-checked notices) | annotated_title_exact 50/53, erratum_note_exact 52/53, original MMS ID 45/46, called a tool 48/48, correctness 50/53. Misses: one 290 s agent timeout and two titles where the agent retyped a curly apostrophe. |
| 2. Inspector Gadget test of `mcp-erratum-note` (OAuth M2M service principal, no agent) | 7/7 tools listed; `process_sru_file` on 48 saved responses: 0 errors, 48/48 original MMS IDs, 46/48 titles (the 2 differences are notices with no original in Alma), median 0.28 s per call. |

See the PDFs for method, per-scorer results, findings and next steps.

## Where the code lives

| | Step 1 | Step 2 |
|---|---|---|
| In this repo | [`src/sru_server/`](../src/sru_server/) (server adapted to the GSA template), [`databricks.yml`](../databricks.yml), [`eval/databricks/`](../eval/databricks/README.md) | [`erratum-annotator/`](../erratum-annotator/README.md): `mcp_server/`, `agent/`, `eval/databricks/` |
| Deploy and safety | [Deploying the two apps safely](../README.md#deploying-the-two-apps-safely) | [Deploying the two apps safely](../README.md#deploying-the-two-apps-safely) |

Both live apps are deployed from NAL's repository (`AmandaZXu-USDA/NAL`, branch `add-mcp-servers`), which
NAL staff use; this repository holds the same code for review (step 2 byte-identical).
