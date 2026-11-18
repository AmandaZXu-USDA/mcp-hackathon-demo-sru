---
name: agent-sru-syntax
description: 'Use, operate, or change the agent-sru-syntax system that turns erratum/correction notice titles ("Correction: ...", "Corrigendum to ...", "Erratum: ...") into NAL Alma production SRU searchRetrieve URLs for the original article. Read this skill when calling the sru-syntax-mcp MCP tool or agent endpoint, building SRU URLs in SQL, deploying the sru-syntax-mcp app, checking its traces or latency, or editing the title-extraction rules.'
---

# agent-sru-syntax

## Overview

NAL staff receive erratum and correction notices and need the catalog record of the article being corrected.
This system extracts the original article title from the notice title and returns an Alma SRU query URL:

```
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22<title>%22%20and%20alma.local_field_912%3D%22Article%22
```

The exact extraction and encoding rules are in [references/sru_url_rules.md](./references/sru_url_rules.md).

## Components

| Component | Where | What it does |
| --- | --- | --- |
| UC function `users.amanda_xu.build_sru_url(correction_title)` | Unity Catalog | Deterministic Python rules: title extraction + SRU URL. Source of truth for the rules. |
| Supervisor Agent `agent-sru-syntax` | Serving endpoint `mas-c8629507-endpoint` (Responses API) | Agent Bricks Supervisor Agent that produces the SRU URL for a title. |
| MCP server `sru-syntax-mcp` | Databricks App, `/mcp` (streamable HTTP, stateless JSON) | One tool, `build_sru_search_url(correction_title)`, that calls the Supervisor Agent. Code: `mcp_server/app.py`. |
| SRU syntax agent | Same app, `POST /invocations`, `POST /responses` | OpenAI Agents SDK agent (`mcp_server/agent.py`) that calls the MCP tool over localhost and answers in Responses format. |
| Bundle | `sru-syntax-mcp/databricks.yml` | Declarative Automation Bundle `sru_syntax`, target `dev`. |
| Traces | Experiment `/Users/amanda.xu@usda.gov/sru-syntax-agent-uc-experiment` (ID `131270370350843`) | MLflow traces stored in `users.amanda_xu.sru_syntax_agent_otel_*`. |

The agent and the MCP server share one app because the workspace is at its 100-app limit. The standalone
`agent/` folder is an unused two-app version.

## Choose the interface

* **Many titles (batch, SQL, pipelines):** call the UC function directly. It is deterministic and fast, and it does not
  depend on the Supervisor Agent (so it avoids the agent's occasional empty replies).

  ```sql
  SELECT title, users.amanda_xu.build_sru_url(title) AS sru_url FROM <table>
  ```

* **An MCP client or coding agent:** connect to `https://sru-syntax-mcp-7474654188777746.aws.databricksapps.com/mcp`
  and call `build_sru_search_url` with the full notice title, unchanged. Callers need `CAN USE` on the app and an
  OAuth token (personal access tokens are rejected).
* **A chat-style request (one or more titles in prose):** `POST /invocations` with
  `{"input": [{"role": "user", "content": "Correction: <title>"}]}` or `{"input": "<text>"}`. The reply is in
  `output[0].content[0].text`.

## Rules the agent must follow

* Pass the notice title exactly as given. Do not strip the prefix yourself; the rules handle it.
* Call the tool once per title. Never invent or hand-build an SRU URL in the reply.
* A blank result is correct for bare notices (`Correction`) and issue-level notices (`Errata for articles ...`,
  `Corrections to Taxon 72(3)`): there is no single article to find.
* If the tool returns the empty-reply message, fall back to `users.amanda_xu.build_sru_url` for that title.
* Use the **production** base `nal.alma.exlibrisgroup.com`. URLs with `nal-psb` or `maximumRecords=50` come from
  the older sandbox spreadsheet.

## Known behaviour

From a 10-title sample (random_state=42) of `Correction-Sample2-1494-Extracted-Titles-FINAL.xlsx`, 2026-11-18:

* 8 of 10 returned a URL; 7 matched the reference title exactly and 1 differed only by punctuation
  (`Solastalgia Scale (SOS)` vs `Solastalgia Scale SOS`).
* 2 of 10 got an empty Supervisor Agent reply (about 3 seconds of tool time). Use the UC function for these.
* Latency (11 traces): request p50 21.1 s, p90 22.1 s. The `build_sru_search_url` tool (Supervisor Agent) is
  about 80% of it (p50 17.1 s); the two model calls are about 1.6 s and 1.9 s.

When comparing with a reference, compare the decoded `alma.title` term, not the whole URL.

## Operate

Run bundle commands from `sru-syntax-mcp/` (the bundle root):

```bash
databricks bundle validate --strict -t dev
databricks bundle deploy -t dev
databricks bundle run sru_syntax_mcp -t dev      # redeploys and restarts the app
databricks apps logs sru-syntax-mcp              # first step when the app misbehaves
```

* The app's permissions come from app resources in `databricks.yml`: `serving-endpoint` (CAN_QUERY),
  `model-service` `models.ai.gpt-5-6-luna` (EXECUTE), `app-experiment` (CAN_EDIT), and the four trace tables (MODIFY).
* Environment variables are set in `mcp_server/app.yaml` via `valueFrom`, not in `databricks.yml`.
* Latency per step: run the saved SQL query **SRU Agent Latency per Step** (reads
  `users.amanda_xu.sru_syntax_agent_otel_spans`). The two model calls share the span name `Response`; number them
  by start time within each trace.

## Change the rules

1. Edit `users.amanda_xu.build_sru_url` (it is the source of truth) and update
   [references/sru_url_rules.md](./references/sru_url_rules.md) to match.
2. Re-run the rule examples in the reference file and a sample from the spreadsheet; check the rule
   distribution does not shift unexpectedly.
3. If the Supervisor Agent's instructions encode the same rules, update them too, then re-run the 10-title sample
   through `/invocations` and compare.

## Security notes (from the mcp-builder completion gate)

Met:

* No tool accepts a URL; the only argument is `correction_title`. The only outbound destinations are the fixed
  workspace host (serving endpoint, Unity Gateway) and localhost `/mcp`.
* The returned SRU URL is built on a fixed base; quotes and backslashes in titles are neutralised before the CQL term.
* Remote access requires Databricks Apps OAuth and `CAN USE`; the app runs as its own service principal with
  least-privilege resources.
* Titles and agent replies are treated as data; the agent is told never to invent URLs.
* Errors are stable categories with an error id, never upstream bodies, URLs or exception text:
  * Tool (`isError: true`): `timeout`, `unavailable`, `rate_limited`, `permission_denied`, `bad_response`,
    e.g. `The SRU syntax agent is unavailable. Try again later. (error unavailable, id 51443671b919)`.
  * `/invocations`: HTTP 502 with `error agent_failed, id <id>`.
  * Server logs (`databricks apps logs sru-syntax-mcp`) hold only `error_id`, category, HTTP status and exception
    class, so search the logs by the error id a user reports. Redirects from the agent endpoint are not followed.
* The tool has MCP annotations: `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`,
  `openWorldHint: false` (annotations are hints, not access control).

Gaps to fix before calling the server complete:

* There are no automated tests for authorization denial paths or for sensitive data in errors and logs
  (error paths were checked by hand on 2026-11-18 with a missing endpoint and a missing model).
