# Databricks notebook source
# DBTITLE 1,Install PDF libraries
# MAGIC %pip install -q reportlab pypdf "mlflow[databricks]>=3.4"
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Load evaluation results
import json
import pandas as pd

DOC = "/Workspace/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/doc"
RESULTS_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261122-detfab.csv"  # Sample 1 + 4, deterministic no_fabrication
PRE_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261122-s4-nocorr.csv"  # previous run: Sample 1 + 4, no_fabrication still an LLM judge
UC_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261122-uc.csv"  # same day, Sample 1 only, traces in Unity Catalog
GT4_CSV = "/Volumes/users/amanda_xu/erratum_files/Correction-Sample4-29-annotated.csv"
PREV_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261121.csv"  # November 21 run, for comparison
BASE_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261122.csv"  # same day, same scorers, no agent trace returned
RUNS_JSON = f"{DOC}/agent-erratum-annotator-eval-runs-20261122-detfab.json"
OUTPUT_PATH = f"{DOC}/agent-erratum-annotator-evaluation-report.pdf"
RUN_DATE = "November 22, 2026"
SRU_DIR = "/Volumes/users/amanda_xu/erratum_files/sru_responses"
import os
n_saved = len([f for f in os.listdir(SRU_DIR) if f.endswith(".xml")])
base = pd.read_csv(BASE_CSV, keep_default_na=False)
uc = pd.read_csv(UC_CSV, keep_default_na=False)
pre = pd.read_csv(PRE_CSV, keep_default_na=False)

r = pd.read_csv(RESULTS_CSV, keep_default_na=False)
BOOL = ["truncated", "annotated_title_exact", "erratum_note_exact", "original_mms_id_match", "called_tool",
        "correctness", "no_fabrication"]
TOOL_COL = "tool_annotated_title_exact"  # added November 21, 2026; not in the November 20 export
for c in BOOL + [TOOL_COL]:
    r[c] = r[c].astype(str) == "True"
runs = json.load(open(RUNS_JSON))
prev = pd.read_csv(PREV_CSV, keep_default_na=False)
for c in BOOL:
    prev[c] = prev[c].astype(str) == "True"

# Direct MCP server test as the Inspector Gadget service principal (notebook "mcp-erratum-note Inspector Gadget Test")
IG_CSV = f"{DOC}/mcp-erratum-note-inspector-test-20261121.csv"
ig = pd.read_csv(IG_CSV, keep_default_na=False)
for c in ["is_error", "title_ok", "mms_ok", "needs_review"]:
    ig[c] = ig[c].astype(str) == "True"
print(len(ig), "Inspector Gadget rows, run", ig["run_ts"].iloc[0])

N = len(r)
S1, S4 = r["sample"] == 1, r["sample"] == 4  # Sample 4 row n has row_num 400 + n
N1, N4 = int(S1.sum()), int(S4.sum())
assert (N1, N4) == (53, 29), (N1, N4)
L = lambda n: f"S{4 if n >= 400 else 1} row {n % 400}"  # row label
C = lambda n: r.loc[r.row_num == n, "case"].iloc[0]
# rows with an expected original MMS ID (Sample 4 row 25 has the original but no correction)
has_original = r["case"].isin(["annotated", "already_annotated", "file_but_no_correction"])
has_file = ~r["case"].isin(["manual_review", "no_file_no_original"])  # rows with a saved SRU response


def count(col, mask=None, smp=None):
    mask = pd.Series(True, index=r.index) if mask is None else mask
    if smp:
        mask = mask & (r["sample"] == smp)
    return int(r.loc[mask, col].sum()), int(mask.sum())


MASK = {"original_mms_id_match": has_original, "called_tool": has_file}
F = lambda k, smp=None: (lambda a, b: f"{a}/{b}")(*count(k, MASK.get(k), smp))


M = {
    "annotated_title_exact": count("annotated_title_exact"),
    "erratum_note_exact": count("erratum_note_exact"),
    "original_mms_id_match": count("original_mms_id_match", has_original),
    "called_tool": count("called_tool", has_file),
    TOOL_COL: count(TOOL_COL),
    "correctness": count("correctness"),
    "no_fabrication": count("no_fabrication"),
}
lat = r["latency_s"]
print(N, "rows", runs)
for k, (a, b) in M.items():
    print(f"{k:25s} {a}/{b}")
print(r["case"].value_counts().to_dict())

# Trace statistics: the full run's traces, read from Unity Catalog with the MLflow SDK (not from the tables directly).
import mlflow
import numpy as np
os.environ.setdefault("MLFLOW_TRACING_SQL_WAREHOUSE_ID", "50d2bd4ddf65e0f5")
TRACE_TABLES = "users.amanda_xu.agent_erratum_eval_otel_*"
traces = mlflow.search_traces(locations=[runs["experiment_id"]], run_id=runs["full_run_id"], max_results=500,
                              return_type="list")
