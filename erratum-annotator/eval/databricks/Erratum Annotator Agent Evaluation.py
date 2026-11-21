# Databricks notebook source
# DBTITLE 1,About this evaluation
# MAGIC %md
# MAGIC # Offline evaluation: agent-erratum-annotator
# MAGIC
# MAGIC Evaluates the Supervisor Agent **agent-erratum-annotator** (endpoint `mas-c341c0aa-endpoint`; tools: MCP app `mcp-erratum-note` + UC function `users.amanda_xu.process_sru_response`) with `mlflow.genai.evaluate`.
# MAGIC
# MAGIC **Ground truth:** `/Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv` (53 rows, librarian-checked). Saved SRU responses: `.../erratum_files/sru_responses/` (48 files).
# MAGIC
# MAGIC **Each row** is a request a librarian would send: the correction notice title, its erratum MMS ID and, when saved, the SRU response file name. The agent should return the original article title with the erratum note appended, or say why it cannot (no original in Alma, bare "Correction" title).
# MAGIC
# MAGIC | Scorer | Kind | Passes when |
# MAGIC |---|---|---|
# MAGIC | `annotated_title_exact` | Deterministic (primary) | Final reply contains the expected annotated title exactly and no other note is attached to a title (restating the note after a label is allowed); or, when none is expected, no note is attached to a title |
# MAGIC | `erratum_note_exact` | Deterministic | The note(s) attached to a title equal the expected `[Erratum: ...]` note (diagnoses title vs. note errors). Notes after a label (e.g. the new correction's note under Details) and placeholders like `[Erratum: ...]` are ignored |
# MAGIC | `original_mms_id_match` | Deterministic | Expected original MMS ID appears in the reply or tool output. Not-applicable rows score True; the last cell reports the rate over applicable rows only |
# MAGIC | `called_tool` | Deterministic | A file row was answered via a `process_sru*` tool call. Rows without a file score True; the last cell reports the rate over file rows only |
# MAGIC | `correctness` | LLM judge | Reply contains the row's `expected_facts` |
# MAGIC | `no_fabrication` | LLM guideline | No invented titles, notes, DOIs or IDs; failures and manual-review cases are stated plainly |
# MAGIC
# MAGIC Deterministic scorers strip markdown escapes, bold and backticks before comparing (hyphens are not normalized). Rows 4 and 24 (`case = file_but_no_original`) have an SRU file but a blank expected title: presenting the search_title fallback as the annotated title fails.
# MAGIC
# MAGIC Run cells in order. Cell 4 checks the scorers against the ground truth itself (no agent calls); cell 6 is a 3-row smoke test before the full run.

# COMMAND ----------

# DBTITLE 1,Install libraries
# MAGIC %pip install -q -U "mlflow[databricks]>=3.4" openai httpx
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Config and evaluation dataset
import os, re, unicodedata
import pandas as pd
import mlflow

# --- CONFIG ---------------------------------------------------------------
ENDPOINT = "mas-c341c0aa-endpoint"  # agent-erratum-annotator (Supervisor Agent)
EXPERIMENT_PATH = "/Users/amanda.xu@usda.gov/agent-erratum-annotator-eval"
GROUND_TRUTH = "/Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv"
SRU_DIR = "/Volumes/users/amanda_xu/erratum_files/sru_responses"
MAX_ROWS = None  # e.g. 10 for a quick run
os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "3")  # keep load on the agent low
# --------------------------------------------------------------------------

mlflow.set_experiment(EXPERIMENT_PATH)


def _unexcel(v: str) -> str:
    """The .csv is Excel-formatted: IDs are written as =\"9917...\"; strip that wrapper."""
    v = (v or "").strip()
    m = re.fullmatch(r'="(.*)"', v)
    return m.group(1) if m else v


gt = pd.read_csv(GROUND_TRUTH, encoding="utf-8-sig", dtype=str, keep_default_na=False)
for c in ("erratum_mms_id", "original_mms_id"):
    gt[c] = gt[c].map(_unexcel)

# Saved SRU responses are named Sample1-Row<n>-<erratum MMS ID>.xml
sru_files = {}
for f in os.listdir(SRU_DIR):
    m = re.match(r"Sample1-Row(\d+)-(\d{16})\.xml$", f)
    if m:
        sru_files[int(m.group(1))] = f


