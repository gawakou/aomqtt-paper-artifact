#!/usr/bin/env python3
"""Run the AOMQTT E3-B cross-epoch topic-linkability experiment.

E3-B reuses one deterministic 8-topic Poisson event plan across four
conditions:

B0  whole-topic + AES-GCM + fixed512, rotation OFF
    Persistent-token reference.  This condition is *not* used to train the
    cross-epoch classifier; it verifies the stable-token reference case.

B1  whole-topic + AES-GCM, no padding, rotation 30 s, overlap 0 s
B2  whole-topic + AES-GCM + fixed512, rotation 30 s, overlap 0 s
B3  whole-topic + AES-GCM + fixed512, rotation 30 s, overlap 5 s

Important design rule
---------------------
The event plan's *planned* relative time controls the token epoch.  The raw
broker observer still records the *actual* receive timestamps.  This separates
the intended rotation state from OS/network scheduling jitter and lets the
later analysis align windows around known 30-s transition boundaries.

For formal runs, --pace-scale must remain 1.0.  A smaller value is permitted
only for disposable pilot/smoke runs.

The implementation under evaluation remains AOMQTT v1.3.7 at commit
6dc0b2c497098aca569a636d1f8f8bb2adc4253a.  This file is experiment
harness code and records both the base implementation commit and the harness
commit in its manifests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


E3B_SCHEMA_VERSION = "e3b-runner-v1"
AOMQTT_VERSION = "1.3.7"
AOMQTT_BASE_COMMIT = "6dc0b2c497098aca569a636d1f8f8bb2adc4253a"
EXPERIMENT_ID = "aomqtt-e3b-topic-linkability"

# Public synthetic evaluation keys; never use these as production secrets.
E3_TOPIC_KEY = "e3-public-topic-key-32chars-demo"
E3_PAYLOAD_KEY = "e3-public-payload-key-32chars-demo"

ROTATION_INTERVAL_SEC = 30
OVERLAP_SEC = 5
FIXED_PADDING_BYTES = 512

CONDITIONS: dict[str, dict[str, Any]] = {
    "B0": {
        "description": "Persistent-token reference; fixed512; rotation off",
        "rotation_enabled": False,
        "rotation_overlap_sec": 0,
        "padding_enabled": True,
        "padding_mode": "fixed",
        "analysis_role": "persistent-token-reference",
    },
    "B1": {
        "description": "Rotation30; overlap0; no padding",
        "rotation_enabled": True,
        "rotation_overlap_sec": 0,
        "padding_enabled": False,
        "padding_mode": "none",
        "analysis_role": "cross-epoch-classifier",
    },
    "B2": {
        "description": "Rotation30; overlap0; fixed512",
        "rotation_enabled": True,
        "rotation_overlap_sec": 0,
        "padding_enabled": True,
        "padding_mode": "fixed",
        "analysis_role": "cross-epoch-classifier",
    },
    "B3": {
        "description": "Rotation30; overlap5; fixed512",
        "rotation_enabled": True,
        "rotation_overlap_sec": OVERLAP_SEC,
        "padding_enabled": True,
        "padding_mode": "fixed",
        "analysis_role": "cross-epoch-classifier-with-overlap",
    },
}

PLAN_FIELDS = [
    "event_index",
    "relative_time_ns",
    "epoch_slot",
    "message_id",
    "logical_topic_id",
    "logical_topic",
    "target_plain_bytes",
]

EXPECTED_TOPIC_IDS = {f"T{i}" for i in range(1, 9)}


@dataclass(frozen=True)
class PlanEvent:
    event_index: int
    relative_time_ns: int
    epoch_slot: int
    message_id: str
    logical_topic_id: str
    logical_topic: str
    target_plain_bytes: int


def _import_generator_helpers():
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
    return f"e3/b/{run_id}/{condition}"


def observer_filter(run_id: str, condition: str) -> str:
    return f"{condition_prefix(run_id, condition)}/#"


def planned_timestamp_sec(event: PlanEvent) -> float:
    """Synthetic timestamp used *only* for rotation/token derivation."""
    return event.relative_time_ns / 1_000_000_000.0


def seconds_into_epoch(event: PlanEvent) -> float:
    return planned_timestamp_sec(event) - event.epoch_slot * ROTATION_INTERVAL_SEC


def physical_epochs_for_event(event: PlanEvent, condition: str) -> tuple[str | None, ...]:
    spec = CONDITIONS[condition]
    if not spec["rotation_enabled"]:
        return (None,)

    current = str(event.epoch_slot)
    if (
        spec["rotation_overlap_sec"] > 0
        and event.epoch_slot > 0
        and seconds_into_epoch(event) < float(spec["rotation_overlap_sec"])
    ):
        return (current, str(event.epoch_slot - 1))
    return (current,)


def expected_physical_count(events: Sequence[PlanEvent], condition: str) -> int:
    return sum(len(physical_epochs_for_event(e, condition)) for e in events)


def expected_overlap_duplicates(events: Sequence[PlanEvent], condition: str) -> int:
    return expected_physical_count(events, condition) - len(events)


def expected_token_identity_pairs(
    events: Sequence[PlanEvent],
    condition: str,
) -> set[tuple[str, str | None]]:
    """Ground-truth (logical topic, epoch) token identities expected on wire.

    B0 has one persistent token per logical topic and therefore epoch=None.
    Rotating conditions use the event's current epoch; B3 additionally emits
    the previous epoch identity during overlap.
    """
    pairs: set[tuple[str, str | None]] = set()
    for event in events:
        for epoch in physical_epochs_for_event(event, condition):
            pairs.add((event.logical_topic, epoch))
    return pairs


def load_plan(
    path: Path,
    *,
    limit_events: int | None = None,
    limit_duration_sec: float | None = None,
) -> list[PlanEvent]:
    build_exact_payload, _ = _import_generator_helpers()

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != PLAN_FIELDS:
            raise ValueError(
                f"unexpected E3-B plan schema: {reader.fieldnames!r}; "
                f"expected {PLAN_FIELDS!r}"
            )
        rows = list(reader)

    events: list[PlanEvent] = []
    previous_time = -1
    for expected_index, row in enumerate(rows):
        event = PlanEvent(
            event_index=int(row["event_index"]),
            relative_time_ns=int(row["relative_time_ns"]),
            epoch_slot=int(row["epoch_slot"]),
            message_id=row["message_id"],
            logical_topic_id=row["logical_topic_id"],
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

        expected_epoch = event.relative_time_ns // (
            ROTATION_INTERVAL_SEC * 1_000_000_000
        )
        if event.epoch_slot != expected_epoch:
            raise ValueError(
                f"epoch_slot mismatch for event {event.event_index}: "
                f"csv={event.epoch_slot}, expected={expected_epoch}"
            )

        build_exact_payload(
            message_id=event.message_id,
            seq=event.event_index,
            target_plain_bytes=event.target_plain_bytes,
        )
        events.append(event)

    if limit_duration_sec is not None:
        if limit_duration_sec <= 0:
            raise ValueError("limit_duration_sec must be positive")
        limit_ns = int(limit_duration_sec * 1_000_000_000)
        events = [e for e in events if e.relative_time_ns < limit_ns]

    if limit_events is not None:
        if limit_events < 1:
            raise ValueError("limit_events must be >= 1")
        events = events[:limit_events]

    if not events:
        raise ValueError("event plan is empty after filtering")
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
                    e.epoch_slot,
                    e.message_id,
                    e.logical_topic_id,
                    e.logical_topic,
                    e.target_plain_bytes,
                ]
            )


def make_aomqtt_config(condition: str, run_id: str):
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
        rotation_enabled=bool(spec["rotation_enabled"]),
        rotation_interval_sec=ROTATION_INTERVAL_SEC,
        rotation_overlap_sec=int(spec["rotation_overlap_sec"]),
        padding_enabled=bool(spec["padding_enabled"]),
        padding_mode=str(spec["padding_mode"]),
        padding_fixed_size=FIXED_PADDING_BYTES,
    )
    cfg.validate()
    return cfg


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
        f"e3b-{run_id}-{condition}-observer",
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
    while True:
        remaining = target_ns - time.monotonic_ns()
        if remaining <= 0:
            break
        time.sleep(remaining / 1_000_000_000)
    return max(0, time.monotonic_ns() - target_ns)


def summarize_pacing(
    lateness_ns: Sequence[int],
    *,
    pace_scale: float,
) -> dict[str, Any]:
    # E3-B has non-periodic Poisson arrivals; there is no single event-slot
    # width.  We therefore report lateness descriptively and define a severe
    # miss only relative to 10 ms, which is conservative versus the observed
    # interarrival times but is *not* used as an acceptance gate.
    severe_threshold_ns = 10_000_000
    return {
        "pace_scale": pace_scale,
        "late_event_count": sum(1 for x in lateness_ns if x > 0),
        "severe_lateness_over_10ms_count": sum(
            1 for x in lateness_ns if x >= severe_threshold_ns
        ),
        "max_lateness_ms": (
            max(lateness_ns) / 1_000_000 if lateness_ns else 0.0
        ),
        "mean_lateness_ms": (
            sum(lateness_ns) / len(lateness_ns) / 1_000_000
            if lateness_ns
            else 0.0
        ),
    }


class E3BSanitySubscriber:
    """Authorized subscriber used only to verify loss/decryption/duplicates.

    Whole-topic mode cannot represent wildcards, so the runner pre-subscribes
    every exact token identity needed by the frozen plan.  For rotating
    conditions this means each (logical topic, epoch) pair that can appear on
    the wire.  The exhaustive preflight occurs before the independent broker
    observer starts and therefore cannot contaminate the privacy trace.
    """

    def __init__(
        self,
        *,
        broker: str,
        port: int,
        run_id: str,
        condition: str,
        events: Sequence[PlanEvent],
        output_csv: Path,
    ) -> None:
        from aomqtt import AOMQTTSubscriber

        self.condition = condition
        self.events = list(events)
        self.config = make_aomqtt_config(condition, run_id)
        self.sub = AOMQTTSubscriber(
            broker_host=broker,
            broker_port=port,
            client_id=f"e3b-{run_id}-{condition}-subscriber",
            config=self.config,
        )
        self.output_csv = output_csv
        self._lock = threading.Lock()
        self._preflight_ids: set[str] = set()
        self._formal_ids: list[str] = []
        self.delivery_logger = None

    def _callback(self, token_topic, payload, raw_msg):
        message_id = ""
        if isinstance(payload, dict):
            message_id = str(payload.get("message_id", ""))

        with self._lock:
            if message_id.startswith("preflight:"):
                self._preflight_ids.add(message_id)
            elif message_id:
                self._formal_ids.append(message_id)

    def connect_and_subscribe(self, timeout_sec: float = 5.0) -> None:
        self.sub.connect()
        self.sub.loop_start()

        deadline = time.monotonic() + timeout_sec
        while not self.sub.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self.sub.connected:
            raise RuntimeError("E3-B sanity subscriber did not connect")

        pairs = sorted(
            expected_token_identity_pairs(self.events, self.condition),
            key=lambda p: (p[0], "" if p[1] is None else p[1]),
        )
        for logical_topic, epoch in pairs:
            self.sub.subscribe(
                logical_topic,
                callback=self._callback,
                qos=1,
                epoch=epoch,
            )

    @property
    def expected_preflight_count(self) -> int:
        return len(expected_token_identity_pairs(self.events, self.condition))

    def wait_preflight(self, timeout_sec: float) -> bool:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            with self._lock:
                if len(self._preflight_ids) >= self.expected_preflight_count:
                    return True
            time.sleep(0.05)
        with self._lock:
            return len(self._preflight_ids) >= self.expected_preflight_count

    def begin_formal(self, run_id: str) -> None:
        from aomqtt import DeliveryCSVLogger

        with self._lock:
            self._formal_ids.clear()

        self.delivery_logger = DeliveryCSVLogger(
            self.output_csv,
            experiment_id=EXPERIMENT_ID,
            run_id=run_id,
        )
        self.sub.enable_delivery_observation(
            csv_logger=self.delivery_logger,
            plaintext_filter="E3-B exact whole-topic token set",
            reset_seen=True,
        )

    @property
    def callback_unique_received(self) -> int:
        with self._lock:
            return len(set(self._formal_ids))

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
        if self.delivery_logger is not None:
            self.delivery_logger.close()
            self.delivery_logger = None
        self.sub.loop_stop()
        self.sub.disconnect()


class E3BPublisherHarness:
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
            client_id=f"e3b-{run_id}-{condition}-publisher",
            config=self.config,
        )
        self.pub.connect()
        self.pub.loop_start()

        deadline = time.monotonic() + 5.0
        while not self.pub.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self.pub.connected:
            raise RuntimeError("E3-B publisher did not connect")

        self.logger = PublishCSVLogger(
            output_csv,
            experiment_id=EXPERIMENT_ID,
            run_id=run_id,
        )

    def send_preflight_pairs(
        self,
        pairs: Sequence[tuple[str, str | None]],
    ) -> None:
        for idx, (logical_topic, epoch) in enumerate(pairs):
            epoch_label = "persistent" if epoch is None else epoch
            payload = {
                "message_id": f"preflight:{self.condition}:{idx:04d}:{epoch_label}",
                "seq": -1,
                "blob": "ready",
            }
            info = self.pub.publish(
                logical_topic,
                payload,
                qos=1,
                epoch=epoch,
            )
            info.wait_for_publish(timeout=5)

    def publish_event(self, event: PlanEvent, payload: dict[str, Any]) -> None:
        metrics = self.pub.publish_observed_rotating(
            event.logical_topic,
            payload,
            qos=1,
            timestamp=planned_timestamp_sec(event),
            logical_seq=event.event_index,
            message_id=event.message_id,
            wait_for_publish=True,
            wait_timeout=5.0,
            csv_logger=self.logger,
        )
        expected = len(physical_epochs_for_event(event, self.condition))
        if len(metrics) != expected:
            raise RuntimeError(
                f"{self.condition} event {event.event_index} produced "
                f"{len(metrics)} physical publishes; expected {expected}"
            )

    @property
    def publish_summary(self) -> dict[str, int]:
        s = self.logger.summary()
        return {
            "physical": s.total,
            "success": s.success,
            "failed": s.failed,
        }

    def stop(self) -> None:
        self.logger.close()
        self.pub.loop_stop()
        self.pub.disconnect()


def start_observer(command: list[str], condition_dir: Path) -> subprocess.Popen[str]:
    log_path = condition_dir / "observer.log"
    log_fh = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        command,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        text=True,
    )
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


def csv_data_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as f:
        count = sum(1 for _ in f)
    return max(0, count - 1)


def summarize_observer(path: Path) -> dict[str, Any]:
    rows = read_csv_rows(path)
    seqs = [int(r["observer_seq"]) for r in rows] if rows else []
    sizes = [int(r["mqtt_payload_bytes"]) for r in rows]
    topics = [r["mqtt_topic"] for r in rows]
    return {
        "row_count": len(rows),
        "sequence_contiguous": seqs == list(range(len(rows))),
        "unique_payload_sizes": sorted(set(sizes)),
        "unique_payload_size_count": len(set(sizes)),
        "unique_mqtt_topic_count": len(set(topics)),
    }


def summarize_publisher_token_mapping(path: Path) -> dict[str, Any]:
    rows = read_csv_rows(path)
    by_plaintext: dict[str, set[str]] = defaultdict(set)
    unique_tokens: set[str] = set()
    overlap_rows = 0
    for row in rows:
        plain = row.get("plaintext_topic", "")
        token = row.get("token_topic", "")
        if plain and token:
            by_plaintext[plain].add(token)
            unique_tokens.add(token)
        if str(row.get("overlap_duplicate", "")).strip().lower() in {
            "true", "1", "yes"
        }:
            overlap_rows += 1

    return {
        "unique_token_topic_count": len(unique_tokens),
        "token_count_per_logical_topic": {
            topic: len(tokens)
            for topic, tokens in sorted(by_plaintext.items())
        },
        "overlap_duplicate_rows": overlap_rows,
    }


def evaluate_gate(
    *,
    condition: str,
    events: Sequence[PlanEvent],
    full_formal_plan: bool,
    publisher_summary: dict[str, int],
    publisher_token_summary: dict[str, Any],
    observer_summary: dict[str, Any],
    delivery_summary: dict[str, Any],
    callback_unique_received: int,
) -> dict[str, Any]:
    expected_logical = len(events)
    expected_physical = expected_physical_count(events, condition)
    expected_duplicates = expected_overlap_duplicates(events, condition)
    expected_tokens = len(expected_token_identity_pairs(events, condition))
    topic_ids = {e.logical_topic_id for e in events}

    checks: dict[str, bool] = {
        "planned_events_positive": expected_logical > 0,
        "publisher_success_equals_expected_physical": (
            publisher_summary["success"] == expected_physical
        ),
        "publisher_physical_equals_expected_physical": (
            publisher_summary["physical"] == expected_physical
        ),
        "publisher_failed_zero": publisher_summary["failed"] == 0,
        "observer_rows_equal_expected_physical": (
            observer_summary["row_count"] == expected_physical
        ),
        "observer_sequence_contiguous": bool(
            observer_summary["sequence_contiguous"]
        ),
        "observer_unique_topics_equal_expected": (
            observer_summary["unique_mqtt_topic_count"] == expected_tokens
        ),
        "publisher_unique_tokens_equal_expected": (
            publisher_token_summary["unique_token_topic_count"] == expected_tokens
        ),
        "subscriber_total_equals_expected_physical": (
            int(delivery_summary["total_received"]) == expected_physical
        ),
        "subscriber_unique_equals_logical": (
            int(delivery_summary["unique_messages"]) == expected_logical
        ),
        "callback_unique_equals_logical": (
            callback_unique_received == expected_logical
        ),
        "decrypt_failures_zero": int(delivery_summary["decrypt_failed"]) == 0,
        "duplicates_equal_expected_overlap": (
            int(delivery_summary["duplicates"]) == expected_duplicates
        ),
        "publisher_overlap_rows_equal_expected": (
            int(publisher_token_summary["overlap_duplicate_rows"])
            == expected_duplicates
        ),
    }

    if full_formal_plan:
        checks["all_eight_logical_topics_present"] = topic_ids == EXPECTED_TOPIC_IDS
        checks["all_twelve_epoch_slots_present"] = {
            e.epoch_slot for e in events
        } == set(range(12))

    if condition in {"B0", "B2", "B3"}:
        checks["fixed_padding_single_observed_size"] = (
            observer_summary["unique_payload_size_count"] == 1
        )

    if condition == "B0":
        checks["persistent_one_token_per_logical_topic"] = all(
            count == 1
            for count in publisher_token_summary[
                "token_count_per_logical_topic"
            ].values()
        )

    return {
        "condition": condition,
        "expected_logical": expected_logical,
        "expected_physical": expected_physical,
        "expected_overlap_duplicates": expected_duplicates,
        "expected_unique_token_topics": expected_tokens,
        "full_formal_plan": full_formal_plan,
        "checks": checks,
        "publisher": publisher_summary,
        "publisher_tokens": publisher_token_summary,
        "observer": observer_summary,
        "subscriber": delivery_summary,
        "callback_unique_received": callback_unique_received,
        "overall_pass": all(checks.values()),
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
    build_exact_payload, _compact_json_bytes = _import_generator_helpers()

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

    expected_physical = expected_physical_count(events, condition)

    subscriber = None
    publisher = None
    observer_proc = None
    observer_exit = None
    pacing_lateness: list[int] = []
    pacing_start_monotonic_ns: int | None = None
    pacing_start_unix_ns: int | None = None
    started_unix_ns = time.time_ns()

    try:
        subscriber = E3BSanitySubscriber(
            broker=args.broker,
            port=args.port,
            run_id=args.run_id,
            condition=condition,
            events=events,
            output_csv=condition_dir / "subscriber_metrics.csv",
        )
        subscriber.connect_and_subscribe(args.subscriber_ready_timeout)

        publisher = E3BPublisherHarness(
            broker=args.broker,
            port=args.port,
            run_id=args.run_id,
            condition=condition,
            output_csv=condition_dir / "publisher_metrics.csv",
        )

        # Exhaustively verify every exact token subscription before the privacy
        # observer starts.  This traffic is intentionally excluded from the
        # broker-visible E3-B trace.
        pairs = sorted(
            expected_token_identity_pairs(events, condition),
            key=lambda p: (p[0], "" if p[1] is None else p[1]),
        )
        publisher.send_preflight_pairs(pairs)
        if not subscriber.wait_preflight(args.preflight_timeout):
            raise RuntimeError(
                f"{condition} exhaustive subscription preflight failed: "
                f"expected {subscriber.expected_preflight_count} token identities"
            )

        subscriber.begin_formal(args.run_id)

        observer_script = (
            repo_root / "experiments" / "e3" / "e3_broker_observer.py"
        )
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

        pacing_start_monotonic_ns = (
            time.monotonic_ns() + args.start_lead_ms * 1_000_000
        )
        pacing_start_unix_ns = time.time_ns() + args.start_lead_ms * 1_000_000

        for event in events:
            scaled_offset_ns = int(event.relative_time_ns * args.pace_scale)
            target_ns = pacing_start_monotonic_ns + scaled_offset_ns
            pacing_lateness.append(wait_until_ns(target_ns))

            payload = build_exact_payload(
                message_id=event.message_id,
                seq=event.event_index,
                target_plain_bytes=event.target_plain_bytes,
            )
            publisher.publish_event(event, payload)

        # Wait for both authorized delivery logging and independent observer
        # logging to drain all expected physical PUBLISH messages.
        deadline = time.monotonic() + args.drain_timeout
        while time.monotonic() < deadline:
            delivery = subscriber.delivery_summary()
            observer_rows = csv_data_row_count(condition_dir / "observer.csv")
            if (
                int(delivery["total_received"]) >= expected_physical
                and observer_rows >= expected_physical
            ):
                break
            time.sleep(0.05)

    finally:
        if observer_proc is not None:
            observer_exit = stop_observer(observer_proc)

        if subscriber is not None:
            delivery_summary = subscriber.delivery_summary()
            callback_unique = subscriber.callback_unique_received
        else:
            delivery_summary = {
                "total_received": 0,
                "decrypt_success": 0,
                "decrypt_failed": 0,
                "unique_messages": 0,
                "duplicates": 0,
            }
            callback_unique = 0

        if publisher is not None:
            publisher_summary = publisher.publish_summary
        else:
            publisher_summary = {
                "physical": 0,
                "success": 0,
                "failed": 0,
            }

        if subscriber is not None:
            subscriber.stop()
        if publisher is not None:
            publisher.stop()

    observer_summary = summarize_observer(condition_dir / "observer.csv")
    publisher_token_summary = summarize_publisher_token_mapping(
        condition_dir / "publisher_metrics.csv"
    )

    full_formal_plan = (
        args.limit_events is None
        and args.limit_duration_sec is None
        and abs(args.pace_scale - 1.0) < 1e-12
        and {e.logical_topic_id for e in events} == EXPECTED_TOPIC_IDS
        and {e.epoch_slot for e in events} == set(range(12))
    )

    gate = evaluate_gate(
        condition=condition,
        events=events,
        full_formal_plan=full_formal_plan,
        publisher_summary=publisher_summary,
        publisher_token_summary=publisher_token_summary,
        observer_summary=observer_summary,
        delivery_summary=delivery_summary,
        callback_unique_received=callback_unique,
    )
    gate["observer_exit_code"] = observer_exit
    gate["pacing"] = summarize_pacing(
        pacing_lateness,
        pace_scale=args.pace_scale,
    )
    gate["pacing_start_monotonic_ns"] = pacing_start_monotonic_ns
    gate["pacing_start_unix_ns"] = pacing_start_unix_ns
    write_json(condition_dir / "gate_report.json", gate)

    manifest = {
        "schema_version": E3B_SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "run_id": args.run_id,
        "condition": condition,
        "condition_description": CONDITIONS[condition]["description"],
        "analysis_role": CONDITIONS[condition]["analysis_role"],
        "aomqtt_version": AOMQTT_VERSION,
        "aomqtt_base_commit": AOMQTT_BASE_COMMIT,
        "harness_commit": git_rev_parse(repo_root),
        "broker": f"{args.broker}:{args.port}",
        "qos": 1,
        "tls": False,
        "token_mode": "whole",
        "rotation_enabled": CONDITIONS[condition]["rotation_enabled"],
        "rotation_interval_sec": ROTATION_INTERVAL_SEC,
        "rotation_overlap_sec": CONDITIONS[condition]["rotation_overlap_sec"],
        "padding_mode": CONDITIONS[condition]["padding_mode"],
        "padding_fixed_size": (
            FIXED_PADDING_BYTES
            if CONDITIONS[condition]["padding_enabled"]
            else None
        ),
        "planned_time_controls_epoch": True,
        "planned_epoch_origin_sec": 0.0,
        "observer_time_is_actual_receive_time": True,
        "pace_scale": args.pace_scale,
        "plan_source": str(Path(args.plan)),
        "plan_sha256": sha256_file(Path(args.plan)),
        "event_count_logical": len(events),
        "expected_event_count_physical": expected_physical,
        "expected_overlap_duplicates": expected_overlap_duplicates(
            events, condition
        ),
        "expected_unique_token_topics": len(
            expected_token_identity_pairs(events, condition)
        ),
        "formal_full_plan": full_formal_plan,
        "pacing_start_monotonic_ns": pacing_start_monotonic_ns,
        "pacing_start_unix_ns": pacing_start_unix_ns,
        "started_unix_ns": started_unix_ns,
        "ended_unix_ns": time.time_ns(),
        "observer_filter": observer_filter(args.run_id, condition),
        "analysis_windows_sec": {
            "profile_old": [-20.0, 0.0],
            "overlap": [0.0, 5.0],
            "profile_new": [5.0, 25.0],
            "overlap_cooccurrence_threshold_ms": 20.0,
        },
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
    per_condition = {}
    for condition in args.conditions:
        per_condition[condition] = {
            "logical_events": len(events),
            "expected_physical_events": expected_physical_count(
                events, condition
            ),
            "expected_overlap_duplicates": expected_overlap_duplicates(
                events, condition
            ),
            "expected_unique_token_topics": len(
                expected_token_identity_pairs(events, condition)
            ),
            "analysis_role": CONDITIONS[condition]["analysis_role"],
        }

    return {
        "schema_version": E3B_SCHEMA_VERSION,
        "mode": "execute" if args.execute else "dry-run",
        "run_id": args.run_id,
        "plan": str(Path(args.plan)),
        "plan_sha256": sha256_file(Path(args.plan)),
        "event_count": len(events),
        "topic_ids": sorted({e.logical_topic_id for e in events}),
        "epoch_slots": sorted({e.epoch_slot for e in events}),
        "conditions": list(args.conditions),
        "per_condition": per_condition,
        "broker": f"{args.broker}:{args.port}",
        "pace_scale": args.pace_scale,
        "out_root": str(Path(args.out_root)),
        "aomqtt_version": AOMQTT_VERSION,
        "aomqtt_base_commit": AOMQTT_BASE_COMMIT,
        "harness_commit": git_rev_parse(repo_root),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AOMQTT E3-B cross-epoch topic-linkability conditions"
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
        default=["B0", "B1", "B2", "B3"],
    )
    parser.add_argument("--limit-events", type=int, default=None)
    parser.add_argument("--limit-duration-sec", type=float, default=None)
    parser.add_argument(
        "--pace-scale",
        type=float,
        default=1.0,
        help=(
            "actual wall-clock pacing multiplier; 1.0 is required for formal "
            "runs; smaller values are for disposable pilots only"
        ),
    )
    parser.add_argument("--observer-ready-timeout", type=float, default=5.0)
    parser.add_argument("--subscriber-ready-timeout", type=float, default=5.0)
    parser.add_argument("--preflight-timeout", type=float, default=10.0)
    parser.add_argument("--drain-timeout", type=float, default=10.0)
    parser.add_argument("--start-lead-ms", type=int, default=100)
    parser.add_argument("--allow-non-local-broker", action="store_true")
    parser.add_argument("--overwrite", action="store_true")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if args.limit_events is not None and args.limit_events < 1:
        parser.error("--limit-events must be >= 1")
    if args.limit_duration_sec is not None and args.limit_duration_sec <= 0:
        parser.error("--limit-duration-sec must be positive")
    if args.pace_scale <= 0:
        parser.error("--pace-scale must be positive")
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
    events = load_plan(
        args.plan,
        limit_events=args.limit_events,
        limit_duration_sec=args.limit_duration_sec,
    )

    args.out_root.mkdir(parents=True, exist_ok=True)
    execution_plan = build_execution_plan(
        args=args,
        events=events,
        repo_root=repo_root,
    )
    write_json(args.out_root / "e3b_execution_plan.json", execution_plan)
    print(json.dumps(execution_plan, indent=2, sort_keys=True))

    if args.dry_run:
        return 0

    gates: dict[str, Any] = {}
    for condition in args.conditions:
        print(f"===== E3-B {condition} =====", flush=True)
        gate = run_condition(
            args=args,
            events=events,
            condition=condition,
            repo_root=repo_root,
        )
        gates[condition] = gate
        print(json.dumps(gate, indent=2, sort_keys=True), flush=True)

        if not gate["overall_pass"]:
            break

    overall = {
        "schema_version": E3B_SCHEMA_VERSION,
        "run_id": args.run_id,
        "conditions_requested": list(args.conditions),
        "conditions_completed": list(gates),
        "gates": gates,
        "overall_pass": (
            list(gates) == list(args.conditions)
            and all(g["overall_pass"] for g in gates.values())
        ),
    }
    write_json(args.out_root / "e3b_run_summary.json", overall)
    print(json.dumps(overall, indent=2, sort_keys=True))
    return 0 if overall["overall_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