assert len(traces) == N, f"expected {N} traces, got {len(traces)}"
t_lat = np.array([t.info.execution_duration for t in traces]) / 1000
t_tok = [t.info.token_usage or {} for t in traces]
t_in = np.array([x.get("input_tokens", 0) for x in t_tok]); t_out = np.array([x.get("output_tokens", 0) for x in t_tok])
t_tools = [s for t in traces for s in t.data.spans if s.span_type == "TOOL"]
t_llm = [s for t in traces for s in t.data.spans if s.span_type == "CHAT_MODEL"]
t_tool_ms = np.array([(s.end_time_ns - s.start_time_ns) / 1e6 for s in t_tools])
t_llm_s = np.array([(s.end_time_ns - s.start_time_ns) / 1e9 for s in t_llm])
t_tool_err = sum(s.status.status_code.value == "ERROR" for s in t_tools)
t_states = pd.Series([t.info.state.value for t in traces]).value_counts().to_dict()
t_tool_names = pd.Series([s.name for s in t_tools]).value_counts().to_dict()
pct = lambda a, q: float(np.percentile(a, q))
print(len(traces), "traces", t_states, "tools", t_tool_names, "errors", t_tool_err, "LLM spans", len(t_llm),
      "tokens", int(t_in.sum()), int(t_out.sum()))

# COMMAND ----------

# DBTITLE 1,Build evaluation report PDF
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#1B3139"))
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#1B3139"))
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9.5, leading=12.5, spaceAfter=4)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8.5, leading=10.5, spaceAfter=0)
CELL_B = ParagraphStyle("CellB", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
CODE = ParagraphStyle("Code", parent=CELL, fontName="Courier", fontSize=7.5, leading=9.5)


def p(text, style=BODY):
    return Paragraph(text, style)


def bullets(items):
    return [p("&bull;&nbsp;" + i) for i in items]


def table(rows, widths, code_cols=()):
    data = [[Paragraph(escape(str(c)), CELL_B) for c in rows[0]]]
    for row in rows[1:]:
        data.append([Paragraph(escape(str(c)), CODE if j in code_cols else CELL) for j, c in enumerate(row)])
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3139")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F7")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


frac = lambda k: f"{M[k][0]}/{M[k][1]} ({M[k][0] / M[k][1]:.0%})"
rows_of = lambda mask: sorted(r.loc[mask, "row_num"].tolist())

# Explanations of every failing row, from reading the replies and judge rationales of this run.
# The asserts stop the build if a rerun produces a different set of failures.
_CURLY = ("Erratum note correct, but the agent replaced the curly apostrophe (U+2019) in the catalog title with a "
          "straight one; the tool's annotated_title was exact.")
_TIMEOUT = ("Agent timeout: the request reached the Supervisor Agent's 290 s limit (302.4 s end to end) and the reply "
            "was a continue / wrap up prompt, with no title, note or MMS ID.")
DET_FAIL = {
    5: _TIMEOUT,
    404: "Both notes, in date order; " + _CURLY[0].lower() + _CURLY[1:],
    429: _CURLY,
    34: "Erratum note correct, but the agent replaced the curly apostrophe (U+2019) in the catalog title with a straight one; the tool's annotated_title was exact.",
    40: "Erratum note correct, but the agent replaced the curly apostrophe (U+2019) in the catalog title with a straight one; the tool's annotated_title was exact.",
}
assert set(rows_of(~r.annotated_title_exact | ~r.erratum_note_exact | ~r.original_mms_id_match)) == set(DET_FAIL), \
    "Deterministic failures changed: update DET_FAIL"
CORR_FAIL = {
    4: "Judge error: the reply says Alma has only the correction notice and gives no annotated title, as expected; the "
       "judge failed it because the reply does not also say that it gives no search_title fallback.",
    5: _TIMEOUT,
    24: "Judge error: the reply says Alma has only the correction notice and gives no annotated title, as expected; the "
        "judge failed it because the reply does not also say that it gives no search_title fallback.",
    41: "Judge error: says the reply's original MMS ID differs from the expected one; both are 9916848606207426. Both "
        "notes and the title are exact.",
}
assert set(rows_of(~r.correctness)) == set(CORR_FAIL), "Correctness failures changed: update CORR_FAIL"
assert rows_of(~r.no_fabrication) == [], "no_fabrication failures changed"
n_fab = int((~r.no_fabrication).sum())
TIMEOUTS = rows_of(r.reply.str.contains("Request Time Out"))
assert TIMEOUTS == [5], f"timeouts changed: {TIMEOUTS}"
reply404 = r.loc[r.row_num == 404, "reply"].iloc[0]
assert r.loc[r.row_num == 404, "erratum_note_exact"].item() and "10.1007/s00018-025-05965-6" in reply404 \
    and reply404.index("05965-6") < reply404.index("05953-w")
reply425 = r.loc[r.row_num == 425, "reply"].iloc[0]
assert "no correction in alma - original only" in reply425.lower() and "no original in alma" not in reply425.lower()
assert r.loc[r.row_num == 425, "annotated_title_exact"].item()
NO_ORIG_LABEL = rows_of(r.case.isin(["file_but_no_original", "no_file_no_original"]))
assert all("no original in alma" in r.loc[r.row_num == n, "reply"].item().lower() for n in NO_ORIG_LABEL)
NO_ANN = rows_of(r.expected_annotated_title == "")
NO_FILE = rows_of(~has_file)
assert (r.loc[~has_file, "tools"] == "").all(), "a no-file row called a tool"
MANUAL_ROWS = rows_of(r.case == "manual_review"); NO_ORIG_ROWS = rows_of(r.case == "no_file_no_original")
reply41 = r.loc[r.row_num == 41, "reply"].iloc[0]
assert r.loc[r.row_num == 41, ["annotated_title_exact", "erratum_note_exact"]].all(axis=None)
assert "mycokeys.124.171105" in reply41 and "mycokeys.134.198487" in reply41

