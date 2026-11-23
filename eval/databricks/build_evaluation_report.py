# Databricks notebook source
# DBTITLE 1,Install PDF libraries
# MAGIC %pip install reportlab pypdf
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Build evaluation report PDF
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

OUTPUT_PATH = '/Workspace/Users/amanda.xu@usda.gov/sru-syntax-mcp-evaluation-report.pdf'
README_URL = 'https://github.com/AmandaZXu-USDA/NAL/blob/add-mcp-servers/sru-syntax-mcp/eval/databricks/README.md'

styles = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=15, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor('#1B3139'))
H2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=12, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor('#1B3139'))
BODY = ParagraphStyle('Body', parent=styles['BodyText'], fontSize=9.5, leading=12.5, spaceAfter=4)
CELL = ParagraphStyle('Cell', parent=BODY, fontSize=8.5, leading=10.5, spaceAfter=0)
CELL_B = ParagraphStyle('CellB', parent=CELL, fontName='Helvetica-Bold', textColor=colors.white)
SMALL = ParagraphStyle('Small', parent=BODY, fontSize=8, leading=10, textColor=colors.HexColor('#555555'))
CODE = ParagraphStyle('Code', parent=CELL, fontName='Courier', fontSize=7.5, leading=9.5)

def p(text, style=BODY):
    return Paragraph(text, style)

def bullets(items):
    return [p('&bull;&nbsp;' + i, BODY) for i in items]

def table(rows, widths, code_cols=()):
    data = [[Paragraph(escape(str(c)), CELL_B) for c in rows[0]]]
    for r in rows[1:]:
        data.append([Paragraph(escape(str(c)), CODE if j in code_cols else CELL) for j, c in enumerate(r)])
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3139')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F5F7')]),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#BBBBBB')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t

SAMPLE_TITLE = 'Correction: Effects of drought stress on maize grain yield and quality'
SAMPLE_URL = ('https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve'
              '&recordSchema=mods&query=alma.title%3D%22Effects%20of%20drought%20stress%20on%20maize%20grain'
              '%20yield%20and%20quality%22%20and%20alma.local_field_912%3D%22Article%22')

story = []

# ---- Title and summary ----
story += [
    p('SRU Syntax MCP Server - Evaluation Report', ParagraphStyle('T', parent=H1, fontSize=19, spaceAfter=4)),
    p('NAL Alma SRU URL builder for erratum/correction notices &nbsp;|&nbsp; Report date: November 18, 2026 (updated November 22, 2026)', SMALL),
    Spacer(1, 8),
    p('This report covers four evaluations, a per-step latency analysis, live testing on November 19, 2026 (section 6), and lessons learned and recommendations (section 7), and re-runs of the offline evaluation and the 142-title MCP test on November 21, 2026 (section 8), and a Phoenix evaluation of an agent that uses the MCP tool on November 22, 2026 (section 9) of the <b>mcp-sru-syntax</b> Databricks App, a custom MCP server '
      '(streamable HTTP at <font face="Courier">/mcp</font>) exposing one tool, '
      '<font face="Courier">build_sru_search_url</font>. The tool sends an erratum/correction notice title to the '
      'agent-sru-syntax Supervisor Agent (serving endpoint <font face="Courier">mas-c8629507-endpoint</font>) and '
      'returns the NAL Alma production SRU searchRetrieve URL for the original article. Since November 21, 2026 the tool '
      'runs the rules function first and asks the Supervisor Agent only if that call fails (section 8).'),
    Spacer(1, 4),
    table([
        ['Evaluation', 'Status', 'Headline result'],
        ['1. Inspector Gadget testing', 'Passed', 'Authenticated as a service principal; 1/1 tools listed and called successfully; correct SRU URL in 13.7 s.'],
        ['2. Offline MLflow evaluation', 'Completed', 'sru_url_match 0.93 (38/41) on the 41-row dataset; 1.00 on the earlier 11-row dataset; safety 1.00 throughout.'],
        ['3. Online evaluation (production monitoring)', 'Configured, stopped', '2 custom LLM-judge scorers registered (ToolCallEfficiency, ToolCallCorrectness) at 0% sample rate, pending admin confirmation of scorer identity and permissions.'],
        ['4. Evaluation run kindly-lamb-651', 'Completed (1 judge error)', 'ToolCallEfficiency LLM judge on 2 agent traces: 1 yes, 1 judge parse error; trace review shows both traces used tools efficiently.'],
        ['5. Agent latency per step', 'Analyzed', '174 requests: those that call the tool take p50 22.5 s (tool about 69% of the time); 35 answered without the tool take p50 2.7 s. 1 error in 176 model calls.'],
        ['6. Live testing (November 19)', 'Passed; retry did not help', 'Page, page API, MCP and agent routes pass as Inspector Gadget. About 18 titles/min at 10 at a time. Every URL the agent returned matched the rules function. The empty-reply retry recovered 0 of 10 titles.'],
        ['7. Lessons learned and recommendations', 'Summary', '20 lessons across access, MCP naming and client, agent, evaluation, performance and engineering; 10 recommendations, starting with an independent, librarian-confirmed ground truth.'],
        ['8. Re-runs (November 21)', 'Completed', 'Function-first tool and databricks-gpt-5-6-luna agent: sru_url_match 1.00 (41/41), correctness 1.00, safety 1.00; median 6.9 s per title on /invocations. 142-title MCP test 142/142 in 79 s (about 108 titles/min).'],
        ['9. Phoenix evaluation (November 22)', 'Completed', 'mcp-eval harness: a LangChain agent whose only tool is the MCP server. 10 gold questions: 10/10 on all three evaluators with both prompts. 4 out-of-scope requests: 1/4 handled correctly with prompt v1, 3/4 with v2.'],
    ], [2.0, 1.1, 4.0]),
    Spacer(1, 6),
    table([
        ['Component', 'Value'],
        ['App', 'mcp-sru-syntax (https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com)'],
        ['MCP endpoint', '/mcp (stateless streamable HTTP, JSON responses)'],
        ['Browser page', 'GET / (one title in, SRU URL out as a link) and its JSON API POST /api/sru-url; added November 19, 2026'],
        ['Tool', 'build_sru_search_url(correction_title: str) -> str (read-only, idempotent)'],
        ['Upstream agent', 'agent-sru-syntax Supervisor Agent, endpoint mas-c8629507-endpoint'],
        ['Rules function', 'users.amanda_xu.build_sru_url (Unity Catalog function)'],
        ['Agent model', 'models.ai.gpt-5-6-luna until November 20, 2026; databricks-gpt-5-6-luna (Databricks-hosted) since November 21'],
        ['Tool path since November 21, 2026', 'Rules function on SQL warehouse 50d2bd4ddf65e0f5 first (about 4 s); Supervisor Agent only if that call fails'],
    ], [1.5, 5.6]),
]

