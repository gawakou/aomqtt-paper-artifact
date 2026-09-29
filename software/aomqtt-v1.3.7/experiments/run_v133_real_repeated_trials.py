#!/usr/bin/env python3
"""Run repeated real local v1.3.3 trials and aggregate them with v1.3.2 statistics."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def command_to_string(cmd: list[str]) -> str:
    import shlex
    return " ".join(shlex.quote(part) for part in cmd)


def run(cmd: list[str]) -> None:
    print("+", command_to_string(cmd))
    subprocess.run(cmd, check=True)


def build_trial_command(args: argparse.Namespace, trial_index: int) -> list[str]:
    trial_id = f"{args.run_id}-trial-{trial_index:02d}"
    trial_out = Path(args.out_dir) / "trials" / f"trial-{trial_index:02d}"
    cmd = [
        sys.executable,
        "experiments/run_v133_real_local_trial.py",
        "--run-id",
        trial_id,
        "--out-dir",
        str(trial_out),
        "--broker",
        args.broker,
        "--port",
        str(args.port),
        "--topic",
        args.topic,
        "--count",
        str(args.count),
        "--interval",
        str(args.interval),
        "--qos",
        str(args.qos),
        "--padding-fixed-size",
        str(args.padding_fixed_size),
        "--rotation-interval",
        str(args.rotation_interval),
        "--rotation-overlap",
        str(args.rotation_overlap),
    ]
    if args.scenarios:
        cmd.extend(["--scenarios", *args.scenarios])
    if args.allow_non_local_broker:
        cmd.append("--allow-non-local-broker")
    cmd.append("--execute" if args.execute else "--dry-run")
    return cmd


def write_manifest(args: argparse.Namespace, trial_commands: list[list[str]], out_dir: Path, mode: str) -> None:
    manifest = {
        "run_id": args.run_id,
        "release": "v1.3.3",
        "mode": mode,
        "trial_count": args.trial_count,
        "count": args.count,
        "broker": f"{args.broker}:{args.port}",
        "out_dir": str(out_dir),
        "trial_commands": [command_to_string(cmd) for cmd in trial_commands],
        "artifacts": {
            "statistics_dir": str(out_dir / "statistics"),
            "v133_repeated_trials_manifest_json": str(out_dir / "v133_repeated_trials_manifest.json"),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "v133_repeated_trials_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps(manifest, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="run-v133-real-local-repeated-001")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--trial-count", type=int, default=3)
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="shelter/siteA/starlink/rtt")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval", type=float, default=0.0)
    parser.add_argument("--qos", type=int, default=1)
    parser.add_argument("--padding-fixed-size", type=int, default=512)
    parser.add_argument("--rotation-interval", type=int, default=30)
    parser.add_argument("--rotation-overlap", type=int, default=5)
    parser.add_argument("--scenarios", nargs="*")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-non-local-broker", action="store_true")
    args = parser.parse_args(argv)

    if args.trial_count < 1:
        raise SystemExit("--trial-count must be >= 1")
    if not args.out_dir:
        args.out_dir = f"results/{args.run_id}"
    if args.execute and args.dry_run:
        raise SystemExit("--execute and --dry-run are mutually exclusive")
    if not args.execute and not args.dry_run:
        args.dry_run = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out_dir)
    trial_commands = [build_trial_command(args, i) for i in range(1, args.trial_count + 1)]

    for cmd in trial_commands:
        run(cmd)

    if args.dry_run:
        write_manifest(args, trial_commands, out_dir, "dry-run")
        return 0

    inputs = [
        str(out_dir / "trials" / f"trial-{i:02d}" / "v131_local_comparison_table.csv")
        for i in range(1, args.trial_count + 1)
    ]
    stats_dir = out_dir / "statistics"
    run(
        [
            sys.executable,
            "experiments/collect_v132_repeated_trial_statistics.py",
            "--inputs",
            *inputs,
            "--out-dir",
            str(stats_dir),
        ]
    )
    write_manifest(args, trial_commands, out_dir, "execute")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