story = []
story += [p("agent-erratum-annotator: Evaluation Report", ParagraphStyle("T", parent=H1, fontSize=18)),
          p(f"NAL erratum annotation agent. Offline MLflow evaluation run on {RUN_DATE}.", SMALL), Spacer(1, 6)]

# 1. Summary
story += [p("1. Summary", H1),
          p(f"The agent was evaluated on {N} rows: all {N1} rows of the librarian-checked Sample 1 spreadsheet (row 41 "
            f"expects two erratum notes) and the {N4} rows of Sample 4 (rows 2 to 30), after a new instruction rule for "
            "the no_correction status and with no_fabrication now a deterministic check (section 10). Sample 4's expected titles were drafted from the tool output, then "
            "checked one by one against the records in Alma by the project owner, who approved all 29 (recorded November "
            f"22, 2026). The agent returned the exact annotated original title on {frac('annotated_title_exact')} "
            f"rows (Sample 1 {F('annotated_title_exact', 1)}, Sample 4 {F('annotated_title_exact', 4)}) and the correct "
            f"original MMS ID on {frac('original_mms_id_match')} rows that have one. It used a saved-response tool on "
            f"every row with an SRU file ({frac('called_tool')})."),
          p("Four exact-title failures (S1 rows 34 and 40, S4 rows 4 and 29) come from a limitation of the Supervisor "
            "Agent: it cannot output the curly apostrophe (U+2019) and writes a straight one; the tool result has the "
            "exact catalog title on those rows. The fifth, S1 row 5, is an agent timeout: the agent called the tool but "
            "reached its 290 s limit and replied with a continue / wrap up prompt. It is the only row failing "
            f"tool_annotated_title_exact ({frac(TOOL_COL)}). There were no endpoint errors or unfinished approval loops. "
            "S4 row 25 is labelled 'no correction in Alma - original only'. "
            f"None of the {len(NO_FILE)} notices with no saved SRU response called a tool or asked for SRU XML. "
            f"no_fabrication, now deterministic, passes {frac('no_fabrication')}. Besides the timeout, the "
            f"{len(CORR_FAIL) - 1} correctness failures are judge errors."),
          p(f"Traces are stored in Unity Catalog ({TRACE_TABLES}) with the agent's own trace attached to each request "
            f"(section 6): {len(t_tools)} tool calls with {t_tool_err} errors, and {int(t_in.sum() + t_out.sum()):,} "
            f"tokens for the {N} requests."),
          table([["Scorer", "Kind", "Rows scored", "All", "Sample 1", "Sample 4"]] +
                [[k + (" (primary)" if k == "annotated_title_exact" else ""), kind, scope, frac(k), F(k, 1), F(k, 4)]
                 for k, kind, scope in [("annotated_title_exact", "Deterministic", "all rows"),
                                        ("erratum_note_exact", "Deterministic", "all rows"),
                                        ("original_mms_id_match", "Deterministic", "rows with an original"),
                                        ("called_tool", "Deterministic", "rows with an SRU file"),
                                        (TOOL_COL, "Deterministic", "all rows"),
                                        ("correctness", "LLM judge", "all rows"),
                                        ("no_fabrication", "Deterministic", "all rows")]],
                [1.9, 0.9, 1.3, 1.0, 0.85, 0.85])]

# 2. System under test
story += [p("2. System under test", H1),
          table([["Component", "Value"],
                 ["Agent", "agent-erratum-annotator (Agent Bricks Supervisor Agent)"],
                 ["Endpoint", runs["endpoint"]],
                 ["Tools", "MCP app mcp-erratum-note (process_sru_file, list_sru_files, ...; calls need approval); "
                           "UC function users.amanda_xu.process_sru_response"],
                 ["Saved SRU responses", f"/Volumes/users/amanda_xu/erratum_files/sru_responses ({n_saved} MODS XML files; the 48 Sample 1 and 25 Sample 4 files are in this evaluation)"],
                 ["Output format", "<original title> [Erratum: Mon. YYYY, v. V, no. N, page, DOI]; already-annotated titles unchanged"]],
                [1.6, 4.9])]