# ---- Section 1: Inspector Gadget ----
story += [
    p('1. Inspector Gadget testing', H1),
    p('<b>Purpose:</b> confirm that an external client, authenticating as a service principal with OAuth M2M, can '
      'reach the OAuth-gated app, discover its tools, and call them end to end.'),
    p('Setup', H2),
    table([
        ['Item', 'Value'],
        ['Client identity', 'Service principal "Inspector Gadget" (f22c554b-c019-4511-8774-079d9891c7d5), OAuth M2M, scope all-apis'],
        ['Credentials', 'Unity Catalog secret models.ai / inspector-gadget (client_id, client_secret, scopes)'],
        ['Client libraries', 'databricks-sdk WorkspaceClient + databricks-mcp DatabricksMCPClient; mcp Client with an httpx2 client for long-running calls'],
        ['Test notebook', '/Shared/how-to-test-apps-mcp/(Clone) nb-apps-mcp-testing-amandaxu'],
        ['Test date', 'November 18, 2026'],
    ], [1.5, 5.6]),
    KeepTogether([p('Results', H2),
    table([
        ['Test', 'Input', 'Result', 'Status'],
        ['List tools', '-', "['build_sru_search_url']", 'PASS'],
        ['Call build_sru_search_url', SAMPLE_TITLE, SAMPLE_URL, 'PASS'],
        ['Test every tool on the app', 'Sample arguments per tool', '1/1 tools passed; build_sru_search_url returned the correct URL in 13.7 s', 'PASS'],
        ['Cross-check', 'Same title sent directly to mas-c8629507-endpoint as the user', 'Identical SRU URL (about 40 s)', 'PASS'],
    ], [1.4, 1.7, 3.3, 0.7], code_cols=(2,))]),
    Spacer(1, 4),
    p('The returned URL uses the NAL Alma production host, decodes to alma.title="Effects of drought stress on maize '
      'grain yield and quality" (the "Correction:" prefix correctly stripped), and filters on alma.local_field_912="Article".'),
    KeepTogether([p('Issues found and resolved during testing', H2),
    table([
        ['Symptom', 'Root cause', 'Resolution'],
        ['ValueError: oauth-m2m Invalid URL \'None\' (host metadata fetch failed)',
         'WorkspaceClient host was set to the app URL; OAuth M2M needs the workspace URL to find its token endpoint.',
         'Host set to the workspace URL (spark.databricks.workspaceUrl).'],
        ['ExceptionGroup / UnsupportedProtocol; app returned HTTP 401',
         'Inspector Gadget service principal had no permission on the app.',
         'Granted CAN USE on mcp-sru-syntax to the service principal.'],
        ['Tool error bad_response (HTTP 200, non-JSON from the agent endpoint)',
         "The app's own service principal (1ba82f86-...) could query the endpoint but had no access to the UC function the Supervisor Agent calls.",
         'Granted EXECUTE on users.amanda_xu.build_sru_url and USE SCHEMA on users.amanda_xu.'],
        ['ReadTimeout on call_tool',
         'DatabricksMCPClient uses the httpx default 5 s timeout; the tool takes 15-90 s.',
         'Session opened directly with httpx2.AsyncClient(timeout=300) and read_timeout_seconds=300.'],
    ], [2.0, 2.7, 2.4])]),
]

# ---- Section 2: Offline evaluation ----
story += [
    PageBreak(),
    p('2. Databricks offline MLflow evaluation: mcp-sru-syntax', H1),
    p('<b>Purpose:</b> verify that the SRU syntax agent produces correct NAL Alma production SRU URLs from '
      'erratum/correction notice titles. A labelled dataset is scored by a deterministic URL match plus four LLM '
      'judges, catching rule regressions, empty Supervisor Agent replies, and instruction-following failures before '
      'deploying changes.'),
    p('Method', H2),
    *bullets([
        '<font face="Courier">mlflow.genai.evaluate</font> runs over the dataset with a <font face="Courier">predict_fn</font> '
        'that calls the SRU syntax agent while it uses the deployed mcp-sru-syntax MCP server.',
        'The app is OAuth-gated, so the eval reaches it as a service principal using OAuth M2M with CAN USE on the app '
        '(personal access tokens are rejected).',
        'Traces and assessments are stored in the Unity Catalog-backed experiment 131270370350843; a SQL warehouse ID '
        'is set for UC trace reads, and no trace destination override is used.',
        'A run takes about 7 minutes (41 rows, 3 at a time; about 20 s per title).',
    ]),
    p('Dataset', H2),
    p('<font face="Courier">datasets/sru-eval-0.csv</font>: 41 erratum titles from '
      'Correction-Sample2-1494-Extracted-Titles-FINAL.xlsx covering every extraction rule (2 to 5 rows each), '
      'including 4 bare notices, 4 issue-level notices, and titles that previously received an empty Supervisor Agent '
      'reply. <font face="Courier">expected_title</font> comes from users.amanda_xu.build_sru_url (blank when no URL is expected).'),
    p('Scorers', H2),
    table([
        ['Scorer', 'Kind', 'Passes when'],
        ['sru_url_match', 'Deterministic (primary)', 'The reply has an SRU URL on the production base whose decoded alma.title equals expected_title; or, when expected_title is blank, the reply has no SRU URL.'],
        ['correctness', 'LLM judge', "The reply contains the row's expected_facts."],
        ['relevant_to_notice', 'LLM guideline', 'The reply gives the SRU URL for the original article, or explains there is no single article.'],
        ['no_invented_urls', 'LLM guideline', 'Only tool-produced URLs, no unrelated commentary, and errors are relayed rather than papered over.'],
        ['safety', 'LLM judge', 'No harmful content.'],
    ], [1.4, 1.4, 4.3]),
    KeepTogether([p('Results: 11-row dataset (local server, before and after handling bare notices)', H2),
    table([
        ['Metric', 'Before', 'After (run 1)', 'After (run 2)'],
        ['sru_url_match', '1.00', '1.00', '1.00'],
        ['correctness', '0.91', '1.00', '1.00'],
        ['relevant_to_notice', '0.91', '1.00', '0.91'],
        ['no_invented_urls', '0.82', '0.91', '0.91'],
        ['safety', '1.00', '1.00', '1.00'],
    ], [2.2, 1.2, 1.2, 1.2])]),
    Spacer(1, 4),
    *bullets([
        'Before the change, the bare "Correction" row failed because the agent asked for the full title; it now replies that the notice names no article, without calling the tool.',
        'The remaining no_invented_urls failure is the issue-level row: the judge counts the explanation of why there is no URL as "unrelated commentary" (guideline wording, not an agent error).',
    ]),
    KeepTogether([p('Results: 41-row dataset (before and after answering issue-level notices directly)', H2),
    table([
        ['Metric', 'Before', 'After'],
        ['sru_url_match', '0.93 (38/41)', '0.93 (38/41)'],
        ['correctness', '0.93', '0.90'],
        ['no_invented_urls', '0.93', '0.93'],
        ['relevant_to_notice', '0.83', '0.85'],
        ['safety', '1.00', '1.00'],
    ], [2.2, 1.5, 1.5])]),
    p('Findings', H2),
    *bullets([
        '<b>Empty Supervisor Agent replies (agent error):</b> 3 titles got no URL ("Overexpression of FBR41 ...", '
        '"Structure-Function Parameters ...", "Homologous promoter derived ..."). These are the only sru_url_match failures.',
        '<b>Issue-level notices without notice wording (agent error, fixed):</b> for "Taxon 61(6)" and "Errata to taxon 59(5)" the '
        'agent asked a clarifying question. After the instruction change, all 4 issue-level rows (and 9 more in the '
        'spreadsheet) get a direct "no SRU URL" answer in 2 to 6 seconds.',
        '<b>Judge strictness:</b> remaining LLM-judge failures on issue-level and Data Papers rows are judge false negatives; the replies are correct.',
        '<b>Judge false negatives:</b> relevant_to_notice failed two correct URL answers for title-only notices '
        '("AAFP and ISFM Guidelines ...", "p21-Activated Kinase 1 ..."), apparently because the request has no notice wording.',
    ]),
]

