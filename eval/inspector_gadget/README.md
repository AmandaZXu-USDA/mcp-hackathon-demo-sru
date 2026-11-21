# Inspector Gadget MCP test suite

[`ig_mcp_suite.py`](ig_mcp_suite.py) tests both deployed MCP apps from outside, as the Inspector Gadget service
principal, and writes the evidence to [`../results/runs/`](../results/README.md). The suites and pass rules are
described in [`../EVALUATION_FRAMEWORK.md`](../EVALUATION_FRAMEWORK.md#1-mcp-servers-inspector-gadget).

## Run it

In a Databricks notebook (serverless), from a clone of this repository:

```python
%pip install -q databricks-mcp databricks-sdk nest_asyncio
%restart_python
```

```python
import json, os, re, sys, nest_asyncio, pandas as pd
from databricks.sdk import WorkspaceClient
nest_asyncio.apply()
repo = "/Workspace/Users/<you>/<repo>"            # the repository root
sys.path.insert(0, f"{repo}/eval/inspector_gadget")
import ig_mcp_suite as ig

p = json.loads(dbutils.secrets.get(catalog="models", schema="ai", key="inspector-gadget"))
gadget = WorkspaceClient(host=WorkspaceClient().config.host, client_id=p["client_id"],
                         client_secret=p["client_secret"], scopes=p["scopes"])

# Ground truth 1: the 41 labelled notices (path differs per repository)
sru_rows = pd.read_csv(f"{repo}/<path to>/datasets/sru-eval-0.csv", dtype=str).to_dict("records")

# Ground truth 2: librarian-checked Sample 1, keyed by saved response file
gt = pd.read_csv("/Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv",
                 encoding="utf-8-sig", dtype=str)
clean = lambda v: v.strip().lstrip("=").strip('"') if isinstance(v, str) else ""
truth = {}
for f in sorted(os.listdir("/Volumes/users/amanda_xu/erratum_files/sru_responses")):
    m = re.match(r"Sample1-Row(\d+)-", f)
    if not m:  # other samples (e.g. Sample2-Row3-...) have no librarian-checked ground truth here
        continue
    row = gt[gt.row_num == m.group(1)].iloc[0]
    oid = clean(row.original_mms_id)
    truth[f] = {"original_mms_id": oid, "annotated_title": row.annotated_title if oid else ""}

ig.run_all(gadget, repo, sru_rows, truth, tester="Inspector Gadget (service principal <id>)",
           git_commit="<commit>")
```

`sru-eval-0.csv` is at `sru-syntax-mcp/eval/databricks/datasets/` in AmandaZXu-USDA/NAL and at
`eval/databricks/datasets/` in AmandaZXu-USDA/mcp-hackathon-demo-sru.

Requirements: Inspector Gadget needs `CAN USE` on both apps. A run takes about 2 minutes and calls only
read-only tools. Each run adds a folder `results/runs/<UTC start>_<app>_<run id>/` and rewrites
`results/INDEX.json` (sha256 of every evidence file). Files that look like they hold a credential are not written.

## Checks done on the suite itself

* The URL rule in `expected_sru_url` gives the same URL as the governed function `users.amanda_xu.build_sru_url`
  for all 41 labelled notices, and reproduces a URL a librarian confirmed works in Alma.
* The first erratum run of 2026-11-21 failed 2 `enhance_title` cases because the check expected plain text; the
  tool returns JSON (`annotated_title`, `already_annotated`), as its description says. The check was fixed and the
  suite rerun; that first run is not kept as evidence.
