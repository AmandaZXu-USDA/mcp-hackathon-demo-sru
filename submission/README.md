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
| [`GSA-MCP-Hackathon-NAL-mcp-sru-syntax-and-erratum-note.pptx`](GSA-MCP-Hackathon-NAL-mcp-sru-syntax-and-erratum-note.pptx) | Hackathon presentation (20 slides, with speaker notes): how the submission meets the judging criteria (slide 2), challenge, solution, `mcp-sru-syntax` design and key decisions, code organization (slide 9), MCP tool design around agent goals (slide 10), demo, the eight-layer evaluation setup and results (slides 12-13), security, lessons learned, the second MCP server `mcp-erratum-note` and its evaluation (slides 16-17), how the MCP apps and two agents meet multi-agent system requirements (slide 18), and next steps |
| [`sru-syntax-mcp-evaluation-report.pdf`](sru-syntax-mcp-evaluation-report.pdf) | Step 1 evaluation report (16 pages, November 18, 2026; updated November 22, 2026), including lessons learned, recommendations, the November 21 re-run (41/41) and the November 22 Phoenix evaluation (section 9) |
| [`agent-erratum-annotator-evaluation-report.pdf`](agent-erratum-annotator-evaluation-report.pdf) | Step 2 evaluation report (6 pages, November 20, 2026; updated November 22, 2026): MLflow evaluation of `agent-erratum-annotator` on 82 notices (Sample 1 and Sample 4, results per sample) with traces in Unity Catalog (tool calls, latency percentiles, token usage), two corrections in one original title, and the Inspector Gadget test of `mcp-erratum-note` |
| [`LIBRARIAN_QUICKSTART.md`](LIBRARIAN_QUICKSTART.md) | Librarian quick-start: four ways to get an SRU URL from a correction title (Supervisor Agent chat, Genie Code with the MCP tool, the app's agent endpoint, the SQL function for lists), with access needed and errors |
| [`DEMO_VIDEO_SCRIPT.md`](DEMO_VIDEO_SCRIPT.md) | Demo video narration script (about 2.5 minutes): timed narration and on-screen cues for the two-app AI Playground demo, a pre-recording checklist, and recording and editing tools |

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

## Playground demo: both MCP apps on one correction notice

**Video demo:** [Two MCP apps side by side in the Databricks AI Playground (YouTube)](https://youtu.be/OXjYBd19azA). It shows the two-app Playground demo described below.

Judges can repeat this demo in the Databricks **AI Playground**. Both prompts use the same correction notice:
MMS ID `9917175652607426` (Sample 1, row 42). Its title has a Unicode hyphen (U+2010) in "Climate‐driven".
Paste each prompt as written. Both were checked on November 23, 2026: each reply matched the ground truth in
`Correction-Sample1-53-annotated.csv`.

| Step | App | Playground pane (serving endpoint) | Tool called | Time |
| --- | --- | --- | --- | --- |
| 1 | `mcp-sru-syntax` | `agent-sru-syntax` (`mas-c8629507-endpoint`) | `users__amanda_xu__build_sru_url` | 50 s |
| 2 | `mcp-erratum-note` | `agent-erratum-annotator` (`mas-c341c0aa-endpoint`) | `process_sru_file` (MCP) | 13 s |

**Prompt 1 (`mcp-sru-syntax`, build the SRU search URL):**

```text
Build the Alma SRU search URL for correction notice MMS ID 9917175652607426. Correction notice title: Correction to: Climate‐driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture
```

Expected: the reply gives this URL (it matches the ground-truth `sru_url` character for character):

```text
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22Climate-driven%20insect%20pest%20outbreaks%20and%20food%20security%20risks%3A%20a%20review%20of%20adaptive%20strategies%20for%20resilient%20agriculture%22%20and%20alma.local_field_912%3D%22Article%22
```

**Prompt 2 (`mcp-erratum-note`, annotate the original title from the saved SRU response):**

```text
Annotate the original article for correction notice MMS ID 9917175652607426. Correction notice title: Correction to: Climate‐driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture. The saved SRU response file is Sample1-Row42-9917175652607426.xml. Return the annotated original title, the erratum note, the original MMS ID, and whether it needs manual review.
```

Expected:

* Annotated title: `Climate-driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture [Erratum: Sept. 2026, v. 99, no. 3, 111, 10.1007/s10340-026-02069-3]`
* Original MMS ID: `9917015258907426`
* Needs manual review: No

**Second example (video demo): MMS ID `9917175553207426` (Sample 1, row 45).** Checked on November 23, 2026 with the same two
panes side by side. Its title has an en dash in "flour–epoxy": step 1 changes it to a plain hyphen for the SRU URL, and step 2 keeps the en dash in the annotated title.

| Step | Tool called | Time | Result |
| --- | --- | --- | --- |
| 1 | `users__amanda_xu__build_sru_url` | 39 s | URL matches the ground-truth `sru_url` exactly |
| 2 | `process_sru_file` (MCP) | 13 s | Annotated title and original MMS ID match the ground truth; no manual review |

Prompt 1:

```text
Build the Alma SRU search URL for correction notice MMS ID 9917175553207426. Correction notice title: Correction: Optimization of material and extrusion parameters for wood flour–epoxy composites with potential additive-manufacturing applications in construction
```

Expected URL:

```text
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22Optimization%20of%20material%20and%20extrusion%20parameters%20for%20wood%20flour-epoxy%20composites%20with%20potential%20additive-manufacturing%20applications%20in%20construction%22%20and%20alma.local_field_912%3D%22Article%22
```

Prompt 2:

```text
Annotate the original article for correction notice MMS ID 9917175553207426. Correction notice title: Correction: Optimization of material and extrusion parameters for wood flour–epoxy composites with potential additive-manufacturing applications in construction. The saved SRU response file is Sample1-Row45-9917175553207426.xml. Return the annotated original title, the erratum note, the original MMS ID, and whether it needs manual review.
```

Expected:

* Annotated title: `Optimization of material and extrusion parameters for wood flour–epoxy composites with potential additive-manufacturing applications in construction [Erratum: Aug. 2026, v. 84, no. 4, 103, 10.1007/s00107-026-02464-8]`
* Original MMS ID: `9917046021407426`
* Needs manual review: No

Notes:

* The two steps run in order. Prompt 1 gives the SRU URL. The librarian runs that URL in Alma and saves the response.
  For this notice the response is already saved as
  `/Volumes/users/amanda_xu/erratum_files/sru_responses/Sample1-Row42-9917175652607426.xml`. Prompt 2 reads that file.
* In pane 2, approve the `mcp-erratum-note` tool call when the Playground asks. The reply arrives after approval.
* Pane 1 talks to `agent-sru-syntax`, the Supervisor Agent behind the `mcp-sru-syntax` tool `build_sru_search_url`. It calls the same rules function
  (`users.amanda_xu.build_sru_url`) that the tool calls first. To call the MCP app itself, open a model pane, choose
  **Tools > MCP servers > Databricks Apps**, add `mcp-sru-syntax` (and `mcp-erratum-note` for step 2), then send the same prompt.

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
| 1. Offline MLflow evaluation of `agent-erratum-annotator` (82 notices: 53 librarian-checked from Sample 1, 29 from Sample 4) | annotated_title_exact 77/82 (Sample 1 50/53, Sample 4 27/29), erratum_note_exact 81/82, original MMS ID 67/68, called a tool 73/73, tool's annotated title exact 81/82, no_fabrication 82/82 (deterministic: every MMS ID, DOI and note comes from a tool result or the request), correctness 78/82. Misses: four titles where the agent retyped a curly apostrophe (the tool's title was exact) and one 290 s agent timeout. Sample 4's expected titles were drafted from the tool output and checked one by one against Alma by the project owner. |
| 2. Inspector Gadget test of `mcp-erratum-note` (OAuth M2M service principal, no agent) | 7/7 tools listed; `process_sru_file` on 48 saved responses: 0 errors, 48/48 original MMS IDs, 46/48 titles (the 2 differences are notices with no original in Alma), median 0.28 s per call. |

See the PDFs for method, per-scorer results, findings and next steps.

## Where the code lives

| | Step 1 | Step 2 |
|---|---|---|
| In this repo | [`src/sru_server/`](../src/sru_server/) (server adapted to the GSA template), [`databricks.yml`](../databricks.yml), [`eval/databricks/`](../eval/databricks/README.md) | [`erratum-annotator/`](../erratum-annotator/README.md): `mcp_server/`, `agent/`, `eval/databricks/` |
| Deploy and safety | [Deploying the two apps safely](../README.md#deploying-the-two-apps-safely) | [Deploying the two apps safely](../README.md#deploying-the-two-apps-safely) |

Both live apps are deployed from NAL's repository (`AmandaZXu-USDA/NAL`, branch `add-mcp-servers`), which
NAL staff use; this repository holds the same code for review (step 2 byte-identical).