# ---- Section 3: Online evaluation ----
story += [
    PageBreak(),
    p('3. Online evaluation (production monitoring)', H1),
    p('<b>Purpose:</b> continuously monitor live agent traces for tool-call efficiency and correctness as the agent '
      'handles real correction titles in production. Two custom LLM judges score each sampled trace once started, '
      'catching regressions in tool usage and URL output quality without running a separate eval script.'),
    p('Registered scorers (MLflow experiment 1096079759943475)', H2),
    table([
        ['Scorer', 'Type', 'What it checks', 'Sample rate'],
        ['ToolCallEfficiency', 'Custom (LLM judge)', 'Whether the agent used tools efficiently: no redundant calls, repeated parameters, or calls that should have been consolidated. Returns yes or no.', '0.0% (stopped)'],
        ['ToolCallCorrectness', 'Custom (LLM judge)', 'Whether the tool call produced a correct SRU URL for the given correction title.', '0.0% (stopped)'],
    ], [1.4, 1.2, 3.4, 1.1]),
    Spacer(1, 4),
    p('Both monitoring jobs are currently <b>turned off</b>. They are started with '
      '<font face="Courier">get_scorer(name=...).start(sampling_config=ScorerSamplingConfig(sample_rate=0.1))</font> '
      'and stopped with <font face="Courier">.stop()</font>.'),
    p('Authentication requirements', H2),
    p('Online scorers are LLM judges that call a Unity Gateway model service (for example models.ai.gpt-5-6-luna) for '
      'each trace. The identity they run as needs EXECUTE on the model service plus USE CATALOG and USE SCHEMA on its '
      'parent catalog and schema. Open questions for the workspace admin:'),
    *bullets([
        'What identity do scheduled scorers run as (experiment owner, system service principal, or a dedicated service principal)?',
        'Does that identity have EXECUTE on the model service, and USE CATALOG / USE SCHEMA on its catalog and schema?',
        'Are workspace-level settings required to allow scheduled scorers to call Unity Gateway model services?',
        'Can the admin start one scorer at a low sample rate (0.1) and confirm new traces get scored?',
    ]),
    KeepTogether([p('Online vs offline evaluation', H2),
    table([
        ['Aspect', 'Offline evaluation', 'Online evaluation (production monitoring)'],
        ['How it runs', 'mlflow.genai.evaluate() in a notebook with a predict_fn that calls the agent', 'Scheduled scorers automatically score traces as they are logged to the experiment'],
        ['Scorers', 'sru_url_match, correctness, relevant_to_notice, no_invented_urls, safety (5)', 'ToolCallEfficiency, ToolCallCorrectness (2 custom)'],
        ['Dataset', '41 labelled notices in datasets/sru-eval-0.csv', 'No dataset; scores live production traces'],
        ['Authentication', 'Service principal with OAuth M2M and CAN USE on the app', "Depends on the scorer's identity (see admin questions)"],
        ['When it runs', 'On demand', 'Continuously when started (sample rate > 0)'],
        ['Cost', 'About 7 minutes per run, 41 traces, 5 scorers', 'Per-trace LLM judge calls at the configured sample rate'],
    ], [1.3, 2.9, 2.9])]),
]

# ---- Section 4: Evaluation run kindly-lamb-651 ----
story += [
    PageBreak(),
    p('4. Evaluation run kindly-lamb-651 (mas-c8629507-dev-experiment)', H1),
    p('<b>Purpose:</b> one-off <font face="Courier">mlflow.genai.evaluate</font> run that applied the '
      'ToolCallEfficiency custom LLM judge (the same scorer registered for online monitoring) to existing Supervisor '
      'Agent traces in experiment /Users/amanda.xu@usda.gov/mas-c8629507-dev-experiment (ID 1096079759943475).'),
    KeepTogether([p('Run details', H2),
    table([
        ['Field', 'Value'],
        ['Run name', 'kindly-lamb-651'],
        ['Run ID', 'e2a843567faa4877ac5e7f71c1e2e662'],
        ['Type', 'genai_evaluate'],
        ['Started', '2026-11-18 07:41 UTC'],
        ['Duration', '115.6 s'],
        ['User', 'amanda.xu@usda.gov'],
        ['Scorer', 'ToolCallEfficiency (LLM judge, source databricks)'],
        ['Traces scored', '2'],
        ['Run-level metrics', 'None logged (results are stored as assessments on the traces)'],
    ], [1.5, 5.6])]),
    KeepTogether([p('Per-trace results', H2),
    table([
        ['Trace', 'tr-6b8343e30cfa92235908fb2aae1a313a'],
        ['Correction notice', 'Correction of "Increasing Incidence of Spotted Fever Group Rickettsioses in the United States, 2010-2018" (Vector-Borne and Zoonotic Diseases, 2022)'],
        ['Agent result', 'Correct SRU URL; 14.7 s; 10,553 tokens'],
        ['Judge verdict', 'yes - single retriever call and single build_sru_url call, no redundancy'],
        ['Trace review', 'Confirmed: 1 retriever span, 1 tool span, 2 LLM calls.'],
    ], [1.5, 5.6])]),
    Spacer(1, 6),
    KeepTogether([table([
        ['Trace', 'tr-49f67341cc640c67a33da696d5cecdd0'],
        ['Correction notice', 'Correction of "Increasing Incidence of Anaplasmosis in the United States, 2012 Through 2016" (Vector-Borne and Zoonotic Diseases, 2020)'],
        ['Agent result', 'Correct SRU URL; 13.8 s; 10,389 tokens'],
        ['Judge verdict', 'Error: "Invalid JSON response from Databricks judge" (the judge wrapped its JSON in a markdown code block). Its unparsed verdict was "no", claiming build_sru_url was called twice with the same input'],
        ['Trace review', 'Not supported: the trace has 17 spans with exactly 1 build_sru_url tool span (3.9 s), 1 retriever span and 2 LLM calls. The agent used tools efficiently.'],
    ], [1.5, 5.6])]),
    p('Findings', H2),
    *bullets([
        'Both traces returned correct SRU URLs with one tool call each; on the trace evidence 2/2 were efficient.',
        'The judge produced 1 valid assessment (yes) and 1 parse error; the error\'s unparsed "no" verdict described a '
        'duplicate tool call that does not exist in the trace, so it should not be counted as a failure.',
        'The sample is only 2 traces, so the run is a smoke test of the scorer, not a measure of agent efficiency '
        'across the experiment\'s traces.',
        'Only ToolCallEfficiency ran; ToolCallCorrectness and any token-efficiency scorer were not part of this run. '
        'Token usage was about 10.4k-10.6k tokens per trace (two LLM calls of about 5k input tokens each).',
    ]),
]

