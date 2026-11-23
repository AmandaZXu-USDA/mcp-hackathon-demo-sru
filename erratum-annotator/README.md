# erratum-annotator

Matches a correction (erratum) notice in the NAL Alma SRU catalog to its original article and appends an erratum
note to the original title, e.g. `<original title> [Erratum: Aug. 2026, v. 52, no. 4, 134, 10.1007/s10695-026-01767-0]`.
Titles that already carry an `[Erratum: ...]` note are returned unchanged.

## Playground demo: both MCP apps on one correction notice

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

Notes:

* The two steps run in order. Prompt 1 gives the SRU URL. The librarian runs that URL in Alma and saves the response.
  For this notice the response is already saved as
  `/Volumes/users/amanda_xu/erratum_files/sru_responses/Sample1-Row42-9917175652607426.xml`. Prompt 2 reads that file.
* In pane 2, approve the `mcp-erratum-note` tool call when the Playground asks. The reply arrives after approval.
* Pane 1 talks to `agent-sru-syntax`, the Supervisor Agent behind the `mcp-sru-syntax` tool `build_sru_search_url`. It calls the same rules function
  (`users.amanda_xu.build_sru_url`) that the tool calls first. To call the MCP app itself, open a model pane, choose
  **Tools > MCP servers > Databricks Apps**, add `mcp-sru-syntax` (and `mcp-erratum-note` for step 2), then send the same prompt.

## Correction categories

How the annotated title is built depends on what the SRU response holds:

| Category | SRU response holds | Annotated title | Example |
| --- | --- | --- | --- |
| One correction, one original | 1 correction record + 1 original article | `<original title> [Erratum: ...]` | Sample 4, rows 2, 3, 5, 6, 8, 9 and 10 |
| **Two corrections in one original title** | 2 or more correction records of the **same** original article + 1 original article | `<original title> [Erratum: A] [Erratum: B]`: every correction's note, ordered by date (year, month, day), then volume, issue and page | Sample 4, row 4; Sample 1, row 41 |
| Already annotated | An original whose title already contains `[Erratum:` | Unchanged | Sample 1; Sample 4, row 7 |
| No original in Alma | Only the correction record | Blank (`""`): no original record to annotate (status `no_original`) | Sample 1, rows 4 and 24; Sample 4, rows 14, 15 and 17 |
| **No correction in Alma** | Only the original article (the correction notice is not catalogued) | Blank (`""`): no erratum note to add (status `no_correction`, with a manual-review warning) | Sample 4, row 25 |
| No SRU response | Nothing: the row's title only carries a correction keyword (erratum, addendum, ERRATA) | Not processed: **manual review** | Sample 4, rows 16, 19, 20 and 22 |

The original title is the MODS main title (`titleInfo` without a `type`) with its `nonSort` and `subTitle`. A
parallel title keeps its `=` (Sample 4, row 10: `MÚLT-JELEN-JÖVŐ ... = PAST-PRESENT-FUTURE in Hungarian soil analyses`);
any other subtitle follows `: `.

Two corrections in one original title (project owner's rule, 2026-11-22): Sample 4, row 4 (correction
`9917012079207426`) returns the original `9917011947507426` and two corrections from the same issue, so page
decides the order:

```text
Characterization of the role of the antioxidant proteins metallothioneins 1 and 2 in an animal model of Alzheimer’s disease [Erratum: Dec. 2025, v. 82, no. 1, 416, 10.1007/s00018-025-05965-6] [Erratum: Dec. 2025, v. 82, no. 1, 429, 10.1007/s00018-025-05953-w]
```

In Sample 1, row 41 the two corrigenda have different dates, so the Nov. 13, 2025 note comes before the June 18,
2026 note (until 2026-11-22 this row got only the June 18, 2026 note). The result is the same whichever of the
corrections' MMS IDs is passed as `correction_id`. A correction counts as one of the original's when its title
matches the original title (similarity at least 0.6). If the response has more than one possible original, only
the selected correction's note is used. `erratum_note` holds all the notes joined by a space; `erratum_notes` and
`note_correction_ids` list them in order. Tests: `tests/test_multiple_corrections.py`.

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
| `tests/` | Tests of the tools' error handling (`test_tool_errors.py`), curly quotes (`test_curly_quotes.py`), two corrections in one original title (`test_multiple_corrections.py`) and the saved SRU responses they use (`fixtures/`) |
| `uc_functions/` | Unity Catalog function definitions (`.sql`) and the script that generates them from `erratum_annotator.py` |
| `demo/` | Offline single-file copy of the demo page (no account or network needed) and its build script |
| `agent/README.md` | `agent-erratum-annotator` configuration: tools, endpoint and the instructions in use, with steps to recreate it |
| `eval/databricks/` | MLflow evaluation of the `agent-erratum-annotator` Supervisor Agent and the [PDF report](eval/databricks/doc/agent-erratum-annotator-evaluation-report.pdf) |


