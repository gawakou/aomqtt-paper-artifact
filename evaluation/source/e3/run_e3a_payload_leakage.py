#!/usr/bin/env python3
"""Run the AOMQTT E3-A payload-length leakage experiment.

E3-A compares the same deterministic event plan under three conditions:

A0  Plain MQTT, no encryption, no padding, no rotation
A1  AOMQTT whole-topic tokenization + AES-GCM, no padding, no rotation
A2  AOMQTT whole-topic tokenization + AES-GCM + fixed 512-byte padding,
    no rotation

The runner deliberately keeps the broker-visible observer separate from the
authorized sanity subscriber.  The observer sees only topic, payload length,
timing, QoS, retain, and DUP metadata.

The implementation under evaluation remains AOMQTT v1.3.7 at commit
6dc0b2c497098aca569a636d1f8f8bb2adc4253a.  This script is experiment
harness code added on a descendant branch and records both the base
implementation commit and the harness commit in its manifests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


E3A_SCHEMA_VERSION = "e3a-runner-v1"
AOMQTT_VERSION = "1.3.7"
AOMQTT_BASE_COMMIT = "6dc0b2c497098aca569a636d1f8f8bb2adc4253a"
EXPERIMENT_ID = "aomqtt-e3a-privacy-leakage"

# These are public, synthetic evaluation keys. They are not production secrets.
E3_TOPIC_KEY = "e3-public-topic-key-32chars-demo"
E3_PAYLOAD_KEY = "e3-public-payload-key-32chars-demo"

CONDITIONS: dict[str, dict[str, Any]] = {
    "A0": {
        "kind": "plain",
        "description": "Plain MQTT; no encryption, padding, or rotation",
        "padding_enabled": False,
        "padding_mode": "none",
    },
    "A1": {
        "kind": "aomqtt",
        "description": "AOMQTT whole-topic + AES-GCM; no padding or rotation",
        "padding_enabled": False,
        "padding_mode": "none",
    },
    "A2": {
        "kind": "aomqtt",
        "description": "AOMQTT whole-topic + AES-GCM + fixed512; no rotation",
        "padding_enabled": True,
        "padding_mode": "fixed",
    },
}

PLAN_FIELDS = [
    "event_index",
    "relative_time_ns",
    "message_id",
    "class_id",
    "logical_topic",
    "target_plain_bytes",
]


@dataclass(frozen=True)
class PlanEvent:
    event_index: int
    relative_time_ns: int
    message_id: str
    class_id: str
    logical_topic: str
    target_plain_bytes: int


def _import_generator_helpers():
    """Import helpers from the sibling event-plan generator at runtime."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from generate_e3_event_plan import build_exact_payload, compact_json_bytes
    return build_exact_payload, compact_json_bytes


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_rev_parse(repo: Path, ref: str = "HEAD") -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def is_local_broker(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


def condition_prefix(run_id: str, condition: str) -> str:
    return f"e3/a/{run_id}/{condition}"


def observer_filter(run_id: str, condition: str) -> str:
    return f"{condition_prefix(run_id, condition)}/#"


def plain_topic(run_id: str, condition: str = "A0") -> str:
    return f"{condition_prefix(run_id, condition)}/plain"


def load_plan(path: Path, *, limit_events: int | None = None) -> list[PlanEvent]:
    build_exact_payload, _compact_json_bytes = _import_generator_helpers()

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != PLAN_FIELDS:
            raise ValueError(
                f"unexpected E3-A plan schema: {reader.fieldnames!r}; "
                f"expected {PLAN_FIELDS!r}"
            )
        rows = list(reader)

    if limit_events is not None:
        if limit_events < 1:
            raise ValueError("limit_events must be >= 1")
        rows = rows[:limit_events]

    events: list[PlanEvent] = []
    previous_time = -1
    for expected_index, row in enumerate(rows):
        event = PlanEvent(
            event_index=int(row["event_index"]),
            relative_time_ns=int(row["relative_time_ns"]),
            message_id=row["message_id"],
            class_id=row["class_id"],
            logical_topic=row["logical_topic"],
            target_plain_bytes=int(row["target_plain_bytes"]),
        )
        if event.event_index != expected_index:
            raise ValueError(
                f"non-contiguous event_index at row {expected_index}: "
                f"{event.event_index}"
            )
        if event.relative_time_ns < previous_time:
            raise ValueError("event plan is not ordered by relative_time_ns")
        previous_time = event.relative_time_ns

        # Revalidate exact JSON length before network execution.
        build_exact_payload(
            message_id=event.message_id,
            seq=event.event_index,
            target_plain_bytes=event.target_plain_bytes,
        )
        events.append(event)

    if not events:
        raise ValueError("event plan is empty")
    return events


def write_ground_truth(events: Sequence[PlanEvent], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(PLAN_FIELDS)
        for e in events:
            writer.writerow(
                [
                    e.event_index,
                    e.relative_time_ns,
                    e.message_id,
                    e.class_id,
                    e.logical_topic,
                    e.target_plain_bytes,
                ]
            )


def make_aomqtt_config(condition: str, run_id: str):
    if condition not in {"A1", "A2"}:
        raise ValueError("AOMQTT config is valid only for A1/A2")
    from aomqtt import AOMQTTConfig

    spec = CONDITIONS[condition]
    cfg = AOMQTTConfig(
        topic_key=E3_TOPIC_KEY,
        payload_key=E3_PAYLOAD_KEY,
        topic_prefix=condition_prefix(run_id, condition),
        token_mode="whole",
        token_hex_len=16,
        payload_format="json",
        mqtt_qos=1,
        retain=False,
        key_id="k001",
        aad_bind_topic=True,
        rotation_enabled=False,
        rotation_interval_sec=30,
        rotation_overlap_sec=5,
        padding_enabled=bool(spec["padding_enabled"]),
        padding_mode=str(spec["padding_mode"]),
        padding_fixed_size=512,
    )
    cfg.validate()
    return cfg


def build_observer_command(
    *,
    observer_script: Path,
    broker: str,
    port: int,
    run_id: str,
    condition: str,
    condition_dir: Path,
) -> list[str]:
    return [
        sys.executable,
        str(observer_script),
        "--broker",
        broker,
        "--port",
        str(port),
        "--filter",
        observer_filter(run_id, condition),
        "--qos",
        "1",
        "--client-id",
        f"e3a-{run_id}-{condition}-observer",
        "--run-id",
        run_id,
        "--condition",
        condition,
        "--output",
        str(condition_dir / "observer.csv"),
        "--ready-file",
        str(condition_dir / "observer.ready"),
        "--summary-file",
        str(condition_dir / "observer.summary.json"),
    ]


def wait_for_path(path: Path, timeout_sec: float) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


def wait_until_ns(target_ns: int) -> int:
    """Wait until target monotonic time and return non-negative lateness in ns."""
    while True:
        remaining = target_ns - time.monotonic_ns()
        if remaining <= 0:
            break
        # Absolute-deadline pacing; sleep instead of post-publish delay.
        time.sleep(remaining / 1_000_000_000)
    return max(0, time.monotonic_ns() - target_ns)


def make_paho_client(client_id: str):
    import paho.mqtt.client as mqtt
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
    except Exception:
        return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)


class PlainSanitySubscriber:
    def __init__(
        self,
        *,
        broker: str,
        port: int,
        topic: str,
        client_id: str,
        output_csv: Path,
    ) -> None:
        self.broker = broker
        self.port = port
        self.topic = topic
        self.client = make_paho_client(client_id)
        self.ready_event = threading.Event()
        self.preflight_event = threading.Event()
        self._formal = False
        self._lock = threading.Lock()
        self._received_ids: list[str] = []

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        self._fh = output_csv.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._fh,
            fieldnames=[
                "recv_unix_ns",
                "message_id",
                "logical_seq",
                "payload_bytes",
                "parse_success",
            ],
            lineterminator="\n",
        )
        self._writer.writeheader()
        self._fh.flush()

        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        client.subscribe(self.topic, qos=1)

    def _on_subscribe(self, client, userdata, mid, *args):
        self.ready_event.set()

    def _on_message(self, client, userdata, msg):
        payload_bytes = bytes(msg.payload)
        parse_success = False
        message_id = ""
        logical_seq = ""
        try:
            decoded = json.loads(payload_bytes.decode("utf-8"))
            message_id = str(decoded.get("message_id", ""))
            logical_seq = str(decoded.get("seq", ""))
            parse_success = True
        except Exception:
            pass

        if message_id.startswith("preflight:"):
            self.preflight_event.set()
            return

        with self._lock:
            if not self._formal:
                return
            self._received_ids.append(message_id)
            self._writer.writerow(
                {
                    "recv_unix_ns": time.time_ns(),
                    "message_id": message_id,
                    "logical_seq": logical_seq,
                    "payload_bytes": len(payload_bytes),
                    "parse_success": int(parse_success),
                }
            )
            self._fh.flush()

    @property
    def unique_received(self) -> int:
        with self._lock:
            return len({m for m in self._received_ids if m})

    @property
    def total_received(self) -> int:
        with self._lock:
            return len(self._received_ids)

    def connect(self, timeout_sec: float = 5.0) -> None:
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()
        if not self.ready_event.wait(timeout_sec):
            raise RuntimeError("plain sanity subscriber did not receive SUBACK")

    def begin_formal(self) -> None:
        with self._lock:
            self._received_ids.clear()
            self._formal = True

    def stop(self) -> None:
        self._formal = False
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()
            self._fh.close()


