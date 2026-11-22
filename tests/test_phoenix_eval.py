"""Offline tests for the eval/phoenix harness: no network, no Phoenix, no models.

They check the datasets (CSV generated from evaluation.xml, gold URLs that match the
curated titles), the exact-match evaluator, how the judges and the agent are wired,
and the environment the MCP server subprocess gets.
"""

from __future__ import annotations

import asyncio
import csv
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

REPO = Path(__file__).resolve().parents[1]
PHOENIX = REPO / "eval" / "phoenix"
sys.path.insert(0, str(PHOENIX))

import agent as agent_mod  # noqa: E402
import create_dataset  # noqa: E402
import gateway  # noqa: E402
import run_experiment  # noqa: E402
from judges import correctness_judge, relevance_judge  # noqa: E402
from judges.url_match import url_exact_match  # noqa: E402

SRU_PREFIX = "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?"
GOLD = "sru-mcp-eval-0"
SCOPE = "sru-mcp-scope-0"
URL = (
    SRU_PREFIX + "version=1.2&operation=searchRetrieve&recordSchema=mods&query="
    "alma.title%3D%22GATA-1%20and%20Gfi-1B%20Interplay%20To%20Regulate%20Bcl-xL"
    "%20Transcription%22%20and%20alma.local_field_912%3D%22Article%22"
)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# --- datasets -------------------------------------------------------------------


def test_registry_lists_both_datasets_with_existing_files():
    registry = create_dataset.load_registry()
    assert set(registry) == {GOLD, SCOPE}
    for entry in registry.values():
        assert (PHOENIX / entry["xml_path"]).is_file()
        assert (PHOENIX / entry["csv_path"]).is_file()
        assert entry["input_keys"] == ["query"]
        assert entry["output_keys"] == ["responses"]


@pytest.mark.parametrize("name", [GOLD, SCOPE])
def test_committed_csv_is_generated_from_its_xml(name):
    entry = create_dataset.get_entry(name)
    assert _csv_rows(PHOENIX / entry["csv_path"]) == create_dataset.xml_rows(
        PHOENIX / entry["xml_path"]
    )


def test_build_csv_writes_the_same_bytes(tmp_path, monkeypatch):
    entry = dict(create_dataset.get_entry(GOLD), csv_path=str(tmp_path / "out.csv"))
    out = create_dataset.build_csv(entry)
    committed = PHOENIX / create_dataset.get_entry(GOLD)["csv_path"]
    assert out.read_bytes() == committed.read_bytes()


def test_gold_set_has_ten_verifiable_answers():
    rows = create_dataset.xml_rows(PHOENIX / create_dataset.get_entry(GOLD)["xml_path"])
    assert len(rows) == 10
    answers = [row["responses"] for row in rows]
    assert all(a.startswith(SRU_PREFIX) or a == "No SRU URL" for a in answers)
    assert answers.count("No SRU URL") == 1
    assert len(set(answers)) == 10


def test_gold_urls_search_for_the_curated_titles():
    """Each gold URL's alma.title is an expected_title in the curated ground truth."""
    curated = REPO / "eval" / "databricks" / "datasets" / "sru-eval-0.csv"
    expected = {row["expected_title"] for row in _csv_rows(curated)}
    rows = create_dataset.xml_rows(PHOENIX / create_dataset.get_entry(GOLD)["xml_path"])
    for row in rows:
        if row["responses"] == "No SRU URL":
            continue
        query = parse_qs(urlparse(row["responses"]).query)["query"][0]
        match = re.fullmatch(
            r'alma\.title="(.*)" and alma\.local_field_912="Article"', query
        )
        assert match, query
        assert match.group(1) in expected


def test_scope_set_describes_declines():
    rows = create_dataset.xml_rows(
        PHOENIX / create_dataset.get_entry(SCOPE)["xml_path"]
    )
    assert len(rows) == 4
    assert all(row["responses"].startswith("Decline:") for row in rows)


