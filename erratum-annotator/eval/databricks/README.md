# agent-erratum-annotator: Databricks evaluation

Offline MLflow evaluation of the `agent-erratum-annotator` Supervisor Agent (endpoint `mas-c341c0aa-endpoint`,
tools: MCP app `mcp-erratum-note` and UC function `users.amanda_xu.process_sru_response`) on the 53-row,
librarian-checked Sample1 spreadsheet.

**Report (PDF, November 21, 2026 run, with the new tool-title scorer and a comparison to November 20):** [`doc/agent-erratum-annotator-evaluation-report.pdf`](doc/agent-erratum-annotator-evaluation-report.pdf)
(on GitHub, use the download icon at the top right of the preview). The same file is in the Databricks volume at
`/Volumes/users/amanda_xu/erratum_files/reports/agent-erratum-annotator-evaluation-report.pdf`
(Catalog Explorer, then Download).

## MLflow evaluation run, November 21, 2026 (latest)

New full run of `Erratum Annotator Agent Evaluation` on all 53 rows, with the current agent instructions and
`mcp-erratum-note` deployment. MLflow experiment `/Users/amanda.xu@usda.gov/agent-erratum-annotator-eval`
(ID `1982416510445692`): smoke run `youthful-foal-70` (3 rows), full run `rogue-conch-731`
(`c0161188c6714e7cbdcb4984215c2e38`), rescore run `sneaky-doe-82` (deterministic scorers, including
`tool_annotated_title_exact`, reapplied to the saved replies without calling the agent again). Scorer self-check against the ground truth
passed before the run. 0 endpoint errors, 0 truncated replies; latency median 11.8 s, max 312.1 s.

| Scorer | Result | Notes |
| --- | --- | --- |
| annotated_title_exact (primary) | 51/53 | Rows 34 and 40: the reply has a straight apostrophe where the catalog title has a curly one (U+2019); see [known limitation](../../agent/README.md#known-limitation-curly-apostrophes) |
| erratum_note_exact | 53/53 | |
| original_mms_id_match (rows with an original) | 46/46 | |
| called_tool (rows with an SRU file) | 48/48 | |
| tool_annotated_title_exact (new) | 53/53 | The tool result's `annotated_title`, the title a librarian copies into Alma, is exact on every row, including rows 34 and 40 |
| correctness (LLM judge) | 51/53 | Row 9: says no SRU response is saved instead of "no original in Alma". Row 4: the judge's own rationale supports the reply |
| no_fabrication (LLM guideline) | 42/53 | All 11 failures are judge errors: in 10 the judge expected the original MMS ID to equal the correction's MMS ID (the IDs match ground truth); in row 31 it missed the sentence saying the title is already annotated |

By case, annotated_title_exact: annotated 31/32, already annotated 13/14, manual review 3/3, file but no
original 2/2, no file and no original 2/2. Per-row results:
[`doc/agent-erratum-annotator-eval-results-20261121.csv`](doc/agent-erratum-annotator-eval-results-20261121.csv);
run IDs: [`doc/agent-erratum-annotator-eval-runs-20261121.json`](doc/agent-erratum-annotator-eval-runs-20261121.json).

## Results (November 20, 2026)

| Scorer | Result |
| --- | --- |
| annotated_title_exact (primary) | 50/53 |
| erratum_note_exact | 52/53 |
| original_mms_id_match (rows with an original) | 45/46 |
| called_tool (rows with an SRU file) | 48/48 |
| correctness (LLM judge) | 50/53 |
| no_fabrication (LLM guideline) | 37/53, 10 of 16 failures are judge errors |

Failures: row 28 hit the Supervisor Agent's 290 s limit; rows 34 and 40 retyped a curly apostrophe in the title.
Notices with no saved SRU response get a request for SRU XML instead of a manual-review / no-original answer.

## Results after error handling (November 21, 2026)

Re-run of the same notebook after the error handling in `mcp-erratum-note` and the new agent rules
([`../../agent/README.md`](../../agent/README.md#error-handling)); MLflow run `flawless-shrike-232`, 53 rows.

| Scorer | November 20 | November 21 |
| --- | --- | --- |
| annotated_title_exact (primary) | 50/53 | 51/53 |
| erratum_note_exact | 52/53 | 53/53 |
| original_mms_id_match | 45/46 | 1.00 |
| called_tool | 48/48 | 1.00 |
| correctness (LLM judge) | 50/53 | 51/53 |

The notebook's `%pip` line now also installs `httpx`, which the Databricks SDK's OpenAI client needs; without it
the notebook failed before running any row.

## MCP server test as Inspector Gadget (November 21, 2026)

The `mcp-erratum-note` app was also tested directly, without the agent, as the Inspector Gadget service
principal (application ID `f22c554b-c019-4511-8774-079d9891c7d5`, CAN_USE on the app, credentials in the UC
secret `models.ai/inspector-gadget`). The test lists the tools, calls `list_sru_files`, then calls
`process_sru_file` on every saved Sample1 SRU response. Report section 8.

| Check | Result |
| --- | --- |
| Tools listed | 7 |
| `list_sru_files` | 48 files |
| `process_sru_file` errors | 0/48 |
| annotated_title exact | 46/48 |
| original MMS ID match | 48/48 |
| Latency per call | median 0.28 s, max 0.49 s |

Rows 4 and 24 are the only differences: Alma has no original, so the ground-truth title is blank, but the tool
still builds a title from the search title with `needs_review` false. Every run is appended to
`users.amanda_xu.erratum_mcp_inspector_test`.

## Contents

| Item | Purpose |
| --- | --- |
| `Erratum Annotator Agent Evaluation` | Dataset, scorers with self-check, predict function, smoke test, full run, failure analysis, rescore, per-row export |
| `Erratum Annotator Evaluation Report` | Builds and verifies the PDF from the per-row export |
| `mcp-erratum-note Inspector Gadget Test` | Live MCP server test as the Inspector Gadget service principal; appends to the results table and exports a per-row CSV |
| `doc/agent-erratum-annotator-eval-results-20261120.csv` | Per-row scores, latency, tools, rationales and replies |
| `doc/agent-erratum-annotator-eval-runs-20261120.json` | MLflow experiment and run IDs |
| `doc/agent-erratum-annotator-eval-results-20261121.csv` | Per-row scores, latency, tools, rationales and replies (latest run) |
| `doc/agent-erratum-annotator-eval-runs-20261121.json` | MLflow experiment and run IDs (latest run) |
| `doc/mcp-erratum-note-inspector-test-20261121.csv` | Inspector Gadget per-file results (run 2026-11-21 01:08:59 UTC) |

The notebooks read and write paths under `/Workspace/Users/amanda.xu@usda.gov/erratum-annotator/eval`; edit
`RESULTS_DIR` / `DOC` to run them from this folder. Run the Inspector Gadget test before the report notebook,
which reads its CSV.
