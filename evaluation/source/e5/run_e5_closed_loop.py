#!/usr/bin/env python3
"""
AOMQTT E5 single-step closed-loop demonstration.

Runs one publisher and one subscriber as separate local processes against a
live MQTT broker, while using the unmodified bundled AOMQTT v1.3.7 controller.

Loop:
  1. Start with rotation overlap = 5 s and fixed 512-B padding.
  2. Observe for PRE_SECONDS.
  3. Freeze raw CSV snapshots.
  4. Use the E5 observation adapter to expose numeric `seq` to the unmodified
     v1.3.7 AutoPolicyController.
  5. Existing v1.3.7 rule detects duplicate_rate > 0.10 and selects
     decrease_overlap.
  6. Existing generator reduces overlap by the configured step. The formal E5
     configuration uses a 2-s step, i.e. 5 s -> 3 s.
  7. Controller signs and publishes the policy through the live broker.
  8. Publisher and subscriber must ACK=accepted and STATUS=applied.
  9. After a settle interval, observe POST_SECONDS and compare behavior.

This is a single-step functional closed-loop demonstration. It is not a test
of control stability, convergence, or optimality.

Important:
  - Broker port must be 1883 because v1.3.7 AutoPolicyController currently
    hard-codes port 1883 for ACK/Status tracking and policy publication.
  - Publisher and subscriber run on the same host in this minimal E5 harness.
    The broker is live and may be local or remote.
  - Ephemeral private signing keys are deleted before the harness exits.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


INITIAL_POLICY_ID = "e5_overlap5_fixed512"
GENERATED_SEQUENCE_NO = 2


def utc_run_id() -> str:
    return time.strftime("e5-%Y%m%dT%H%M%SZ", time.gmtime())


def git_value(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_tcp(host: str, port: int, timeout: float = 5.0) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass


def ensure_alive(proc: subprocess.Popen, name: str) -> None:
    rc = proc.poll()
    if rc is not None:
        raise RuntimeError(f"{name} exited early with rc={rc}")


def stop_process(proc: subprocess.Popen | None, name: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=8)
        return
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=5)
        return
    except Exception:
        pass
    try:
        proc.kill()
        proc.wait(timeout=3)
    except Exception:
        print(f"WARNING: failed to stop {name}", file=sys.stderr)


def stable_copy_csv(src: Path, dst: Path, attempts: int = 10) -> None:
    """Copy a flushed CSV prefix and require it to parse cleanly."""
    last_error: Exception | None = None
    dst.parent.mkdir(parents=True, exist_ok=True)

    for _ in range(attempts):
        try:
            shutil.copyfile(src, dst)
            data = dst.read_bytes()
            if data and not data.endswith(b"\n"):
                raise ValueError("snapshot does not end at a complete line")
            with dst.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                raise ValueError("snapshot has no data rows")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.15)

    raise RuntimeError(f"could not create stable CSV snapshot from {src}: {last_error}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def f(row: dict[str, str], key: str) -> float | None:
    try:
        s = row.get(key, "").strip()
        return float(s) if s else None
    except Exception:
        return None


def truthy(v: str | None) -> bool | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "ok", "success", "succeeded"}:
        return True
    if s in {"0", "false", "no", "n", "ng", "fail", "failed"}:
        return False
    return None


def filter_by_time(rows: list[dict[str, str]], start: float, end: float) -> list[dict[str, str]]:
    out = []
    for row in rows:
        ts = f(row, "timestamp")
        if ts is not None and start <= ts < end:
            out.append(row)
    return out


def message_id(row: dict[str, str]) -> str:
    return (row.get("message_id") or row.get("logical_seq") or "").strip()


def phase_metrics(pub_rows: list[dict[str, str]], sub_rows: list[dict[str, str]]) -> dict[str, Any]:
    all_pub_ids: set[str] = set()
    successful_pub_ids: set[str] = set()

    for row in pub_rows:
        mid = message_id(row)
        if not mid:
            continue
        all_pub_ids.add(mid)
        if truthy(row.get("success")) is True:
            successful_pub_ids.add(mid)

    failed_pub_ids = all_pub_ids - successful_pub_ids

    recv_counts: dict[str, int] = {}
    decrypt_values: list[bool] = []
    latencies: list[float] = []

    for row in sub_rows:
        mid = message_id(row)
        b = truthy(row.get("decrypt_success"))
        if b is not None:
            decrypt_values.append(b)
        if b is not False and mid:
            recv_counts[mid] = recv_counts.get(mid, 0) + 1
        lat = f(row, "delivery_latency_ms")
        if lat is not None and lat >= 0:
            latencies.append(lat)

    recv_ids = set(recv_counts)
    lost = sorted(successful_pub_ids - recv_ids)
    duplicate_ids = sorted(k for k, count in recv_counts.items() if count > 1)

    physical_publish_rows = len(pub_rows)
    logical_publish = len(successful_pub_ids)
    physical_per_logical = (
        physical_publish_rows / logical_publish if logical_publish else None
    )
    duplicate_rows = sum(max(0, c - 1) for c in recv_counts.values())
    total_recv_rows = sum(recv_counts.values())
    controller_style_duplicate_rate = (
        duplicate_rows / total_recv_rows if total_recv_rows else None
    )
    duplicate_id_rate = (
        len(duplicate_ids) / len(recv_ids) if recv_ids else None
    )
    loss_rate = len(lost) / logical_publish if logical_publish else None
    decrypt_success_rate = (
        sum(1 for b in decrypt_values if b) / len(decrypt_values)
        if decrypt_values else None
    )
    avg_delivery_latency_ms = (
        sum(latencies) / len(latencies) if latencies else None
    )

    policy_ids_pub = sorted({r.get("policy_id", "") for r in pub_rows if r.get("policy_id")})
    policy_ids_sub = sorted({r.get("policy_id", "") for r in sub_rows if r.get("policy_id")})

    reconnect_values = []
    for row in pub_rows:
        try:
            s = (row.get("reconnect_count") or "").strip()
            if s:
                reconnect_values.append(int(float(s)))
        except Exception:
            pass
    reconnect_count_max = max(reconnect_values) if reconnect_values else 0

    return {
        "publisher_rows": physical_publish_rows,
        "subscriber_rows": len(sub_rows),
        "all_publisher_logical_messages": len(all_pub_ids),
        "successfully_published_logical_messages": logical_publish,
        "failed_publisher_logical_messages": len(failed_pub_ids),
        "failed_publisher_logical_ids": sorted(failed_pub_ids)[:20],
        "publisher_reconnect_count": reconnect_count_max,
        "unique_received_messages": len(recv_ids),
        "lost_messages": len(lost),
        "loss_rate": loss_rate,
        "duplicate_message_ids": len(duplicate_ids),
        "duplicate_extra_rows": duplicate_rows,
        "duplicate_rate_per_received_row": controller_style_duplicate_rate,
        "duplicate_rate_per_unique_received": duplicate_id_rate,
        "physical_publish_rows_per_successful_logical_message": physical_per_logical,
        "decrypt_success_rate": decrypt_success_rate,
        "avg_delivery_latency_ms": avg_delivery_latency_ms,
        "publisher_policy_ids": policy_ids_pub,
        "subscriber_policy_ids": policy_ids_sub,
        "lost_ids": lost[:20],
        "duplicate_ids": duplicate_ids[:20],
    }


def extract_controller_json(text: str) -> dict[str, Any]:
    """Extract AutoPolicyController's result JSON from mixed stdout.

    The bundled v1.3.7 controller invokes policy_controller_publish.py as a
    subprocess without capturing its stdout.  That helper prints human-readable
    lines and a control-message JSON object before policy_auto_controller.py
    prints the final result JSON.  Therefore stdout is not a single JSON
    document and cannot be decoded from byte zero.

    Scan every possible JSON-object start and select the object that has the
    distinctive AutoPolicyController result keys.
    """
    decoder = json.JSONDecoder()
    required = {"metrics", "decision", "generated_policy_id", "output_policy_path"}

    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and required.issubset(obj.keys()):
            return obj

    preview = text[:2000]
    raise ValueError(
        "AutoPolicyController result JSON not found in mixed stdout. "
        f"stdout preview:\n{preview}"
    )


def tracker_has_client_applied(summary: str, client_id: str) -> bool:
    for line in summary.splitlines():
        if client_id in line and "accepted" in line and "applied" in line:
            return True
    return False


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"invalid YAML mapping: {path}")
    return data


def extract_policy_dict(data: dict[str, Any]) -> dict[str, Any]:
    p = data.get("policy", data)
    if not isinstance(p, dict):
        raise ValueError("policy YAML does not contain a mapping")
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", required=True)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--pre-seconds", type=float, default=90.0)
    ap.add_argument("--post-seconds", type=float, default=90.0)
    ap.add_argument("--settle-seconds", type=float, default=5.0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument(
        "--overlap-step-sec",
        type=int,
        default=2,
        help="controller decrease-overlap step; formal E5 uses 2 s (5 s -> 3 s)",
    )
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--out-root", default=None)
    args = ap.parse_args()

    if args.port != 1883:
        raise SystemExit(
            "E5 requires --port 1883 because bundled v1.3.7 AutoPolicyController "
            "uses port 1883 internally."
        )
    if args.pre_seconds < 60:
        raise SystemExit("--pre-seconds should be >= 60 s for the 30-s rotation experiment")
    if args.post_seconds < 30:
        raise SystemExit("--post-seconds should be >= 30 s")
    if args.overlap_step_sec <= 0 or args.overlap_step_sec > 5:
        raise SystemExit("--overlap-step-sec must be in 1..5 for this E5 design")

    expected_overlap_sec = max(0, 5 - args.overlap_step_sec)

    script_path = Path(__file__).resolve()
    repo = script_path.parents[3]
    software = repo / "software" / "aomqtt-v1.3.7"
    e5_dir = repo / "evaluation" / "source" / "e5"
    adapter = e5_dir / "build_closed_loop_observation.py"
    initial_policy = e5_dir / "e5_initial_policy.yaml"
    config = software / "examples" / "config.example.yaml"

    for required in (adapter, initial_policy, config):
        if not required.is_file():
            raise SystemExit(f"missing required file: {required}")

    run_id = args.run_id or utc_run_id()
    out_root = (
        Path(args.out_root).resolve()
        if args.out_root
        else repo / "results" / "e5" / run_id
    )
    out_root.mkdir(parents=True, exist_ok=False)

    logs = out_root / "logs"
    raw = out_root / "raw"
    pre = out_root / "pre"
    final = out_root / "final"
    for d in (logs, raw, pre, final):
        d.mkdir(parents=True, exist_ok=True)

    private_key = out_root / ".policy_signing_private.key"
    public_key = out_root / "policy_signing_public.key"
    generated_policy = out_root / "generated_policy.yaml"

    pub_csv = raw / "publisher_metrics.csv"
    sub_csv = raw / "subscriber_metrics.csv"
    pre_pub_raw = pre / "publisher_raw_snapshot.csv"
    pre_sub_raw = pre / "subscriber_raw_snapshot.csv"

    pub_id = f"e5-pub-{run_id[-8:]}"
    sub_id = f"e5-sub-{run_id[-8:]}"
    group_id = f"e5-{run_id[-8:]}"
    experiment_id = "aomqtt-e5-closed-loop"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(software)

    pub_proc: subprocess.Popen | None = None
    sub_proc: subprocess.Popen | None = None
    pub_log = None
    sub_log = None

    wall_started = time.time()
    pre_start_wall: float | None = None
    pre_end_wall: float | None = None
    controller_started_wall: float | None = None
    controller_finished_wall: float | None = None
    post_start_wall: float | None = None
    post_end_wall: float | None = None

    try:
        print("AOMQTT E5 closed-loop demonstration")
        print("===================================")
        print(f"repo: {repo}")
        print(f"broker: {args.broker}:{args.port}")
        print(f"run_id: {run_id}")
        print(f"output: {out_root}")

        wait_tcp(args.broker, args.port)
        print("broker TCP preflight: PASS")

        subprocess.run(
            [
                sys.executable,
                "examples/generate_policy_keys.py",
                "--private-out", str(private_key),
                "--public-out", str(public_key),
            ],
            cwd=software,
            env=env,
            check=True,
        )

        # The publisher must outlive pre + controller + post. It is stopped
        # explicitly after the formal post window.
        publisher_count = int(
            math.ceil(
                (
                    args.pre_seconds
                    + args.post_seconds
                    + args.settle_seconds
                    + 120.0
                ) / args.interval
            )
        )

        sub_cmd = [
            sys.executable,
            "examples/subscriber_example.py",
            "--broker", args.broker,
            "--port", str(args.port),
            "--client-id", sub_id,
            "--config", str(config),
            "--policy", str(initial_policy),
            "--enable-control-topic",
            "--control-group-id", group_id,
            "--control-policy-public-key-file", str(public_key),
            "--topic", "e5/siteA/closedloop",
            "--delivery-csv", str(sub_csv),
            "--experiment-id", experiment_id,
            "--run-id", run_id,
            "--save-experiment-config",
            "--experiment-config-out", str(raw / "subscriber_experiment_config.json"),
        ]

        pub_cmd = [
            sys.executable,
            "examples/publisher_example.py",
            "--broker", args.broker,
            "--port", str(args.port),
            "--client-id", pub_id,
            "--config", str(config),
            "--policy", str(initial_policy),
            "--enable-control-topic",
            "--control-group-id", group_id,
            "--control-policy-public-key-file", str(public_key),
            "--topic", "e5/siteA/closedloop",
            "--count", str(publisher_count),
            "--interval", str(args.interval),
            "--pacing", "fixed-rate",
            "--metrics-csv", str(pub_csv),
            "--experiment-id", experiment_id,
            "--run-id", run_id,
            "--save-experiment-config",
            "--experiment-config-out", str(raw / "publisher_experiment_config.json"),
        ]

        sub_log = (logs / "subscriber.log").open("w", encoding="utf-8")
        sub_proc = subprocess.Popen(
            sub_cmd,
            cwd=software,
            env=env,
            stdout=sub_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(2.0)
        ensure_alive(sub_proc, "subscriber")

        pub_log = (logs / "publisher.log").open("w", encoding="utf-8")
        pre_start_wall = time.time()
        pub_proc = subprocess.Popen(
            pub_cmd,
            cwd=software,
            env=env,
            stdout=pub_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(2.0)
        ensure_alive(pub_proc, "publisher")
        ensure_alive(sub_proc, "subscriber")

        print(f"pre-observation: {args.pre_seconds:.1f} s")
        target = time.monotonic() + max(0.0, args.pre_seconds - 2.0)
        while time.monotonic() < target:
            ensure_alive(pub_proc, "publisher")
            ensure_alive(sub_proc, "subscriber")
            time.sleep(min(1.0, target - time.monotonic()))

        pre_end_wall = time.time()
        stable_copy_csv(pub_csv, pre_pub_raw)
        stable_copy_csv(sub_csv, pre_sub_raw)

        adapter_cmd = [
            sys.executable,
            str(adapter),
            "--publisher-raw", str(pre_pub_raw),
            "--subscriber-raw", str(pre_sub_raw),
            "--out-root", str(pre / "controller-input"),
            "--label", "pre-control",
        ]
        adapter_result = subprocess.run(
            adapter_cmd,
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        (logs / "adapter.log").write_text(adapter_result.stdout, encoding="utf-8")

        manifest = json.loads(
            (pre / "controller-input" / "observation_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        pre_pub_obs = manifest["independent_metrics"]["publisher"]
        pre_obs = manifest["independent_metrics"]["subscriber"]
        dup = pre_obs.get("duplicate_rate")
        loss = pre_obs.get("loss_rate")
        dec = pre_obs.get("decrypt_success_rate")
        failed_pub = int(pre_pub_obs.get("failed_logical_messages") or 0)
        pre_reconnects = int(pre_pub_obs.get("reconnect_count") or 0)

        if pre_reconnects != 0:
            raise RuntimeError(
                "pre reconnect gate failed: "
                f"publisher reconnect_count={pre_reconnects}"
            )
        if failed_pub != 0:
            raise RuntimeError(
                "pre publisher-success gate failed: "
                f"{failed_pub} logical message(s) had no successful physical publish; "
                f"ids={pre_pub_obs.get('failed_logical_ids')}"
            )
        if dup is None or not (float(dup) > 0.10):
            raise RuntimeError(f"pre duplicate_rate gate failed: {dup!r} <= 0.10")
        if loss is None or abs(float(loss)) > 1e-12:
            raise RuntimeError(f"pre loss_rate gate failed: {loss!r}")
        if dec is None or abs(float(dec) - 1.0) > 1e-12:
            raise RuntimeError(f"pre decrypt_success_rate gate failed: {dec!r}")

        print(
            "pre gate: PASS "
            f"(publisher_reconnect_count={pre_reconnects}, "
            f"publisher_failed_logical={failed_pub}, "
            f"duplicate_rate={float(dup):.6f}, "
            f"loss_rate={float(loss):.6f}, decrypt_success_rate={float(dec):.6f})"
        )

        controller_cmd = [
            sys.executable,
            "examples/policy_auto_controller.py",
            "--broker", args.broker,
            "--group-id", group_id,
            "--base-policy", str(initial_policy),
            "--publisher-metrics",
            str(pre / "controller-input" / "publisher_controller_input.csv"),
            "--subscriber-metrics",
            str(pre / "controller-input" / "subscriber_controller_input.csv"),
            "--sequence-no", str(GENERATED_SEQUENCE_NO),
            "--output-policy", str(generated_policy),
            "--valid-after", "2.0",
            "--expires-after", "3600",
            "--signing-private-key-file", str(private_key),
            "--expected-clients", f"{pub_id},{sub_id}",
            "--ack-timeout-sec", "10",
            "--apply-timeout-sec", "20",
            "--duplicate-rate-threshold", "0.10",
            "--overlap-step-sec", str(args.overlap_step_sec),
        ]

        controller_started_wall = time.time()
        controller_result = subprocess.run(
            controller_cmd,
            cwd=software,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
        controller_finished_wall = time.time()

        (logs / "controller.log").write_text(
            controller_result.stdout
            + ("\n--- STDERR ---\n" + controller_result.stderr if controller_result.stderr else ""),
            encoding="utf-8",
        )
        if controller_result.returncode != 0:
            raise RuntimeError(
                f"controller failed rc={controller_result.returncode}; "
                f"see {logs / 'controller.log'}"
            )

        cobj = extract_controller_json(controller_result.stdout)
        action = cobj.get("decision", {}).get("action")
        if action != "decrease_overlap":
            raise RuntimeError(f"unexpected controller action: {action!r}")

        generated = load_yaml(generated_policy)
        generated_p = extract_policy_dict(generated)
        generated_policy_id = str(
            generated_p.get("id") or generated_p.get("policy_id") or ""
        )
        generated_overlap = int(
            generated_p.get("rotation", {}).get("overlap_sec", -1)
        )
        if generated_overlap != expected_overlap_sec:
            raise RuntimeError(
                "generated overlap gate failed: "
                f"expected {expected_overlap_sec}, got {generated_overlap}"
            )

        tracker_summary = cobj.get("tracker_summary") or ""
        if not tracker_has_client_applied(tracker_summary, pub_id):
            raise RuntimeError(f"publisher ACK/Status gate failed: {pub_id}")
        if not tracker_has_client_applied(tracker_summary, sub_id):
            raise RuntimeError(f"subscriber ACK/Status gate failed: {sub_id}")

        print(
            "controller/apply gate: PASS "
            f"(action={action}, policy={generated_policy_id}, overlap={generated_overlap}s)"
        )

        ensure_alive(pub_proc, "publisher")
        ensure_alive(sub_proc, "subscriber")

        print(f"settle: {args.settle_seconds:.1f} s")
        time.sleep(args.settle_seconds)
        post_start_wall = time.time()

        print(f"post-observation: {args.post_seconds:.1f} s")
        target = time.monotonic() + args.post_seconds
        while time.monotonic() < target:
            ensure_alive(pub_proc, "publisher")
            ensure_alive(sub_proc, "subscriber")
            time.sleep(min(1.0, target - time.monotonic()))
        post_end_wall = time.time()

        stop_process(pub_proc, "publisher")
        stop_process(sub_proc, "subscriber")
        pub_proc = None
        sub_proc = None

        if pub_log:
            pub_log.flush()
        if sub_log:
            sub_log.flush()

        all_pub = read_csv(pub_csv)
        all_sub = read_csv(sub_csv)

        pre_pub = filter_by_time(all_pub, pre_start_wall, pre_end_wall)
        pre_sub = filter_by_time(all_sub, pre_start_wall, pre_end_wall)
        post_pub = filter_by_time(all_pub, post_start_wall, post_end_wall)
        post_sub = filter_by_time(all_sub, post_start_wall, post_end_wall)

        pre_metrics = phase_metrics(pre_pub, pre_sub)
        post_metrics = phase_metrics(post_pub, post_sub)

        final_gates = {
            "pre_publisher_reconnect_zero": (
                pre_metrics["publisher_reconnect_count"] == 0
            ),
            "pre_publisher_failed_logical_zero": (
                pre_metrics["failed_publisher_logical_messages"] == 0
            ),
            "pre_duplicate_rate_gt_0_10": (
                pre_metrics["duplicate_rate_per_received_row"] is not None
                and pre_metrics["duplicate_rate_per_received_row"] > 0.10
            ),
            "controller_action_decrease_overlap": action == "decrease_overlap",
            "generated_overlap_expected": (
                generated_overlap == expected_overlap_sec
            ),
            "publisher_ack_applied": tracker_has_client_applied(tracker_summary, pub_id),
            "subscriber_ack_applied": tracker_has_client_applied(tracker_summary, sub_id),
            "post_generated_policy_publisher": (
                generated_policy_id in post_metrics["publisher_policy_ids"]
                and INITIAL_POLICY_ID not in post_metrics["publisher_policy_ids"]
            ),
            "post_generated_policy_subscriber": (
                generated_policy_id in post_metrics["subscriber_policy_ids"]
                and INITIAL_POLICY_ID not in post_metrics["subscriber_policy_ids"]
            ),
            "post_duplicate_rate_lower": (
                pre_metrics["duplicate_rate_per_received_row"] is not None
                and post_metrics["duplicate_rate_per_received_row"] is not None
                and post_metrics["duplicate_rate_per_received_row"]
                < pre_metrics["duplicate_rate_per_received_row"]
            ),
            "post_duplicate_rate_below_threshold": (
                post_metrics["duplicate_rate_per_received_row"] is not None
                and post_metrics["duplicate_rate_per_received_row"] <= 0.10
            ),
            "post_publisher_reconnect_zero": (
                post_metrics["publisher_reconnect_count"] == 0
            ),
            "post_publisher_failed_logical_zero": (
                post_metrics["failed_publisher_logical_messages"] == 0
            ),
            "post_loss_zero": (
                post_metrics["loss_rate"] is not None
                and abs(post_metrics["loss_rate"]) < 1e-12
            ),
            "post_decrypt_success_one": (
                post_metrics["decrypt_success_rate"] is not None
                and abs(post_metrics["decrypt_success_rate"] - 1.0) < 1e-12
            ),
        }

        formal_pass = all(final_gates.values())

        summary = {
            "schema": "aomqtt-e5-closed-loop-v3",
            "scope": (
                "single-step functional closed-loop demonstration; local publisher "
                "and subscriber processes; live MQTT broker"
            ),
            "run_id": run_id,
            "broker": f"{args.broker}:{args.port}",
            "paper_artifact_git_head": git_value(repo, "rev-parse", "HEAD"),
            "paper_artifact_git_status_short": git_value(repo, "status", "--short"),
            "python": sys.version.split()[0],
            "initial_policy_id": INITIAL_POLICY_ID,
            "generated_policy_id": generated_policy_id,
            "initial_overlap_sec": 5,
            "overlap_step_sec": args.overlap_step_sec,
            "expected_overlap_sec": expected_overlap_sec,
            "generated_overlap_sec": generated_overlap,
            "duplicate_rate_threshold": 0.10,
            "controller_decision": cobj.get("decision"),
            "controller_metrics": cobj.get("metrics"),
            "tracker_summary": tracker_summary,
            "timing": {
                "run_started_wall": wall_started,
                "pre_start_wall": pre_start_wall,
                "pre_end_wall": pre_end_wall,
                "controller_started_wall": controller_started_wall,
                "controller_finished_wall": controller_finished_wall,
                "post_start_wall": post_start_wall,
                "post_end_wall": post_end_wall,
                "pre_seconds_requested": args.pre_seconds,
                "post_seconds_requested": args.post_seconds,
                "settle_seconds": args.settle_seconds,
            },
            "pre": pre_metrics,
            "post": post_metrics,
            "gates": final_gates,
            "formal_pass": formal_pass,
            "artifacts": {
                "publisher_metrics_sha256": sha256_file(pub_csv),
                "subscriber_metrics_sha256": sha256_file(sub_csv),
                "pre_publisher_snapshot_sha256": sha256_file(pre_pub_raw),
                "pre_subscriber_snapshot_sha256": sha256_file(pre_sub_raw),
                "generated_policy_sha256": sha256_file(generated_policy),
                "public_signing_key_sha256": sha256_file(public_key),
            },
        }

        summary_json = final / "closed_loop_summary.json"
        summary_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        def pct(v):
            return "None" if v is None else f"{100.0 * v:.3f}%"

        lines = [
            "AOMQTT E5 closed-loop summary",
            "==============================",
            f"run_id: {run_id}",
            f"broker: {args.broker}:{args.port}",
            f"initial policy: {INITIAL_POLICY_ID}, overlap=5 s",
            f"decision: {action}",
            f"configured overlap step: {args.overlap_step_sec} s",
            f"generated policy: {generated_policy_id}, overlap={generated_overlap} s",
            "",
            "pre:",
            f"  successfully published logical: {pre_metrics['successfully_published_logical_messages']}",
            f"  publisher reconnects: {pre_metrics['publisher_reconnect_count']}",
            f"  failed publisher logical: {pre_metrics['failed_publisher_logical_messages']}",
            f"  physical/successful logical: {pre_metrics['physical_publish_rows_per_successful_logical_message']}",
            f"  duplicate rate / received row: {pct(pre_metrics['duplicate_rate_per_received_row'])}",
            f"  loss rate: {pct(pre_metrics['loss_rate'])}",
            f"  decrypt success: {pct(pre_metrics['decrypt_success_rate'])}",
            "",
            "post:",
            f"  successfully published logical: {post_metrics['successfully_published_logical_messages']}",
            f"  publisher reconnects: {post_metrics['publisher_reconnect_count']}",
            f"  failed publisher logical: {post_metrics['failed_publisher_logical_messages']}",
            f"  physical/successful logical: {post_metrics['physical_publish_rows_per_successful_logical_message']}",
            f"  duplicate rate / received row: {pct(post_metrics['duplicate_rate_per_received_row'])}",
            f"  loss rate: {pct(post_metrics['loss_rate'])}",
            f"  decrypt success: {pct(post_metrics['decrypt_success_rate'])}",
            "",
            "gates:",
        ]
        for key, value in final_gates.items():
            lines.append(f"  {key}: {'PASS' if value else 'FAIL'}")
        lines += [
            "",
            f"E5-CLOSED-LOOP={'PASS' if formal_pass else 'FAIL'}",
        ]

        summary_txt = final / "closed_loop_summary.txt"
        summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print()
        print("\n".join(lines))

        if not formal_pass:
            raise RuntimeError(
                f"E5 formal gates failed; inspect {summary_json}"
            )

        return 0

    finally:
        stop_process(pub_proc, "publisher")
        stop_process(sub_proc, "subscriber")
        if pub_log is not None:
            pub_log.close()
        if sub_log is not None:
            sub_log.close()

        # Never retain the private signing key in the artifact.
        try:
            if private_key.exists():
                private_key.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