class AOMQTTSanitySubscriber:
    def __init__(
        self,
        *,
        broker: str,
        port: int,
        run_id: str,
        condition: str,
        logical_topic: str,
        output_csv: Path,
    ) -> None:
        from aomqtt import AOMQTTSubscriber

        self.condition = condition
        self.logical_topic = logical_topic
        self.config = make_aomqtt_config(condition, run_id)
        self.sub = AOMQTTSubscriber(
            broker_host=broker,
            broker_port=port,
            client_id=f"e3a-{run_id}-{condition}-subscriber",
            config=self.config,
        )
        self.output_csv = output_csv
        self.preflight_event = threading.Event()
        self._formal = False
        self._lock = threading.Lock()
        self._received_ids: list[str] = []
        self.delivery_logger = None

    def _callback(self, token_topic, payload, raw_msg):
        message_id = ""
        if isinstance(payload, dict):
            message_id = str(payload.get("message_id", ""))

        if message_id.startswith("preflight:"):
            self.preflight_event.set()
            return

        with self._lock:
            if self._formal:
                self._received_ids.append(message_id)

    def connect(self, timeout_sec: float = 5.0) -> None:
        self.sub.connect()
        self.sub.loop_start()
        deadline = time.monotonic() + timeout_sec
        while not self.sub.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self.sub.connected:
            raise RuntimeError("AOMQTT sanity subscriber did not connect")
        self.sub.subscribe(self.logical_topic, callback=self._callback, qos=1)
        # Subscription readiness is verified by the preflight message before
        # the independent observer is started.

    def begin_formal(self, run_id: str) -> None:
        from aomqtt import DeliveryCSVLogger

        with self._lock:
            self._received_ids.clear()
            self._formal = True

        self.delivery_logger = DeliveryCSVLogger(
            self.output_csv,
            experiment_id=EXPERIMENT_ID,
            run_id=run_id,
        )
        self.sub.enable_delivery_observation(
            csv_logger=self.delivery_logger,
            plaintext_filter=self.logical_topic,
            reset_seen=True,
        )

    @property
    def unique_received(self) -> int:
        with self._lock:
            return len({m for m in self._received_ids if m})

    @property
    def total_received(self) -> int:
        with self._lock:
            return len(self._received_ids)

    def delivery_summary(self) -> dict[str, Any]:
        if self.delivery_logger is None:
            return {
                "total_received": 0,
                "decrypt_success": 0,
                "decrypt_failed": 0,
                "unique_messages": 0,
                "duplicates": 0,
            }
        s = self.delivery_logger.summary()
        return {
            "total_received": s.total_received,
            "decrypt_success": s.decrypt_success,
            "decrypt_failed": s.decrypt_failed,
            "unique_messages": s.unique_messages,
            "duplicates": s.duplicates,
        }

    def stop(self) -> None:
        self._formal = False
        if self.delivery_logger is not None:
            self.delivery_logger.close()
            self.delivery_logger = None
        self.sub.loop_stop()
        self.sub.disconnect()


