"""Copy changed files from the NAL repo to the hackathon fork, refusing unsafe copies.

NAL (AmandaZXu-USDA/NAL, branch add-mcp-servers) is what the live apps are deployed
from; the fork (AmandaZXu-USDA/mcp-hackathon-demo-sru, branch main) is pushed to the
submission repository judges review (gsa-mcp-hackathon/mcp-sru-erratum). Change NAL
first, then copy to the fork with this script.

Usage (from either repo; both clones side by side, as in the Databricks workspace):

    python scripts/sync_to_fork.py --changed             # NAL edits not committed yet
    python scripts/sync_to_fork.py --since HEAD~1         # files in NAL's last commit
    python scripts/sync_to_fork.py PATH [...] [--apply]   # NAL-relative paths

For every file it reports one of:

  copy      the fork's copy equals NAL's earlier version (--base), so it is safe
  same      the fork already has NAL's current version
  new       the file is not in the fork yet
  diverged  the fork's committed copy differs from NAL's earlier version; port by hand
  dirty     the fork has uncommitted changes to the file; commit or discard them first
  manual    the fork keeps its own version of this file (MANUAL below)

Only --apply writes, and only copy/new files. It never deletes, commits or pushes;
review `git diff` in the fork, run its tests and ruff, then commit there. Exit code 1
if any file needs a manual step.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
NAL = HERE.parent / "NAL"
FORK = HERE.parent / "mcp-hackathon-demo-sru"

# NAL path prefix -> fork path prefix, where the layouts differ.
PATH_MAP = {"sru-syntax-mcp/.agents/": ".agents/"}
# Files the fork keeps in its own (ruff-formatted) version: port changes by hand.
MANUAL = {
    "title-extraction/erratum_title_extractor.py": "fork copy is ruff-formatted",
}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True)


def show(repo: Path, rev: str, path: str) -> bytes | None:
    r = git(repo, "show", f"{rev}:{path}")
    return r.stdout if r.returncode == 0 else None


def fork_path(path: str) -> str:
    for nal_prefix, fork_prefix in PATH_MAP.items():
        if path.startswith(nal_prefix):
            return fork_prefix + path[len(nal_prefix) :]
    return path


def changed_files(since: str | None) -> list[str]:
    if since:
        out = git(NAL, "diff", "--name-only", since, "HEAD").stdout
    else:
        out = git(NAL, "diff", "--name-only", "HEAD").stdout
        out += git(NAL, "ls-files", "--others", "--exclude-standard").stdout
    return sorted(set(out.decode().split()))


def classify(path: str, base: str) -> str:
    if path in MANUAL:
        return "manual"
    target = fork_path(path)
    current = (NAL / path).read_bytes()
    fork_file = FORK / target
    if fork_file.exists() and fork_file.read_bytes() == current:
        return "same"  # already copied (committed in the fork or not)
    fork_head = show(FORK, "HEAD", target)
    working = fork_file.read_bytes() if fork_file.exists() else None
    if working != fork_head:  # edited, untracked or deleted in the fork
        return "dirty"
    if fork_head is None:
        return "new"
    return "copy" if fork_head == show(NAL, base, path) else "diverged"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("paths", nargs="*", help="NAL-relative file paths")
    p.add_argument("--changed", action="store_true", help="NAL's uncommitted files")
    p.add_argument("--since", help="files changed in NAL from this revision to HEAD")
    p.add_argument(
        "--base",
        help="NAL revision the fork last matched (default: HEAD, or --since)",
    )
    p.add_argument("--apply", action="store_true", help="copy the copy/new files")
    args = p.parse_args()

    paths = list(args.paths)
    if args.changed or args.since:
        paths += changed_files(args.since)
    base = args.base or args.since or "HEAD"
    paths = [x for x in dict.fromkeys(paths) if (NAL / x).is_file()]
    if not paths:
        print("No files to sync.")
        return 0

    status = {x: classify(x, base) for x in paths}
    for x, s in status.items():
        note = f"  ({MANUAL[x]})" if s == "manual" else ""
        target = fork_path(x)
        arrow = f" -> {target}" if target != x else ""
        print(f"{s:<9} {x}{arrow}{note}")
        if args.apply and s in ("copy", "new"):
            (FORK / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(NAL / x, FORK / target)
    needs_hand = [x for x, s in status.items() if s in ("diverged", "dirty", "manual")]
    if not args.apply:
        print("Dry run; add --apply to copy the 'copy' and 'new' files.")
    return 1 if needs_hand else 0


if __name__ == "__main__":
    sys.exit(main())