def build_row(r) -> dict:
    n = int(r.row_num)
    f = sru_files.get(n, "")
    expected = r.annotated_title.strip()
    status = r.erratum_status.strip()
    request = (f'Annotate the original article title for the correction notice "{r.erratum_title}" '
               f"(erratum MMS ID {r.erratum_mms_id}).")
    request += f" The saved SRU response file is {f}." if f else " No SRU response file is saved for this notice."
    if not f and not expected and "manual" not in status:
        # Rows 9 and 39: the librarian's Alma search found only the correction notice. The request passes that
        # search result on, as a librarian would; the agent cannot tell it from a missing file alone.
        request += " The librarian's Alma search found only the correction notice; the original article is not in Alma."
    note = re.search(r"\[Erratum:.*?\]", expected)
    if expected:
        case = "already_annotated" if status.startswith("already") else "annotated"
        facts = [f'The annotated original title is "{expected}"']
        if r.original_mms_id:
            facts.append(f"The original article's MMS ID is {r.original_mms_id}")
        if case == "already_annotated":
            facts.append("The original title already carried an erratum note, so no second note was added")
    elif "manual" in status:
        case = "manual_review"
        facts = ["No annotated title is given: the notice is a generic 'Correction' title that needs manual review"]
    elif f:
        # Rows 4 and 24: the SRU file has only the correction record. The librarian ground truth is blank,
        # so a search_title fallback presented as the annotated original title is a failure.
        case = "file_but_no_original"
        facts = ["No annotated title is given: the original article is not in Alma (only the correction notice "
                 "is); the response does not present the search_title fallback as the annotated original title"]
    else:
        case = "no_file_no_original"
        facts = ["No annotated title is given: the original article is not in Alma (only the correction notice is)"]
    return {
        "inputs": {"request": request},
        "expectations": {
            "expected_annotated_title": expected,
            "expected_erratum_note": note.group(0) if note else "",
            "expected_original_mms_id": r.original_mms_id,
            "has_sru_file": bool(f),
            "expected_facts": facts,
        },
        "tags": {"row_num": str(n), "erratum_status": status, "has_sru_file": str(bool(f)), "case": case},
    }


eval_dataset = [build_row(r) for r in gt.itertuples(index=False)]
if MAX_ROWS:
    eval_dataset = eval_dataset[:MAX_ROWS]

print(f"{len(eval_dataset)} rows; {sum(r['expectations']['has_sru_file'] for r in eval_dataset)} with an SRU file")
print(gt["erratum_status"].value_counts().to_string())
print(pd.Series([r["tags"]["case"] for r in eval_dataset]).value_counts().to_string())
display(pd.DataFrame([{**r["tags"], "request": r["inputs"]["request"],
                       "expected_annotated_title": r["expectations"]["expected_annotated_title"]}
                      for r in eval_dataset]).head(10))

# COMMAND ----------

# DBTITLE 1,Scorers and self-check against ground truth
import json

from mlflow.entities import Feedback
from mlflow.genai.scorers import Correctness, Guidelines, scorer

NOTE_RE = re.compile(r"\[Erratum:[^\]]*\]")
# Placeholders used in prose ("the title already contains an [Erratum: ...] note") are not notes.
PLACEHOLDER_RE = re.compile(r"\[Erratum:\s*(?:\.{2,}|\u2026)?\s*\]")


def _real_notes(text: str) -> list:
    return [m for m in NOTE_RE.findall(text or "") if not PLACEHOLDER_RE.fullmatch(m)]


def _n(s: str) -> str:
    """Strip markdown escapes/bold/backticks, then NFC + collapse whitespace. Hyphens are NOT normalized."""
    s = s or ""
    s = re.sub(r"\\([\[\]()*_`])", r"\1", s)  # \[ -> [, \_ -> _, ...
    s = re.sub(r"\*\*|`", "", s)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "")).strip()


def _reply(outputs) -> str:
    return outputs.get("response", "") if isinstance(outputs, dict) else str(outputs or "")


def _tool_calls(outputs) -> list:
    return outputs.get("tool_calls", []) if isinstance(outputs, dict) else []


