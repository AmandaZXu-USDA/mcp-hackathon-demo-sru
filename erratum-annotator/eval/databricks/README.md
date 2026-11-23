# agent-erratum-annotator: Databricks evaluation

Offline MLflow evaluation of the `agent-erratum-annotator` Supervisor Agent (endpoint `mas-c341c0aa-endpoint`,
tools: MCP app `mcp-erratum-note` and UC function `users.amanda_xu.process_sru_response`) on the 53-row,
librarian-checked Sample1 spreadsheet.

**Report (PDF, November 22, 2026 run with traces in Unity Catalog: tool calls, latency percentiles, token usage, and a comparison to November 21 and 22):** [`doc/agent-erratum-annotator-evaluation-report.pdf`](doc/agent-erratum-annotator-evaluation-report.pdf)
(on GitHub, use the download icon at the top right of the preview). The same file is in the Databricks volume at
`/Volumes/users/amanda_xu/erratum_files/reports/agent-erratum-annotator-evaluation-report.pdf`
(Catalog Explorer, then Download).

## MLflow evaluation run with the deterministic no_fabrication scorer, November 22, 2026

Same 82 rows and instructions as the run after the no_correction rule; no_fabrication is the deterministic scorer
described below. Smoke run `learned-perch-382`, full run `agreeable-asp-911`, rescore run `redolent-wren-21`; per-row
results in
[`doc/agent-erratum-annotator-eval-results-20261122-detfab.csv`](doc/agent-erratum-annotator-eval-results-20261122-detfab.csv).
0 endpoint errors, 0 truncated loops; latency median 16.9 s, p95 27.3 s, max 302.4 s (one timeout).

| Scorer | Sample 1 | Sample 4 | Previous run (S1 / S4) |
| --- | --- | --- | --- |
| annotated_title_exact | 50/53 (rows 5, 34, 40) | 27/29 (rows 4, 29) | 51/53 / 27/29 |
| erratum_note_exact | 52/53 (row 5) | 29/29 | 53/53 / 29/29 |
| original_mms_id_match | 45/46 (row 5) | 22/22 | 46/46 / 22/22 |
| called_tool | 48/48 | 25/25 | 48/48 / 25/25 |
| tool_annotated_title_exact | 52/53 (row 5) | 29/29 | 53/53 / 29/29 |
| correctness (LLM judge) | 49/53 (rows 4, 5, 24, 41) | 29/29 | 51/53 / 29/29 |
| no_fabrication (deterministic) | 53/53 | 29/29 | 40/53 / 21/29 (LLM judge) |

* Sample 1 row 5 timed out: the agent called process_sru_file, then reached the Supervisor Agent's 290 s limit
  (302.4 s) and replied with a continue / wrap up prompt. It passed in the previous run; timeouts are intermittent.
* The other title misses are the curly apostrophe (rows 34 and 40; Sample 4 rows 4 and 29).
* Correctness rows 4 and 24 are judge errors (no mention of the search_title fallback), row 41 a judge error (two
  identical MMS IDs called different), row 5 the timeout.
* no_fabrication: no reply has an MMS ID, DOI or note outside the tool results and the request. Sample 1 row 39 gave
  no note this time. A timed-out reply has no IDs and passes; the title scorers catch timeouts.

## no_fabrication is now deterministic (November 22, 2026)

