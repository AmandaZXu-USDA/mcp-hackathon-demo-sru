# Evaluation framework

How to check that the two MCP apps (`mcp-sru-syntax`, `mcp-erratum-note`) and their two agents
(`agent-sru-syntax`, `agent-erratum-annotator`) work, what has been measured, and what is still open. This is a
design document. Measured results are in [`results/`](results/README.md); every number below points at a file
there or at an existing evaluation report.

## Status labels

| Label | Meaning |
| --- | --- |
| **done** | Run; evidence is committed and can be reproduced. |
| **partial** | Some evidence exists, but it does not answer the whole question. |
| **design-only** | Protocol written; not run. |
| **blocked** | Ready to run, waiting on access outside the project's control. |

## What each output needs

| Output | Produced by | Question | Ground truth |
| --- | --- | --- | --- |
| SRU search URL | `build_sru_search_url` (`mcp-sru-syntax`), UC function `build_sru_url` | Is the URL exactly the one the librarians' rules give, and is there no URL when the notice names no single article? | 41 labelled notices (`sru-eval-0.csv`, expected title per notice); the URL rule reproduces `users.amanda_xu.build_sru_url` on all 41 |
| Original record and erratum note | `process_sru_file` / `process_sru_response` (`mcp-erratum-note`), UC function `process_sru_response` | Is the right original MMS ID picked, and is the annotated title exactly the librarian-checked one? | 48 saved SRU responses with the librarian-checked Sample 1 spreadsheet (`Correction-Sample1-53-annotated.csv`) |
| Agent reply | `agent-sru-syntax`, `agent-erratum-annotator` | Does the agent call the tool, copy its answer exactly and never invent a URL, MMS ID or note? | Same datasets, scored in MLflow |
| Librarian task | Demo pages, Genie Code | Can a librarian finish the task without help? | Task success and time, observed (see [`usability/`](usability/PROTOCOL.md)) |

## Summary