def _appended_notes(text: str) -> list:
    """Notes attached to title text on the same line, i.e. presented as part of an annotated title.
    A note on its own line or after a label ('Erratum note: [Erratum: ...]', table cell) does not count,
    so restating the note in a details section is allowed."""
    found = []
    for line in (text or "").splitlines():
        line = _n(line)
        for m in NOTE_RE.finditer(line):
            if PLACEHOLDER_RE.fullmatch(m.group(0)):
                continue
            before = re.sub(r"^[\s>*\-\u2022\d.)]+", "", line[:m.start()]).strip()
            if before and not before.endswith((":", "|")):
                found.append(m.group(0))
    return found


@scorer
def annotated_title_exact(outputs, expectations) -> Feedback:
    exp, got = _n(expectations["expected_annotated_title"]), _n(_reply(outputs))
    appended = _appended_notes(_reply(outputs))
    if not exp:
        return Feedback(value=not appended, rationale="No annotation expected; " + (
            f"reply presents an annotated title with {appended[0]}" if appended else "no annotated title given"))
    if exp not in got:
        return Feedback(value=False, rationale=f"Expected: {exp}")
    # Double annotation: another note right after the expected title, or a different note attached to a title.
    extra = sorted(set(appended) - set(NOTE_RE.findall(exp)))
    if (exp + " [Erratum:") in got or extra:
        return Feedback(value=False, rationale=f"Expected title found, but an extra note was attached: {extra or 'repeated note'}")
    return Feedback(value=True, rationale="Exact annotated title found, no extra note")


@scorer
def erratum_note_exact(outputs, expectations) -> Feedback:
    exp = _n(expectations["expected_erratum_note"])
    appended = _appended_notes(_reply(outputs))
    if not exp:
        return Feedback(value=not appended, rationale="No annotation expected; " + (
            f"reply attaches {appended[0]} to a title" if appended else "no note attached to a title"))
    # Judge the note(s) attached to a title. Notes after a label (e.g. the new correction's note listed
    # under Details for an already-annotated title) are ignored. If no note is attached to a title
    # (title and note on separate lines), fall back to every real note in the reply.
    notes = appended or [_n(x) for x in _real_notes(_n(_reply(outputs)))]
    distinct = set(notes)
    ok = distinct == {exp}
    if ok:
        why = "Note matches"
    elif exp in distinct:
        why = f"Expected note found, but the reply also has {sorted(distinct - {exp})}"
    else:
        why = f"Expected {exp}; got {notes or 'no note'}"
    return Feedback(value=ok, rationale=why)


@scorer
def original_mms_id_match(outputs, expectations) -> Feedback:
    exp = expectations["expected_original_mms_id"]
    if not exp:
        return Feedback(value=True, rationale="Not applicable: no original MMS ID expected")
    haystack = _reply(outputs) + " " + " ".join(str(t) for t in _tool_calls(outputs))
    return Feedback(value=exp in haystack, rationale=f"Original MMS ID {exp} " + ("found" if exp in haystack else "not found in reply or tool output"))


@scorer
def called_tool(outputs, expectations) -> Feedback:
    if not expectations["has_sru_file"]:
        return Feedback(value=True, rationale="Not applicable: no SRU file for this row")
    names = [t.get("name") or "" for t in _tool_calls(outputs)]
    ok = any("process_sru" in n for n in names)
    return Feedback(value=ok, rationale=f"Tools called: {names or 'none'}")


