# agent-erratum-annotator: Databricks evaluation

Offline MLflow evaluation of the `agent-erratum-annotator` Supervisor Agent (endpoint `mas-c341c0aa-endpoint`,
tools: MCP app `mcp-erratum-note` and UC function `users.amanda_xu.process_sru_response`) on the 53-row,
librarian-checked Sample1 spreadsheet.

**Report (PDF, November 21, 2026 run, with the new tool-title scorer and a comparison to November 20):** [`doc/agent-erratum-annotator-evaluation-report.pdf`](doc/agent-erratum-annotator-evaluation-report.pdf)
(on GitHub, use the download icon at the top right of the preview). The same file is in the Databricks volume at
`/Volumes/users/amanda_xu/erratum_files/reports/agent-erratum-annotator-evaluation-report.pdf`
(Catalog Explorer, then Download).

## MLflow evaluation run with traces in Unity Catalog, November 22, 2026

Same 53 rows, scorers and ground truth as the run below, now in a new experiment whose traces are stored in Unity
Catalog: `/Users/amanda.xu@usda.gov/agent-erratum-annotator-eval-uc` (ID `1982416510487747`), trace tables
`users.amanda_xu.agent_erratum_eval_otel_spans`, `_otel_logs` and `_otel_annotations` (written through SQL warehouse
`50d2bd4ddf65e0f5`). The earlier experiment `1982416510445692` keeps its runs and traces in experiment storage; a new experiment
keeps the two apart (a Unity Catalog trace location, once bound, cannot be changed).

`predict` now asks the Supervisor Agent to return its own trace (`databricks_options.return_trace`) and attaches it
with `mlflow.add_trace`, so each evaluation trace has the agent's `CHAT_MODEL` spans with token usage and `TOOL`
spans for `process_sru_file`. The experiment's overview (tool calls, latency, token usage, quality) is computed from
these spans. Smoke run `big-fish-133`, full run `fearless-grub-772` (`5e437af7cd8348af82afcac1bd3d3a24`), rescore run
`amusing-wren-737`; per-row results in
[`doc/agent-erratum-annotator-eval-results-20261122-uc.csv`](doc/agent-erratum-annotator-eval-results-20261122-uc.csv).
The experiment also holds 1 probe trace from the setup check, with no run.

