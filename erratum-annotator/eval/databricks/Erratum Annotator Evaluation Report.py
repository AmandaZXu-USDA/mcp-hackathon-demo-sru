# Databricks notebook source
# DBTITLE 1,Install PDF libraries
# MAGIC %pip install -q reportlab pypdf
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Load evaluation results
import json
import pandas as pd

DOC = "/Workspace/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/doc"
RESULTS_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261121.csv"
PREV_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261120.csv"  # November 20 run, for comparison
RUNS_JSON = f"{DOC}/agent-erratum-annotator-eval-runs-20261121.json"
OUTPUT_PATH = f"{DOC}/agent-erratum-annotator-evaluation-report.pdf"
RUN_DATE = "November 21, 2026"

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
has_original = r["case"].isin(["annotated", "already_annotated"])  # rows with an expected original MMS ID
has_file = ~r["case"].isin(["manual_review", "no_file_no_original"])  # rows with a saved SRU response


def count(col, mask=None):
    mask = pd.Series(True, index=r.index) if mask is None else mask
    return int(r.loc[mask, col].sum()), int(mask.sum())


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
DET_FAIL = {
    34: "Erratum note correct, but the agent replaced the curly apostrophe (U+2019) in the catalog title with a straight one; the tool's annotated_title was exact.",
    40: "Erratum note correct, but the agent replaced the curly apostrophe (U+2019) in the catalog title with a straight one; the tool's annotated_title was exact.",
}
assert set(rows_of(~r.annotated_title_exact | ~r.erratum_note_exact | ~r.original_mms_id_match)) == set(DET_FAIL), \
    "Deterministic failures changed: update DET_FAIL"
CORR_FAIL = {
    4: "Judge error: the reply says Alma has only the correction notice and gives no annotated title, as expected; the judge "
       "failed it because the tool output names search_title as the lookup source.",
    9: "No SRU file: the agent says it cannot produce a title and asks for the SRU XML instead of saying the original is not in Alma.",
}
assert set(rows_of(~r.correctness)) == set(CORR_FAIL), "Correctness failures changed: update CORR_FAIL"
FAB_GROUPS = [
    ("Judge error: expects the original article's MMS ID to equal the correction notice's MMS ID. The reported original "
     "MMS ID comes from process_sru_file (original_id) and matches the ground truth.", [3, 11, 13, 18, 21, 22, 35, 42, 44, 47]),
    ("Judge error: says the reply does not state that the title already carries a note; its first sentence says so.", [31]),
]
assert sorted(sum((g for _, g in FAB_GROUPS), [])) == rows_of(~r.no_fabrication), "no_fabrication failures changed"
assert r.loc[r.row_num.isin(FAB_GROUPS[0][1]), "original_mms_id_match"].all()

story = []
story += [p("agent-erratum-annotator: Evaluation Report", ParagraphStyle("T", parent=H1, fontSize=18)),
          p(f"NAL erratum annotation agent. Offline MLflow evaluation run on {RUN_DATE}.", SMALL), Spacer(1, 6)]

# 1. Summary
story += [p("1. Summary", H1),
          p(f"The agent was evaluated on all {N} rows of the librarian-checked Sample1 spreadsheet. It returned the exact "
            f"annotated original title on {frac('annotated_title_exact')} rows and the correct original MMS ID on "
            f"{frac('original_mms_id_match')} rows that have one. It used a saved-response tool on every row with an SRU "
            f"file ({frac('called_tool')}). Both exact-match failures (rows 34 and 40) come from a limitation of the "
            "Supervisor Agent: it cannot output the curly apostrophe (U+2019) and writes a straight one. The tool result "
            f"the reply is built from has the exact catalog title on every row ({frac(TOOL_COL)}, "
            "tool_annotated_title_exact). There were no Supervisor Agent timeouts, endpoint errors or unfinished approval loops. "
            "On the 5 notices with no saved SRU response, 4 replies say the notice needs manual review and one (row 9) "
            "still asks for SRU XML. All 11 no_fabrication failures are judge errors."),
          table([["Scorer", "Kind", "Rows scored", "Result"],
                 ["annotated_title_exact (primary)", "Deterministic", "all rows", frac("annotated_title_exact")],
                 ["erratum_note_exact", "Deterministic", "all rows", frac("erratum_note_exact")],
                 ["original_mms_id_match", "Deterministic", "rows with an original", frac("original_mms_id_match")],
                 ["called_tool", "Deterministic", "rows with an SRU file", frac("called_tool")],
                 ["tool_annotated_title_exact", "Deterministic", "all rows", frac(TOOL_COL)],
                 ["correctness", "LLM judge", "all rows", frac("correctness")],
                 ["no_fabrication", "LLM guideline", "all rows", frac("no_fabrication")]],
                [2.3, 1.2, 1.6, 1.4])]