# ---- Section 5: Agent latency per step ----
story += [
    PageBreak(),
    p('5. Agent latency per step (SRU Agent Latency per Step query)', H1),
    p('<b>Purpose:</b> show where time goes in one SRU syntax agent request, using the OpenTelemetry spans the agent '
      'logs to Unity Catalog (<font face="Courier">users.amanda_xu.sru_syntax_agent_otel_spans</font>).'),
    p('How the metrics are computed', H2),
    table([
        ['Column', 'Meaning'],
        ['step', 'Stage of a request: sru_syntax_agent_run (whole request), preprocessing (input handling), model call #1 (the model reads the title and decides to call the tool), build_sru_search_url (MCP tool call, which waits on the Supervisor Agent), model call #2 (the model writes the final answer from the tool result). Model calls share the span name "Response" and are numbered by start order within each trace.'],
        ['n_spans / n_traces', 'Number of spans for the step and number of distinct requests (traces) they come from. Equal values mean each step ran exactly once per request.'],
        ['avg_s', 'Mean duration in seconds (span end time minus start time).'],
        ['p50_s', 'Median: half of the requests were faster than this.'],
        ['p90_s', '90th percentile: 9 in 10 requests were at or below this; a measure of the slow tail.'],
        ['min_s / max_s', 'Fastest and slowest observed duration.'],
        ['n_errors', 'Spans whose status is not STATUS_CODE_OK.'],
    ], [1.5, 5.6]),
    KeepTogether([p('Workbook snapshot: SRU_Agent_Latency_per_Step.xlsx (11 traces)', H2),
    table([
        ['Step', 'Spans', 'Traces', 'Avg (s)', 'p50 (s)', 'p90 (s)', 'Min (s)', 'Max (s)', 'Errors'],
        ['sru_syntax_agent_run', '11', '11', '18.62', '21.10', '22.12', '6.19', '23.35', '0'],
        ['preprocessing', '11', '11', '0.00', '0.00', '0.00', '0.00', '0.00', '0'],
        ['model call #1', '11', '11', '1.57', '1.58', '1.75', '1.29', '1.97', '0'],
        ['build_sru_search_url', '11', '11', '15.06', '17.10', '18.41', '3.11', '19.71', '0'],
        ['model call #2', '11', '11', '1.85', '1.89', '2.05', '1.36', '2.20', '0'],
    ], [1.7, 0.55, 0.6, 0.7, 0.7, 0.7, 0.7, 0.7, 0.55])]),
    Spacer(1, 4),
    p('In the snapshot every request called the tool once. build_sru_search_url took 15.06 of 18.62 s on average '
      '(about 81%); the two model calls added about 3.4 s, and there were no errors.'),
    KeepTogether([p('Current data: same query re-run on November 18, 2026 (174 requests, 04:14-06:36 UTC)', H2),
    table([
        ['Step', 'Spans', 'Traces', 'Avg (s)', 'p50 (s)', 'p90 (s)', 'Min (s)', 'Max (s)', 'Errors'],
        ['sru_syntax_agent_run', '174', '174', '18.84', '21.90', '26.61', '1.34', '53.77', '0'],
        ['preprocessing', '176', '176', '0.00', '0.00', '0.00', '0.00', '0.01', '0'],
        ['model call #1', '176', '176', '1.93', '2.00', '2.41', '0.20', '3.62', '1'],
        ['build_sru_search_url', '140', '140', '15.56', '15.48', '18.77', '0.09', '43.62', '0'],
        ['model call #2', '140', '140', '2.16', '2.20', '2.61', '1.21', '3.62', '0'],
    ], [1.7, 0.55, 0.6, 0.7, 0.7, 0.7, 0.7, 0.7, 0.55])]),
    KeepTogether([p('Current data split by whether the tool was called', H2),
    table([
        ['Requests', 'Count', 'Request avg (s)', 'Request p50 (s)', 'Request p90 (s)', 'Tool avg (s)', 'Tool share of time'],
        ['Tool called', '140 (139 with a request span)', '22.74', '22.51', '27.17', '15.56', '68.9%'],
        ['No tool call', '35', '3.35', '2.68', '5.47', '-', '-'],
    ], [1.1, 1.5, 0.9, 0.9, 0.9, 0.8, 1.0])]),
    PageBreak(),
    p('Findings', H2),
    *bullets([
        '<b>The workbook is an early snapshot.</b> Its 11 traces are a small subset of the 174 requests now in the spans '
        'table, so its figures (for example the 81% tool share) are superseded by the current data below.',
        '<b>The tool call dominates latency.</b> In the 140 requests that call build_sru_search_url, the tool averages '
        '15.56 s of a 22.74 s request (about 69%); the two model calls add about 4.1 s and preprocessing is negligible.',
        '<b>About 3 s per tool request is not covered by any measured step.</b> 22.74 s minus the tool and both model '
        'calls leaves about 3.1 s, likely time between spans such as MCP session setup. It is not attributed to a step '
        'by this query.',
        '<b>Requests without a tool call are fast.</b> 35 of 174 requests (20%) were answered without calling the tool, '
        'in a p50 of 2.7 s. This is consistent with the agent answering bare and issue-level notices directly (section 2).',
        '<b>Tail latency:</b> p90 is 26.6 s for all requests, but the slowest request took 53.8 s, with a 43.6 s tool call, '
        'so the Supervisor Agent occasionally runs about 3 times longer than usual.',
        '<b>Model calls are fast and stable</b> (p50 2.0-2.2 s, p90 under 2.7 s), so tuning or replacing the agent model '
        'would save little time.',
        '<b>Reliability:</b> 1 error in 176 first model calls (0.6%); no errors in the tool or the second model call. '
        'Two traces have no request span, so step counts (176) are slightly higher than request counts (174).',
        '<b>Inside the tool:</b> in the two Supervisor Agent traces reviewed in section 4, the Supervisor took 13.8-14.7 s, '
        'of which the code_safety guardrail check before the tool ran took 4.9-5.3 s and the UC function '
        'build_sru_url itself took 3.9-4.0 s. The guardrail check and the Supervisor\'s model calls, not the URL rules, '
        'account for most of the tool time.',
    ]),
    # ---- Section 6: Live testing on November 19, 2026 ----
    PageBreak(),
    p('6. Live testing on November 19, 2026: browser page, throughput, agent vs rules function, empty-reply retry', H1),
    p('<b>Purpose:</b> re-test the deployed app as the Inspector Gadget service principal after adding a browser page '
      'for librarians and an automatic retry on empty agent replies; measure how many titles per minute each path '
      'handles; and compare the agent path with calling the rules function users.amanda_xu.build_sru_url directly.'),
    p('6.1 Inspector Gadget tests of the deployed app', H2),
    table([
        ['Test', 'Result', 'Time'],
        ['GET / without a token', '302 redirect to the workspace login', '-'],
        ['GET /health', '200 {"status": "ok"}', '-'],
        ['GET / (browser page)', '200; Content-Security-Policy with a per-request nonce', '-'],
        ['POST /api/sru-url, 3 titles', '200; one correct SRU URL each', '55 s (first call), 16 s, 20 s'],
        ['POST /api/sru-url as a plain HTML form post', '415 (refused; JSON required)', '-'],
        ['MCP tools/list', "200; ['build_sru_search_url']", '-'],
        ['MCP tools/call build_sru_search_url', '200; correct SRU URL', '14 s'],
        ['POST /invocations (agent endpoint)', '200; correct SRU URL', '21 s'],
        ['After the retry was deployed: normal title via the page API and the MCP tool', '200; correct SRU URL', '53 s (first call after redeploy), 17 s'],
        ['After the retry was deployed: known empty-reply title via the page API and the MCP tool', '200; empty-reply message after one automatic retry (confirmed in the app logs)', '5 s each'],
        ['New notebook cell "Test the browser page and /api/sru-url"', '4/4 PASS', '55 s (first call)'],
    ], [2.6, 3.0, 1.5]),
    Spacer(1, 4),
    p('The first reply after the app has been idle or redeployed takes 46-55 s; later replies take 14-21 s. '
      'Send one title before a demo.'),
    KeepTogether([p('6.2 Titles per minute', H2),
    table([
        ['How titles were sent', 'Titles', 'At a time', 'Per-title time', 'Titles per minute'],
        ['MCP tool as Inspector Gadget (Sample3 workbook)', '142', '10', 'median 27.0 s, p90 58.2 s, max 70.4 s', 'about 18 at most (run took at least 7.8 min)'],
        ['Supervisor Agent endpoint directly (eval dataset)', '41', '4', 'median 15 s, p90 52 s, max 55 s', '10.6 (231 s in total)'],
        ['MCP tool or page, one at a time (steady state)', '-', '1', '14-21 s; 46-55 s for the first call', 'about 3-4'],
        ['Rules function via the SQL Statement API, one title per call', '41', '1', '3.3-3.6 s steady; 36 s for the first call', 'about 17'],
    ], [2.2, 0.6, 0.7, 2.0, 1.6])]),
    Spacer(1, 4),
    *bullets([
        'Sending more titles at once raises throughput but slows each title: at 10 at a time the median was 27 s, '
        'against 15 s at 4 at a time.',
        'The 142-title run took at least 7.8 minutes (its per-title times add up to 4,706 s across 10 parallel calls). '
        'Its total run time was not recorded, so about 18 titles a minute is an upper bound.',
        'For long lists the librarian quickstart recommends one SQL query with the rules function over the whole list; '
        'that path was not timed here.',
    ]),
    KeepTogether([p('6.3 Agent vs rules function', H2),
    table([
        ['Dataset', 'Agent', 'Rules function'],
        ['41 eval titles (33 with an article, 8 bare or issue-level notices); agent called directly',
         'Same URL as the function on 30/33; 3 empty replies; 0 different URLs; no URL for 8/8 notices',
         '41/41 match expected; empty result for the 8 notices'],
        ['142 Sample3 titles via the MCP tool (run at 04:19 UTC)',
         '130 exact; 7 empty replies; 4 bare notices answered with text and no URL; 1 correct URL with extra text; 0 wrong URLs',
         '142/142 match expected_url'],
    ], [2.4, 2.7, 2.0])]),
    Spacer(1, 4),
    *bullets([
        '<b>Caveat:</b> expected_title and expected_url were generated by the rules function, so its 100% shows only '
        'that it has not changed. The useful result is agreement: every URL the agent returned was the function\'s URL.',
        '<b>Every agent miss was an empty reply.</b> Empty replies arrive fast (median 3.2 s in the 142-title run), so '
        'they are not timeouts.',
        '<b>The function was timed through the SQL Statement API, not through MCP.</b> The MCP tool always calls the '
        'agent; no MCP tool calls the function directly.',
        '<b>Decision:</b> the agent-only MCP path is kept for the demo. Calling the function first would have been about '
        '4 times faster per title (3.5 s vs 15 s median) with the same URLs.',
        '<b>Agent replies to no-URL notices vary.</b> Bare notices get a request for the full title. "Taxon 61(6)" got '
        '"Let me search for correction or erratum notices from this journal issue" with no search done, so the '
        'section 2 fix for issue-level notices does not hold on every run.',
    ]),
    KeepTogether([p('6.4 Empty-reply retry', H2),
    p('When the agent\'s reply is empty, the MCP tool and the browser page now ask it once more. Errors such as '
      'timeouts are not retried, so a slow failure never doubles the wait. Deployed November 19, 2026; also in the '
      'fork\'s src/sru_server code.'),
    table([
        ['Test', 'Result'],
        ['Unit tests, agent stubbed (MCP tool and page API)', 'URL first: 1 call. Empty then URL: 2 calls, URL returned. Whitespace then URL: 2 calls. Empty twice: 2 calls, empty-reply message. Timeout: 1 call, no retry. Fork CI: 50 tests pass.'],
        ['3 empty-reply titles from the 41-row dataset, before deploying', '9/9 extra calls to the agent empty (3 per title, 2-6 s each)'],
        ['Same titles after deploying (one via the page, one via MCP)', 'Retry ran (app logs: retrying=1, then retry_result=empty); empty-reply message in 5 s'],
        ['7 empty-reply titles from the 142-title run, via the deployed MCP tool', '7/7 still empty; 7 retries in the app logs, all empty; 4-9 s each (4 at a time)'],
    ], [2.6, 4.5])]),
    Spacer(1, 4),
    *bullets([
        '<b>The retry recovered none of the 10 titles that got empty replies.</b> For these titles the empty reply is '
        'consistent, not intermittent. The retry was kept at the owner\'s request in case other titles\' empty replies '
        'are intermittent; it adds about 2-3 s per empty reply.',
        '<b>Pattern (not verified):</b> most of the 10 titles are about viruses or antivirals (for example sheeppox virus, '
        'anticoronaviral therapies, anti-viral mushroom extracts) or plant disease and resistance (fungicides, a '
        'resistance locus, a mycotoxin), but not all (for example "Structure-Function Parameters Over Different Surface '
        'Footprints in Coastal Zones"). A Supervisor Agent guardrail is one possibility; their traces have not been reviewed.',
        '<b>Workaround:</b> the rules function users.amanda_xu.build_sru_url returns the expected URL for all 10.',
    ]),
    # ---- Section 7: Lessons learned and recommendations ----
    PageBreak(),
    p('7. Lessons learned and recommendations', H1),
    p('<b>Purpose:</b> collect what the testing in sections 1-6 taught about building, securing, evaluating and running '
      'this MCP server, and turn it into recommendations. The evidence column points to the section with the data.'),
    p('7.1 Lessons learned', H2),
    table([
        ['Area', 'Lesson', 'Evidence'],
        ['Access', 'An OAuth-gated app accepts only OAuth tokens. Offline evals and external clients need a service principal using OAuth M2M with CAN USE on the app; personal access tokens and the notebook identity do not work.', 'Sections 1, 2'],
        ['Access', "Two identities need permissions: the caller (CAN USE on the app) and the app's own service principal (CAN QUERY on the agent endpoint, EXECUTE on the UC function, USE SCHEMA). A missing grant on the app side showed up as a misleading bad_response error.", 'Section 1'],
        ['Access', 'The WorkspaceClient host must be the workspace URL, not the app URL; OAuth M2M finds its token endpoint there.', 'Section 1'],
        ['Access', 'Sharing the app needs workspace accounts first: none of the 8 planned NAL stakeholders had one, and adding users needs a workspace admin.', 'Access request, November 19'],
        ['MCP client', 'Client defaults assume fast tools: DatabricksMCPClient times out after 5 s, but this tool takes 15-90 s. Long-running tools need an explicit client timeout (300 s here).', 'Section 1'],
        ['MCP naming', 'A Databricks App that hosts a custom MCP server must be named with the mcp- prefix to be offered as a custom MCP server in the Genie Code connectors. The first name, sru-syntax-mcp, did not appear there; after renaming the app to mcp-sru-syntax it did. Choose the name before the first deploy: the rename meant a new app with a new URL and service principal, so permissions and links in both repos had to be redone.', 'Databricks docs (Host an MCP server on Databricks Apps); app rename'],
        ['Agent', 'The agent never returned a wrong URL. Every miss was an empty reply that arrived in about 3 s, for the same titles each time.', 'Sections 6.3, 6.4'],
        ['Agent', 'A retry only helps intermittent failures. A live check before deploying showed the empty replies were tied to the title (0 of 10 recovered), so the retry adds latency without recovering these titles.', 'Section 6.4'],
        ['Agent', 'Prompt fixes can regress between runs: the issue-level fix from section 2 did not hold for "Taxon 61(6)" on November 19.', 'Sections 2, 6.3'],
        ['Evaluation', 'A deterministic URL check is the reliable primary metric. LLM judges added false negatives on correct replies and one parse error with an unsupported verdict.', 'Sections 2, 4'],
        ['Evaluation', 'Expected values generated by the rules function make the function look perfect by construction; they measure agreement with it, not correctness.', 'Section 6.3'],
        ['Evaluation', 'Each test run needs a run ID, start and end time and concurrency recorded, with results appended rather than overwritten. Without the total time, the 142-title throughput could only be bounded.', 'Section 6.2'],
        ['Evaluation', 'With Unity Catalog-backed traces, setting a trace destination drops assessments, and reading traces needs a SQL warehouse ID.', 'Section 2'],
        ['Performance', "Latency is in the tool, not the model: the tool takes about 69% of a request, and inside it the Supervisor's guardrail check (about 5 s) costs more than the URL rules (about 4 s). Model calls take about 2 s each.", 'Section 5'],
        ['Performance', 'Parallel calls trade latency for throughput: 10 at a time gives about 18 titles a minute at most, but the median title takes 27 s instead of 15 s. In a 20-title batch test, 6 calls timed out.', 'Section 6.2; librarian quickstart'],
        ['Performance', 'The first call after idle or a redeploy takes 46-55 s (36 s for the SQL warehouse after it starts). Demos need a warm-up call.', 'Sections 6.1, 6.2'],
        ['Performance', 'Calling the rules function directly is about 4 times faster per title with the same URLs. The agent path was kept because the project demonstrates MCP.', 'Section 6.3'],
        ['Engineering', 'The deployed server (NAL repo) and the template-structured server (fork) are kept in sync by hand; the browser page HTML now exists in both.', 'Fork commit 39df5c4'],
        ['Engineering', 'Logging error IDs and fixed markers, never titles, kept request content out of the logs and still made the retry verifiable from the app logs.', 'Section 6.4'],
        ['Engineering', 'Renaming the bundle resource key would delete and recreate the live app, so renames need an unbind and re-bind plan.', 'Bundle configuration'],
    ], [1.0, 4.9, 1.2]),
    KeepTogether([p('7.2 Recommendations', H2),
    table([
        ['#', 'Recommendation', 'Based on'],
        ['1', 'Create an independent ground truth: have a librarian confirm the correct Alma record for a sample (for example 50 titles, including the 10 empty-reply titles), and score the agent and the rules function against it.', 'Expected values come from the function (6.3)'],
        ['2', 'Use the MCP tool and the browser page for one title at a time, and the SQL function for lists. The librarian quickstart already says this; keep it prominent.', 'Throughput and batch timeouts (6.2)'],
        ['3', 'Review the Supervisor traces for the 10 empty-reply titles to find the cause (for example a guardrail or a tool error) before changing prompts or adding retries.', 'Empty replies are title-specific (6.4)'],
        ['4', 'Keep the retry but watch retry_result in the app logs; remove it if no retry returns ok over a set period (for example two weeks).', 'Retry recovered 0 of 10 (6.4)'],
        ['5', 'Gate changes on the deterministic sru_url_match score. Treat LLM-judge scores as advisory until the judge output format and guideline wording are fixed.', 'Judge false negatives (2, 4)'],
        ['6', 'Record run ID, start and end time, concurrency and per-title time in every test run, and append results so runs can be compared.', 'Throughput only bounded (6.2)'],
        ['7', 'Send a warm-up title before demos and after each redeploy.', 'Cold start 46-55 s (6.1)'],
        ['8', 'Keep a permissions checklist for both identities, and request workspace accounts for stakeholders well before they need access.', 'Sections 1, 7.1'],
        ['9', 'Make one repo the source of the server code, or add a CI check that the deployed and fork copies match.', 'Two copies of the server (7.1)'],
        ['10', 'Re-run the offline MLflow evaluation and the 142-title MCP test after any change to the Supervisor Agent, its guardrails or the title rules, and compare runs by run ID.', 'Prompt regression (6.3)'],
    ], [0.35, 4.75, 2.0])]),
    # ---- Section 8: Offline evaluation re-run on November 21, 2026 ----
    PageBreak(),
    p('8. Re-runs on November 21, 2026: function-first tool, new agent model', H1),
    p("<b>Purpose:</b> re-score the deployed agent after two changes on November 21, 2026, with the same 41-row "
      "dataset and the same five scorers as section 2, and re-run the 142-title MCP test of section 6.2 (8.4)."),
    p('8.1 What changed', H2),
    table([
        ['Change', 'Detail'],
        ['Tool runs the rules function first', 'build_sru_search_url and the browser page run users.amanda_xu.build_sru_url on SQL warehouse 50d2bd4ddf65e0f5 (title as a bound parameter) and ask the Supervisor Agent only if that call fails. If the function finds no single article, the tool says so at once. Deployment 01f1e558046f12c68fdc6ec13900905b.'],
        ['Agent model', 'Every models.ai model service (gpt-5-6-luna, gpt-5-6-terra, gpt-5-6-sol, gpt-6-astra) returned 401 "API key has expired", so /invocations returned 502. The app agent now uses the Databricks-hosted endpoint databricks-gpt-5-6-luna (AGENT_MODEL in app.yaml). Deployment 01f1e55cbc5d174c85c3e21d90ee1023.'],
        ['Evaluation script', 'agent_eval_deployed.py: predict_fn sends each title to the deployed app (POST /invocations) as Inspector Gadget, so it scores what users get. The section 2 script drives a separate agent copy through models.ai and cannot run while that key is expired.'],
    ], [1.6, 5.5]),
    KeepTogether([p('8.2 Results', H2),
    table([
        ['Metric', 'November 18 (Supervisor Agent tool, models.ai)', 'November 21 (function first, databricks-gpt-5-6-luna)'],
        ['sru_url_match', '0.93 (38/41)', '1.00 (41/41)'],
        ['correctness', '0.90', '1.00'],
        ['relevant_to_notice', '0.85', '0.90'],
        ['no_invented_urls', '0.93', '0.90'],
        ['safety', '1.00', '1.00'],
    ], [1.6, 2.75, 2.75])]),
    Spacer(1, 4),
    p('MLflow run 3bd980fb57ec4b769ba66036c91091ee in experiment 131270370350843; 41 rows, 3 at a time, 212 s in total. '
      'Per title: median 6.9 s, p90 7.3 s, max 7.5 s; the fastest, bare and issue-level notices, about 1 s.'),
    *bullets([
        "<b>All 41 replies are right.</b> The 3 titles that got empty Supervisor Agent replies on November 18 now get the "
        "correct URL, because the tool no longer goes through the Supervisor Agent.",
        "<b>The 7 judge failures are judge strictness, not agent errors</b> (each reply checked by hand). relevant_to_notice "
        "failed the issue-level rows Errata to taxon 59(5) and Taxon 61(6), and two correct URL answers for title-only "
        "notices (AAFP and ISFM Guidelines ..., Monographic Revision of the American Genus Euphoria ...). no_invented_urls "
        "failed the two Data Papers rows (the explanation counted as commentary) and two correct URL answers, because this "
        "script sees only the HTTP reply: the judge cannot see the tool call.",
        "<b>Caveat:</b> expected_title comes from the rules function, and the tool now calls that same function, so "
        "sru_url_match mostly checks that the agent relays the tool's URL unchanged and skips the tool for bare and "
        "issue-level notices. It does not show the rules pick the right Alma record; recommendation 1 (section 7.2) still applies.",
    ]),
    KeepTogether([p('8.3 Live response times after both changes (Inspector Gadget)', H2),
    table([
        ['Route', 'Result', 'Time'],
        ['Browser page API POST /api/sru-url, 3 titles', '200; source function; correct URL, or the no-URL message for a bare "Correction"', '3.9-4.7 s'],
        ['MCP tools/call build_sru_search_url', '200; correct SRU URL', '4.0 s'],
        ['POST /invocations (app agent), 2 titles', '200; correct SRU URL', '6.6 s, 10.1 s'],
        ['POST /invocations, "Corrigendum"', '200; names no article, no URL', '1.1 s'],
    ], [2.6, 3.3, 1.2])]),
    KeepTogether([p('8.4 142-title MCP test re-run', H2),
    table([
        ['Run', 'Correct', 'Empty replies', 'Per title', 'Whole run'],
        ['November 19 (agent path; sections 6.2, 6.3)', '135/142', '7', 'median 27.0 s, max 70.4 s', 'at least 7.8 min (not recorded)'],
        ['November 20, run 20261120T025204 (agent path, with retry)', '135/142', '7', 'median 30.5 s, max 76.1 s', 'not recorded'],
        ['November 21, run 20261121T041852 (function first)', '142/142', '0', 'median 5.2 s, p90 6.1 s, max 9.2 s', '79 s, about 108 titles/min'],
    ], [2.5, 0.75, 0.85, 1.75, 1.25])]),
    Spacer(1, 4),
    p('Same test as section 6.2: the 142 Sample3 titles through the deployed MCP tool build_sru_search_url as '
      'Inspector Gadget, 10 at a time, results appended to users.amanda_xu.sample3_mcp_offline_test. On November 21: '
      '138 EXACT and 4 BARE_NOTICE_NO_URL, 0 errors, and all 142 answered by the rules function (none needed the '
      'agent fallback).'),
    *bullets([
        "<b>All misses of the earlier runs are fixed.</b> The 12 titles that were not exact on November 20 "
        "(7 empty replies, 5 correct URLs with extra text) are all exact now.",
        "<b>Checked a second way:</b> a SQL query extracted the SRU URL from every stored reply and compared it with "
        "users.amanda_xu.build_sru_url recomputed for the title: 138 equal, the 4 bare notices blank in both, 0 different.",
        "<b>The test now records its run.</b> It stores run_seconds, concurrency and answered_by (function or agent), "
        "so titles per minute is measured (recommendation 6). Its classifier compares the URL in the reply, because "
        "function-first replies put a label line before the URL.",
        "<b>Same caveat as 8.2:</b> the expected URLs also come from the rules function, so 142/142 shows the tool "
        "passes the function's URL through unchanged, not that each URL finds the right Alma record.",
    ]),
    # ---- Section 9: Phoenix evaluation on November 22, 2026 ----
    PageBreak(),
    p('9. Phoenix evaluation on November 22, 2026: an agent using the MCP tool', H1),
    p("<b>Purpose:</b> score what an LLM agent does when its only tool is this MCP server: whether it relays the "
      "tool's SRU URL exactly, and whether it stays within scope when asked for something the server cannot do. "
      "Sections 2 and 8 score the Supervisor Agent and the app's /invocations agent; this section scores a separate "
      "client agent through the MCP interface, with every answer traced in Arize Phoenix."),
    p('9.1 Harness', H2),
    table([
        ['Part', 'Detail'],
        ['Harness', 'eval/phoenix/ in both repos, built with the mcp-eval skill (fork commit d2f6b1d; NAL commit c2bccc4, byte-identical). It runs from the fork, where the server is the src/sru_server package launched over stdio; its tool calls users.amanda_xu.build_sru_url (about 4 s).'],
        ['Agent under test', 'LangChain agent on databricks-gpt-5-6-luna, temperature 0, reasoning_effort none. Its only tool is build_sru_search_url from the MCP server.'],
        ['System prompts', 'v1: tool-use rules only (pass the title unchanged, relay the URL unchanged, say No SRU URL when the tool does, report errors). v2: v1 plus a scope paragraph listing what to decline.'],
        ['Evaluators', 'url_exact_match: code, no LLM; the reply must contain exactly the reference URL, or no URL. match_expected_response: LLM judge, correct or incorrect against the reference. check_answer_scope: LLM judge, within or out of scope. Both judges use databricks-claude-sonnet-4-6, a different model family from the agent.'],
        ['Datasets', 'sru-mcp-eval-0: 10 gold questions, one per title-cleaning rule of sru-eval-0 (9 exact SRU URLs; 1 No SRU URL, an issue-level notice). sru-mcp-scope-0: 4 out-of-scope requests (a DOI lookup, running the search and counting records, a subscription recommendation, a MARC 245 field); each answer starts with Decline:.'],
        ['Phoenix', 'Local Phoenix 19.17. Experiments RXhwZXJpbWVudDox (gold, v1), RXhwZXJpbWVudDoy (gold, v2), RXhwZXJpbWVudDoz (scope, v1), RXhwZXJpbWVudDo0 (scope, v2).'],
    ], [1.3, 5.8]),
    KeepTogether([p('9.2 Results', H2),
    table([
        ['Dataset', 'Prompt', 'url_exact_match', 'match_expected_response', 'check_answer_scope'],
        ['sru-mcp-eval-0 (10 gold)', 'v1', '10/10', '10/10', '10/10'],
        ['sru-mcp-eval-0 (10 gold)', 'v2', '10/10', '10/10', '10/10'],
        ['sru-mcp-scope-0 (4 out of scope)', 'v1', 'n/a', '1/4', '1/4'],
        ['sru-mcp-scope-0 (4 out of scope)', 'v2', 'n/a', '3/4', '3/4'],
    ], [1.95, 0.55, 1.2, 1.8, 1.6])]),
    Spacer(1, 4),
    *bullets([
        "<b>Gold questions: no misses.</b> With either prompt the agent relayed the exact URL for all 9 URL questions "
        "and gave no URL for the issue-level notice. The code check and the LLM correctness judge agree on all 20 answers.",
        "<b>Prompt v1 overreaches.</b> Asked to run the search, it made up a record count; asked about the "
        "subscription, it gave advice. The server can do neither.",
        "<b>The two judges disagreed on two v1 answers:</b> the subscription advice (scope: out of scope; correctness: "
        "correct) and a bare SRU URL in reply to the DOI question (scope: within scope; correctness: incorrect). Both "
        "score 1/4, but on different rows, so each judge catches failures the other misses.",
        "<b>Prompt v2 fixes the record count and the advice</b> without changing any gold result. Its one remaining "
        "miss: asked for a MARC 245 field, it returns only the SRU URL without saying it cannot write MARC.",
        "<b>Caveats:</b> the gold URLs come from users.amanda_xu.build_sru_url, which the tool also calls (same caveat "
        "as 8.2); the scope set has only 4 questions and each configuration ran once; the server ran locally over "
        "stdio from the fork, not as the deployed app.",
    ]),
    p('10. Playground demo prompt (November 23, 2026)', H1),
    p('Judges can repeat this check in the Databricks AI Playground. The demo uses one correction notice for both MCP '
      'apps: MMS ID 9917175652607426 (Sample 1, row 42). Its title has a Unicode hyphen (U+2010). This prompt is step 1. '
      'Step 2 (mcp-erratum-note) is in section 11 of the agent-erratum-annotator evaluation report.'),
    table([['Item', 'Value'],
           ['Playground pane', 'agent-sru-syntax (serving endpoint mas-c8629507-endpoint), the Supervisor Agent behind the mcp-sru-syntax tool build_sru_search_url'],
           ['Prompt', 'Build the Alma SRU search URL for correction notice MMS ID 9917175652607426. Correction notice title: Correction to: Climate‐driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture'],
           ['Tool called', 'users__amanda_xu__build_sru_url'],
           ['Reply URL', 'https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22Climate-driven%20insect%20pest%20outbreaks%20and%20food%20security%20risks%3A%20a%20review%20of%20adaptive%20strategies%20for%20resilient%20agriculture%22%20and%20alma.local_field_912%3D%22Article%22'],
           ['Result', 'Matches the ground-truth sru_url in Correction-Sample1-53-annotated.csv character for character; 50 s'],
          ], [1.3, 5.6], code_cols=()),
    Spacer(1, 4),
    *bullets([
        'To call the MCP app itself, add mcp-sru-syntax to a model pane under Tools &gt; MCP servers &gt; Databricks Apps, '
        'then send the same prompt.',
        'The prompts are also in the README files (repository root, submission/, sru-syntax-mcp/ and erratum-annotator/), '
        'under Playground demo: both MCP apps on one correction notice.',
    ]),
    PageBreak(),
    KeepTogether([p('Next steps', H1),
    *bullets([
        'Investigate the empty Supervisor Agent replies (10 titles across both datasets; the only agent misses, and not '
        'fixed by the retry): review their Supervisor traces for a guardrail or tool error (section 6.4). Users no longer see them: the tool calls the rules function first (section 8).',
        'Done November 21, 2026: the 142-title MCP test records its total run time and concurrency, so titles per minute is measured (section 8.4).',
        'Tighten the relevant_to_notice and no_invented_urls guideline wording to remove judge false negatives on title-only and issue-level notices.',
        'Confirm the online scorer identity and permissions with the workspace admin, then start both scorers at a 0.1 sample rate.',
        'Provision the dedicated eval service principal (sp-sru-syntax-eval) so offline runs target the deployed app rather than a local server copy.',
        'Fix the ToolCallEfficiency judge\'s output format (it returned JSON inside a markdown code block, causing a '
        'parse error and an unsupported verdict), then re-run it on a larger trace sample before starting online monitoring.',
        'Response time: done November 21, 2026. The tool now calls users.amanda_xu.build_sru_url first (about 4 s instead of '
        '15-25 s); the Supervisor Agent is only the fallback (section 8).',
        'Phoenix (section 9): add a rule for catalog records and MARC fields to prompt v2 and more out-of-scope '
        'questions to sru-mcp-scope-0, then re-run both datasets after any change to the prompt or the tool.',
    ])]),
    Spacer(1, 10),
    p(f'Sources: Inspector Gadget results from the test notebook runs on November 18, 2026; offline and online '
      f'evaluation details from <link href="{README_URL}" color="blue">sru-syntax-mcp/eval/databricks/README.md</link> '
      f'(branch add-mcp-servers); kindly-lamb-651 results from the run\'s trace assessments and span data in '
      f'experiment 1096079759943475; latency from the SRU Agent Latency per Step query over '
      f'users.amanda_xu.sru_syntax_agent_otel_spans; section 6 from Inspector Gadget runs against the deployed app '
      f'on November 19, 2026, users.amanda_xu.sample3_mcp_offline_test, and the app logs; section 7 from sections 1-6 '
      f'and the deployment and access work on the app; section 8 from MLflow run 3bd980fb57ec4b769ba66036c91091ee '
      f'(experiment 131270370350843), Inspector Gadget calls to the deployed app on November 21, 2026, and runs '
      f'20261120T025204 and 20261121T041852 in users.amanda_xu.sample3_mcp_offline_test; section 9 from the '
      f'eval/phoenix harness (fork commit d2f6b1d) and its Phoenix experiments RXhwZXJpbWVudDox to RXhwZXJpbWVudDo0 '
      f'on November 22, 2026.', SMALL),
]

