"""Unit tests for scripts/. No Databricks credentials: workspace calls are faked."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from databricks.sdk.service.sql import StatementState

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "erratum-annotator" / "tests" / "fixtures"
ROW14 = FIXTURES / "Sample2-Row14-9917224359507426.xml"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


asr = load("add_sru_response")
ruc = load("recreate_uc_function")
sts = load("sync_to_fork")
cl = load("check_live")


# --- add_sru_response.py ---------------------------------------------------------


def test_check_reads_sample_with_curly_quotes():
    data, r = asr.check(ROW14)
    assert data == ROW14.read_bytes()
    assert (r["correction_id"], r["original_id"]) == (
        "9917224359507426",
        "9917193984707426",
    )
    assert r["erratum_note"] == (
        "[Erratum: Sept. 2026, v. 127, no. 6, e71126, 10.1111/tpj.71126]"
    )


def test_check_refuses_bad_name(tmp_path):
    bad = tmp_path / "row14.xml"
    shutil.copyfile(ROW14, bad)
    with pytest.raises(ValueError, match="name must be"):
        asr.check(bad)


def test_check_refuses_mms_id_not_in_response(tmp_path):
    wrong = tmp_path / "Sample2-Row99-9917226153507426.xml"
    shutil.copyfile(ROW14, wrong)
    with pytest.raises(ValueError, match="no correction record with MMS ID"):
        asr.check(wrong)


class FakeFiles:
    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.uploads: list[tuple[str, bool]] = []

    def download(self, path):
        if path not in self.store:
            raise FileNotFoundError(path)
        return SimpleNamespace(contents=SimpleNamespace(read=lambda: self.store[path]))

    def upload(self, path, stream, overwrite):
        self.uploads.append((path, overwrite))
        self.store[path] = stream.read()


def test_upload_saves_once_and_never_overwrites():
    w = SimpleNamespace(files=FakeFiles())
    name, data = ROW14.name, ROW14.read_bytes()
    asr.upload(w, name, data)
    asr.upload(w, name, data)  # identical: skipped
    assert w.files.uploads == [(f"{asr.VOLUME_DIR}/{name}", False)]
    with pytest.raises(FileExistsError):
        asr.upload(w, name, data + b"\n")
    assert w.files.store[f"{asr.VOLUME_DIR}/{name}"] == data


def test_add_fixture_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(asr, "ROOT", tmp_path)
    monkeypatch.setattr(asr, "FIXTURES", tmp_path / "fixtures")
    (tmp_path / "fixtures").mkdir()
    asr.add_fixture(ROW14, ROW14.read_bytes())
    asr.add_fixture(ROW14, ROW14.read_bytes())  # identical: skipped
    assert (tmp_path / "fixtures" / ROW14.name).read_bytes() == ROW14.read_bytes()
    with pytest.raises(FileExistsError):
        asr.add_fixture(ROW14, b"changed")


def test_main_without_flags_only_checks(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["add_sru_response.py", str(ROW14)])
    assert asr.main() == 0
    assert "Checked only" in capsys.readouterr().out


# --- recreate_uc_function.py ------------------------------------------------------

FN = "users.amanda_xu.build_sru_url"
SP = "e10a6ba5-9088-4856-8c13-70193f8f8b31"


class FakeWarehouse:
    """CREATE OR REPLACE drops the function's own grants, as Unity Catalog does."""

    def __init__(self, grants, grant_sticks=True):
        self.grants = set(grants)
        self.grant_sticks = grant_sticks
        self.statements: list[str] = []

    def execute_statement(self, warehouse_id, statement, wait_timeout):
        self.statements.append(statement)
        rows = []
        if statement.startswith("SHOW GRANTS"):
            rows = [[p, a, "FUNCTION", FN] for p, a in sorted(self.grants)]
            rows.append(["amanda.xu@usda.gov", "ALL PRIVILEGES", "SCHEMA", "users.x"])
        elif "CREATE OR REPLACE FUNCTION" in statement:
            self.grants.clear()
        elif statement.startswith("GRANT") and self.grant_sticks:
            privilege, principal = statement.split(" ON ")[0][6:], statement[:-1]
            self.grants.add((principal.rsplit("`", 1)[-1], privilege))
        ok = SimpleNamespace(state=StatementState.SUCCEEDED, error=None)
        return SimpleNamespace(status=ok, result=SimpleNamespace(data_array=rows))


def run_recreate(monkeypatch, fake, *flags):
    w = SimpleNamespace(statement_execution=fake)
    monkeypatch.setattr(ruc, "WorkspaceClient", lambda: w)
    sql = ROOT / "sru-syntax-mcp" / "uc_functions" / "build_sru_url.sql"
    argv = ["recreate_uc_function.py", str(sql), "--warehouse-id", "wh", *flags]
    monkeypatch.setattr(sys, "argv", argv)
    return ruc.main()


