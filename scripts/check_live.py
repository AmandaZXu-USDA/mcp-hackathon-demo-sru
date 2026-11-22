"""Quick check that both live MCP apps answer correctly (about 30 seconds).

Usage (OAuth credentials from the SDK default chain: `databricks auth login`, or a
service principal's DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET; a personal
access token is not accepted by Databricks Apps):

    python scripts/check_live.py [--warehouse-id <id>]
                                 [--uc-secret <catalog.schema.key>]

With --uc-secret (in a Databricks job or notebook), sign in as the service principal
whose JSON credentials (client_id, client_secret, scopes) are in that Unity Catalog
secret; the daily job uses models.ai.inspector-gadget.

Checks, against known answers:

  mcp-erratum-note  tools/list has the 7 tools, all marked read-only;
                    process_sru_file on Sample 1 row 1 gives the librarian's title;
                    the demo page's /api/examples lists every file in the volume.
  mcp-sru-syntax    build_sru_search_url on a curly-quoted title gives the URL for the
                    original title; with --warehouse-id, the same URL as the UC
                    function users.amanda_xu.build_sru_url.

Everything is read-only. Exit code 1 if any check fails. For the full suite (89 + 55
cases), use eval/inspector_gadget/.
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import quote

import requests
from databricks.sdk import WorkspaceClient

HOST = "7474654188777746.aws.databricksapps.com"
ERRATUM = f"https://mcp-erratum-note-{HOST}"
SRU = f"https://mcp-sru-syntax-{HOST}"
VOLUME_DIR = "/Volumes/users/amanda_xu/erratum_files/sru_responses"

ERRATUM_TOOLS = {
    "health", "parse_sru_response", "extract_erratum_note", "enhance_title",
    "process_sru_response", "list_sru_files", "process_sru_file",
}  # fmt: skip
ROW1_FILE = "Sample1-Row1-9916524607707426.xml"
ROW1_TITLE = (
    "STING-dependent trained immunity contributes to host defense against Clostridium"
    " perfringens infection via mTOR signaling"
    " [Erratum: Dec. 2024, v. 55, no. 1, 77, 10.1186/s13567-024-01322-w]"
)
SRU_TITLE = (
    "Correction to \u201cNatural haplotype variation in OsGSK3 fine\u2010tunes grain"
    " length via phosphorylating and stabilizing OsRanBP1 in rice\u201d"
)
SRU_ORIGINAL = (
    "Natural haplotype variation in OsGSK3 fine-tunes grain length via"
    " phosphorylating and stabilizing OsRanBP1 in rice"
)


class Mcp:
    """Minimal MCP streamable-HTTP client: initialize once, then JSON-RPC calls."""

    def __init__(self, url: str, headers: dict) -> None:
        self.url, self.n = url, 0
        self.headers = {
            **headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        info = {"name": "check_live", "version": "1"}
        params = {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": info,
        }
        r = self._post("initialize", params)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self.headers["mcp-session-id"] = sid
        note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        requests.post(url, headers=self.headers, json=note, timeout=30)

    def _post(self, method: str, params: dict) -> requests.Response:
        self.n += 1
        body = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}
        r = requests.post(self.url, headers=self.headers, json=body, timeout=120)
        r.raise_for_status()
        return r

    def request(self, method: str, params: dict) -> dict:
        r = self._post(method, params)
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            r.encoding = "utf-8"  # SSE has no charset; requests would guess ISO-8859-1
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:])
                    if msg.get("id") == self.n:
                        break
        else:
            msg = r.json()
        if "error" in msg:
            raise RuntimeError(msg["error"])
        return msg["result"]

    def tool_text(self, name: str, arguments: dict) -> str:
        res = self.request("tools/call", {"name": name, "arguments": arguments})
        if res.get("isError"):
            raise RuntimeError(res["content"])
        return "".join(c.get("text", "") for c in res["content"])


def uc_url(w: WorkspaceClient, warehouse: str) -> str:
    from databricks.sdk.service.sql import StatementParameterListItem

    st = w.statement_execution.execute_statement(
        warehouse_id=warehouse,
        statement="SELECT users.amanda_xu.build_sru_url(:t)",
        parameters=[StatementParameterListItem(name="t", value=SRU_TITLE)],
        wait_timeout="30s",
    )
    if not st.result or not st.result.data_array:
        raise RuntimeError(f"{st.status.state}: {st.status.error}")
    return st.result.data_array[0][0]


def run_checks(w: WorkspaceClient, auth: dict, warehouse: str | None) -> int:
    """Run the checks; `auth` reaches the apps, `w` reads the volume and the UC
    function. Each check is independent, so one failure does not hide the others."""
    failed = total = 0

    def check(name: str, test) -> None:
        nonlocal failed, total
        total += 1
        try:
            ok, detail = test()
        except Exception as exc:  # a check that cannot run counts as failed
            ok, detail = False, repr(exc)[:200]
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  - ' + detail if detail else ''}")

    def tools():
        listed = Mcp(f"{ERRATUM}/mcp", auth).request("tools/list", {})["tools"]
        names = {t["name"] for t in listed}
        ro = all((t.get("annotations") or {}).get("readOnlyHint") for t in listed)
        return names == ERRATUM_TOOLS and ro, f"{len(names)} tools, read-only: {ro}"

    def row1():
        e = Mcp(f"{ERRATUM}/mcp", auth)
        r = json.loads(e.tool_text("process_sru_file", {"file_name": ROW1_FILE}))
        return r.get("annotated_title") == ROW1_TITLE, ""

    def demo():
        got = requests.get(f"{ERRATUM}/api/examples", headers=auth, timeout=120)
        got.raise_for_status()
        listed = {x["file_name"] for x in got.json()["examples"]}
        files = {
            f.name
            for f in w.files.list_directory_contents(VOLUME_DIR)
            if f.name.lower().endswith(".xml")
        }
        return listed == files, f"demo {len(listed)}, volume {len(files)}"

    sru_text = ""

    def sru():
        nonlocal sru_text
        s = Mcp(f"{SRU}/mcp", auth)
        sru_text = s.tool_text("build_sru_search_url", {"correction_title": SRU_TITLE})
        return quote(f'alma.title="{SRU_ORIGINAL}"', safe="") in sru_text, ""

    check("erratum: 7 tools, all read-only", tools)
    check("erratum: Sample 1 row 1 annotated title", row1)
    check("erratum: demo lists every saved file", demo)
    check("sru: URL for the original title", sru)
    if warehouse:
        check(
            "sru: same URL as the UC function",
            lambda: (bool(sru_text) and uc_url(w, warehouse) in sru_text, ""),
        )
    print(f"{total - failed}/{total} checks passed")
    return 1 if failed else 0


def client(uc_secret: str | None) -> WorkspaceClient:
    """SDK default credentials, or a service principal's from a UC secret."""
    if not uc_secret:
        return WorkspaceClient()
    from databricks.sdk.runtime import dbutils  # only available on Databricks

    catalog, schema, key = uc_secret.split(".", 2)
    p = json.loads(dbutils.secrets.get(catalog=catalog, schema=schema, key=key))
    return WorkspaceClient(
        host=WorkspaceClient().config.host,
        client_id=p["client_id"],
        client_secret=p["client_secret"],
        scopes=p.get("scopes"),
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--warehouse-id", help="also compare with the UC function")
    p.add_argument("--uc-secret", help="catalog.schema.key of OAuth M2M credentials")
    args = p.parse_args()
    w = client(args.uc_secret)
    print(f"signed in as {w.config.client_id or 'SDK default credentials'}")
    return run_checks(w, w.config.authenticate(), args.warehouse_id)


if __name__ == "__main__":
    # Exit only on failure: a Databricks Python task runs under IPython, which reports
    # even sys.exit(0) as a failed run.
    if rc := main():
        sys.exit(rc)