# 3. Dataset
CASE_DESC = {
    "annotated": "Original found in the SRU response; note(s) appended",
    "already_annotated": "Original title already carries an [Erratum: ...] note; must be returned unchanged",
    "manual_review": "No SRU file: generic 'Correction' title (Sample 1) or no SRU response saved (Sample 4); needs manual review",
    "file_but_no_original": "SRU file holds only the correction; no annotation expected (no search-title fallback)",
    "file_but_no_correction": "SRU file holds only the original (correction not in Alma); no annotation expected",
    "no_file_no_original": "No SRU file and no original in Alma; no annotation expected",
}
assert set(r["case"]) <= set(CASE_DESC), set(r["case"]) - set(CASE_DESC)
cc = r.groupby(["case", "sample"]).size()
gt4 = pd.read_csv(GT4_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
assert len(gt4) == N4 and (gt4.librarian_decision == "OK").all()
story += [p("3. Evaluation dataset", H1),
          p("Ground truth: /Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv (librarian-checked) "
            "and Correction-Sample4-29-annotated.csv (drafted from process_sru_response on November 22, 2026, and "
            f"checked one by one against the Alma records and approved by {gt4.reviewed_by.iloc[0]}; the draft is kept as "
            "Correction-Sample4-29-annotated-DRAFT-unreviewed). Sample 4 row n is row_num 400 + n in the results. "
            "Each request gives the correction notice title, the erratum MMS ID and, when saved, the SRU response file "
            "name, e.g. <i>Annotate the original article title for the correction notice \"Correction: ...\" (erratum "
            "MMS ID 9916524607707426). The saved SRU response file is Sample1-Row1-9916524607707426.xml.</i>"),
          table([["Case", "Sample 1", "Sample 4", "Meaning"]] +
                [[c, int(cc.get((c, 1), 0)), int(cc.get((c, 4), 0)), d] for c, d in CASE_DESC.items()],
                [1.6, 0.65, 0.65, 3.6])]

# 4. Method
story += [p("4. Method", H1),
          *bullets([
              "mlflow.genai.evaluate with a predict function that calls the endpoint through the Responses API and "
              "auto-approves each mcp_approval_request (up to 8 rounds, 300 s client timeout, 2 retries). Only the final "
              "round's text is scored; all text and tool calls are kept for diagnosis.",
              "Traces are stored in Unity Catalog: the experiment is bound to " + TRACE_TABLES + ". Each request asks "
              "the endpoint to return its own trace (databricks_options.return_trace) and attaches it with "
              "mlflow.add_trace, which adds the agent's LLM spans (with token usage) and TOOL spans.",
              "Deterministic scorers compare after removing markdown escapes, bold and backticks and collapsing "
              "whitespace. Hyphens and quote characters are not normalized, because the catalog title must be exact.",
              "annotated_title_exact: the expected title appears exactly and no other note is attached to a title. "
              "erratum_note_exact: the set of notes attached to the title equals the expected notes (one, or two for "
              "Sample 1 row 41 and Sample 4 row 4). Notes restated after a label (e.g. under Details) and placeholders such as [Erratum: ...] in "
              "prose are ignored.",
              "no_fabrication (deterministic since November 22): every 16-digit MMS ID outside a DOI and every DOI in "
              "the reply must appear in a tool call (arguments or output) or in the request, and every erratum note in "
              "a tool output.",
              "Before any agent call, a self-check scores the ground truth itself (must pass), plus corrupted notes, "
              "doubled notes and markdown-formatted titles (67/67 each), and regression cases from earlier runs.",
              "A 5-row smoke test (Sample 1 rows 4, 41, 43; Sample 4 rows 4 and 25) preceded the full run (up to 3 parallel workers).",
          ]),
          p("Scorer revisions", H2),
          *bullets([
              "November 20, smoke test: the first scorers counted notes, so a correct reply that restated its note in a "
              "Details list failed (0/3). Changed to count only notes attached to a title.",
              "November 20, full run: 2 replies wrote '[Erratum: ...]' as a placeholder in a status sentence, and 9 "
              "already-annotated replies listed the new correction's note under Details. Both were scored as extra "
              "notes. Fixed and rescored from the saved replies without calling the agent: title 48 to 50/53, note 40 "
              "to 52/53.",
              "November 22: the expected note became every note in the expected title, compared as a set, so a reply "
              "with only one of row 41's two notes fails.",
              "November 22, Sample 4: a new case file_but_no_correction (S4 row 25), and the manual-review expected "
              "fact now depends on the reason (generic title or no SRU response).",
          ])]

# 5. Results
r1, r4 = r[S1], r[S4]
p1, p4 = pre[pre["sample"] == 1], pre[pre["sample"] == 4]
by_case = r.groupby("case").agg(rows=("row_num", "size"), title=("annotated_title_exact", "sum"),
                                note=("erratum_note_exact", "sum"), correct=("correctness", "sum"),
                                lat=("latency_s", "median")).reindex(list(CASE_DESC))
story += [p("5. Results", H1), p("5.1 By case", H2),
          table([["Case", "Rows", "Title exact", "Note exact", "Correctness", "Median latency"]] +
                [[c, int(x.rows), f"{int(x.title)}/{int(x.rows)}", f"{int(x.note)}/{int(x.rows)}",
                  f"{int(x.correct)}/{int(x.rows)}", f"{x.lat:.1f} s"] for c, x in by_case.iterrows()],
                [1.7, 0.6, 0.9, 0.9, 1.0, 1.1]),
          p("5.2 Deterministic failures", H2),
          table([["Row", "Case", "What happened"]] +
                [[L(n), C(n), t] for n, t in sorted(DET_FAIL.items())], [0.5, 1.4, 4.6]),
          p("5.3 LLM judge (correctness) and no_fabrication", H2),
          p(f"<b>correctness</b> {frac('correctness')}. Failing rows:"),
          table([["Row", "Case", "Reason"]] +
                [[L(n), C(n), t] for n, t in sorted(CORR_FAIL.items())], [0.5, 1.4, 4.6]),
          Spacer(1, 6),
          p(f"<b>no_fabrication</b> {frac('no_fabrication')} (Sample 1 {F('no_fabrication', 1)}, Sample 4 "
            f"{F('no_fabrication', 4)}). Now a deterministic check (section 4): every MMS ID, DOI and erratum note in the "
            "reply is in a tool result or the request. The LLM judge it replaced failed 14 to 21 correct replies per run, "
            "and applied to the previous run's saved replies the check found one real fabrication the judge passed: an "
            "erratum note the agent built for S1 row 39 without a tool call. In this run no reply has a note without a "
            "tool call. A timed-out reply has no IDs, so it passes; the title scorers catch timeouts.", SMALL),
          p(", ".join(L(n) for n in NO_ANN) + " pass the deterministic scorers only because they give no annotation; "
            "the deterministic scorers do not check that the reply explains why. The report checks the status label: S4 "
            "row 25 says 'no correction in Alma - original only', and the " + str(len(NO_ORIG_LABEL)) + " no-original rows "
            "say 'no original in Alma'.",
            SMALL),
          p("5.4 Compared with earlier runs", H2),
          table([["Scorer", "Nov. 21", "Nov. 22, UC traces", "Previous run: S1", "Previous run: S4", "This run: S1", "This run: S4"]] +
                [[k] + [f"{int(d.loc[m(d), k].astype(str).eq('True').sum())}/{int(m(d).sum())}" for d in (prev, uc, p1, p4, r1, r4)]
                 for k, m in [("annotated_title_exact", lambda d: d.index == d.index),
                              ("erratum_note_exact", lambda d: d.index == d.index),
                              ("original_mms_id_match", lambda d: d["case"].isin(["annotated", "already_annotated", "file_but_no_correction"])),
                              ("called_tool", lambda d: ~d["case"].isin(["manual_review", "no_file_no_original"])),
                              ("correctness", lambda d: d.index == d.index),
                              ("no_fabrication", lambda d: d.index == d.index)]] +
                [["Median latency"] + [f"{d.latency_s.median():.1f} s" for d in (prev, uc, p1, p4, r1, r4)]],
                [1.5, 0.8, 0.95, 0.95, 0.95, 0.9, 0.9]),
          p("The November 21 run was scored against the ground truth before row 41's change (one expected note); "
            "all November 22 runs use the updated ground truth. Between November 21 and 22, mcp-erratum-note returns "
            "a blank annotated_title when the response has no original or no correction record. The first two runs are "
            "Sample 1 only. 'Previous run' is valuable-turtle-195, after the no_correction rule; no_fabrication was "
            "still an LLM judge in all runs except this one, so that row is not comparable across columns.", SMALL)]

# 6. Latency and tool use
tools = r["tools"].replace("", "(none)").value_counts()
story += [p("6. Latency, tool calls and token usage", H1),
          p(f"From the {len(traces)} full-run traces in Unity Catalog (states: "
            + ", ".join(f"{k} {v}" for k, v in t_states.items()) + ") and the per-row results.", SMALL),
          table([["Measure", "Value"],
                 [f"Per-request latency ({N} rows)", f"p50 {pct(t_lat, 50):.1f} s, p90 {pct(t_lat, 90):.1f} s, "
                                                  f"p95 {pct(t_lat, 95):.1f} s, p99 {pct(t_lat, 99):.1f} s, max {t_lat.max():.1f} s"],
                 ["Rows with an SRU file", f"median {r.loc[has_file, 'latency_s'].median():.1f} s (one tool call, one approval)"],
                 ["Rows without an SRU file", f"median {r.loc[~has_file, 'latency_s'].median():.1f} s (no tool call)"],
                 ["Slowest row", f"{L(int(r.loc[lat.idxmax(), 'row_num']))}: {lat.max():.1f} s (reply " + ("passes" if r.loc[lat.idxmax(), "annotated_title_exact"] else "fails") + " annotated_title_exact)"],
                 ["Endpoint errors / truncated loops", f"{int((r.error != '').sum())} / {int(r.truncated.sum())}"],
                 ["Tool calls (TOOL spans)", ", ".join(f"{k} {v}" for k, v in t_tool_names.items())
                  + f"; {t_tool_err} errors; p50 {pct(t_tool_ms, 50):.0f} ms, p95 {pct(t_tool_ms, 95):.0f} ms, "
                    f"max {t_tool_ms.max():.0f} ms"],
                 ["LLM calls (CHAT_MODEL spans)", f"{len(t_llm)}, about {len(t_llm) / len(traces):.1f} per request; "
                                                  f"p50 {pct(t_llm_s, 50):.1f} s, p95 {pct(t_llm_s, 95):.1f} s"],
                 ["Input tokens per request", f"median {int(np.median(t_in)):,}, mean {int(t_in.mean()):,}, max {int(t_in.max()):,}"],
                 ["Output tokens per request", f"median {int(np.median(t_out)):,}, mean {int(t_out.mean()):,}, max {int(t_out.max()):,}"],
                 ["Tokens, whole run", f"{int(t_in.sum()):,} input + {int(t_out.sum()):,} output = {int(t_in.sum() + t_out.sum()):,}"]] +
                [[f"Rows by tool used: {k}", f"{v} rows"] for k, v in tools.items()],
                [2.4, 4.1]),
          p(f"Median latency was {lat.median():.1f} s, against {base.latency_s.median():.1f} s in the same day's run "
            "that did not ask the endpoint to return its trace. Returning the trace may add time; this was not "
            "measured separately.", SMALL)]

# 7. Findings and recommendations
story += [p("7. Findings and recommendations", H1),
          *bullets([
              "<b>Take the catalog title from the tool result, not the reply.</b> The Supervisor Agent cannot output the "
              "curly apostrophe U+2019: given d\u2019I in a plain message, it reports the character as U+0027. A stronger "
              "instruction (worked example, character check, title in a code block) gave 0 of 6 exact on rows 34 and 40, "
              "so it was reverted. Sample 4 rows 4 and 29 fail the same way. The tool's annotated_title is exact on all "
              f"{N} rows; librarians should copy it from the tool result, and tool_annotated_title_exact scores it.",
              "<b>Two corrections in one original work end to end.</b> S1 row 41 and S4 row 4 carry both notes in date "
              "order; row 41 passes both exact scorers, and S4 row 4 fails the title only on the apostrophe.",
              f"<b>No SRU file.</b> None of the {len(NO_FILE)} no-file replies calls a tool or asks for XML. "
              + ", ".join(L(n) for n in MANUAL_ROWS) + " say the notice needs manual review; "
              + " and ".join(L(n) for n in NO_ORIG_ROWS) + ", whose requests pass on the librarian's Alma search result, "
              "say the original is not in Alma.",
              "<b>no_correction status: done.</b> S4 row 25 (only the original in Alma) used to be labelled 'No original "
              "in Alma'. A new instruction rule gives the label 'no correction in Alma - original only'; in this run row 25 "
              "uses it and the no-original rows keep theirs (section 10).",
              f"<b>Watch latency and cost.</b> p95 {pct(t_lat, 95):.1f} s, max {t_lat.max():.1f} s, one timeout (S1 row 5, after the tool call). "
              "Timeouts are intermittent: S4 row 26 timed out two runs earlier and took about 13 s since, and S1 row 5 "
              "passed in the previous run. "
              f"Each request uses about {int(np.median(t_in)):,} input tokens, mostly the agent's instructions and context.",
              "<b>no_fabrication is deterministic: done.</b> It replaces the LLM guideline judge, whose failures were "
              "judge errors that changed from run to run, and it catches notes the agent builds without a tool.",
              "<b>Grow the dataset.</b> Add Sample3 (142 rows) once its SRU responses are saved.",
          ])]


# 8. MCP server test (Inspector Gadget)
ig_diff = sorted(ig.loc[ig.is_error | ~ig.title_ok | ~ig.mms_ok, "row_num"].tolist())
assert ig_diff == [4, 24], f"Inspector Gadget differences changed: {ig_diff}"
assert not ig.loc[ig.row_num.isin(ig_diff), "needs_review"].any()
ig_frac = lambda col: f"{int(ig[col].sum())}/{len(ig)}"
story += [p("8. MCP server test (Inspector Gadget)", H1),
          p(f"The MCP server was also tested directly, without the agent, on {ig['run_ts'].iloc[0].replace('T', ' ')} "
            "UTC. A test client signed in as the Inspector Gadget service principal (OAuth M2M, CAN_USE on the app), "
            f"listed the 7 tools, called list_sru_files and then process_sru_file on each of the {len(ig)} saved SRU "
            "responses, and compared annotated_title and original_id with the ground truth. Each run is appended to "
            "the table users.amanda_xu.erratum_mcp_inspector_test."),
          table([["Check", "Result"],
                 ["Tools listed", "7: health, parse_sru_response, extract_erratum_note, enhance_title, "
                                  "process_sru_response, list_sru_files, process_sru_file"],
                 ["Tool errors", f"{int(ig.is_error.sum())}/{len(ig)}"],
                 ["annotated_title exact", ig_frac("title_ok")],
                 ["original MMS ID match", ig_frac("mms_ok")],
                 ["Latency per process_sru_file call",
                  f"median {ig.latency_sec.median():.2f} s, max {ig.latency_sec.max():.2f} s"]],
                [2.0, 4.5]),
          p("Rows 4 and 24 are the only differences. Alma has no original for them, so the ground-truth title is "
            "blank. The tool correctly returns no original_id, but it still builds an annotated title from the search "
            "title and sets needs_review to false. Recommendation: when no original is found, return no annotated_title "
            "or set needs_review to true. Done November 22, 2026: annotated_title is now blank when no original is found (section 10)."),
          p("The tool answers in under a second, so nearly all of the agent's per-request time (section 6) is spent "
            "in the Supervisor Agent, not in the MCP server.")]

# 9. Artifacts
story += [p("9. Artifacts and reproduction", H1),
          table([["Item", "Location"],
                 ["Evaluation notebook", "/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/Erratum Annotator Agent Evaluation"],
                 ["Report notebook", "/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/Erratum Annotator Evaluation Report"],
                 ["MLflow experiment", f"{runs['experiment']} (id {runs['experiment_id']})"],
                 ["Full run", runs["full_run_id"]], ["Rescore run", runs["rescore_run_id"]],
                 ["Smoke run", runs["smoke_run_id"]],
                 ["Per-row results", RESULTS_CSV],
                 ["Sample 4 ground truth", GT4_CSV],
                 ["Inspector Gadget test notebook",
                  "/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/mcp-erratum-note Inspector Gadget Test"],
                 ["Inspector Gadget results", IG_CSV]],
                [1.5, 5.0], code_cols=(1,)),
          Spacer(1, 4),
          p("To reproduce: run the evaluation notebook top to bottom (cells 2 to 4 need no agent calls), then this "
            "notebook. The rescore cell reapplies the deterministic scorers to saved replies.", SMALL)]

# 10. Changes since the November 21 run (computed from the current code and files)
import importlib.util
_ANN = "/Workspace/Users/amanda.xu@usda.gov/NAL/erratum-annotator/mcp_server/erratum_annotator.py"
_spec = importlib.util.spec_from_file_location("erratum_annotator_now", _ANN)
ea_now = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ea_now)
GT_CSV = "/Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv"
_xml = lambda f: open(f"{SRU_DIR}/{f}", encoding="utf-8-sig").read()
TWO = [("Sample 4, row 4", "Sample4-Row4-9917012079207426-TwoCorrectionsInOneOriginalTitle.xml", "9917012079207426"),
       ("Sample 1, row 41", "Sample1-Row41-9917175655407426.xml", "9917175655407426")]