The LLM guideline judge `no_fabrication` failed 14 to 21 correct replies per run, mostly by treating the original
article's MMS ID as invented. It is replaced by a deterministic scorer of the same name: every MMS ID (16 digits, not
inside a DOI) and DOI in the reply must appear in a tool call (arguments or output) or in the request, and every
erratum note must appear in a tool output. The scorer self-check adds cases that must fail (an MMS ID, DOI or note in
no tool result; a note without a tool call) and must pass (the user's erratum MMS ID, a note copied from the tool).

Applied to the 82 saved replies of `valuable-turtle-195` (not yet a new MLflow run): 81/82. The one failure is a real
fabrication the LLM judge passed: for Sample 1 row 39 (no SRU file, original not in Alma) the agent wrote an erratum
note itself from the correction title, without a tool call and in the wrong format
(`[Erratum: 2026, v. 17, no., e168486, https://doi.org/...]`). The instructions forbid building notes.

## MLflow evaluation run after the no_correction instruction rule, November 22, 2026

Same 82 rows and scorers as the Sample 4 run below, after the agent's instructions gained a rule for the
no_correction status ([`../../agent/README.md`](../../agent/README.md#no-correction-in-alma-november-22-2026)). Smoke run
`industrious-eel-855`, full run `valuable-turtle-195`, rescore run `secretive-mule-359`; per-row results in
[`doc/agent-erratum-annotator-eval-results-20261122-s4-nocorr.csv`](doc/agent-erratum-annotator-eval-results-20261122-s4-nocorr.csv).
0 endpoint errors, 0 truncated loops, no timeouts; latency median 16.9 s, p95 18.7 s, max 26.3 s.

| Scorer | Sample 1 | Sample 4 | Before the rule (S1 / S4) |
| --- | --- | --- | --- |
| annotated_title_exact | 51/53 (rows 34, 40) | 27/29 (rows 4, 29) | 51/53 / 26/29 |
| erratum_note_exact | 53/53 | 29/29 | 53/53 / 28/29 |
| original_mms_id_match | 46/46 | 22/22 | 46/46 / 21/22 |
| called_tool | 48/48 | 25/25 | 48/48 / 25/25 |
| tool_annotated_title_exact | 53/53 | 29/29 | 53/53 / 28/29 |
| correctness (LLM judge) | 51/53 (rows 4, 41) | 29/29 | 53/53 / 27/29 |
| no_fabrication (LLM judge) | 40/53 | 21/29 | 46/53 / 22/29 |

* All four exact-title misses are the curly apostrophe (the tool's title is exact on 82/82).
* Sample 4 row 25 is now labelled "no correction in Alma - original only"; the 7 no-original rows still say
  "no original in Alma". Sample 4 row 26 (290 s timeout before) passes in 13 s.
* Every judge failure is a judge error: correctness row 4 (no mention of the search_title fallback) and row 41
  (says two identical MMS IDs differ); no_fabrication 17 rows with the MMS ID mistake and 4 (S1 rows 35, 48, 49, 50)
  that apply the "no title can be produced" guideline to replies that gave one. The judges failed different rows in
  the run before, so their results vary from run to run.

## MLflow evaluation run with Sample 4 added, November 22, 2026

82 rows: the 53 Sample 1 rows plus the 29 Sample 4 rows (2 to 30) from
`/Volumes/users/amanda_xu/erratum_files/Correction-Sample4-29-annotated.csv`. Sample 4's expected titles were drafted
from the tool output (`Correction-Sample4-29-annotated-DRAFT-unreviewed.csv`, kept), then checked one by one against
the records in Alma by the project owner, who approved all 29. Sample 4 row n is `row_num` 400 + n
(columns `sample` and `sample_row` in the results). New case `file_but_no_correction` (row 25: only the original in
Alma); rows 16, 19, 20 and 22 (no SRU response) expect a manual-review reply. The smoke test adds rows 404 and 425.
The scorer self-check passed (67/67 corrupted and doubled notes caught).

Experiment `/Users/amanda.xu@usda.gov/agent-erratum-annotator-eval-uc` (traces in Unity Catalog): smoke run
`wistful-newt-32`, full run `bright-wolf-355` (`f4ca00e917804a619c7443ccc4109289`), rescore run `ambitious-hare-632`;
per-row results in
[`doc/agent-erratum-annotator-eval-results-20261122-s4.csv`](doc/agent-erratum-annotator-eval-results-20261122-s4.csv).
0 endpoint errors, 0 truncated loops; latency median 17.0 s, max 302.2 s.

| Scorer | Sample 1 | Sample 4 |
| --- | --- | --- |
| annotated_title_exact | 51/53 (rows 34, 40: curly apostrophe) | 26/29 (rows 4, 29: curly apostrophe; row 26: agent timeout) |
| erratum_note_exact | 53/53 | 28/29 (row 26) |
| original_mms_id_match | 46/46 | 21/22 (row 26) |
| called_tool | 48/48 | 25/25 |
| tool_annotated_title_exact | 53/53 | 28/29 (row 26) |
| correctness (LLM judge) | 53/53 | 27/29 (rows 17, 26) |
| no_fabrication (LLM judge) | 46/53 | 22/29 (rows 2, 5, 23, 24, 28: judge expected the original MMS ID to equal the correction's; 25; 26) |

* Sample 4 row 4 (two corrections in one original): both notes, in order; fails only on the curly apostrophe.
* Sample 4 row 26: the Supervisor Agent hit its 290 s limit (302.2 s) and replied with a continue / wrap up prompt.
* Sample 4 row 25: the reply is right in substance (original present, correction not in Alma, no annotated title) but
  labels the status "No original in Alma - correction notice only"; the agent instructions do not yet name the
  no_correction case.

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

## Row 9: "no original in Alma" (Latest for November 21, 2026)

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
describes the run with traces in Unity Catalog (section above).

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
