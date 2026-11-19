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
    p('NAL Alma SRU URL builder for erratum/correction notices &nbsp;|&nbsp; Report date: November 18, 2026', SMALL),
    Spacer(1, 8),
    p('This report covers four evaluations and a per-step latency analysis of the <b>sru-syntax-mcp</b> Databricks App (renamed <b>mcp-sru-syntax</b> on November 19, 2026 so Genie Code lists it as a custom MCP server; all tests in this report ran before the rename), a custom MCP server '
      '(streamable HTTP at <font face="Courier">/mcp</font>) exposing one tool, '
      '<font face="Courier">build_sru_search_url</font>. The tool sends an erratum/correction notice title to the '
      'agent-sru-syntax Supervisor Agent (serving endpoint <font face="Courier">mas-c8629507-endpoint</font>) and '
      'returns the NAL Alma production SRU searchRetrieve URL for the original article.'),
    Spacer(1, 4),
    table([
        ['Evaluation', 'Status', 'Headline result'],
        ['1. Inspector Gadget testing', 'Passed', 'Authenticated as a service principal; 1/1 tools listed and called successfully; correct SRU URL in 13.7 s.'],
        ['2. Offline MLflow evaluation', 'Completed', 'sru_url_match 0.93 (38/41) on the 41-row dataset; 1.00 on the earlier 11-row dataset; safety 1.00 throughout.'],
        ['3. Online evaluation (production monitoring)', 'Configured, stopped', '2 custom LLM-judge scorers registered (ToolCallEfficiency, ToolCallCorrectness) at 0% sample rate, pending admin confirmation of scorer identity and permissions.'],
        ['4. Evaluation run kindly-lamb-651', 'Completed (1 judge error)', 'ToolCallEfficiency LLM judge on 2 agent traces: 1 yes, 1 judge parse error; trace review shows both traces used tools efficiently.'],
        ['5. Agent latency per step', 'Analyzed', '174 requests: those that call the tool take p50 22.5 s (tool about 69% of the time); 35 answered without the tool take p50 2.7 s. 1 error in 176 model calls.'],
    ], [2.0, 1.1, 4.0]),
    Spacer(1, 6),
    table([
        ['Component', 'Value'],
        ['App', 'mcp-sru-syntax (https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com); tested as sru-syntax-mcp before the November 19, 2026 rename'],
        ['MCP endpoint', '/mcp (stateless streamable HTTP, JSON responses)'],
        ['Tool', 'build_sru_search_url(correction_title: str) -> str (read-only, idempotent)'],
        ['Upstream agent', 'agent-sru-syntax Supervisor Agent, endpoint mas-c8629507-endpoint'],
        ['Rules function', 'users.amanda_xu.build_sru_url (Unity Catalog function)'],
        ['Agent model', 'models.ai.gpt-5-6-luna'],
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
         'Granted CAN USE on sru-syntax-mcp to the service principal.'],
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
    p('2. Databricks offline MLflow evaluation: sru-syntax-mcp', H1),
    p('<b>Purpose:</b> verify that the SRU syntax agent produces correct NAL Alma production SRU URLs from '
      'erratum/correction notice titles. A labelled dataset is scored by a deterministic URL match plus four LLM '
      'judges, catching rule regressions, empty Supervisor Agent replies, and instruction-following failures before '
      'deploying changes.'),
    p('Method', H2),
    *bullets([
        '<font face="Courier">mlflow.genai.evaluate</font> runs over the dataset with a <font face="Courier">predict_fn</font> '
        'that calls the SRU syntax agent while it uses the deployed sru-syntax-mcp MCP server.',
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
    KeepTogether([p('Next steps', H1),
    *bullets([
        'Investigate the empty Supervisor Agent replies (3/41 titles), the only remaining sru_url_match failures.',
        'Tighten the relevant_to_notice and no_invented_urls guideline wording to remove judge false negatives on title-only and issue-level notices.',
        'Confirm the online scorer identity and permissions with the workspace admin, then start both scorers at a 0.1 sample rate.',
        'Provision the dedicated eval service principal (sp-sru-syntax-eval) so offline runs target the deployed app rather than a local server copy.',
        'Fix the ToolCallEfficiency judge\'s output format (it returned JSON inside a markdown code block, causing a '
        'parse error and an unsupported verdict), then re-run it on a larger trace sample before starting online monitoring.',
        'To cut response time, focus on the build_sru_search_url path (about 69% of latency in tool requests): review whether the '
        'Supervisor Agent\'s code_safety guardrail is needed for this read-only UC function, and consider calling '
        'users.amanda_xu.build_sru_url directly for well-formed titles. Re-run the latency query on a larger sample.',
    ])]),
    Spacer(1, 10),
    p(f'Sources: Inspector Gadget results from the test notebook runs on November 18, 2026; offline and online '
      f'evaluation details from <link href="{README_URL}" color="blue">sru-syntax-mcp/eval/databricks/README.md</link> '
      f'(branch add-mcp-servers); kindly-lamb-651 results from the run\'s trace assessments and span data in '
      f'experiment 1096079759943475; latency from the SRU Agent Latency per Step query over '
      f'users.amanda_xu.sru_syntax_agent_otel_spans.', SMALL),
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
from pypdf import PdfReader

reader = PdfReader(OUTPUT_PATH)
text = '\n'.join(page.extract_text() for page in reader.pages)
print(f'{os.path.getsize(OUTPUT_PATH):,} bytes, {len(reader.pages)} pages')
for check in ['1. Inspector Gadget testing', '2. Databricks offline MLflow evaluation', '3. Online evaluation',
              'build_sru_search_url', '0.93 (38/41)', 'ToolCallEfficiency', 'ToolCallCorrectness', '1096079759943475',
              'kindly-lamb-651', 'tr-49f67341cc640c67a33da696d5cecdd0', '4. Evaluation run',
              '5. Agent latency per step', '18.62', '15.06', '68.9%', '53.77', 'about 69%', 'mcp-sru-syntax on November 19, 2026']:
    print('OK  ' if check in text else 'MISSING  ', check)