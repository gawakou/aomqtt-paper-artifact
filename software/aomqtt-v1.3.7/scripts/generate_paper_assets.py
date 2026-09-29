#!/usr/bin/env python3
"""Generate all paper-ready assets for AOMQTT evaluation results.

This script generates both tables and figures under:

    results/<run_id>/paper/

It is a convenience wrapper around:

    scripts/generate_paper_tables.py
    scripts/generate_paper_figures.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate paper-ready tables and figures for AOMQTT evaluation results."
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        type=Path,
        help="Path to results/<run_id>/",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if required derived CSV files are missing when generating tables.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results_dir = args.results_dir

    if not results_dir.exists():
        print(f"[ERROR] Results directory does not exist: {results_dir}", file=sys.stderr)
        return 1

    script_dir = Path(__file__).resolve().parent

    tables_module = load_module(
        "generate_paper_tables",
        script_dir / "generate_paper_tables.py",
    )
    figures_module = load_module(
        "generate_paper_figures",
        script_dir / "generate_paper_figures.py",
    )

    print(f"[INFO] Generating paper-ready tables from {results_dir}")
    tables_module.generate_tables(results_dir, strict=args.strict)

    print(f"[INFO] Generating paper-ready figures from {results_dir}")
    figures_module.generate_figures(results_dir)

    print(f"[OK] Paper-ready assets generated under {results_dir / 'paper'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