## Demo web page

<https://mcp-erratum-note-7474654188777746.aws.databricksapps.com> (sign in with a workspace account; needs
`CAN USE` on the app). Pick one of the 75 saved correction notices (48 from Sample 1, Sample 2 rows 3 and 14,
whose correction titles are in curly double quotes, and 25 from Sample 4, rows 2 to 30 except 16, 19, 20 and 22, which
have no SRU response; row 4 has two corrections in one original title, row 10 a parallel title with a subtitle and
row 25 only the original), or paste SRU XML, and see the correction
notice, the original article found, the erratum note and the annotated title, with a status (ready, needs
review, no original in Alma, no correction notice in Alma, already annotated). **See all saved notices at once**
annotates all 75 in one
table. The page is served by the same app and code as the MCP tools (`GET /`, `GET /api/examples`,
`POST /api/annotate`, `GET /api/annotate-all`); it only reads the saved responses. Steps for librarians:
[`LIBRARIAN_QUICKSTART.md`, Part 1](../submission/LIBRARIAN_QUICKSTART.md#part-1-erratum-annotator-add-the-erratum-note-to-the-original-title).
For people without a Databricks account, [`demo/`](demo/README.md) has an offline, single-file copy of the page.

## MCP tools

All code is in Git, at the same paths in both repos
([AmandaZXu-USDA/NAL](https://github.com/AmandaZXu-USDA/NAL/tree/add-mcp-servers/erratum-annotator), branch
`add-mcp-servers`, and [AmandaZXu-USDA/mcp-hackathon-demo-sru](https://github.com/AmandaZXu-USDA/mcp-hackathon-demo-sru/tree/main/erratum-annotator)).
The 7 tools of `mcp-erratum-note` (at `/mcp`) are defined in `mcp_server/app.py` and call the logic in
`mcp_server/erratum_annotator.py`. All are read-only: none writes anything. Errors are described in [Error handling](#error-handling).

| Tool | Input | What it does |
| --- | --- | --- |
| `health` | none | Checks that the server is running and can read the saved SRU responses |
| `parse_sru_response` | `xml` | Parses an SRU searchRetrieveResponse (MODS XML) into records: title, MMS ID, part text, DOI and whether it is a correction |
| `extract_erratum_note` | `part_text`, `doi` | Formats the erratum note `[Erratum: Mon. YYYY, v. V, no. N, page, DOI]` from a correction record's `<part><text>` and DOI; empty if either is missing |
| `enhance_title` | `original_title`, `erratum_note` | Appends the note to the end of the original title; leaves a title that already has `[Erratum:` unchanged |
| `process_sru_response` | `xml`, `search_title` (optional), `correction_id` (optional) | Full pipeline: parses the XML, matches the correction record (the one with MMS ID `correction_id`, if given) to its original article (falling back to `search_title`) and returns the annotated title, the erratum note (all notes, in date/page order, when the response has two or more corrections of the same original), both MMS IDs, review flags, record counts, `status` and `warnings` |
| `list_sru_files` | `contains` (optional) | Lists the saved SRU response files in `SRU_VOLUME_DIR`, filtered by a substring such as `Row43` or an MMS ID |
| `process_sru_file` | `file_name`, `search_title` (optional), `correction_id` (optional) | Reads one saved response by bare file name (no paths) and runs `process_sru_response`; takes the 16-digit MMS ID from the end of the file name (before an optional `-Label` suffix such as `-TwoCorrectionsInOneOriginalTitle`) when `correction_id` is empty |

The demo page routes (`GET /`, `GET /api/examples`, `POST /api/annotate`, `GET /api/annotate-all`) are in the
same `app.py` and call the same code.

## Error handling

Every tool checks its input before it runs and returns a short message that says what to do, ending with
`[error <category>, id <error id>]`. The app log records the error id, category and tool, never the XML, titles or
file contents, so an error a user reports can be found in the logs by its id.

| Category | When | Message tells the caller to |
| --- | --- | --- |
| `invalid_input` | Empty or too long input (XML over 2,000,000 characters, text over 2,000), `correction_id` not 16 digits, `file_name` with a folder or not `.xml` | Fix the named input |
| `not_well_formed` | The XML does not parse (gives line and column); usually it was cut off when pasted | Paste the complete SRU response |
| `not_sru` | Well-formed XML, but not an SRU `searchRetrieveResponse` | Use the response of an NAL Alma SRU search with `recordSchema=mods` |
| `sru_diagnostic` | The SRU response holds a diagnostic (an Alma error) and no records | Check the SRU search URL and run it again |
| `not_found` | No saved SRU response with that file name | Call `list_sru_files` for the exact name |
| `bad_file` | A saved file is not UTF-8 or not a usable SRU response | Save the SRU response again |
| `permission_denied` | The app cannot read the volume | Ask the app owner to grant `READ VOLUME` |
| `unavailable` | The volume could not be read, also after one automatic retry | Try again in a minute |
| `internal` | Anything else (details are not shown) | Send the error id to the app owner |

`process_sru_response` and `process_sru_file` also return `status` and `warnings`, so an empty result is never
mistaken for a good one:

| `status` | Meaning |
| --- | --- |
| `ready`, `needs_review`, `no_original`, `already_annotated` | As on the demo page |
| `no_records` | The SRU response has no records (the search found nothing) |
| `no_correction` | No correction record, so there is no erratum note |
| `no_note` | The correction record has no part text or DOI; needs manual review |

`warnings` lists, for example, a `correction_id` that is not in the response (the first correction record was
used) or a response with several correction records and no `correction_id`. `health` also checks that the saved
SRU responses can be read. The demo page uses the same checks, so pasted XML that is cut off or not SRU gets the
same message. Arguments of the wrong type, or missing ones, are rejected by the MCP library before a tool runs and
keep the library's message.

The agent `agent-erratum-annotator` has matching rules (see [`agent/README.md`](agent/README.md#error-handling)).

Tests: `tests/test_tool_errors.py` (28 tests, no workspace access needed; run `python -m pytest tests -q` from this
folder with the app's requirements and `pytest` installed).

## Unity Catalog functions

The same logic is registered as Unity Catalog functions, so SQL users and the Supervisor Agent can call it without
the app. Each function body is the whole `mcp_server/erratum_annotator.py` followed by a short entry call, so the
functions and the MCP tools run the same code.

| Function | Returns | Used by | Definition |
| --- | --- | --- | --- |
| `users.amanda_xu.process_sru_response(xml, search_title, correction_id)` | Struct: `annotated_title`, `erratum_note`, `correction_id`, `original_id`, `original_source`, `original_candidates`, `needs_review`, `already_annotated`, `num_records`, `num_corrections` | `agent-erratum-annotator` (tool 2, for pasted XML) and SQL users | `uc_functions/process_sru_response.sql` |
| `users.amanda_xu.parse_sru_response(xml)` | Array of records: `title`, `record_id`, `part_text`, `doi`, `is_correction`, `notes` | SQL users | `uc_functions/parse_sru_response.sql` |
| `users.amanda_xu.extract_erratum_note(part_text, doi)` | The erratum note, or an empty string | SQL users | `uc_functions/extract_erratum_note.sql` |
| `users.amanda_xu.enhance_title(original_title, erratum_note)` | The annotated title | SQL users | `uc_functions/enhance_title.sql` |

The `.sql` files were exported from Unity Catalog on November 21, 2026. Recreating each function from its file gave
the same definition and the same output for all 48 saved SRU responses (last regenerated 2026-11-22: SQL and Python
agree on all 75). They are generated by
`uc_functions/build_uc_functions.py`: after changing `erratum_annotator.py`, run it, then run the changed `.sql`
files in the SQL editor (`CREATE OR REPLACE` keeps existing grants).

## Deploy

Deploy `mcp_server/` as a Databricks App named `mcp-erratum-note`. The app's service principal needs READ VOLUME on
the volume in `SRU_VOLUME_DIR`. The Supervisor Agent `agent-erratum-annotator` uses this MCP app plus the UC
function `users.amanda_xu.process_sru_response`. To recreate the UC functions in a new workspace or schema, run the
files in `uc_functions/` in the SQL editor and grant `EXECUTE` to the callers.

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
* **Test before every deploy.** Run `python -m pytest tests -q` in this folder (28 tests).
* **Check after every deploy.** Run `eval/databricks/mcp-erratum-note Inspector Gadget Test` (expect 0 errors,
  annotated_title 46/48, MMS ID 48/48) and, after changing `erratum_annotator.py`, regenerate the UC functions
  with `uc_functions/build_uc_functions.py` and run the changed `.sql` files.