def test_every_uc_function_file_names_one_function():
    files = sorted(ROOT.glob("*/uc_functions/*.sql"))
    assert len(files) >= 5
    for f in files:
        names = ruc.NAME_RE.findall(f.read_text(encoding="utf-8"))
        assert len(names) == 1 and names[0].startswith("users.amanda_xu."), f


def test_dry_run_does_not_recreate(monkeypatch):
    fake = FakeWarehouse({(SP, "EXECUTE")})
    assert run_recreate(monkeypatch, fake) == 0
    assert not any("CREATE" in s for s in fake.statements)


def test_apply_restores_only_function_grants(monkeypatch):
    fake = FakeWarehouse({(SP, "EXECUTE")})
    assert run_recreate(monkeypatch, fake, "--apply") == 0
    grants = [s for s in fake.statements if s.startswith("GRANT")]
    assert grants == [f"GRANT EXECUTE ON FUNCTION {FN} TO `{SP}`"]  # not the schema one
    assert fake.grants == {(SP, "EXECUTE")}


def test_apply_fails_if_grants_are_not_restored(monkeypatch):
    fake = FakeWarehouse({(SP, "EXECUTE")}, grant_sticks=False)
    assert run_recreate(monkeypatch, fake, "--apply") == 1


def test_refuses_unexpected_principal(monkeypatch):
    fake = FakeWarehouse({("x` TO `everyone", "EXECUTE")})
    assert run_recreate(monkeypatch, fake, "--apply") == 2
    assert not any("CREATE" in s for s in fake.statements)


# --- sync_to_fork.py --------------------------------------------------------------


def git(repo: Path, *args: str) -> None:
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args]
    subprocess.run(cmd, cwd=repo, check=True, capture_output=True)


