"""Build a standalone, offline copy of the mcp-erratum-note demo page.

The output is one HTML file with every saved SRU response already annotated, for NAL staff who have no
Databricks workspace account. It runs in any browser with no server and no sign-in; it cannot annotate
pasted XML. Results come from the same code as the app (erratum_annotator.py).

Run from this folder on Databricks (reads the saved responses with your credentials):
    python build_offline_demo.py [output.html]
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))

import app  # noqa: E402  (the deployed app module; provides the page and the helpers)

LIVE_URL = "https://mcp-erratum-note-7474654188777746.aws.databricksapps.com"

LOCAL_CALL = """  async function call(url) {
    var D = JSON.parse(document.getElementById("demo-data").textContent);
    if (url === "api/examples") return { folder: D.folder, examples: D.examples };
    if (url === "api/annotate-all") return D.all;
    throw new Error("Not available in the offline copy.");
  }
  async function annotateLocal(fileName) {
    var D = JSON.parse(document.getElementById("demo-data").textContent);
    var d = D.results[fileName]; if (!d) throw new Error("No saved result for that notice."); return d;
  }"""


def build(out_path: str) -> dict:
    examples = app._load_examples()
    results = {ex["file_name"]: app._explain(app._cache["xml"][ex["file_name"]], "", ex["correction_id"])
               for ex in examples}
    rows = [{"sample": ex["sample"], "row": ex["row"], "label": ex["label"], "file_name": ex["file_name"],
             "status": results[ex["file_name"]]["status"],
             "correction_title": results[ex["file_name"]]["correction_title"],
             "annotated_title": results[ex["file_name"]]["annotated_title"]} for ex in examples]
    data = {"folder": app.SRU_DIR, "examples": examples, "results": results,
            "all": {"count": len(rows), "rows": rows,
                    "elapsed_ms": round(sum(r["elapsed_ms"] for r in results.values()), 1)}}

    html = app.DEMO_PAGE.replace(' nonce="__NONCE__"', "").replace("__RECORD_URL__", json.dumps(app.SRU_RECORD_URL))
    # no server: answer the page's requests from the embedded results
    html = re.sub(r"  async function call\(url, opts\) \{.*?\n  \}\n", lambda m: LOCAL_CALL + "\n", html, count=1, flags=re.S)
    html = html.replace(
        'var d = await call("api/annotate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });',
        "var d = await annotateLocal(body.file_name);")
    html = html.replace('" ms by the same code as the MCP server and the SQL function.',
                        '" ms when this copy was built, by the same code as the MCP server and the SQL function.')
    html = html.replace(' s (including the network).";', ' s.";')
    html = re.sub(r"<details>\s*<summary>Paste your own SRU response.*?</details>\n", "", html, count=1, flags=re.S)
    html = re.sub(r'  document.getElementById\("goxml"\).*?\n  \}\);\n', "", html, count=1, flags=re.S)
    html = html.replace("in about a second.</p>",
        "in about a second.</p>\n  <p class=\"meta\"><strong>Offline copy</strong> built "
        + datetime.date.today().isoformat() + " from the " + str(len(examples))
        + " saved SRU responses; it needs no sign-in and no network. The live version, which also accepts "
        "pasted SRU XML, is <a href=\"" + LIVE_URL + "\">" + LIVE_URL + "</a> (needs a NAL Databricks account).</p>")
    html = html.replace("<head>\n<meta charset=\"utf-8\">", "<head>\n<meta charset=\"utf-8\">\n"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("<script>", "<script type=\"application/json\" id=\"demo-data\">" + payload + "</script>\n<script>", 1)
    assert "__NONCE__" not in html and "api/annotate\"" not in html and "goxml" not in html, "page template changed"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return {"notices": len(examples), "bytes": len(html.encode("utf-8"))}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "erratum-annotator-demo-offline.html")
    print(build(out))
