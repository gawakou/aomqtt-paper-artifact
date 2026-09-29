#!/usr/bin/env python3
"""Run one real v1.3.3 local broker measurement trial.

This runner connects v1.3.1 measurement tools into a single local trial:

- plain MQTT baseline;
- AOMQTT basic;
- AOMQTT fixed padding;
- AOMQTT fixed padding + rotation/overlap;
- local comparison table generation.

Safety: by default, this script allows only localhost/127.0.0.1 brokers. Use
--allow-non-local-broker only for explicitly authorized environments.
"""

from __future__ import annotations

import argparse
import json
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCENARIOS = [
    "plain_mqtt_baseline",
    "aomqtt_basic",
    "aomqtt_padding512",
    "aomqtt_padding512_rotation30_overlap5",
]


def is_local_broker(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


def command_to_string(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run_command(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", command_to_string(cmd))
    subprocess.run(cmd, check=True, cwd=str(cwd) if cwd else None)


def start_process(cmd: list[str]) -> subprocess.Popen[str]:
    print("+", command_to_string(cmd))
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def terminate_process(proc: subprocess.Popen[str], timeout: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=timeout)


def drain_process_output(proc: subprocess.Popen[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    output = ""
    if proc.stdout is not None:
        try:
            output = proc.stdout.read() or ""
        except Exception:
            output = ""
    log_path.write_text(output)


def scenario_dir(base_out_dir: Path, scenario_id: str) -> Path:
    return base_out_dir / "scenarios" / scenario_id


def plain_commands(args: argparse.Namespace, scenario_out: Path) -> list[list[str]]:
    summary_json = scenario_out / "summaries" / "plain_mqtt_baseline.json"
    raw_csv = scenario_out / "raw" / "plain_mqtt_baseline.csv"
    return [
        [
            sys.executable,
            "experiments/run_v131_plain_mqtt_measurement.py",
            "--run-id",
            f"{args.run_id}-plain",
            "--broker",
            args.broker,
            "--port",
            str(args.port),
            "--count",
            str(args.count),
            "--qos",
            str(args.qos),
            "--raw-csv",
            str(raw_csv),
            "--summary-json",
            str(summary_json),
        ],
        [
            sys.executable,
            "experiments/run_v131_local_measurements.py",
            "--run-id",
            f"{args.run_id}-plain",
            "--out-dir",
            str(scenario_out),
            "--broker",
            f"{args.broker}:{args.port}",
            "--mode",
            "collect",
        ],
    ]


def subscriber_command(args: argparse.Namespace, scenario_id: str, scenario_out: Path) -> list[str]:
    cmd = [
        sys.executable,
        "examples/subscriber_example.py",
        "--broker",
        args.broker,
        "--port",
        str(args.port),
        "--client-id",
        f"{args.run_id}-{scenario_id}-subscriber",
        "--topic",
        args.topic,
        "--qos",
        str(args.qos),
        "--delivery-csv",
        str(scenario_out / "raw" / "subscriber_metrics.csv"),
        "--run-id",
        f"{args.run_id}-{scenario_id}",
    ]
    if "rotation" in scenario_id:
        cmd.extend(
            [
                "--rotation",
                "--rotation-interval",
                str(args.rotation_interval),
                "--rotation-overlap",
                str(args.rotation_overlap),
            ]
        )
    return cmd


def publisher_command(args: argparse.Namespace, scenario_id: str, scenario_out: Path) -> list[str]:
    cmd = [
        sys.executable,
        "examples/publisher_example.py",
        "--broker",
        args.broker,
        "--port",
        str(args.port),
        "--client-id",
        f"{args.run_id}-{scenario_id}-publisher",
        "--topic",
        args.topic,
        "--count",
        str(args.count),
        "--interval",
        str(args.interval),
        "--qos",
        str(args.qos),
        "--metrics-csv",
        str(scenario_out / "raw" / "publisher_metrics.csv"),
        "--run-id",
        f"{args.run_id}-{scenario_id}",
    ]
    if scenario_id in {"aomqtt_padding512", "aomqtt_padding512_rotation30_overlap5"}:
        cmd.extend(["--padding-mode", "fixed", "--padding-fixed-size", str(args.padding_fixed_size)])
    if "rotation" in scenario_id:
        cmd.extend(
            [
                "--rotation",
                "--rotation-interval",
                str(args.rotation_interval),
                "--rotation-overlap",
                str(args.rotation_overlap),
            ]
        )
    return cmd


def aomqtt_collect_commands(args: argparse.Namespace, scenario_id: str, scenario_out: Path) -> list[list[str]]:
    return [
        [
            sys.executable,
            "experiments/collect_v131_aomqtt_measurement.py",
            "--run-id",
            f"{args.run_id}-{scenario_id}",
            "--scenario-id",
            scenario_id,
            "--publisher-csv",
            str(scenario_out / "raw" / "publisher_metrics.csv"),
            "--subscriber-csv",
            str(scenario_out / "raw" / "subscriber_metrics.csv"),
            "--summary-json",
            str(scenario_out / "summaries" / f"{scenario_id}.json"),
        ],
        [
            sys.executable,
            "experiments/run_v131_local_measurements.py",
            "--run-id",
            f"{args.run_id}-{scenario_id}",
            "--out-dir",
            str(scenario_out),
            "--broker",
            f"{args.broker}:{args.port}",
            "--mode",
            "collect",
        ],
    ]


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    base_out_dir = Path(args.out_dir)
    selected = args.scenarios or SCENARIOS
    steps: list[dict[str, Any]] = []

    for scenario_id in selected:
        out = scenario_dir(base_out_dir, scenario_id)
        if scenario_id == "plain_mqtt_baseline":
            for cmd in plain_commands(args, out):
                steps.append({"scenario_id": scenario_id, "kind": "command", "command": cmd})
        else:
            steps.append({"scenario_id": scenario_id, "kind": "subscriber", "command": subscriber_command(args, scenario_id, out)})
            steps.append({"scenario_id": scenario_id, "kind": "publisher", "command": publisher_command(args, scenario_id, out)})
            for cmd in aomqtt_collect_commands(args, scenario_id, out):
                steps.append({"scenario_id": scenario_id, "kind": "command", "command": cmd})

    comparison_inputs = [str(scenario_dir(base_out_dir, s) / "unified_measurements.csv") for s in selected]
    comparison_cmd = [
        sys.executable,
        "experiments/collect_v131_local_comparison_table.py",
        "--inputs",
        *comparison_inputs,
        "--out-dir",
        str(base_out_dir),
    ]
    steps.append({"scenario_id": "local_comparison", "kind": "command", "command": comparison_cmd})

    return {
        "run_id": args.run_id,
        "release": "v1.3.3",
        "broker": f"{args.broker}:{args.port}",
        "count": args.count,
        "qos": args.qos,
        "topic": args.topic,
        "scenarios": selected,
        "out_dir": str(base_out_dir),
        "steps": steps,
        "safety_policy": "Default execution is limited to localhost/127.0.0.1 brokers.",
    }


def write_plan_files(plan: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "v133_trial_plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True))
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    lines.append("# Generated v1.3.3 local trial plan. Review before executing manually.")
    for step in plan["steps"]:
        lines.append("")
        lines.append(f"# {step['scenario_id']} / {step['kind']}")
        lines.append(command_to_string(step["command"]))
    plan_sh = out_dir / "v133_trial_plan.sh"
    plan_sh.write_text("\n".join(lines) + "\n")
    plan_sh.chmod(0o755)


def execute_plan(args: argparse.Namespace, plan: dict[str, Any]) -> None:
    base_out_dir = Path(args.out_dir)
    base_out_dir.mkdir(parents=True, exist_ok=True)

    for step in plan["steps"]:
        scenario_id = step["scenario_id"]
        kind = step["kind"]
        cmd = step["command"]

        if kind == "subscriber":
            out = scenario_dir(base_out_dir, scenario_id)
            out.mkdir(parents=True, exist_ok=True)
            proc = start_process(cmd)
            time.sleep(args.subscriber_startup_wait)
            # Publisher step follows immediately in the plan.
            step["_process"] = proc
        elif kind == "publisher":
            # Find the most recent subscriber process for this scenario.
            proc = None
            for prior in reversed(plan["steps"]):
                if prior.get("scenario_id") == scenario_id and prior.get("kind") == "subscriber" and "_process" in prior:
                    proc = prior["_process"]
                    break
            try:
                run_command(cmd)
                time.sleep(args.subscriber_drain_wait)
            finally:
                if proc is not None:
                    terminate_process(proc)
                    drain_process_output(proc, scenario_dir(base_out_dir, scenario_id) / "logs" / "subscriber.log")
        elif kind == "command":
            run_command(cmd)

    manifest = {
        "run_id": args.run_id,
        "release": "v1.3.3",
        "mode": "execute",
        "out_dir": str(base_out_dir),
        "comparison_table": str(base_out_dir / "v131_local_comparison_table.csv"),
        "comparison_summary": str(base_out_dir / "v131_local_comparison_summary.json"),
    }
    (base_out_dir / "v133_trial_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps(manifest, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="run-v133-real-local-trial-001")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="shelter/siteA/starlink/rtt")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval", type=float, default=0.0)
    parser.add_argument("--qos", type=int, default=1)
    parser.add_argument("--padding-fixed-size", type=int, default=512)
    parser.add_argument("--rotation-interval", type=int, default=30)
    parser.add_argument("--rotation-overlap", type=int, default=5)
    parser.add_argument("--subscriber-startup-wait", type=float, default=1.0)
    parser.add_argument("--subscriber-drain-wait", type=float, default=1.0)
    parser.add_argument("--scenarios", nargs="*", choices=SCENARIOS)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-non-local-broker", action="store_true")
    args = parser.parse_args(argv)

    if not args.out_dir:
        args.out_dir = f"results/{args.run_id}"

    if args.execute and args.dry_run:
        raise SystemExit("--execute and --dry-run are mutually exclusive")
    if not args.execute and not args.dry_run:
        args.dry_run = True

    if not args.allow_non_local_broker and not is_local_broker(args.broker):
        raise SystemExit(
            f"refusing non-local broker {args.broker!r}; use --allow-non-local-broker only for explicitly authorized environments"
        )

    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out_dir)
    plan = build_plan(args)
    write_plan_files(plan, out_dir)

    if args.dry_run:
        print(json.dumps({"mode": "dry-run", "plan": str(out_dir / "v133_trial_plan.json")}, indent=2, sort_keys=True))
        return 0

    execute_plan(args, plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