class PlainPublisher:
    def __init__(
        self,
        *,
        broker: str,
        port: int,
        run_id: str,
        condition: str,
        output_csv: Path,
    ) -> None:
        self.topic = plain_topic(run_id, condition)
        self.client = make_paho_client(f"e3a-{run_id}-{condition}-publisher")
        self.client.connect(broker, port, 60)
        self.client.loop_start()

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        self._fh = output_csv.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._fh,
            fieldnames=[
                "event_index",
                "message_id",
                "logical_seq",
                "mqtt_topic",
                "payload_plain_bytes",
                "payload_wire_bytes",
                "success",
                "mid",
                "publish_complete_ms",
            ],
            lineterminator="\n",
        )
        self._writer.writeheader()
        self._fh.flush()
        self.success_count = 0

    def preflight(self, payload_bytes: bytes) -> None:
        info = self.client.publish(self.topic, payload=payload_bytes, qos=1, retain=False)
        info.wait_for_publish(timeout=5)

    def publish_event(self, event: PlanEvent, payload_bytes: bytes) -> None:
        start = time.perf_counter()
        info = self.client.publish(self.topic, payload=payload_bytes, qos=1, retain=False)
        info.wait_for_publish(timeout=5)
        end = time.perf_counter()
        success = bool(info.is_published())
        if success:
            self.success_count += 1
        self._writer.writerow(
            {
                "event_index": event.event_index,
                "message_id": event.message_id,
                "logical_seq": event.event_index,
                "mqtt_topic": self.topic,
                "payload_plain_bytes": len(payload_bytes),
                "payload_wire_bytes": len(payload_bytes),
                "success": int(success),
                "mid": int(getattr(info, "mid", -1)),
                "publish_complete_ms": (end - start) * 1000.0,
            }
        )
        self._fh.flush()

    def stop(self) -> None:
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()
            self._fh.close()


