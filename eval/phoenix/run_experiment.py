"""Run the agent and the evaluators against a Phoenix dataset.

From ``eval/phoenix/``, with Phoenix running and the dataset uploaded::

    uv run run_experiment.py --dataset-name sru-mcp-eval-0
    uv run run_experiment.py --dataset-name sru-mcp-scope-0 --system-prompt-version v2
"""

from __future__ import annotations

import argparse
import os
import subprocess

import gateway
from agent import (
    DEFAULT_PHOENIX_ENDPOINT,
    DEFAULT_PROJECT,
    HERE,
    SRUSyntaxAgent,
    prompt_versions,
)
from dotenv import load_dotenv
from judges import check_answer_scope, match_expected_response, url_exact_match

load_dotenv()

EVALUATORS = [check_answer_scope, match_expected_response, url_exact_match]
TASK_TIMEOUT_S = (
    180  # per question; the tool needs about 5 s, a cold agent fallback 90 s
)


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def validate(
    examples: list[dict], input_key: str = "query", output_key: str = "responses"
) -> int:
    """Check every example has a non-empty input query and reference answer."""
    if not examples:
        raise SystemExit("The dataset has no examples.")
    bad = [
        example.get("id", "?")
        for example in examples
        if not str((example.get("input") or {}).get(input_key, "")).strip()
        or not str((example.get("output") or {}).get(output_key, "")).strip()
    ]
    if bad:
        raise SystemExit(f"Examples without '{input_key}' or '{output_key}': {bad}")
    return len(examples)


def summarize(experiment) -> dict[str, tuple[float, int, int]]:
    """Per evaluator: (points, scored runs, errors).

    Runs scored None (``not_applicable``, e.g. url_exact_match on a decline row) are
    not counted.
    """
    totals: dict[str, tuple[float, int, int]] = {}
    for run in experiment["evaluation_runs"]:
        points, scored, errors = totals.get(run.name, (0.0, 0, 0))
        score = (run.result or {}).get("score")
        if run.error:
            errors += 1
        elif score is not None:
            points, scored = points + score, scored + 1
        totals[run.name] = (points, scored, errors)
    return totals


def print_summary(experiment) -> None:
    tasks = experiment["task_runs"]
    failed = sum(1 for task in tasks if task.get("error"))
    print(f"task runs: {len(tasks)} ({failed} failed)")
    for name, (points, scored, errors) in sorted(summarize(experiment).items()):
        note = f", {errors} evaluator errors" if errors else ""
        print(f"{name}: {points:g}/{scored}{note}")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument(
        "--system-prompt-version", default="v1", choices=prompt_versions()
    )
    parser.add_argument("--project-name", default=DEFAULT_PROJECT)
    parser.add_argument(
        "--phoenix-endpoint",
        default=os.getenv("PHOENIX_COLLECTOR_ENDPOINT", DEFAULT_PHOENIX_ENDPOINT),
    )
    parser.add_argument("--experiment-description")
    parser.add_argument("--dataset-version-id")
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args(argv)

    from phoenix.client import Client

    client = Client(base_url=args.phoenix_endpoint)
    dataset = client.datasets.get_dataset(
        dataset=args.dataset_name, version_id=args.dataset_version_id
    )
    if not args.no_validate:
        count = validate(list(dataset.examples))
        print(f"{args.dataset_name}: {count} examples")

    agent = SRUSyntaxAgent(
        system_prompt_version=args.system_prompt_version,
        project_name=args.project_name,
        phoenix_endpoint=args.phoenix_endpoint,
    ).initialize()
    metadata = {
        "server": "mcp-sru-syntax (src/sru_server over stdio)",
        "agent_model": agent.model,
        "judge_model": gateway.judge_model(),
        "system_prompt_version": args.system_prompt_version,
        "git_commit": git_commit(),
    }
    name = f"{args.dataset_name} {args.system_prompt_version} {agent.model}"
    experiment = client.experiments.run_experiment(
        dataset=dataset,
        task=agent.create_experiment_task(),
        evaluators=EVALUATORS,
        experiment_name=name,
        experiment_description=args.experiment_description,
        experiment_metadata=metadata,
        timeout=TASK_TIMEOUT_S,
    )
    print_summary(experiment)
    return experiment


if __name__ == "__main__":
    main()