def test_load_dataframe_rejects_missing_column_and_empty_value(tmp_path):
    entry = create_dataset.get_entry(GOLD)
    bad = tmp_path / "bad.csv"
    bad.write_text("query,answer\nq,a\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="missing column"):
        create_dataset.load_dataframe(entry, bad)
    bad.write_text("query,responses\nq,\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="empty values on CSV line"):
        create_dataset.load_dataframe(entry, bad)


def test_dry_run_validates_without_phoenix(capsys):
    create_dataset.main(["--dataset-name", GOLD, "--dry-run"])
    assert "10 examples" in capsys.readouterr().out


# --- url_exact_match ------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "score"),
    [
        (URL, 1),
        (f"Here it is: {URL}.", 1),
        (f"[{URL}]({URL})", 1),
        (URL.replace("GATA-1", "GATA-2"), 0),
        (URL.replace("%20Transcription", ""), 0),
        (f"{URL} or {URL.replace('Article', 'Book')}", 0),
        ("I could not build it.", 0),
    ],
)
def test_url_exact_match_on_a_url_question(response, score):
    result = url_exact_match({"response": response}, {"responses": URL})
    assert result["score"] == score


def test_url_exact_match_on_no_url_and_decline_rows():
    none = {"responses": "No SRU URL"}
    assert url_exact_match({"response": "No SRU URL: whole issue."}, none)["score"] == 1
    assert url_exact_match({"response": URL}, none)["score"] == 0
    decline = url_exact_match({"response": URL}, {"responses": "Decline: no DOI."})
    assert decline == {
        "label": "not_applicable",
        "score": None,
        "explanation": "not a URL question",
    }


# --- LLM judges (fake LLM) ------------------------------------------------------


class _FakeEvaluator:
    calls: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def evaluate(self, record):
        _FakeEvaluator.calls.append((self.kwargs, record))
        label = next(iter(self.kwargs["choices"]))
        return [SimpleNamespace(label=label, score=1, explanation="because")]


@pytest.fixture
def fake_judge_llm(monkeypatch):
    _FakeEvaluator.calls = []
    models = []
    for module in (correctness_judge, relevance_judge):
        module._evaluator.cache_clear()
        monkeypatch.setattr(module, "ClassificationEvaluator", _FakeEvaluator)
        monkeypatch.setattr(
            module, "LLM", lambda **kw: models.append(kw) or SimpleNamespace(**kw)
        )
    monkeypatch.setattr(gateway, "base_url", lambda: "https://ws/serving-endpoints")
    monkeypatch.setattr(gateway, "api_key", lambda: "token")
    monkeypatch.setenv("JUDGE_MODEL", "judge-endpoint")
    yield models
    for module in (correctness_judge, relevance_judge):
        module._evaluator.cache_clear()


def test_correctness_judge_wiring(fake_judge_llm):
    result = correctness_judge.match_expected_response(
        {"query": "Q"}, {"response": "A", "tool_calls": []}, {"responses": "R"}
    )
    assert result == {"label": "correct", "score": 1, "explanation": "because"}
    kwargs, record = _FakeEvaluator.calls[-1]
    assert record == {"input": "Q", "output": "A", "reference": "R"}
    assert kwargs["choices"] == {"correct": 1, "incorrect": 0}
    assert kwargs["temperature"] == 0.0
    assert fake_judge_llm[-1]["model"] == "judge-endpoint"
    assert fake_judge_llm[-1]["base_url"] == "https://ws/serving-endpoints"
    for placeholder in ("{input}", "{output}", "{reference}"):
        assert placeholder in kwargs["prompt_template"]


def test_scope_judge_wiring(fake_judge_llm):
    result = relevance_judge.check_answer_scope({"query": "Q"}, {"response": "A"})
    assert result["label"] == "within_scope"
    kwargs, record = _FakeEvaluator.calls[-1]
    assert record == {"input": "Q", "output": "A"}
    assert kwargs["choices"] == {"within_scope": 1, "out_of_scope": 0}
    assert kwargs["temperature"] == 0.0
    assert "{reference}" not in kwargs["prompt_template"]


# --- gateway and the server subprocess ------------------------------------------


def test_agent_and_judge_models_default_to_different_endpoints(monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    assert gateway.agent_model() != gateway.judge_model()


def test_reasoning_effort(monkeypatch):
    monkeypatch.delenv("AGENT_REASONING_EFFORT", raising=False)
    assert gateway.reasoning_effort("databricks-gpt-5-6-luna") == "none"
    assert gateway.reasoning_effort("databricks-claude-sonnet-4-6") is None
    monkeypatch.setenv("AGENT_REASONING_EFFORT", "low")
    assert gateway.reasoning_effort("databricks-gpt-5-6-luna") == "low"
    monkeypatch.setenv("AGENT_REASONING_EFFORT", "")
    assert gateway.reasoning_effort("databricks-gpt-5-6-luna") is None


def test_server_gets_credentials_and_settings_only(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://ws")
    monkeypatch.setenv("DATABRICKS_TOKEN", "t")
    monkeypatch.setenv("SQL_WAREHOUSE_ID", "wh")
    monkeypatch.setenv("AGENT_MODEL", "harness-model")
    monkeypatch.setenv("UNRELATED_SECRET", "x")
    connection = agent_mod.server_connection()
    env = connection["env"]
    assert env["DATABRICKS_TOKEN"] == "t"
    assert env["SQL_WAREHOUSE_ID"] == "wh"
    assert env["MCP_TRANSPORT"] == "stdio"
    assert "AGENT_MODEL" not in env
    assert "UNRELATED_SECRET" not in env
    assert connection["command"] == sys.executable
    assert connection["args"] == ["-m", "sru_server.app"]
    assert Path(connection["cwd"]) == REPO
    assert (REPO / "src" / "sru_server" / "app.py").is_file()


def test_server_gets_a_token_when_credentials_are_implicit(monkeypatch):
    for key in list(gateway.os.environ):
        if key.startswith("DATABRICKS_"):
            monkeypatch.delenv(key)
    fake = SimpleNamespace(
        host="https://ws", authenticate=lambda: {"Authorization": "Bearer abc"}
    )
    monkeypatch.setattr(gateway, "_config", lambda: fake)
    env = gateway.server_env(set())
    assert env == {"DATABRICKS_HOST": "https://ws", "DATABRICKS_TOKEN": "abc"}


# --- agent and experiment wiring -------------------------------------------------


def test_prompt_versions_match_files_and_cli_choices():
    assert agent_mod.prompt_versions() == ["v1", "v2"]
    with pytest.raises(SystemExit) as error:
        run_experiment.main(["--dataset-name", GOLD, "--system-prompt-version", "v9"])
    assert error.value.code == 2
    with pytest.raises(ValueError, match="available: v1, v2"):
        agent_mod.SRUSyntaxAgent(system_prompt_version="v9")


def test_v2_prompt_adds_scope_to_v1():
    v1 = agent_mod.SRUSyntaxAgent(system_prompt_version="v1").system_prompt
    v2 = agent_mod.SRUSyntaxAgent(system_prompt_version="v2").system_prompt
    assert v2.startswith(v1)
    assert "Scope." in v2 and "Scope." not in v1


def test_run_requires_initialize():
    with pytest.raises(RuntimeError, match="initialize"):
        asyncio.run(agent_mod.SRUSyntaxAgent().run("q"))


def test_run_returns_final_text_and_tool_calls(monkeypatch):
    seen = {}

    class FakeGraph:
        async def ainvoke(self, state, config):
            seen["state"], seen["config"] = state, config
            return {
                "messages": [
                    SimpleNamespace(content="q"),
                    SimpleNamespace(
                        content="", tool_calls=[{"name": "build_sru_search_url"}]
                    ),
                    SimpleNamespace(content="tool reply"),
                    SimpleNamespace(content=[{"type": "text", "text": URL}]),
                ]
            }

    def fake_create_agent(model, tools, system_prompt):
        seen["system_prompt"] = system_prompt
        return FakeGraph()

    monkeypatch.setattr(agent_mod, "create_agent", fake_create_agent)
    agent = agent_mod.SRUSyntaxAgent(system_prompt_version="v2")
    monkeypatch.setattr(agent, "_chat_model", lambda: "model")
    agent.tools = []
    task = agent.create_experiment_task()
    result = task({"query": "Which URL?"})
    assert result == {"response": URL, "tool_calls": ["build_sru_search_url"]}
    assert seen["state"]["messages"][0]["content"] == "Which URL?"
    assert seen["config"]["recursion_limit"] == agent_mod.RECURSION_LIMIT
    assert seen["system_prompt"] == agent.system_prompt


def test_validate_examples():
    good = [{"id": "1", "input": {"query": "q"}, "output": {"responses": "r"}}]
    assert run_experiment.validate(good) == 1
    with pytest.raises(SystemExit, match="no examples"):
        run_experiment.validate([])
    bad = [{"id": "2", "input": {"query": " "}, "output": {"responses": "r"}}]
    with pytest.raises(SystemExit, match="2"):
        run_experiment.validate(bad)


def test_summary_skips_not_applicable_and_counts_errors(capsys):
    def run(name, score=None, error=None):
        return SimpleNamespace(name=name, result={"score": score}, error=error)

    experiment = {
        "task_runs": [{"error": None}, {"error": "timeout"}],
        "evaluation_runs": [
            run("url_exact_match", 1),
            run("url_exact_match", None),
            run("match_expected_response", 1),
            run("match_expected_response", 0),
            run("match_expected_response", error="boom"),
        ],
    }
    assert run_experiment.summarize(experiment) == {
        "url_exact_match": (1, 1, 0),
        "match_expected_response": (1, 2, 1),
    }
    run_experiment.print_summary(experiment)
    out = capsys.readouterr().out
    assert "task runs: 2 (1 failed)" in out
    assert "match_expected_response: 1/2, 1 evaluator errors" in out
    assert "url_exact_match: 1/1" in out


def test_experiment_uses_all_three_evaluators():
    names = [fn.__name__ for fn in run_experiment.EVALUATORS]
    assert names == ["check_answer_scope", "match_expected_response", "url_exact_match"]
