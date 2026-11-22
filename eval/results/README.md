# Committed evidence

Records written by the Inspector Gadget suite ([`../inspector_gadget/`](../inspector_gadget/README.md)) and the
demo replay. Every file is hashed in [`INDEX.json`](INDEX.json). The writer refuses to save a file that looks like
it holds a credential. Identifiers that are not credentials are kept: app URLs, the Inspector Gadget service
principal ID and MMS IDs are already public in this repository.

## Runs on November 22, 2026 UTC (commit `e6eb71c` of AmandaZXu-USDA/NAL)

Full suite on both apps after the Sample 2 files (50 saved responses) and the `build_sru_url` repeated-prefix fix.
Ground truth is unchanged (41 labelled notices; 48 librarian-checked Sample 1 files), so the case counts match the
November 21 runs.

| Run | App | Result | By suite | Functional latency (new session per call) |
| --- | --- | --- | --- | --- |
| [`20261122T0054Z_mcp-sru-syntax_ed14312e`](runs/20261122T0054Z_mcp-sru-syntax_ed14312e/report.log) | `mcp-sru-syntax` | **55/55 pass** | smoke 1/1, contract 3/3, functional 41/41, errors 3/3, security 3/3, determinism 2/2, auth 2/2 | p50 4.29 s, p95 5.88 s, max 12.67 s (41 calls, 5 at a time) |
| [`20261122T0055Z_mcp-erratum-note_d6a3ab58`](runs/20261122T0055Z_mcp-erratum-note_d6a3ab58/report.log) | `mcp-erratum-note` (deployment `01f1e6067e42168f80fdb82ba7b4d9a9`) | **89/89 pass** | smoke 3/3, contract 21/21, functional 51/51, errors 7/7, security 3/3, determinism 2/2, auth 2/2 | p50 2.39 s, p95 2.69 s, max 2.74 s (51 calls, 8 at a time) |

## Runs on November 21, 2026 (commit `8316e98` of AmandaZXu-USDA/NAL)

| Run | App | Result | By suite | Functional latency (new session per call) |
| --- | --- | --- | --- | --- |
| [`20261121T2055Z_mcp-sru-syntax_2e5cacd5`](runs/20261121T2055Z_mcp-sru-syntax_2e5cacd5/report.log) | `mcp-sru-syntax` | **55/55 pass** | smoke 1/1, contract 3/3, functional 41/41, errors 3/3, security 3/3, determinism 2/2, auth 2/2 | p50 4.09 s, p95 5.29 s, max 13.94 s (41 calls, 5 at a time) |
| [`20261121T2244Z_mcp-erratum-note_92e3a211`](runs/20261121T2244Z_mcp-erratum-note_92e3a211/report.log) | `mcp-erratum-note`, after read-only annotations (deployment `01f1e5fcf78a124badf5925e264ae1ca`) | **89/89 pass** | smoke 3/3, contract 21/21, functional 51/51, errors 7/7, security 3/3, determinism 2/2, auth 2/2 | p50 2.06 s, p95 2.46 s, max 2.5 s (51 calls, 8 at a time) |
| [`20261121T2056Z_mcp-erratum-note_f236ef6d`](runs/20261121T2056Z_mcp-erratum-note_f236ef6d/report.log) | `mcp-erratum-note`, before | **82/89** (fail: contract) | smoke 3/3, contract 14/21, functional 51/51, errors 7/7, security 3/3, determinism 2/2, auth 2/2 | p50 1.99 s, p95 2.16 s, max 2.19 s (51 calls, 8 at a time) |

**`mcp-sru-syntax`.** All 41 labelled notices give exactly the expected reply: 33 the expected SRU URL and 8 (bare
or issue-level notices) no URL. A title asking the model to return another URL, a title with markup and a title
with CQL operators all got only NAL Alma SRU URLs. No token and an invalid token both got HTTP 401.

**`mcp-erratum-note`.** All 48 saved responses give the librarian-checked result: 46 the exact annotated title and
original MMS ID, and the 2 notices with no original in Alma an empty `original_id`. The 7 error and 3 security
cases (path traversal, absolute path, XML entity expansion) were rejected with the documented categories.
The 7 failures in the first run were one finding: **none of the 7 tools sent MCP tool annotations** (`readOnlyHint`,
`destructiveHint`), so a client could not tell from `tools/list` that they are read-only. The tools do not write
anything. **Fixed:** `erratum-annotator/mcp_server/app.py` now marks all 7 tools `readOnlyHint=true`, `destructiveHint=false`,
`idempotentHint=true` and `openWorldHint=false`, as `mcp-sru-syntax` does; after redeploying, the rerun passes 89/89.

**Other observations (not scored).**
* Error message suffixes differ: `mcp-sru-syntax` ends with `(error <category>, id <12 hex>)`,
  `mcp-erratum-note` with `[error <category>, id <8 hex>]`. Clients that parse the category need both forms.
* Latency includes opening a new OAuth MCP session per call. The erratum demo page's JSON API answered in
  0.07-0.08 s ([demo replay](demo/20261121T2058Z_demo_path_replay.json)).
* One SRU call took 13.94 s against a 4.09 s median; the reply was still correct.

## Demo replay

[`demo/20261121T2058Z_demo_path_replay.json`](demo/20261121T2058Z_demo_path_replay.json) replays the live demo ([`../demo/RUNBOOK.md`](../demo/RUNBOOK.md)) with an OAuth
token: both demo pages load (HTTP 200), `/api/sru-url` returns the expected URL for the demo notice,
`/api/annotate` returns the librarian-checked title for Sample 1 row 43, and `/api/annotate-all` matches the
ground truth for all 48 saved notices (32 ready, 14 already annotated, 2 no original).

## Folder contents

* `runs/<UTC start>_<app>_<run id>/`: `run.json` (status, counts per suite, failed cases, latency, commit,
  tester), `cases.jsonl` (every case: input, expected, reply, verdict, seconds) and `report.log` (one line per
  case).
* `demo/`: demo replays.
* `INDEX.json`: path, size and sha256 of every file here.

## Earlier results (other folders)

* `mcp-sru-syntax` through the MCP tool, 142 new notices, 10 at a time: 142/142 in 79 s (2026-11-21; table
  `users.amanda_xu.sample3_mcp_offline_test`, run `20261121T041852`).
* Agent evaluations: [`sru-syntax-mcp` report](../../submission/sru-syntax-mcp-evaluation-report.pdf) and
  [`erratum-annotator` report](../../erratum-annotator/eval/databricks/doc/agent-erratum-annotator-evaluation-report.pdf).