two = {lab: ea_now.process_sru_response(_xml(f), "", cid) for lab, f, cid in TWO}
assert all(len(v["erratum_notes"]) == 2 for v in two.values()), "two-note rule changed"
gt_now = pd.read_csv(GT_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
_strip = lambda s: s[2:-1] if s.startswith('="') else s
now_ok, now_diff, now_n = 0, [], 0
for _, g in gt_now.iterrows():
    _cid = _strip(g.erratum_mms_id); _f = f"Sample1-Row{g.row_num}-{_cid}.xml"
    if not os.path.exists(f"{SRU_DIR}/{_f}"):
        continue
    now_n += 1
    if ea_now.process_sru_response(_xml(_f), "", _cid)["annotated_title"] == g.annotated_title:
        now_ok += 1
    else:
        now_diff.append(int(g.row_num))
assert now_diff == [], f"tool vs updated ground truth changed: {now_diff}"
assert gt_now.loc[gt_now.row_num == "41", "annotated_title"].item() == two["Sample 1, row 41"]["annotated_title"]
s4_ok, s4_n = 0, 0
for _, g in gt4.iterrows():
    if g.sru_response_file:
        s4_n += 1
        s4_ok += ea_now.process_sru_response(_xml(g.sru_response_file), "", _strip(g.erratum_mms_id))["annotated_title"] == g.annotated_title
assert (s4_ok, s4_n) == (25, 25), (s4_ok, s4_n)
_r25 = ea_now.process_sru_response(_xml("Sample4-Row25-9917162397207426-OnlyOriginalTitle.xml"), "", "9917162397207426")
assert _r25["annotated_title"] == "" and _r25["num_corrections"] == 0
story += [p("10. Changes since the November 21 run", H1),
          p("<b>Two corrections in one original title.</b> New rule from the project owner: when an SRU response holds "
            "two or more correction records of one original article, every correction's erratum note goes into the single "
            "original title, ordered by date (year, month, day), then volume, issue and page. Two saved responses have "
            "this case:"),
          table([["Notice", "Notes appended, in order"]] +
                [[lab, "  ".join(v["erratum_notes"])] for lab, v in two.items()], [1.3, 5.2], code_cols=(1,)),
          Spacer(1, 4),
          *bullets([
              "<b>Ground truth changed for row 41.</b> Its expected annotated title in Correction-Sample1-53-annotated "
              "now carries both notes (Nov. 13, 2025, then June 18, 2026). The previous files are kept as "
              "Correction-Sample1-53-annotated-before-20261122.csv and .xlsx. In this run the agent's row 41 reply "
              "has both notes and passes.",
              "<b>Blank annotated_title when nothing can be annotated.</b> If the response has no original record "
              "(Sample 1 rows 4 and 24) or no correction record (Sample 4 row 25: only the original is in Alma, status "
              "no_correction, with a manual-review warning), annotated_title is blank. This is the fix recommended in "
              "section 8.",
              f"<b>Tool check against the updated ground truth.</b> process_sru_response, run now on the {now_n} Sample1 "
              f"rows with a saved response, gives the expected annotated title on {now_ok}/{now_n}.",
              f"<b>Saved responses.</b> {n_saved} files: 48 from Sample 1, Sample 2 rows 3 and 14, and 25 from Sample 4 "
              "(rows 2 to 30 except 16, 19, 20 and 22, which have no SRU response and need manual review).",
              f"<b>Sample 4 added.</b> {N4} rows (2 to 30); expected titles drafted from the tool output and checked one by "
              f"one against Alma by the project owner (section 3). process_sru_response gives the expected title on "
              f"{s4_ok}/{s4_n} Sample 4 rows with a saved response.",
              "<b>no_correction instruction rule.</b> The agent's instructions now say: when status is no_correction "
              "(original_id set, no correction record; for the UC function, num_corrections 0), report 'no correction in "
              "Alma - original only', give both MMS IDs, say it needs manual review and give no annotated title. Checked "
              "before this run: S4 row 25 3 of 3, and 7 regression rows pass.",
              "<b>Deterministic no_fabrication.</b> The LLM guideline judge is replaced by a check that every MMS ID, "
              "DOI and erratum note in the reply comes from a tool result or the request (section 4).",
              "<b>Traces in Unity Catalog.</b> The evaluation now writes to the experiment "
              f"{runs['experiment']} (id {runs['experiment_id']}), bound to {TRACE_TABLES}. The earlier experiment keeps "
              "the November 20 to 22 runs.",
          ])]

# Section 11: Playground demo prompt (step 2 of the two-app demo), checked November 23, 2026
PG_PROMPT = 'Annotate the original article for correction notice MMS ID 9917175652607426. Correction notice title: Correction to: Climate‐driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture. The saved SRU response file is Sample1-Row42-9917175652607426.xml. Return the annotated original title, the erratum note, the original MMS ID, and whether it needs manual review.'
_pg = ea_now.process_sru_response(_xml("Sample1-Row42-9917175652607426.xml"), "", "9917175652607426")
assert _pg["annotated_title"] == 'Climate-driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture [Erratum: Sept. 2026, v. 99, no. 3, 111, 10.1007/s10340-026-02069-3]', _pg["annotated_title"]
story += [p("11. Playground demo prompt (November 23, 2026)", H1),
          p("Judges can repeat this check in the Databricks AI Playground. The demo uses one correction notice for both MCP "
            "apps: MMS ID 9917175652607426 (Sample 1, row 42). This prompt is step 2. Step 1 (mcp-sru-syntax, which "
            "builds the SRU URL) is in section 10 of the mcp-sru-syntax evaluation report."),
          table([["Item", "Value"],
                 ["Playground pane", "agent-erratum-annotator (serving endpoint mas-c341c0aa-endpoint)"],
                 ["Prompt", PG_PROMPT],
                 ["Tool called", "process_sru_file (mcp-erratum-note); approve the tool call in the Playground"],
                 ["Annotated title", _pg["annotated_title"]],
                 ["Original MMS ID", '9917015258907426'],
                 ["Needs manual review", "No"],
                 ["Result", "Matches the ground truth for row 42 in Correction-Sample1-53-annotated.csv; 13 s"],
                ], [1.4, 5.1]),
          Spacer(1, 4),
          *bullets(["The prompts are also in the README files (repository root, submission/, sru-syntax-mcp/ and "
                    "erratum-annotator/), under Playground demo: both MCP apps on one correction notice."])]



def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(0.75 * inch, 0.5 * inch, f"agent-erratum-annotator evaluation report, {RUN_DATE}")
    canvas.drawRightString(7.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


SimpleDocTemplate(OUTPUT_PATH, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                  topMargin=0.7 * inch, bottomMargin=0.75 * inch,
                  title="agent-erratum-annotator evaluation report").build(story, onFirstPage=_footer, onLaterPages=_footer)
print("Saved", OUTPUT_PATH)

# COMMAND ----------

# DBTITLE 1,Verify report PDF
import os
from pypdf import PdfReader

reader = PdfReader(OUTPUT_PATH)
flat = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
print(f"{os.path.getsize(OUTPUT_PATH):,} bytes, {len(reader.pages)} pages")
checks = ["1. Summary", "2. System under test", "3. Evaluation dataset", "4. Method", "5. Results",
          "6. Latency, tool calls and token usage", "7. Findings and recommendations",
          "8. MCP server test (Inspector Gadget)", "9. Artifacts and reproduction", "erratum_mcp_inspector_test",
          ig_frac("title_ok"), ig_frac("mms_ok"),
          frac("annotated_title_exact"), frac("erratum_note_exact"), frac("original_mms_id_match"), frac("called_tool"),
          frac("correctness"), frac("no_fabrication"), runs["full_run_id"], runs["rescore_run_id"], runs["experiment_id"],
          runs["endpoint"], "U+2019", "48 to 50/53", "40 to 52/53", f"max {t_lat.max():.1f} s",
          "5.4 Compared with earlier runs", RUN_DATE, "tool_annotated_title_exact", "U+0027",
          "10. Changes since the November 21 run", "10.1007/s00018-025-05953-w", "10.3897/mycokeys.124.171105",
          f"{now_ok}/{now_n}", "before-20261122", "agent_erratum_eval_otel", f"{int(t_in.sum() + t_out.sum()):,}",
          f"{len(t_tools)} tool calls", "no_correction", "Sample 4", "Correction-Sample4-29-annotated", "checked one by one against the records in Alma",
          "file_but_no_correction", "no correction in Alma - original only", "Previous run: S4", "S4 row 26", "S4 row 25", "S1 row 5", "no_fabrication is deterministic", F("annotated_title_exact", 4), f"{s4_ok}/{s4_n}",
          "11. Playground demo prompt", "9917175652607426", "mas-c341c0aa-endpoint"]
missing = [c for c in checks if c not in flat]
for c in checks:
    print("OK  " if c not in missing else "MISSING  ", c)
assert not missing, missing