# 2. System under test
story += [p("2. System under test", H1),
          table([["Component", "Value"],
                 ["Agent", "agent-erratum-annotator (Agent Bricks Supervisor Agent)"],
                 ["Endpoint", runs["endpoint"]],
                 ["Tools", "MCP app mcp-erratum-note (process_sru_file, list_sru_files, ...; calls need approval); "
                           "UC function users.amanda_xu.process_sru_response"],
                 ["Saved SRU responses", "/Volumes/users/amanda_xu/erratum_files/sru_responses (48 MODS XML files)"],
                 ["Output format", "<original title> [Erratum: Mon. YYYY, v. V, no. N, page, DOI]; already-annotated titles unchanged"]],
                [1.6, 4.9])]

# 3. Dataset
case_counts = r["case"].value_counts()
CASE_DESC = {
    "annotated": "Original found in the SRU response; note appended",
    "already_annotated": "Original title already carries an [Erratum: ...] note; must be returned unchanged",
    "manual_review": "Generic 'Correction' title, no SRU file; needs manual review",
    "file_but_no_original": "SRU file holds only the correction; no annotation expected (no search-title fallback)",
    "no_file_no_original": "No SRU file and no original in Alma; no annotation expected",
}
story += [p("3. Evaluation dataset", H1),
          p("Ground truth: /Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv. Each request gives "
            "the correction notice title, the erratum MMS ID and, when saved, the SRU response file name, e.g. "
            "<i>Annotate the original article title for the correction notice \"Correction: ...\" (erratum MMS ID "
            "9916524607707426). The saved SRU response file is Sample1-Row1-9916524607707426.xml.</i>"),
          table([["Case", "Rows", "Meaning"]] + [[c, int(case_counts.get(c, 0)), d] for c, d in CASE_DESC.items()],
                [1.6, 0.6, 4.3])]

# 4. Method
story += [p("4. Method", H1),
          *bullets([
              "mlflow.genai.evaluate with a predict function that calls the endpoint through the Responses API and "
              "auto-approves each mcp_approval_request (up to 8 rounds, 300 s client timeout, 2 retries). Only the final "
              "round's text is scored; all text and tool calls are kept for diagnosis.",
              "Deterministic scorers compare after removing markdown escapes, bold and backticks and collapsing "
              "whitespace. Hyphens and quote characters are not normalized, because the catalog title must be exact.",
              "annotated_title_exact: the expected title appears exactly and no other note is attached to a title. "
              "erratum_note_exact: the note attached to the title equals the expected note. Notes restated after a "
              "label (e.g. under Details) and placeholders such as [Erratum: ...] in prose are ignored.",
              "Before any agent call, a self-check scores the ground truth itself (must pass), plus corrupted notes, "
              "doubled notes and markdown-formatted titles (46/46 each), and regression cases from this run.",
              "A 3-row smoke test (rows 4, 41, 43) preceded the full run, which used 4 parallel workers.",
          ]),
          p("Scorer revisions (made during the November 20 run; unchanged since)", H2),
          *bullets([
              "Smoke test: the first scorers counted notes, so a correct reply that restated its note in a Details list "
              "failed (0/3). Changed to count only notes attached to a title.",
              "Full run: 2 replies wrote '[Erratum: ...]' as a placeholder in a status sentence, and 9 already-annotated "
              "replies listed the new correction's note under Details. Both were scored as extra notes. Fixed and "
              "rescored from the saved replies without calling the agent: title 48 to 50/53, note 40 to 52/53.",
          ])]

# 5. Results
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
                [[n, r.loc[r.row_num == n, "case"].iloc[0], t] for n, t in sorted(DET_FAIL.items())], [0.5, 1.4, 4.6]),
          p("5.3 LLM judges", H2),
          p(f"<b>correctness</b> {frac('correctness')}. Failing rows:"),
          table([["Row", "Case", "Reason"]] +
                [[n, r.loc[r.row_num == n, "case"].iloc[0], t] for n, t in sorted(CORR_FAIL.items())], [0.5, 1.4, 4.6]),
          Spacer(1, 6),
          p(f"<b>no_fabrication</b> {frac('no_fabrication')}. Reading the 11 rationales: all are judge errors. The "
            "deterministic scorers found no invented title, note or MMS ID."),
          table([["Group", "Rows"]] + [[g, ", ".join(map(str, rows))] for g, rows in FAB_GROUPS], [5.0, 1.5]),
          p("Rows 6, 9, 16, 19 and 39 pass the deterministic scorers only because they give no annotation; the "
            "deterministic scorers do not check that the reply explains why.", SMALL),
          p("5.4 Compared with the November 20 run", H2),
          table([["Scorer", "November 20", "November 21"]] +
                [[k, f"{int(prev.loc[pm, k].sum())}/{int(pm.sum())}", f"{M[k][0]}/{M[k][1]}"]
                 for k, pm in [("annotated_title_exact", prev.index == prev.index),
                               ("erratum_note_exact", prev.index == prev.index),
                               ("original_mms_id_match", prev["case"].isin(["annotated", "already_annotated"])),
                               ("called_tool", ~prev["case"].isin(["manual_review", "no_file_no_original"])),
                               ("correctness", prev.index == prev.index),
                               ("no_fabrication", prev.index == prev.index)]] +
                [["Median latency", f"{prev.latency_s.median():.1f} s", f"{lat.median():.1f} s"]],
                [2.5, 2.0, 2.0]),
          p("Between the runs, mcp-erratum-note gained error handling and the agent instructions were updated "
            "(erratum-annotator/agent/README.md, instructions in use since November 21, 2026).", SMALL)]

