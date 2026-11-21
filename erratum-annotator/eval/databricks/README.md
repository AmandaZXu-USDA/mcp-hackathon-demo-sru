# agent-erratum-annotator: Databricks evaluation

Offline MLflow evaluation of the `agent-erratum-annotator` Supervisor Agent (endpoint `mas-c341c0aa-endpoint`,
tools: MCP app `mcp-erratum-note` and UC function `users.amanda_xu.process_sru_response`) on the 53-row,
librarian-checked Sample1 spreadsheet.

**Report (PDF):** [`doc/agent-erratum-annotator-evaluation-report.pdf`](doc/agent-erratum-annotator-evaluation-report.pdf)
(on GitHub, use the download icon at the top right of the preview). The same file is in the Databricks volume at
`/Volumes/users/amanda_xu/erratum_files/reports/agent-erratum-annotator-evaluation-report.pdf`
(Catalog Explorer, then Download).

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
| `doc/mcp-erratum-note-inspector-test-20261121.csv` | Inspector Gadget per-file results (run 2026-11-21 01:08:59 UTC) |

The notebooks read and write paths under `/Workspace/Users/amanda.xu@usda.gov/erratum-annotator/eval`; edit
`RESULTS_DIR` / `DOC` to run them from this folder. Run the Inspector Gadget test before the report notebook,
which reads its CSV.