| # | Area | Item | Status | Evidence |
| --- | --- | --- | --- | --- |
| 1.1 | MCP servers | Inspector Gadget suite on both live apps: smoke, contract, functional, errors, security, auth, determinism, latency | done (2026-11-21) | [`results/runs/`](results/README.md) |
| 1.2 | MCP servers | `mcp-sru-syntax` functional accuracy on 41 labelled notices | done: 41/41 | `20261121T2055Z_mcp-sru-syntax_2e5cacd5` |
| 1.3 | MCP servers | `mcp-erratum-note` functional accuracy on 48 saved responses | done: 48/48 (46 annotated titles exact, 2 correctly with no original) | `20261121T2056Z_mcp-erratum-note_f236ef6d` |
| 1.4 | MCP servers | Tool contract (descriptions, schemas, read-only annotations) | done: `mcp-sru-syntax` 3/3; `mcp-erratum-note` 21/21 after read-only annotations were added (14/21 before) | `20261121T2244Z_mcp-erratum-note_92e3a211`, suite `contract` |
| 1.5 | MCP servers | Error categories and security probes (prompt injection, CQL operators, path traversal, XML entities) | done: 6/6 and 10/10 | both runs, suites `errors`, `security` |
| 1.6 | MCP servers | Live throughput: 142 new notices through the MCP tool, 10 at a time | done: 142/142 in 79 s (2026-11-21) | table `users.amanda_xu.sample3_mcp_offline_test`, run `20261121T041852` |
| 1.7 | MCP servers | Load beyond 10 concurrent callers, and behaviour during an outage | design-only | 3.3 below |
| 2.1 | Agents | `agent-sru-syntax` offline evaluation (MLflow, 41 notices) | done | [`sru-syntax-mcp` evaluation report](../submission/sru-syntax-mcp-evaluation-report.pdf) |
| 2.2 | Agents | `agent-erratum-annotator` offline evaluation (MLflow, 53 notices) | done | [`erratum-annotator/eval/databricks/`](../erratum-annotator/eval/databricks/README.md) |
| 2.3 | Agents | Agent behaviour on bad input (cut-off XML, 8-digit MMS ID) | partial: checked by hand; the MMS ID rule held in 2 of 4 runs | [`erratum-annotator/agent/README.md`](../erratum-annotator/agent/README.md#error-handling) |
| 2.4 | Agents | An agent whose only tool is `mcp-sru-syntax` (Phoenix, mcp-eval skill): 10 gold and 4 out-of-scope questions, system prompts v1 and v2 | done (2026-11-22): gold 10/10 on all three evaluators with both prompts; out of scope 1/4 (v1), 3/4 (v2) | [`phoenix/`](phoenix/README.md); [`sru-syntax-mcp` evaluation report](../submission/sru-syntax-mcp-evaluation-report.pdf) section 9 |
| 3.1 | Demo | Replay of the demo path (both pages and their JSON APIs) as an external client | done: 6/6 steps HTTP 200; demo notice and all 48 saved notices match ground truth | [`results/demo/20261121T2058Z_demo_path_replay.json`](results/demo/20261121T2058Z_demo_path_replay.json) |
| 3.2 | Demo | Live demo script | done | [`demo/RUNBOOK.md`](demo/RUNBOOK.md) |
| 4.1 | Usability | Expert walkthrough of the librarian tasks (not a usability study) | done (2026-11-21) | [`usability/HEURISTIC_REVIEW_2026-11-21.md`](usability/HEURISTIC_REVIEW_2026-11-21.md) |
| 4.2 | Usability | Sessions with NAL metadata librarians | design-only | [`usability/PROTOCOL.md`](usability/PROTOCOL.md) |

## 1. MCP servers (Inspector Gadget)

Inspector Gadget is a service principal used as an outside MCP client: it signs in with OAuth machine-to-machine
credentials (kept in the Unity Catalog secret `models.ai/inspector-gadget`), opens a new MCP session per call over
streamable HTTP, and calls the deployed apps exactly as Genie Code or any other client would. The suite is
[`inspector_gadget/ig_mcp_suite.py`](inspector_gadget/README.md).

| Suite | What it checks | Pass rule |
| --- | --- | --- |
| smoke | `tools/list`; for `mcp-erratum-note` also `health` and `list_sru_files` | The expected tools are listed; every ground-truth file is listed |
| contract | Each tool's description, input schema and MCP annotations | Description present; schema is an object whose required fields are declared; `readOnlyHint` true and not destructive |
| functional | Every ground-truth row | SRU: the reply holds exactly the expected URL, or no URL when none is expected. Erratum: same `original_id` and `annotated_title` as the spreadsheet; empty `original_id` when there is no original |
| errors | Empty, too long, cut-off, non-SRU and diagnostic inputs; bad MMS IDs and file names | The tool returns an error with the documented category |
| security | Prompt injection and markup in titles; CQL operators; path traversal; absolute paths; XML entity expansion | Only NAL Alma SRU URLs in a reply; unsafe file names rejected; entities never expanded |
| auth | `tools/list` with no token and with an invalid token | Refused (HTTP 401/403 or a login redirect) |
| determinism | The same request twice | Same reply |
| latency | Every functional call (new session each time, 5-8 in parallel) | Reported, not scored |

**What it does not show.** The SRU ground truth is the librarians' rules, so a perfect score means the tool
follows the rules, not that every rule is right for every notice. The erratum ground truth is 48 responses from
one sample; other publishers' record formats may differ. Calls run at most 8 at a time.

## 2. Agents

Agents are scored with MLflow GenAI evaluation (deterministic scorers first, LLM judges second); see the two
evaluation reports. Agents are not part of the Inspector Gadget suite because their replies are free text.

## 3. Open protocols

### 3.1 Librarian usability sessions (design-only)

See [`usability/PROTOCOL.md`](usability/PROTOCOL.md): 5 librarians, 4 tasks each, measured task success, time,
errors and a System Usability Scale score.

### 3.2 New notices from a later export (design-only)

Draw 100 notices from an Alma export after November 2026, have one librarian label the original title and the
annotated title blind to the tool, then run the Inspector Gadget suite with that file as ground truth. Report
accuracy per extraction rule and per publisher.

### 3.3 Load and outage behaviour (design-only)

Run the SRU functional suite at 10, 25 and 50 concurrent sessions and record p50/p95 latency and error
categories. Then stop the SQL warehouse and confirm the tool falls back to the Supervisor Agent and still
answers, and stop the volume grant to confirm `permission_denied` is returned.