def _tool_results(outputs) -> list:
    """JSON results of process_sru_file / process_sru_response calls, in call order (approval requests skipped)."""
    found = []
    for t in _tool_calls(outputs):
        if "process_sru" not in (t.get("name") or ""):
            continue
        try:
            d = json.loads(t.get("output") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(d, dict):
            found.append(d)
    return found


@scorer
def tool_annotated_title_exact(outputs, expectations) -> Feedback:
    """The catalog title a librarian copies: the tool's annotated_title field, compared exactly (NFC only).

    The Supervisor Agent cannot output the curly apostrophe U+2019 (it writes U+0027), so the reply text can
    differ from the catalog title even when the tool is right; this scorer checks the tool result itself.
    Uses the last process_sru* result. When no annotation is expected, passes unless a tool result reports an
    original record (original_id) with an annotated title.
    """
    exp = unicodedata.normalize("NFC", expectations["expected_annotated_title"] or "").strip()
    res = _tool_results(outputs)
    if not exp:
        bad = [d for d in res if d.get("original_id") and d.get("annotated_title")]
        return Feedback(value=not bad, rationale="No annotation expected; " + (
            f"tool reported original {bad[-1]['original_id']} with a title" if bad else "no original record in tool results"))
    if not res:
        return Feedback(value=False, rationale="No process_sru_file / process_sru_response result")
    got = unicodedata.normalize("NFC", res[-1].get("annotated_title") or "").strip()
    return Feedback(value=got == exp, rationale="Tool annotated_title matches" if got == exp else f"Tool returned: {got}")


SCORERS = [
    annotated_title_exact,  # primary
    erratum_note_exact,
    original_mms_id_match,
    called_tool,
    tool_annotated_title_exact,  # catalog title from the tool result (reply can lose U+2019)
    Correctness(),  # LLM judge on expected_facts
    Guidelines(
        name="no_fabrication",
        guidelines=[
            "The response only reports annotated titles, erratum notes, DOIs and MMS IDs that come from the "
            "tool results; it does not invent or alter them.",
            "If no annotated title can be produced (no original record, a generic 'Correction' title, or a tool "
            "error), the response says so plainly instead of guessing.",
        ],
    ),
]

# --- Self-check: the deterministic scorers must pass on the ground truth itself and fail on a corrupted note.
DET = [annotated_title_exact, erratum_note_exact, original_mms_id_match, called_tool, tool_annotated_title_exact]
fails, caught = [], 0
for r in eval_dataset:
    e = r["expectations"]
    perfect = {"response": e["expected_annotated_title"] or "No annotated title: needs manual review.",
               "tool_calls": [{"name": "process_sru_file", "output": json.dumps(
                   {"original_id": e["expected_original_mms_id"], "annotated_title": e["expected_annotated_title"]},
                   ensure_ascii=False)}]}
    for s in DET:
        if s(outputs=perfect, expectations=e).value is not True:
            fails.append((r["tags"]["row_num"], s.name))
    if e["expected_erratum_note"]:
        broken = {**perfect, "response": perfect["response"].replace("[Erratum: ", "[Erratum: X ")}
        caught += annotated_title_exact(outputs=broken, expectations=e).value is False
# Doubled note must fail; markdown-escaped + bold expected title must pass.
doubled_caught, escaped_ok, escaped_fail = 0, 0, []
for r in eval_dataset:
    e = r["expectations"]
    if not e["expected_erratum_note"]:
        continue
    tools = [{"name": "process_sru_file", "output": e["expected_original_mms_id"]}]
    doubled = {"response": e["expected_annotated_title"] + " [Erratum: X]", "tool_calls": tools}
    doubled_caught += annotated_title_exact(outputs=doubled, expectations=e).value is False
    md = "**" + e["expected_annotated_title"].replace("[", "\\[").replace("]", "\\]") + "**"
    escaped = {"response": md, "tool_calls": tools}
    if annotated_title_exact(outputs=escaped, expectations=e).value is True and \
            erratum_note_exact(outputs=escaped, expectations=e).value is True:
        escaped_ok += 1
    else:
        escaped_fail.append(r["tags"]["row_num"])

n_notes = sum(bool(r["expectations"]["expected_erratum_note"]) for r in eval_dataset)
print(f"Ground truth as output: {len(fails)} scorer failures {fails[:5]}")
print(f"Corrupted notes caught: {caught}/{n_notes}")
print(f"Doubled notes caught: {doubled_caught}/{n_notes}")
print(f"Markdown-escaped titles passing: {escaped_ok}/{n_notes} {escaped_fail[:5]}")
assert not fails and caught == n_notes == doubled_caught == escaped_ok, "Scorer self-check failed"

# Regression cases from the full run (rows 26, 32 and 9 already-annotated rows): a placeholder note in prose
# and the new correction's note listed under Details must pass; a second note attached to the title must fail.
e = next(r for r in eval_dataset if r["tags"]["case"] == "already_annotated")["expectations"]
prose = {"response": e["expected_annotated_title"] + "\n- Status: the title already contains an [Erratum: ...] note."
                     "\n- Erratum note: [Erratum: Jan. 2000, v. 1, 1, 10.0000/x]", "tool_calls": []}
attached = {"response": e["expected_annotated_title"] + " [Erratum: Jan. 2000, v. 1, 1, 10.0000/x]", "tool_calls": []}
assert annotated_title_exact(outputs=prose, expectations=e).value is True
assert erratum_note_exact(outputs=prose, expectations=e).value is True
assert annotated_title_exact(outputs=attached, expectations=e).value is False
assert erratum_note_exact(outputs=attached, expectations=e).value is False
# tool_annotated_title_exact: a straight apostrophe in the tool's title must fail; a straight apostrophe in the
# reply alone (rows 34 and 40) must not affect it.
curly = [r for r in eval_dataset if "\u2019" in r["expectations"]["expected_annotated_title"]]
for r in curly:
    e = r["expectations"]
    tool = lambda title: [{"name": "process_sru_file", "output": json.dumps(
        {"original_id": e["expected_original_mms_id"], "annotated_title": title}, ensure_ascii=False)}]
    straight = e["expected_annotated_title"].replace("\u2019", "'")
    assert tool_annotated_title_exact(outputs={"response": straight, "tool_calls": tool(straight)}, expectations=e).value is False
    assert tool_annotated_title_exact(outputs={"response": straight, "tool_calls": tool(e["expected_annotated_title"])},
                                      expectations=e).value is True
    assert annotated_title_exact(outputs={"response": straight, "tool_calls": []}, expectations=e).value is False
no_tool = next(r for r in eval_dataset if r["expectations"]["expected_annotated_title"])["expectations"]
assert tool_annotated_title_exact(outputs={"response": no_tool["expected_annotated_title"], "tool_calls": []},
                                  expectations=no_tool).value is False
print(f"Regression checks passed (tool title: {len(curly)} rows with U+2019)")

# COMMAND ----------

# DBTITLE 1,Predict function: call the agent endpoint
import json
from databricks.sdk import WorkspaceClient

client = WorkspaceClient().serving_endpoints.get_open_ai_client().with_options(timeout=300, max_retries=2)
MAX_ROUNDS = 8  # approval round trips per request


def _dump(item) -> dict:
    return item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else dict(item)


@mlflow.trace(span_type="AGENT", name="agent_erratum_annotator")
def predict(request: str) -> dict:
    """Query the Supervisor Agent; auto-approve its MCP tool calls (mcp-erratum-note needs approval).

    Returns {response: assistant text of the LAST round (the final answer), all_text: text of every round,
             tool_calls: [{type, name, arguments, output}], truncated: approvals still pending after
             MAX_ROUNDS, error: exception text or ''}. Scorers read `response`.
    """
    history = [{"role": "user", "content": request}]
    texts, tool_calls, approvals = [], [], []
    final_text = ""
    for _ in range(MAX_ROUNDS):
        try:
            resp = client.responses.create(model=ENDPOINT, input=history)
        except Exception as e:
            return {"response": final_text, "all_text": "\n".join(texts).strip(), "tool_calls": tool_calls,
                    "truncated": False, "error": f"{type(e).__name__}: {e}"}
        items = [_dump(i) for i in resp.output]
        history += items
        approvals, round_texts = [], []
        for it in items:
            t = it.get("type")
            if t == "message":
                round_texts += [c.get("text", "") for c in it.get("content", []) if c.get("type") == "output_text"]
                continue
            tool_calls.append({"type": t, "name": it.get("name"), "arguments": it.get("arguments"),
                               "output": str(it.get("output", ""))[:4000]})
            if t == "mcp_approval_request":
                approvals.append({"type": "mcp_approval_response", "id": it["id"],
                                  "approval_request_id": it["id"], "approve": True})
        texts += round_texts
        final_text = "\n".join(round_texts).strip()  # last round only
        if not approvals:
            break
        history += approvals
    # approvals is non-empty only if MAX_ROUNDS ran out with tool calls still waiting for approval
    return {"response": final_text, "all_text": "\n".join(texts).strip(), "tool_calls": tool_calls,
            "truncated": bool(approvals), "error": ""}

# COMMAND ----------

# DBTITLE 1,Smoke test on 3 rows
# Rows 43 and 41 were annotated from the SRU file; row 4 has a file but no original in Alma.
smoke = [r for r in eval_dataset if r["tags"]["row_num"] in {"43", "41", "4"}]
smoke_results = mlflow.genai.evaluate(data=smoke, predict_fn=predict, scorers=SCORERS)
print(smoke_results.metrics)

# COMMAND ----------

# DBTITLE 1,Full evaluation run
results = mlflow.genai.evaluate(data=eval_dataset, predict_fn=predict, scorers=SCORERS)
for k, v in sorted(results.metrics.items()):
    print(f"{k:45s} {v:.3f}" if isinstance(v, float) else f"{k:45s} {v}")
# Per-row results and traces: experiment -> Evaluations tab.

# COMMAND ----------

# DBTITLE 1,Failures by row
import json

df = results.result_df.copy()
meta = {r["inputs"]["request"]: r for r in eval_dataset}


def _as_dict(v):
    """result_df cells may hold dicts or JSON strings depending on the MLflow version."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            j = json.loads(v)
            return j if isinstance(j, dict) else None
        except ValueError:
            return None
    return None


def _req(v) -> str:
    d = _as_dict(v)
    return d.get("request", "") if d else (v if isinstance(v, str) else "")


def _out(v) -> dict:
    d = _as_dict(v)
    return d if d else {"response": v if isinstance(v, str) else ""}


# Join row metadata from the dataset by request text (no dependence on a tags column).
req_col = "request" if "request" in df.columns else "inputs"
rows = df[req_col].map(lambda v: meta.get(_req(v)))
print(f"Rows matched to dataset: {rows.notna().sum()}/{len(df)}")
df["row_num"] = rows.map(lambda r: r["tags"]["row_num"] if r else None)
df["status"] = rows.map(lambda r: r["tags"]["erratum_status"] if r else None)
df["case"] = rows.map(lambda r: r["tags"]["case"] if r else None)
df["expected_original_mms_id"] = rows.map(lambda r: r["expectations"]["expected_original_mms_id"] if r else "")
df["has_sru_file"] = rows.map(lambda r: bool(r and r["expectations"]["has_sru_file"]))

out_col = "response" if "response" in df.columns else "outputs"
outs = df[out_col].map(_out)
df["reply"] = outs.map(lambda o: o.get("response", ""))
df["error"] = outs.map(lambda o: o.get("error", ""))
df["truncated"] = outs.map(lambda o: bool(o.get("truncated", False)))

val = lambda name: next(c for c in df.columns if c.startswith(name) and c.endswith("value"))
passed = lambda col: df[col].astype(str) == "True"
primary = val("annotated_title_exact")
df["_primary_pass"] = passed(primary)

for key in ("status", "case"):
    print(f"\nannotated_title_exact by {key}:")
    print(df.groupby(key)["_primary_pass"].agg(lambda s: f"{s.sum()}/{len(s)}").to_string())

# Applicable-only rates (the scorers return True for not-applicable rows, which inflates results.metrics).
m = df["expected_original_mms_id"] != ""
print(f"\noriginal_mms_id_match (rows with an expected original MMS ID): "
      f"{passed(val('original_mms_id_match'))[m].sum()}/{m.sum()}")
f = df["has_sru_file"]
print(f"called_tool (rows with an SRU file): {passed(val('called_tool'))[f].sum()}/{f.sum()}")
print(f"Rows with error: {(df['error'] != '').sum()}; truncated: {df['truncated'].sum()}")

cols = ["row_num", "case", "status", "reply", "error", "truncated"] + [val(s.name) for s in DET]
display(df.loc[~df["_primary_pass"], cols])

# COMMAND ----------

# DBTITLE 1,Rescore saved outputs (no agent calls)
# Re-apply the current deterministic scorers to the full run's saved replies, without calling the agent again.
# LLM judge scores are unchanged: see the full run. Logs a separate run in the same experiment.
rescore_data = []
for _, x in results.result_df.iterrows():
    r = meta[_req(x[req_col])]
    rescore_data.append({"inputs": r["inputs"], "outputs": _out(x[out_col]),
                         "expectations": r["expectations"], "tags": r["tags"]})
rescored = mlflow.genai.evaluate(data=rescore_data, scorers=DET)

rd = rescored.result_df.copy()
rrows = rd["request" if "request" in rd.columns else "inputs"].map(lambda v: meta.get(_req(v)))
rd["row_num"] = rrows.map(lambda r: r["tags"]["row_num"])
rd["case"] = rrows.map(lambda r: r["tags"]["case"])
rd_val = lambda name: next(c for c in rd.columns if c.startswith(name) and c.endswith("value"))
rd_ok = lambda name: rd[rd_val(name)].astype(str) == "True"

for s in DET:
    try:
        before = f"{passed(val(s.name)).sum():>2}/{len(df)}"
    except StopIteration:  # scorer added after the full run
        before = "   -"
    print(f"{s.name:27s} before {before}  after {rd_ok(s.name).sum():>2}/{len(rd)}")
m = rrows.map(lambda r: bool(r["expectations"]["expected_original_mms_id"]))
print(f"original_mms_id_match (applicable rows): {rd_ok('original_mms_id_match')[m].sum()}/{m.sum()}")
print("\nannotated_title_exact by case:")
print(rd.assign(_p=rd_ok("annotated_title_exact")).groupby("case")["_p"].agg(lambda s: f"{s.sum()}/{len(s)}").to_string())

rat = lambda name: next(c for c in rd.columns if c.startswith(name) and c.endswith("rationale"))
bad = rd[~(rd_ok("annotated_title_exact") & rd_ok("erratum_note_exact"))]
display(bad[["row_num", "case", rd_val("annotated_title_exact"), rat("annotated_title_exact"),
             rd_val("erratum_note_exact"), rat("erratum_note_exact")]]
        .sort_values("row_num", key=lambda s: s.astype(int)))

# COMMAND ----------

# DBTITLE 1,Save per-row results for the report
# Per-row results (deterministic scores from the rescore, judge scores from the full run) for the report notebook.
import json, os

RESULTS_DIR = "/Workspace/Users/amanda.xu@usda.gov/erratum-annotator/eval/doc"
os.makedirs(RESULTS_DIR, exist_ok=True)

rs = rd.set_index("row_num")
exp_by_row = {r["tags"]["row_num"]: r["expectations"] for r in eval_dataset}
judge = lambda c: df[val(c)].astype(str).str.lower().isin(["yes", "true"])
rat_df = lambda c: next(x for x in df.columns if x.startswith(c) and x.endswith("rationale"))
out = pd.DataFrame({
    "row_num": df["row_num"].astype(int),
    "case": df["case"],
    "erratum_status": df["status"],
    "latency_s": (df["execution_duration"] / 1000).round(1),
    "tools": df[out_col].map(lambda o: ";".join(sorted({t["name"] for t in _out(o).get("tool_calls", []) if t.get("name")}))),
    "error": df["error"], "truncated": df["truncated"],
    **{s.name: df["row_num"].map(lambda n, s=s: str(rs.loc[n, rd_val(s.name)]) == "True") for s in DET},
    "correctness": judge("correctness"), "no_fabrication": judge("no_fabrication"),
    "title_rationale": df["row_num"].map(lambda n: rs.loc[n, rat("annotated_title_exact")]),
    "correctness_rationale": df[rat_df("correctness")],
    "no_fabrication_rationale": df[rat_df("no_fabrication")],
    "expected_annotated_title": df["row_num"].map(lambda n: exp_by_row[n]["expected_annotated_title"]),
    "reply": df["reply"].str.slice(0, 2000),
}).sort_values("row_num")

csv_path = f"{RESULTS_DIR}/agent-erratum-annotator-eval-results-20261120.csv"
out.to_csv(csv_path, index=False)
run_info = {"experiment": EXPERIMENT_PATH, "experiment_id": mlflow.get_experiment_by_name(EXPERIMENT_PATH).experiment_id,
            "full_run_id": results.run_id, "rescore_run_id": rescored.run_id, "smoke_run_id": smoke_results.run_id,
            "endpoint": ENDPOINT, "rows": len(out)}
with open(f"{RESULTS_DIR}/agent-erratum-annotator-eval-runs-20261120.json", "w") as fh:
    json.dump(run_info, fh, indent=2)
print(csv_path, len(out), "rows"); print(run_info)
print(out[[s.name for s in DET] + ["correctness", "no_fabrication"]].sum().to_string())