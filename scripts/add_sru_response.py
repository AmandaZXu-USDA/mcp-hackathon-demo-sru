"""Add a saved NAL Alma SRU response (a new correction-notice sample) to the project.

Usage (from the repo root; Databricks credentials from the SDK default chain):

    python scripts/add_sru_response.py Sample2-Row14-9917224359507426.xml
    python scripts/add_sru_response.py FILE.xml [...] --upload --fixture

The file name must be Sample<N>-Row<R>-<16-digit correction MMS ID>.xml. For each file
the script:

1. reads it as UTF-8 and runs process_sru_response() from
   erratum-annotator/mcp_server/erratum_annotator.py (the code the live app runs);
2. checks the response holds a correction record with the MMS ID in the file name;
3. prints the original MMS ID, the erratum note and the annotated title, so you can
   compare them with the librarian's expected result before saving anything;
4. with --upload, saves the file to the SRU responses volume, where list_sru_files,
   process_sru_file and the demo page find it (no app restart needed);
5. with --fixture, copies it to erratum-annotator/tests/fixtures/ for a unit test.

Without --upload or --fixture nothing is written. The script never overwrites: a file
that is already saved with the same bytes is skipped, and one with different bytes is
refused (exit code 1).
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "erratum-annotator" / "mcp_server"))

import erratum_annotator as ea  # noqa: E402

VOLUME_DIR = "/Volumes/users/amanda_xu/erratum_files/sru_responses"
FIXTURES = ROOT / "erratum-annotator" / "tests" / "fixtures"
NAME_RE = re.compile(r"^Sample(\d+)-Row(\d+)-(\d{16})\.xml$")


def check(path: Path) -> tuple[bytes, dict]:
    """Validate one file; return its bytes and the annotator result."""
    m = NAME_RE.match(path.name)
    if not m:
        raise ValueError("name must be Sample<N>-Row<R>-<16-digit MMS ID>.xml")
    data = path.read_bytes()
    xml = data.decode("utf-8")
    correction_id = m.group(3)
    result = ea.process_sru_response(xml, "", correction_id)
    if result.get("correction_id") != correction_id:
        raise ValueError(
            f"no correction record with MMS ID {correction_id} "
            f"(found {result.get('correction_id') or 'none'})"
        )
    return data, result


def save_once(target_exists: bool, same: bool, label: str) -> bool:
    """Return True if the file should be written; raise if it would overwrite."""
    if target_exists and same:
        print(f"  {label}: already saved, identical - skipped")
        return False
    if target_exists:
        raise FileExistsError(f"{label}: a different file with this name exists")
    return True


def upload(w, name: str, data: bytes) -> None:
    target = f"{VOLUME_DIR}/{name}"
    try:
        existing = w.files.download(target).contents.read()
    except Exception:  # not found
        existing = None
    if save_once(existing is not None, existing == data, f"volume {target}"):
        w.files.upload(target, io.BytesIO(data), overwrite=False)
        print(f"  volume: saved {target} ({len(data):,} bytes)")


def add_fixture(path: Path, data: bytes) -> None:
    target = FIXTURES / path.name
    same = target.exists() and target.read_bytes() == data
    if save_once(target.exists(), same, f"fixture {target.relative_to(ROOT)}"):
        shutil.copyfile(path, target)
        print(f"  fixture: saved {target.relative_to(ROOT)}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--upload", action="store_true", help=f"save to {VOLUME_DIR}")
    p.add_argument("--fixture", action="store_true", help="copy to tests/fixtures")
    args = p.parse_args()

    w = None
    if args.upload:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
    failed = 0
    for path in args.files:
        print(path.name)
        try:
            data, r = check(path)
            print(f"  records: {r['num_records']}, corrections: {r['num_corrections']}")
            print(f"  original MMS ID: {r['original_id'] or '(none in response)'}")
            print(f"  needs review: {r['needs_review']}")
            print(f"  erratum note: {r['erratum_note']}")
            print(f"  annotated title: {r['annotated_title']}")
            if w is not None:
                upload(w, path.name, data)
            if args.fixture:
                add_fixture(path, data)
        except (ValueError, FileExistsError, UnicodeDecodeError) as exc:
            print(f"  REFUSED: {exc}")
            failed += 1
    if not (args.upload or args.fixture):
        print("Checked only; add --upload and/or --fixture to save.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