def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(colors.HexColor('#777777'))
    canvas.drawString(0.7 * inch, 0.45 * inch, 'SRU Syntax MCP Server - Evaluation Report')
    canvas.drawRightString(letter[0] - 0.7 * inch, 0.45 * inch, f'Page {doc.page}')
    canvas.restoreState()

doc = SimpleDocTemplate(OUTPUT_PATH, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                        title='SRU Syntax MCP Server - Evaluation Report', author='Amanda Xu')
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print('Saved', OUTPUT_PATH)

# COMMAND ----------

# DBTITLE 1,Verify report PDF
import os
import re
from pypdf import PdfReader

reader = PdfReader(OUTPUT_PATH)
text = '\n'.join(page.extract_text() for page in reader.pages)
flat = ' '.join(text.split())  # phrases can wrap across lines in extracted text
print(f'{os.path.getsize(OUTPUT_PATH):,} bytes, {len(reader.pages)} pages')
for check in ['1. Inspector Gadget testing', '2. Databricks offline MLflow evaluation', '3. Online evaluation',
              'build_sru_search_url', '0.93 (38/41)', 'ToolCallEfficiency', 'ToolCallCorrectness', '1096079759943475',
              'kindly-lamb-651', 'tr-49f67341cc640c67a33da696d5cecdd0', '4. Evaluation run',
              '5. Agent latency per step', '18.62', '15.06', '68.9%', '53.77', 'about 69%', '2. Databricks offline MLflow evaluation: mcp-sru-syntax',
              'Granted CAN USE on mcp-sru-syntax', 'deployed mcp-sru-syntax MCP server',
              '6. Live testing on November 19, 2026', 'updated November 22, 2026', '6.2 Titles per minute',
              '4,706 s', 'at least 7.8 min', '10.6 (231 s in total)', '30/33', '142/142', '6.4 Empty-reply retry',
              'recovered 0 of 10', '7/7 still empty', 'Test the browser page and /api/sru-url', 'POST /api/sru-url',
              '7. Lessons learned and recommendations', '7.1 Lessons learned', '7.2 Recommendations',
              'independent ground truth', 'lessons learned and recommendations (section 7)', 'warm-up title',
              'named with the mcp- prefix', '20 lessons',
              '8. Re-runs on November 21, 2026', '8.4 142-title MCP test re-run', '20261121T041852', 'about 108 titles/min', '0 different', '1.00 (41/41)', 'databricks-gpt-5-6-luna',
              '3bd980fb57ec4b769ba66036c91091ee', '8.3 Live response times', 'Response time: done November 21, 2026',
              '9. Phoenix evaluation on November 22, 2026', '9. Phoenix evaluation (November 22)', 'Phoenix evaluation of an agent',
              '9.1 Harness', '9.2 Results', 'url_exact_match', 'match_expected_response', 'check_answer_scope',
              'databricks-claude-sonnet-4-6', 'RXhwZXJpbWVudDo0', 'Phoenix (section 9)', 'section 9 from the',
              '10. Playground demo prompt', '9917175652607426', 'mas-c8629507-endpoint']:
    print('OK  ' if check in flat else 'MISSING  ', check)

# The server is named mcp-sru-syntax throughout. The only allowed old-name text is the
# repo folder path sru-syntax-mcp/ (README link), which was not renamed, and the MCP naming lesson
# in section 7.1, which names the first app name on purpose.
left = [flat[max(0, m.start() - 60):m.end() + 40] for m in re.finditer(r'sru-syntax-mcp', flat)
        if not flat[m.end():m.end() + 1] == '/' and not flat[:m.start()].endswith('The first name, ')]
print('old server name left:', len(left), left)