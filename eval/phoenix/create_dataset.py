"""Upload a CSV dataset to Phoenix, or rebuild the CSV from its evaluation.xml.

From ``eval/phoenix/``::

    uv run create_dataset.py --list
    uv run create_dataset.py --dataset-name sru-mcp-eval-0 --build-csv  # XML -> CSV
    uv run create_dataset.py --dataset-name sru-mcp-eval-0 --dry-run    # validate only
    uv run create_dataset.py --dataset-name sru-mcp-eval-0              # upload
"""

from __future__ import annotations

import argparse
import csv
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

load_dotenv()

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "datasets.yaml"
DEFAULT_PHOENIX_ENDPOINT = "http://localhost:6006"
CSV_COLUMNS = ("query", "responses")


def load_registry(path: Path = REGISTRY) -> dict[str, dict]:
    """The ``datasets:`` mapping of datasets.yaml (name -> entry)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("datasets") or {}


def get_entry(name: str, registry: dict[str, dict] | None = None) -> dict:
    registry = load_registry() if registry is None else registry
    if name not in registry:
        known = ", ".join(sorted(registry)) or "none"
        raise SystemExit(f"Unknown dataset {name!r} (in datasets.yaml: {known}).")
    return registry[name]


def xml_rows(path: Path) -> list[dict[str, str]]:
    """The qa_pairs of an mcp-builder evaluation.xml as {query, responses} rows."""
    rows = []
    for pair in ET.parse(path).getroot().iter("qa_pair"):
        question = (pair.findtext("question") or "").strip()
        answer = (pair.findtext("answer") or "").strip()
        if not question or not answer:
            raise ValueError(f"{path}: every qa_pair needs a question and an answer.")
        rows.append({"query": question, "responses": answer})
    if not rows:
        raise ValueError(f"{path}: no qa_pair elements.")
    return rows


def build_csv(entry: dict) -> Path:
    """Write the entry's CSV from its evaluation.xml; return the CSV path."""
    rows = xml_rows(HERE / entry["xml_path"])
    out = HERE / entry["csv_path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return out


def load_dataframe(entry: dict, csv_path: str | Path | None = None) -> pd.DataFrame:
    """Read the CSV and check the input and output columns exist and are filled."""
    path = Path(csv_path) if csv_path else HERE / entry["csv_path"]
    if not path.is_file():
        raise SystemExit(f"CSV not found: {path} (run with --build-csv first?)")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    keys = list(entry["input_keys"]) + list(entry["output_keys"])
    missing = [key for key in keys if key not in df.columns]
    if missing:
        raise SystemExit(
            f"{path}: missing column(s) {missing}; has {list(df.columns)}."
        )
    if df.empty:
        raise SystemExit(f"{path}: no rows.")
    empty = [i + 2 for i, row in df[keys].iterrows() if any(not v.strip() for v in row)]
    if empty:
        raise SystemExit(f"{path}: empty values on CSV line(s) {empty}.")
    return df


def upload(name: str, df: pd.DataFrame, entry: dict, endpoint: str):
    from phoenix.client import Client

    client = Client(base_url=endpoint)
    return client.datasets.create_dataset(
        name=name,
        dataframe=df,
        input_keys=entry["input_keys"],
        output_keys=entry["output_keys"],
        dataset_description=entry.get("description"),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list", action="store_true", help="list registered datasets")
    parser.add_argument("--dataset-name", help="dataset name in datasets.yaml")
    parser.add_argument(
        "--phoenix-name", help="name in Phoenix (default: --dataset-name)"
    )
    parser.add_argument("--csv-path", help="CSV to load instead of the registered one")
    parser.add_argument(
        "--build-csv",
        action="store_true",
        help="regenerate the CSV from evaluation.xml",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="validate without uploading"
    )
    parser.add_argument(
        "--phoenix-endpoint",
        default=os.getenv("PHOENIX_COLLECTOR_ENDPOINT", DEFAULT_PHOENIX_ENDPOINT),
    )
    args = parser.parse_args(argv)

    registry = load_registry()
    if args.list:
        for name, entry in sorted(registry.items()):
            print(f"{name}: {entry.get('description', '')}")
        return
    if not args.dataset_name:
        parser.error("--dataset-name is required (or use --list)")
    entry = get_entry(args.dataset_name, registry)
    if args.build_csv:
        print(f"wrote {build_csv(entry).relative_to(HERE)}")
    df = load_dataframe(entry, args.csv_path)
    print(f"{args.dataset_name}: {len(df)} examples, columns {list(df.columns)}")
    if args.dry_run:
        print("dry run: not uploaded")
        return
    dataset = upload(
        args.phoenix_name or args.dataset_name, df, entry, args.phoenix_endpoint
    )
    print(f"uploaded {dataset.name} (id {dataset.id}, version {dataset.version_id})")


if __name__ == "__main__":
    main()