class AOMQTTPublisherHarness:
    def __init__(
        self,
        *,
        broker: str,
        port: int,
        run_id: str,
        condition: str,
        output_csv: Path,
    ) -> None:
        from aomqtt import AOMQTTPublisher, PublishCSVLogger

        self.condition = condition
        self.config = make_aomqtt_config(condition, run_id)
        self.pub = AOMQTTPublisher(
            broker_host=broker,
            broker_port=port,
            client_id=f"e3a-{run_id}-{condition}-publisher",
            config=self.config,
        )
        self.pub.connect()
        self.pub.loop_start()

        deadline = time.monotonic() + 5.0
        while not self.pub.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self.pub.connected:
            raise RuntimeError("AOMQTT publisher did not connect")

        self.logger = PublishCSVLogger(
            output_csv,
            experiment_id=EXPERIMENT_ID,
            run_id=run_id,
        )

    def preflight(self, logical_topic: str, payload: dict[str, Any]) -> None:
        infos = self.pub.publish_rotating(logical_topic, payload, qos=1)
        for info in infos:
            info.wait_for_publish(timeout=5)

    def publish_event(self, event: PlanEvent, payload: dict[str, Any]) -> None:
        metrics = self.pub.publish_observed_rotating(
            event.logical_topic,
            payload,
            qos=1,
            logical_seq=event.event_index,
            message_id=event.message_id,
            wait_for_publish=True,
            wait_timeout=5.0,
            csv_logger=self.logger,
        )
        if len(metrics) != 1:
            raise RuntimeError(
                f"{self.condition} produced {len(metrics)} physical publishes "
                "with rotation disabled"
            )

    @property
    def success_count(self) -> int:
        return self.logger.summary().success

    @property
    def physical_count(self) -> int:
        return self.logger.summary().total

    def stop(self) -> None:
        self.logger.close()
        self.pub.loop_stop()
        self.pub.disconnect()