def write(repo: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """NAL and fork repos where each file is set up for one status."""
    nal, fork = tmp_path / "NAL", tmp_path / "fork"
    nal.mkdir()
    fork.mkdir()
    base = {f"a/{n}.txt": "v1" for n in ("copy", "same", "diverged", "dirty", "gone")}
    base["sru-syntax-mcp/.agents/rules.md"] = "v1"
    base["title-extraction/erratum_title_extractor.py"] = "v1"
    write(nal, base)
    git(nal, "init", "-q")
    git(nal, "add", "-A")
    git(nal, "commit", "-qm", "base")
    write(fork, {"a/copy.txt": "v1", "a/dirty.txt": "v1", "a/gone.txt": "v1"})
    write(fork, {"a/same.txt": "v2", "a/diverged.txt": "fork's own"})
    write(fork, {".agents/rules.md": "v1"})
    write(fork, {"title-extraction/erratum_title_extractor.py": "formatted"})
    git(fork, "init", "-q")
    git(fork, "add", "-A")
    git(fork, "commit", "-qm", "base")
    write(fork, {"a/dirty.txt": "local edit"})
    (fork / "a" / "gone.txt").unlink()
    write(nal, {p: "v2" for p in base} | {"a/new.txt": "v2"})
    monkeypatch.setattr(sts, "NAL", nal)
    monkeypatch.setattr(sts, "FORK", fork)
    return nal, fork


EXPECTED = {
    "a/copy.txt": "copy",
    "a/same.txt": "same",
    "a/new.txt": "new",
    "a/diverged.txt": "diverged",
    "a/dirty.txt": "dirty",
    "a/gone.txt": "dirty",
    "sru-syntax-mcp/.agents/rules.md": "copy",
    "title-extraction/erratum_title_extractor.py": "manual",
}


def test_classify_each_status(repos):
    assert sts.changed_files(None) == sorted(EXPECTED)
    assert {p: sts.classify(p, "HEAD") for p in EXPECTED} == EXPECTED
    assert sts.fork_path("sru-syntax-mcp/.agents/rules.md") == ".agents/rules.md"


def test_dry_run_writes_nothing(repos, monkeypatch):
    _, fork = repos
    monkeypatch.setattr(sys, "argv", ["sync_to_fork.py", "--changed"])
    assert sts.main() == 1  # diverged, dirty and manual files need a hand
    assert (fork / "a" / "copy.txt").read_text() == "v1"
    assert not (fork / "a" / "new.txt").exists()


def test_apply_copies_only_safe_files(repos, monkeypatch):
    _, fork = repos
    monkeypatch.setattr(sys, "argv", ["sync_to_fork.py", "--changed", "--apply"])
    sts.main()
    got = {
        "copy": (fork / "a" / "copy.txt").read_text(),
        "new": (fork / "a" / "new.txt").read_text(),
        "rules": (fork / ".agents" / "rules.md").read_text(),
        "diverged": (fork / "a" / "diverged.txt").read_text(),
        "dirty": (fork / "a" / "dirty.txt").read_text(),
        "manual": (
            fork / "title-extraction" / "erratum_title_extractor.py"
        ).read_text(),
    }
    assert got == {
        "copy": "v2",
        "new": "v2",
        "rules": "v2",
        "diverged": "fork's own",
        "dirty": "local edit",
        "manual": "formatted",
    }
    assert not (fork / "a" / "gone.txt").exists()
    # Copied but not committed in the fork yet: reported as same, not dirty.
    assert sts.classify("a/copy.txt", "HEAD") == "same"


def test_since_lists_the_commit(repos, monkeypatch, capsys):
    nal, _ = repos
    git(nal, "add", "-A")
    git(nal, "commit", "-qm", "change")
    monkeypatch.setattr(sys, "argv", ["sync_to_fork.py", "--since", "HEAD~1"])
    assert sts.main() == 1  # the commit also has the diverged/dirty/manual files
    out = capsys.readouterr().out
    for path, status in EXPECTED.items():
        assert re.search(rf"^{status}\s+{re.escape(path)}", out, re.M), path


def test_base_with_explicit_safe_paths_exits_0(repos, monkeypatch):
    nal, _ = repos
    git(nal, "add", "-A")
    git(nal, "commit", "-qm", "change")
    paths = ["a/copy.txt", "a/new.txt", "a/same.txt", "sru-syntax-mcp/.agents/rules.md"]
    monkeypatch.setattr(sys, "argv", ["sync_to_fork.py", *paths, "--base", "HEAD~1"])
    assert sts.main() == 0
    assert sts.classify("a/copy.txt", "HEAD~1") == "copy"
    assert sts.classify("a/copy.txt", "HEAD") == "diverged"  # wrong base: refused


# --- check_live.py ----------------------------------------------------------------


class FakeResponse:
    def __init__(self, body, headers=None, sse=False):
        self.body, self.headers = body, dict(headers or {})
        if sse:
            self.headers["content-type"] = "text/event-stream"
            self.text = "event: message\ndata: " + json.dumps(body) + "\n\n"
        else:
            self.headers["content-type"] = "application/json"

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


def test_mcp_client_session_json_and_event_stream(monkeypatch):
    sent = []

    def post(url, headers, json, timeout):
        sent.append((json.get("method"), headers.get("mcp-session-id")))
        if json["method"] == "initialize":
            return FakeResponse({"id": 1, "result": {}}, {"mcp-session-id": "s1"})
        if json["method"] == "tools/list":
            return FakeResponse({"id": json["id"], "result": {"tools": []}})
        text = {"content": [{"type": "text", "text": "hello"}]}
        return FakeResponse({"id": json.get("id"), "result": text}, sse=True)

    monkeypatch.setattr(cl.requests, "post", post)
    m = cl.Mcp("https://app/mcp", {"Authorization": "Bearer t"})
    assert m.request("tools/list", {}) == {"tools": []}
    assert m.tool_text("x", {}) == "hello"
    assert sent[0] == ("initialize", None)
    assert all(sid == "s1" for _, sid in sent[1:])


def fake_apps(monkeypatch, title=cl.ROW1_TITLE, demo_files=None):
    url = "https://sru?query=" + cl.quote(f'alma.title="{cl.SRU_ORIGINAL}"', safe="")
    tools = [
        {"name": n, "annotations": {"readOnlyHint": True}} for n in cl.ERRATUM_TOOLS
    ]

    class FakeMcp:
        def __init__(self, url, auth):
            pass

        def request(self, method, params):
            return {"tools": tools}

        def tool_text(self, name, arguments):
            if name == "process_sru_file":
                return json.dumps({"annotated_title": title})
            return f"NAL Alma SRU search URL for the original article:\n{url}"

    files = demo_files or ["Sample1-Row1-9916524607707426.xml"]
    examples = {"examples": [{"file_name": f} for f in files]}
    monkeypatch.setattr(cl, "Mcp", FakeMcp)
    monkeypatch.setattr(cl.requests, "get", lambda *a, **k: FakeResponse(examples))
    monkeypatch.setattr(cl, "uc_url", lambda w, wh: url)
    listing = [SimpleNamespace(name="Sample1-Row1-9916524607707426.xml")]
    return SimpleNamespace(
        files=SimpleNamespace(list_directory_contents=lambda d: listing)
    )


def test_run_checks_all_pass(monkeypatch, capsys):
    w = fake_apps(monkeypatch)
    assert cl.run_checks(w, {}, "wh") == 0
    assert "5/5 checks passed" in capsys.readouterr().out


def test_run_checks_reports_each_failure(monkeypatch, capsys):
    w = fake_apps(monkeypatch, title="wrong", demo_files=["a.xml"])
    assert cl.run_checks(w, {}, None) == 1
    out = capsys.readouterr().out
    assert "FAIL  erratum: Sample 1 row 1 annotated title" in out
    assert "FAIL  erratum: demo lists every saved file  - demo 1, volume 1" in out
    assert "PASS  sru: URL for the original title" in out
    assert "2/4 checks passed" in out


def test_run_checks_counts_an_error_as_a_failure(monkeypatch, capsys):
    w = fake_apps(monkeypatch)

    def denied(d):
        raise PermissionError("no READ VOLUME")

    w.files.list_directory_contents = denied
    assert cl.run_checks(w, {}, None) == 1
    assert "PermissionError('no READ VOLUME')" in capsys.readouterr().out
