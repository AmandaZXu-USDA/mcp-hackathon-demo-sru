# Phoenix evaluation harness for `mcp-sru-syntax`

Built with the [`mcp-eval`](../../.agents/skills/mcp-eval/SKILL.md) skill. A LangChain
agent that can use only the `mcp-sru-syntax` MCP server (`src/sru_server`, launched over
stdio) answers questions from a dataset. Its traces go to
[Arize Phoenix](https://arize.com/docs/phoenix), and each answer is scored by two LLM
judges and one exact check.

| Part | What it is |
| --- | --- |
| `agent.py` | `SRUSyntaxAgent`: launches the server, loads its tools, runs one question, traces to Phoenix |
| `gateway.py` | Databricks serving endpoints as an OpenAI-compatible gateway; credentials for the server subprocess |
| `judges/correctness_judge.py` | `match_expected_response`: LLM judge, `correct` / `incorrect` against the reference |
| `judges/relevance_judge.py` | `check_answer_scope`: LLM judge, `within_scope` / `out_of_scope` |
| `judges/url_match.py` | `url_exact_match`: no LLM; the reply must contain exactly the reference SRU URL |
| `prompts/system_prompt_v1.txt` | Tool-use rules only |
| `prompts/system_prompt_v2.txt` | v1 plus scope boundaries (what to decline) |
| `datasets.yaml` | Dataset registry |
| `datasets/<name>/evaluation.xml` | Questions and answers in the mcp-builder format: the source of truth |
| `datasets/<name>/examples/<name>.csv` | Generated from the XML (`query`, `responses`); uploaded to Phoenix |
| `create_dataset.py`, `run_experiment.py` | The two CLIs |

## Datasets

* `sru-mcp-eval-0`: 10 gold questions, one per title-cleaning rule in
  [`../databricks/datasets/sru-eval-0.csv`](../databricks/datasets/sru-eval-0.csv). Each
  answer can be checked by direct string comparison: the exact NAL Alma SRU URL (9), or
  `No SRU URL` for a notice that covers a whole issue (1). The URLs come from the
  governed UC function `users.amanda_xu.build_sru_url`. Each URL's decoded `alma.title`
  equals the curated `expected_title` (checked by
  `tests/test_phoenix_eval.py::test_gold_urls_search_for_the_curated_titles`).
* `sru-mcp-scope-0`: 4 out-of-scope requests the agent should decline: a DOI lookup,
  running the search and counting records, a subscription recommendation, a MARC field.
  The answers start with `Decline:` and describe the expected behaviour, so
  `url_exact_match` scores them `not_applicable`.

## Models

Both run on Databricks serving endpoints at `<workspace>/serving-endpoints`, called with
an OpenAI client, at temperature 0.

| Role | Default | Override |
| --- | --- | --- |
| Agent-under-test | `databricks-gpt-5-6-luna` | `AGENT_MODEL` |
| Judges | `databricks-claude-sonnet-4-6` (a different model family from the agent) | `JUDGE_MODEL` |

GPT-5 endpoints accept function tools on chat completions only with
`reasoning_effort="none"`. The harness sends it for `gpt-5` models; set
`AGENT_REASONING_EFFORT` to change it, or set it empty to send nothing.

## Setup

From the repo root:

```bash
uv sync --group dev
cp .env.example .env   # then set the variables below
uv run phoenix serve   # in another terminal; UI at http://localhost:6006
```

In `.env`:

* `DATABRICKS_HOST` plus `DATABRICKS_TOKEN`, or OAuth (`DATABRICKS_CLIENT_ID` +
  `DATABRICKS_CLIENT_SECRET`), or `DATABRICKS_CONFIG_PROFILE`. These credentials call the
  serving endpoints and run the tool's UC function.
* `SQL_WAREHOUSE_ID`: without it the tool falls back to the supervisor agent
  (`SERVING_ENDPOINT`), which is slower and needs `CAN_QUERY` on that endpoint.

The MCP stdio transport gives a server only a few variables (`PATH`, `HOME`, ...) unless
it is passed an environment. The harness passes the `DATABRICKS_*` variables and the
server's own settings, and nothing else, so the harness's `AGENT_MODEL` does not reach the
server.

## Run

From `eval/phoenix/`:

```bash
uv run agent.py --no-trace                      # smoke test, one question
uv run create_dataset.py --list
uv run create_dataset.py --dataset-name sru-mcp-eval-0 --dry-run
uv run create_dataset.py --dataset-name sru-mcp-eval-0
uv run create_dataset.py --dataset-name sru-mcp-scope-0
uv run run_experiment.py --dataset-name sru-mcp-eval-0 --system-prompt-version v1
uv run run_experiment.py --dataset-name sru-mcp-scope-0 --system-prompt-version v2
```

`run_experiment.py` prints a score per evaluator and links to the experiment in Phoenix.
There you can compare prompt versions side by side and open the trace of every answer:
the model calls, the `build_sru_search_url` call and its result. Experiment metadata
records the agent and judge models, the prompt version and the git commit.

To change a dataset, edit its `evaluation.xml`, then regenerate the CSV and upload it:

```bash
uv run create_dataset.py --dataset-name sru-mcp-eval-0 --build-csv
```

`tests/test_phoenix_eval.py` fails if a committed CSV no longer matches its XML.

## First results (2026-11-22, local Phoenix 19.17)

Agent `databricks-gpt-5-6-luna`, judges `databricks-claude-sonnet-4-6`, the server at
commit `e6b9c24`, tool calls through the UC function (about 4 s).

| Dataset | Prompt | `url_exact_match` | `match_expected_response` | `check_answer_scope` |
| --- | --- | --- | --- | --- |
| `sru-mcp-eval-0` | v1 | 10/10 | 10/10 | 10/10 |
| `sru-mcp-eval-0` | v2 | 10/10 | 10/10 | 10/10 |
| `sru-mcp-scope-0` | v1 | n/a | 1/4 | 1/4 |
| `sru-mcp-scope-0` | v2 | n/a | 3/4 | 3/4 |

With the v1 prompt the agent made up a record count when asked to run the search, and
gave subscription advice. The two judges disagreed on two v1 answers: the subscription
advice (scope: out of scope; correctness: correct) and a bare SRU URL in reply to the
DOI question (scope: within scope; correctness: incorrect). The v2 prompt fixes the
record count and the advice without changing any gold result. Its one remaining miss: asked for a
MARC 245 field, it returns only the SRU URL without saying it cannot write MARC.

## Tests

`tests/test_phoenix_eval.py` runs in CI with no network, Phoenix or model. It checks the
datasets, the exact URL check, how the judges and the agent are wired, the CLI
validation, and the environment the server subprocess gets.