# 6. Latency and tool use
tools = r["tools"].replace("", "(none)").value_counts()
story += [p("6. Latency and tool use", H1),
          table([["Measure", "Value"],
                 ["Per-request latency (53 rows)", f"mean {lat.mean():.1f} s, median {lat.median():.1f} s, "
                                                  f"p90 {lat.quantile(0.9):.1f} s, max {lat.max():.1f} s"],
                 ["Rows with an SRU file", f"median {r.loc[has_file, 'latency_s'].median():.1f} s (one tool call, one approval)"],
                 ["Rows without an SRU file", f"median {r.loc[~has_file, 'latency_s'].median():.1f} s (mostly no tool call)"],
                 ["Slowest row", f"row {int(r.loc[lat.idxmax(), 'row_num'])}: {lat.max():.1f} s (reply correct)"],
                 ["Endpoint errors / truncated loops", f"{int((r.error != '').sum())} / {int(r.truncated.sum())}"]] +
                [[f"Tools used: {k}", f"{v} rows"] for k, v in tools.items()],
                [2.4, 4.1])]

# 7. Findings and recommendations
story += [p("7. Findings and recommendations", H1),
          *bullets([
              "<b>Take the catalog title from the tool result, not the reply.</b> The Supervisor Agent cannot output the "
              "curly apostrophe U+2019: given d’I in a plain message, it reports the character as U+0027. A stronger "
              "instruction (worked example, character check, title in a code block) gave 0 of 6 exact on rows 34 and 40, "
              "the same as before, so it was reverted. The tool's annotated_title is exact on all rows; librarians should "
              "copy it from the tool result, and tool_annotated_title_exact now scores it.",
              "<b>Finish the no-file rule.</b> Rows 6, 16, 19 and 39 now say manual review instead of asking for XML (all 5 "
              "asked on November 20). Row 9 still asks for SRU XML, and row 39 says manual review where the ground truth "
              "is 'no original in Alma'. Add a deterministic scorer that checks for that wording.",
              "<b>Track Supervisor latency and timeouts.</b> No timeouts in this run (1/53 on November 20), but row 13 took "
              f"{lat.max():.0f} s against a median of {lat.median():.1f} s. Detect a 'Request Time Out' reply in the "
              "predict function and retry once.",
              "<b>Replace or ground the no_fabrication judge.</b> All 11 of its failures here are judge errors (10 of 16 on "
              "November 20). Either pass the "
              "tool outputs to the judge as context, or use a deterministic check that every MMS ID and DOI in the reply "
              "appears in a tool output.",
              "<b>Validate scorers on real replies.</b> Synthetic self-checks passed, but real replies restated notes "
              "and used placeholders. Keep the smoke test and the regression cases.",
              "<b>Grow the dataset.</b> Add Sample3 (142 rows) once its SRU responses are saved, plus multi-correction "
              "responses and needs_review cases.",
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
            "or set needs_review to true."),
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
                 ["Inspector Gadget test notebook",
                  "/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/mcp-erratum-note Inspector Gadget Test"],
                 ["Inspector Gadget results", IG_CSV]],
                [1.5, 5.0], code_cols=(1,)),
          Spacer(1, 4),
          p("To reproduce: run the evaluation notebook top to bottom (cells 2 to 4 need no agent calls), then this "
            "notebook. The rescore cell reapplies the deterministic scorers to saved replies.", SMALL)]


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
          "6. Latency and tool use", "7. Findings and recommendations", "8. MCP server test (Inspector Gadget)",
          "9. Artifacts and reproduction", "erratum_mcp_inspector_test", ig_frac("title_ok"), ig_frac("mms_ok"),
          f"median {ig.latency_sec.median():.2f} s",
          frac("annotated_title_exact"), frac("erratum_note_exact"), frac("original_mms_id_match"), frac("called_tool"),
          frac("correctness"), frac("no_fabrication"), runs["full_run_id"], runs["rescore_run_id"], runs["experiment_id"],
          runs["endpoint"], "U+2019", "48 to 50/53", "40 to 52/53", f"max {lat.max():.1f} s",
          "5.4 Compared with the November 20 run", "November 21, 2026", "row 13", "tool_annotated_title_exact", "U+0027"]
missing = [c for c in checks if c not in flat]
for c in checks:
    print("OK  " if c not in missing else "MISSING  ", c)
assert not missing, missing