"""Recreate a Unity Catalog function from its .sql file and keep its grants.

Usage (from the repo root; Databricks credentials from the SDK default chain):

    python scripts/recreate_uc_function.py \
        sru-syntax-mcp/uc_functions/build_sru_url.sql --warehouse-id <id> [--apply]

CREATE OR REPLACE FUNCTION drops every grant on the function. On Nov 21, 2026 that
silently removed EXECUTE from the mcp-sru-syntax app's service principal. This script:

1. reads the function name from the CREATE OR REPLACE FUNCTION line of the file;
2. records SHOW GRANTS ON FUNCTION (grants made on the function itself);
3. with --apply, runs the file, then GRANTs each recorded privilege again;
4. runs SHOW GRANTS again and fails (exit code 1) unless the grants are the same.

Without --apply it only prints the function name and the grants it would restore.
Each .sql file holds one CREATE OR REPLACE FUNCTION statement after its comments.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

NAME_RE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+([A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+)",
    re.I,
)
# Principals are user e-mails, group names or service-principal application IDs.
PRINCIPAL_RE = re.compile(r"^[\w.@+\- ]+$")
PRIVILEGE_RE = re.compile(r"^[A-Z_ ]+$")


def run(w: WorkspaceClient, warehouse: str, sql: str) -> list[list[str]]:
    r = w.statement_execution.execute_statement(
        warehouse_id=warehouse, statement=sql, wait_timeout="50s"
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error}")
    return (r.result and r.result.data_array) or []


def grants(w: WorkspaceClient, warehouse: str, fn: str) -> set[tuple[str, str]]:
    """(principal, privilege) granted on the function itself, not inherited."""
    rows = run(w, warehouse, f"SHOW GRANTS ON FUNCTION {fn}")
    # Columns: Principal, ActionType, ObjectType, ObjectKey
    return {(r[0], r[1]) for r in rows if r[2] == "FUNCTION" and r[3] == fn}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("sql_file", type=Path)
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--apply", action="store_true", help="recreate the function")
    args = p.parse_args()

    sql = args.sql_file.read_text(encoding="utf-8")
    names = NAME_RE.findall(sql)
    if len(names) != 1:
        print(f"Expected one CREATE OR REPLACE FUNCTION, found {len(names)}.")
        return 2
    fn = names[0]
    w = WorkspaceClient()
    before = grants(w, args.warehouse_id, fn)
    print(f"{fn}: {len(before)} grant(s)")
    for principal, privilege in sorted(before):
        print(f"  {privilege:<15} {principal}")
        if not (PRINCIPAL_RE.match(principal) and PRIVILEGE_RE.match(privilege)):
            print(f"Unexpected grant row {principal!r} {privilege!r}; stopping.")
            return 2
    if not args.apply:
        print("Dry run; add --apply to recreate the function and restore the grants.")
        return 0

    run(w, args.warehouse_id, sql)
    print(f"recreated {fn} from {args.sql_file}")
    for principal, privilege in sorted(before):
        grant = f"GRANT {privilege} ON FUNCTION {fn} TO `{principal}`"
        run(w, args.warehouse_id, grant)
    after = grants(w, args.warehouse_id, fn)
    if after != before:
        print(f"GRANTS DIFFER. missing: {before - after}; extra: {after - before}")
        return 1
    print(f"grants restored: {len(after)} (same as before)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