def make_preflight_payload() -> dict[str, Any]:
    return {
        "message_id": "preflight:e3a",
        "seq": -1,
        "blob": "ready",
    }


def start_observer(command: list[str], condition_dir: Path) -> subprocess.Popen[str]:
    log_path = condition_dir / "observer.log"
    log_fh = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        command,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Attach the handle for deterministic close after process exit.
    proc._e3_log_fh = log_fh  # type: ignore[attr-defined]
    return proc


def stop_observer(proc: subprocess.Popen[str], timeout_sec: float = 5.0) -> int:
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=timeout_sec)
    log_fh = getattr(proc, "_e3_log_fh", None)
    if log_fh is not None:
        log_fh.close()
    return int(proc.returncode or 0)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarize_observer(path: Path) -> dict[str, Any]:
    rows = read_csv_rows(path)
    seqs = [int(r["observer_seq"]) for r in rows] if rows else []
    payload_sizes = [int(r["mqtt_payload_bytes"]) for r in rows]
    return {
        "row_count": len(rows),
        "sequence_contiguous": seqs == list(range(len(rows))),
        "unique_payload_sizes": sorted(set(payload_sizes)),
        "unique_payload_size_count": len(set(payload_sizes)),
    }


def evaluate_gate(
    *,
    condition: str,
    expected_events: int,
    full_formal_plan: bool,
    class_counts: dict[str, int],
    publisher_success: int,
    publisher_physical: int,
    observer_summary: dict[str, Any],
    subscriber_total: int,
    subscriber_unique: int,
    decrypt_failed: int,
    duplicates: int,
) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "planned_events_positive": expected_events > 0,
        "publisher_success_equals_plan": publisher_success == expected_events,
        "publisher_physical_equals_plan": publisher_physical == expected_events,
        "observer_rows_equal_plan": observer_summary["row_count"] == expected_events,
        "observer_sequence_contiguous": bool(observer_summary["sequence_contiguous"]),
        "subscriber_total_equals_plan": subscriber_total == expected_events,
        "subscriber_unique_equals_plan": subscriber_unique == expected_events,
        "decrypt_failures_zero": decrypt_failed == 0,
        "duplicates_zero": duplicates == 0,
    }

    if full_formal_plan:
        checks["class_balance_500_each"] = class_counts == {
            f"C{i}": 500 for i in range(1, 9)
        }

    if condition == "A2":
        checks["fixed_padding_single_observed_size"] = (
            observer_summary["unique_payload_size_count"] == 1
        )

    return {
        "condition": condition,
        "expected_events": expected_events,
        "full_formal_plan": full_formal_plan,
        "class_counts": class_counts,
        "publisher_success": publisher_success,
        "publisher_physical": publisher_physical,
        "observer": observer_summary,
        "subscriber_total": subscriber_total,
        "subscriber_unique": subscriber_unique,
        "decrypt_failed": decrypt_failed,
        "duplicates": duplicates,
        "checks": checks,
        "overall_pass": all(checks.values()),
    }