| Scorer | Result |
| --- | --- |
| annotated_title_exact | 51/53 (rows 34 and 40, curly apostrophe limitation) |
| erratum_note_exact | 53/53 |
| original_mms_id_match | 46/46 |
| called_tool | 48/48 |
| tool_annotated_title_exact | 53/53 |
| correctness (LLM judge) | 52/53 (row 4: the judge wanted the reply to say it gives no search_title fallback; the reply is right) |
| no_fabrication (LLM judge) | 45/53 (rows 8, 39, 42, 43, 44, 51, 52, 53: judge errors, mostly expecting the original MMS ID to equal the correction's) |

Trace statistics for the 53 full-run traces (all `OK`, 0 endpoint errors, 0 truncated replies):

| Metric | Value |
| --- | --- |
| Latency per request | p50 17.2 s, p90 18.7 s, p95 19.6 s, p99 20.6 s, max 20.7 s (the run below, without the returned trace: median 11.3 s) |
| Tool calls | 48 `process_sru_file` calls, one per row with an SRU file, 0 errors; p50 643 ms, p95 945 ms, max 1125 ms. The 5 rows without a file call no tool |
| LLM calls | 202 (about 3.8 per request); p50 3.4 s, p95 8.3 s |
| Tokens per request | input median 13,467, mean 12,826; output median 294, mean 282 |
| Tokens, whole run | 679,830 input + 14,981 output = 694,811 |

## MLflow evaluation run, November 22, 2026 (after all Sample 4 files)

Re-run of `Erratum Annotator Agent Evaluation` on all 53 Sample 1 rows after the Sample 4 work, with the updated
ground truth (row 41 now expects two notes, Nov. 13, 2025 then June 18, 2026; backup
`Correction-Sample1-53-annotated-before-20261122.csv`) and the current `mcp-erratum-note` deployment (blank
`annotated_title` when the response has no original or no correction record). Sample 4 has no librarian ground
truth yet, so it is not part of this evaluation; its 25 files are covered by the tests in `../../tests/`.

Before the run, `expected_erratum_note` became every note in the expected title (joined by a space), and
`erratum_note_exact` now compares the set of notes, so a reply with only one of row 41's two notes fails. The scorer
self-check against the ground truth passed (46/46 corrupted and doubled notes caught). Experiment ID
`1982416510445692`: smoke run `bouncy-kit-309`, full run `placid-roo-533` (`9eb0fc3ec06d4925a8d8b227d5af54ad`), rescore run
`grandiose-croc-373`; per-row results in
[`doc/agent-erratum-annotator-eval-results-20261122.csv`](doc/agent-erratum-annotator-eval-results-20261122.csv).
0 endpoint errors, 0 truncated replies; latency median 11.3 s, max 17.8 s.

| Scorer | Nov 21 (row 9) run | This run |
| --- | --- | --- |
| annotated_title_exact | 51/53 | 51/53 (rows 34 and 40, curly apostrophe limitation; row 41's two-note title passes) |
| erratum_note_exact | 53/53 | 53/53 (row 41: both notes) |
| original_mms_id_match | 46/46 | 46/46 |
| called_tool | 48/48 | 48/48 |
| tool_annotated_title_exact | 53/53 | 53/53 |
| correctness (LLM judge) | 52/53 | 52/53 (row 24: same judge objection as before) |
| no_fabrication (LLM judge) | 42/53 | 46/53; rows 3, 22, 44, 51 and 53: the judge expected the original MMS ID to equal the correction's; rows 33 and 39: the judge objected to restating the existing note or the correction's own title and DOI. All IDs, titles and notes match the ground truth |

Only rows 4, 9, 24 and 39 say `no original in Alma`, the four rows with that ground-truth status.

## Row 9: "no original in Alma" (November 21, 2026, latest)

Rows 9 and 39 have no saved SRU response, and the librarian's Alma search found only the correction notice
(ground truth `no original in Alma - correction notice only`). The agent cannot tell that from a missing file, so:

* The evaluation request for these two rows now passes on the librarian's search result: "The librarian's Alma
  search found only the correction notice; the original article is not in Alma." Other rows are unchanged.
* New agent rule (live, and in [`../../agent/README.md`](../../agent/README.md)): when the request says the Alma
  search found only the correction notice, report `no original in Alma - correction notice only` and the correction
  MMS ID, with no annotated title and no request for XML; never conclude this only because no file is saved.

Checks before the full run: rows 9 and 39 said `no original in Alma` in 6 of 6 runs (3 of 4 with the new request
but the old instructions); rows 6, 16 and 19 (manual review) and row 9 without the search result (2 runs) did not.

Full run `capricious-hound-768` (`cfbf93c778a74563915c1a52878dae9b`), smoke run `bemused-koi-45`, rescore run
`kindly-worm-600`; per-row results in
[`doc/agent-erratum-annotator-eval-results-20261121-row9.csv`](doc/agent-erratum-annotator-eval-results-20261121-row9.csv).

| Scorer | Earlier Nov 21 run | This run |
| --- | --- | --- |
| annotated_title_exact | 51/53 | 51/53 (rows 34 and 40, curly apostrophe limitation) |
| erratum_note_exact | 53/53 | 53/53 |
| original_mms_id_match | 46/46 | 46/46 |
| called_tool | 48/48 | 48/48 |
| tool_annotated_title_exact | 53/53 | 53/53 |
| correctness (LLM judge) | 51/53 | 52/53; row 9 now passes; row 24's reply is right (no original, no title) but the judge wanted it to say it gives no search_title fallback |
| no_fabrication (LLM judge) | 42/53 | 42/53 |

Only rows 4, 9, 24 and 39 say `no original in Alma`, the four rows with that ground-truth status. The PDF report
still describes the earlier November 21 run.

## MLflow evaluation run, November 21, 2026

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