def summarize_pacing(
    lateness_ns: Sequence[int],
    events: Sequence[PlanEvent],
) -> dict[str, Any]:
    """Summarize absolute-deadline pacing without treating any positive wake-up
    latency as a missed transmission slot.

    OS scheduling normally makes the process wake a small positive amount after
    an absolute deadline.  A true slot miss is therefore defined here as being
    late by at least one nominal event interval.  ``late_event_count`` is kept
    as a descriptive scheduler statistic, while ``slot_miss_count`` is the
    experiment-integrity indicator.
    """
    positive_deltas = [
        events[i].relative_time_ns - events[i - 1].relative_time_ns
        for i in range(1, len(events))
        if events[i].relative_time_ns > events[i - 1].relative_time_ns
    ]
    nominal_interval_ns = min(positive_deltas) if positive_deltas else 0

    return {
        "late_event_count": sum(1 for x in lateness_ns if x > 0),
        "slot_miss_count": (
            sum(1 for x in lateness_ns if nominal_interval_ns > 0 and x >= nominal_interval_ns)
        ),
        "nominal_interval_ms": nominal_interval_ns / 1_000_000 if nominal_interval_ns else 0.0,
        "max_lateness_ms": (
            max(lateness_ns) / 1_000_000 if lateness_ns else 0.0
        ),
        "mean_lateness_ms": (
            sum(lateness_ns) / len(lateness_ns) / 1_000_000
            if lateness_ns
            else 0.0
        ),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_condition(
    *,
    args: argparse.Namespace,
    events: Sequence[PlanEvent],
    condition: str,
    repo_root: Path,
) -> dict[str, Any]:
    build_exact_payload, compact_json_bytes = _import_generator_helpers()

    condition_dir = Path(args.out_root) / condition
    if condition_dir.exists() and any(condition_dir.iterdir()):
        if not args.overwrite:
            raise RuntimeError(
                f"refusing non-empty condition directory {condition_dir}; "
                "use --overwrite only for a disposable pilot rerun"
            )
        shutil.rmtree(condition_dir)
    condition_dir.mkdir(parents=True, exist_ok=True)

    write_ground_truth(events, condition_dir / "ground_truth.csv")

    logical_topic = events[0].logical_topic
    if any(e.logical_topic != logical_topic for e in events):
        raise RuntimeError("E3-A requires one logical topic")

    subscriber = None
    publisher = None
    observer_proc = None
    observer_exit = None
    start_wall_ns = time.time_ns()
    pacing_lateness: list[int] = []

    try:
        if condition == "A0":
            subscriber = PlainSanitySubscriber(
                broker=args.broker,
                port=args.port,
                topic=plain_topic(args.run_id, condition),
                client_id=f"e3a-{args.run_id}-{condition}-subscriber",
                output_csv=condition_dir / "subscriber_metrics.csv",
            )
            subscriber.connect(args.subscriber_ready_timeout)
            publisher = PlainPublisher(
                broker=args.broker,
                port=args.port,
                run_id=args.run_id,
                condition=condition,
                output_csv=condition_dir / "publisher_metrics.csv",
            )
            preflight = make_preflight_payload()
            publisher.preflight(compact_json_bytes(preflight))
            if not subscriber.preflight_event.wait(args.preflight_timeout):
                raise RuntimeError("A0 subscriber preflight delivery was not observed")
            subscriber.begin_formal()
        else:
            subscriber = AOMQTTSanitySubscriber(
                broker=args.broker,
                port=args.port,
                run_id=args.run_id,
                condition=condition,
                logical_topic=logical_topic,
                output_csv=condition_dir / "subscriber_metrics.csv",
            )
            subscriber.connect(args.subscriber_ready_timeout)
            publisher = AOMQTTPublisherHarness(
                broker=args.broker,
                port=args.port,
                run_id=args.run_id,
                condition=condition,
                output_csv=condition_dir / "publisher_metrics.csv",
            )
            preflight = make_preflight_payload()
            publisher.preflight(logical_topic, preflight)
            if not subscriber.preflight_event.wait(args.preflight_timeout):
                raise RuntimeError(
                    f"{condition} subscriber preflight delivery was not observed"
                )
            subscriber.begin_formal(args.run_id)

        observer_script = repo_root / "experiments" / "e3" / "e3_broker_observer.py"
        observer_cmd = build_observer_command(
            observer_script=observer_script,
            broker=args.broker,
            port=args.port,
            run_id=args.run_id,
            condition=condition,
            condition_dir=condition_dir,
        )
        observer_proc = start_observer(observer_cmd, condition_dir)
        ready_file = condition_dir / "observer.ready"
        if not wait_for_path(ready_file, args.observer_ready_timeout):
            observer_exit = stop_observer(observer_proc)
            observer_proc = None
            log_text = (condition_dir / "observer.log").read_text(
                encoding="utf-8", errors="replace"
            )
            raise RuntimeError(
                f"{condition} observer did not become ready; "
                f"exit={observer_exit}; log={log_text[-2000:]}"
            )

        # Give the ready observer a small fixed lead before the first scheduled
        # event. This lead is not part of the event plan.
        pacing_start_ns = time.monotonic_ns() + args.start_lead_ms * 1_000_000

        for event in events:
            target_ns = pacing_start_ns + event.relative_time_ns
            lateness = wait_until_ns(target_ns)
            pacing_lateness.append(lateness)

            payload = build_exact_payload(
                message_id=event.message_id,
                seq=event.event_index,
                target_plain_bytes=event.target_plain_bytes,
            )
            if condition == "A0":
                publisher.publish_event(event, compact_json_bytes(payload))
            else:
                publisher.publish_event(event, payload)

        # Drain subscriber callbacks without altering the broker-visible trace.
        deadline = time.monotonic() + args.drain_timeout
        while (
            subscriber.unique_received < len(events)
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)

    finally:
        if observer_proc is not None:
            observer_exit = stop_observer(observer_proc)
        # Capture summaries before logger close.
        if subscriber is not None:
            if condition == "A0":
                subscriber_delivery = {
                    "total_received": subscriber.total_received,
                    "unique_messages": subscriber.unique_received,
                    "decrypt_failed": 0,
                    "duplicates": max(
                        0, subscriber.total_received - subscriber.unique_received
                    ),
                }
            else:
                subscriber_delivery = subscriber.delivery_summary()
        else:
            subscriber_delivery = {
                "total_received": 0,
                "unique_messages": 0,
                "decrypt_failed": 0,
                "duplicates": 0,
            }

        if publisher is not None:
            publisher_success = publisher.success_count
            publisher_physical = (
                len(events)
                if condition == "A0"
                else publisher.physical_count
            )
        else:
            publisher_success = 0
            publisher_physical = 0

        if subscriber is not None:
            subscriber.stop()
        if publisher is not None:
            publisher.stop()

    observer_summary = summarize_observer(condition_dir / "observer.csv")
    class_counts = dict(sorted(Counter(e.class_id for e in events).items()))
    full_formal_plan = (
        args.limit_events is None
        and len(events) == 4000
        and class_counts == {f"C{i}": 500 for i in range(1, 9)}
    )

    gate = evaluate_gate(
        condition=condition,
        expected_events=len(events),
        full_formal_plan=full_formal_plan,
        class_counts=class_counts,
        publisher_success=publisher_success,
        publisher_physical=publisher_physical,
        observer_summary=observer_summary,
        subscriber_total=int(subscriber_delivery["total_received"]),
        subscriber_unique=int(subscriber_delivery["unique_messages"]),
        decrypt_failed=int(subscriber_delivery["decrypt_failed"]),
        duplicates=int(subscriber_delivery["duplicates"]),
    )
    gate["observer_exit_code"] = observer_exit
    gate["pacing"] = summarize_pacing(pacing_lateness, events)
    write_json(condition_dir / "gate_report.json", gate)

    harness_commit = git_rev_parse(repo_root)
    manifest = {
        "schema_version": E3A_SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "run_id": args.run_id,
        "condition": condition,
        "condition_description": CONDITIONS[condition]["description"],
        "aomqtt_version": AOMQTT_VERSION,
        "aomqtt_base_commit": AOMQTT_BASE_COMMIT,
        "harness_commit": harness_commit,
        "broker": f"{args.broker}:{args.port}",
        "qos": 1,
        "tls": False,
        "token_mode": "none" if condition == "A0" else "whole",
        "rotation_enabled": False,
        "padding_mode": CONDITIONS[condition]["padding_mode"],
        "padding_fixed_size": 512 if condition == "A2" else None,
        "plan_source": str(Path(args.plan)),
        "plan_sha256": sha256_file(Path(args.plan)),
        "event_count": len(events),
        "formal_full_plan": full_formal_plan,
        "started_unix_ns": start_wall_ns,
        "ended_unix_ns": time.time_ns(),
        "observer_filter": observer_filter(args.run_id, condition),
        "artifacts": {
            "ground_truth": "ground_truth.csv",
            "publisher_metrics": "publisher_metrics.csv",
            "subscriber_metrics": "subscriber_metrics.csv",
            "observer": "observer.csv",
            "observer_summary": "observer.summary.json",
            "gate_report": "gate_report.json",
        },
        "overall_pass": gate["overall_pass"],
    }
    write_json(condition_dir / "run_manifest.json", manifest)

    return gate


def build_execution_plan(
    *,
    args: argparse.Namespace,
    events: Sequence[PlanEvent],
    repo_root: Path,
) -> dict[str, Any]:
    return {
        "schema_version": E3A_SCHEMA_VERSION,
        "mode": "execute" if args.execute else "dry-run",
        "run_id": args.run_id,
        "plan": str(Path(args.plan)),
        "plan_sha256": sha256_file(Path(args.plan)),
        "event_count": len(events),
        "conditions": list(args.conditions),
        "broker": f"{args.broker}:{args.port}",
        "out_root": str(Path(args.out_root)),
        "aomqtt_version": AOMQTT_VERSION,
        "aomqtt_base_commit": AOMQTT_BASE_COMMIT,
        "harness_commit": git_rev_parse(repo_root),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AOMQTT E3-A payload-length leakage conditions"
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=sorted(CONDITIONS),
        default=["A0", "A1", "A2"],
    )
    parser.add_argument("--limit-events", type=int, default=None)
    parser.add_argument("--observer-ready-timeout", type=float, default=5.0)
    parser.add_argument("--subscriber-ready-timeout", type=float, default=5.0)
    parser.add_argument("--preflight-timeout", type=float, default=5.0)
    parser.add_argument("--drain-timeout", type=float, default=5.0)
    parser.add_argument("--start-lead-ms", type=int, default=100)
    parser.add_argument("--allow-non-local-broker", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if args.limit_events is not None and args.limit_events < 1:
        parser.error("--limit-events must be >= 1")
    if args.start_lead_ms < 0:
        parser.error("--start-lead-ms must be >= 0")
    if not args.allow_non_local_broker and not is_local_broker(args.broker):
        parser.error(
            f"refusing non-local broker {args.broker!r}; "
            "use --allow-non-local-broker only for an explicitly authorized environment"
        )
    if not args.execute and not args.dry_run:
        args.dry_run = True
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    events = load_plan(args.plan, limit_events=args.limit_events)

    args.out_root.mkdir(parents=True, exist_ok=True)
    execution_plan = build_execution_plan(
        args=args,
        events=events,
        repo_root=repo_root,
    )
    write_json(args.out_root / "e3a_execution_plan.json", execution_plan)
    print(json.dumps(execution_plan, indent=2, sort_keys=True))

    if args.dry_run:
        return 0

    gates: dict[str, Any] = {}
    for condition in args.conditions:
        print(f"===== E3-A {condition} =====", flush=True)
        gate = run_condition(
            args=args,
            events=events,
            condition=condition,
            repo_root=repo_root,
        )
        gates[condition] = gate
        print(json.dumps(gate, indent=2, sort_keys=True), flush=True)

        if not gate["overall_pass"]:
            # Stop rather than silently carrying a failed condition into the
            # formal comparison. The artifacts remain preserved for diagnosis.
            break

    overall = {
        "schema_version": E3A_SCHEMA_VERSION,
        "run_id": args.run_id,
        "conditions_requested": list(args.conditions),
        "conditions_completed": list(gates),
        "gates": gates,
        "overall_pass": (
            list(gates) == list(args.conditions)
            and all(g["overall_pass"] for g in gates.values())
        ),
    }
    write_json(args.out_root / "e3a_run_summary.json", overall)
    print(json.dumps(overall, indent=2, sort_keys=True))
    return 0 if overall["overall_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
