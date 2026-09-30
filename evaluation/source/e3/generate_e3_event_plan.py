#!/usr/bin/env python3
"""Generate deterministic event plans for the AOMQTT E3 privacy micro-evaluation.

E3-A
----
Creates a balanced, fixed-rate plan for payload-length inference:
8 classes x 500 messages = 4,000 logical messages per run by default.

E3-B
----
Creates a 360-s multi-topic plan using independent Poisson processes for
8 logical topics.  The same generated plan is intended to be reused across
B0--B3 so that the privacy conditions differ only in AOMQTT protection.

The payload-size helper in this module mirrors AOMQTT v1.3.7 JSON
serialization:
    json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

No cryptographic key material is generated or written by this script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


PLAN_SCHEMA_VERSION = "e3-event-plan-v1"

E3A_TOPIC = "e3/payload"
E3A_CLASS_MEANS = {
    "C1": 80,
    "C2": 110,
    "C3": 140,
    "C4": 170,
    "C5": 200,
    "C6": 240,
    "C7": 290,
    "C8": 350,
}
E3A_CLASS_SD = 20.0
E3A_MIN_PLAIN_BYTES = 64
E3A_MAX_PLAIN_BYTES = 440
E3A_MESSAGES_PER_CLASS = 500
E3A_INTERVAL_NS = 10_000_000  # 100 logical messages/s

E3B_TOPICS = (
    ("T1", "e3/site/temp", 0.60, 96),
    ("T2", "e3/site/humidity", 0.75, 112),
    ("T3", "e3/site/pressure", 0.95, 136),
    ("T4", "e3/site/power", 1.20, 168),
    ("T5", "e3/site/vibration", 1.50, 208),
    ("T6", "e3/site/door", 1.80, 256),
    ("T7", "e3/site/fan", 2.15, 320),
    ("T8", "e3/site/status", 2.50, 384),
)
E3B_PAYLOAD_SD = 20.0
E3B_MIN_PLAIN_BYTES = 64
E3B_MAX_PLAIN_BYTES = 440
E3B_DURATION_SEC = 360.0
E3B_ROTATION_INTERVAL_SEC = 30


@dataclass(frozen=True)
class E3AEvent:
    event_index: int
    relative_time_ns: int
    message_id: str
    class_id: str
    logical_topic: str
    target_plain_bytes: int


@dataclass(frozen=True)
class E3BEvent:
    event_index: int
    relative_time_ns: int
    epoch_slot: int
    message_id: str
    logical_topic_id: str
    logical_topic: str
    target_plain_bytes: int


def compact_json_bytes(payload: dict) -> bytes:
    """Serialize exactly as AOMQTT v1.3.7 PayloadCrypto JSON mode does."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def build_exact_payload(
    *,
    message_id: str,
    seq: int,
    target_plain_bytes: int,
) -> dict:
    """Build a compact-JSON payload with an exact serialized byte length.

    Only ``message_id``, ``seq``, and a deterministic ASCII ``blob`` are
    included.  Semantic class/topic labels are intentionally excluded from
    the payload so that E3 ground truth is not leaked to the observer.
    """
    if target_plain_bytes <= 0:
        raise ValueError("target_plain_bytes must be positive")

    base = {
        "message_id": message_id,
        "seq": seq,
        "blob": "",
    }
    base_len = len(compact_json_bytes(base))
    if target_plain_bytes < base_len:
        raise ValueError(
            f"target_plain_bytes={target_plain_bytes} is smaller than "
            f"minimum serialized size {base_len}"
        )

    payload = dict(base)
    payload["blob"] = "x" * (target_plain_bytes - base_len)
    actual = len(compact_json_bytes(payload))
    if actual != target_plain_bytes:
        raise AssertionError(
            f"exact payload construction failed: target={target_plain_bytes}, "
            f"actual={actual}"
        )
    return payload


def _sample_truncated_int(
    rng: random.Random,
    mean: float,
    sd: float,
    lower: int,
    upper: int,
) -> int:
    """Draw a Gaussian integer and clamp it to the pre-registered range."""
    value = int(round(rng.gauss(mean, sd)))
    return max(lower, min(upper, value))


def generate_e3a_events(
    *,
    run_index: int,
    seed: int,
    messages_per_class: int = E3A_MESSAGES_PER_CLASS,
    interval_ns: int = E3A_INTERVAL_NS,
) -> list[E3AEvent]:
    if run_index < 1:
        raise ValueError("run_index must be >= 1")
    if messages_per_class < 1:
        raise ValueError("messages_per_class must be >= 1")
    if interval_ns <= 0:
        raise ValueError("interval_ns must be positive")

    rng = random.Random(seed)
    candidates: list[tuple[str, int]] = []

    for class_id, mean in E3A_CLASS_MEANS.items():
        for _ in range(messages_per_class):
            target = _sample_truncated_int(
                rng,
                mean,
                E3A_CLASS_SD,
                E3A_MIN_PLAIN_BYTES,
                E3A_MAX_PLAIN_BYTES,
            )
            candidates.append((class_id, target))

    # The exact same shuffled plan is reused by A0/A1/A2.
    rng.shuffle(candidates)

    events: list[E3AEvent] = []
    for idx, (class_id, target) in enumerate(candidates):
        message_id = f"e3a-r{run_index:02d}-{idx:06d}"
        # Validate exactness at generation time, not only at execution time.
        build_exact_payload(
            message_id=message_id,
            seq=idx,
            target_plain_bytes=target,
        )
        events.append(
            E3AEvent(
                event_index=idx,
                relative_time_ns=idx * interval_ns,
                message_id=message_id,
                class_id=class_id,
                logical_topic=E3A_TOPIC,
                target_plain_bytes=target,
            )
        )
    return events


def generate_e3b_events(
    *,
    run_index: int,
    seed: int,
    duration_sec: float = E3B_DURATION_SEC,
    rotation_interval_sec: int = E3B_ROTATION_INTERVAL_SEC,
) -> list[E3BEvent]:
    if run_index < 1:
        raise ValueError("run_index must be >= 1")
    if duration_sec <= 0:
        raise ValueError("duration_sec must be positive")
    if rotation_interval_sec <= 0:
        raise ValueError("rotation_interval_sec must be positive")

    rng = random.Random(seed)

    # Generate each topic independently, then merge all events by planned time.
    raw: list[tuple[int, str, str, int, int]] = []
    # tuple = (relative_time_ns, topic_id, topic, target_bytes, topic_seq)

    for topic_id, topic, rate, payload_mean in E3B_TOPICS:
        if rate <= 0:
            raise ValueError(f"invalid non-positive rate for {topic_id}: {rate}")

        t = 0.0
        topic_seq = 0
        while True:
            t += rng.expovariate(rate)
            if t >= duration_sec:
                break

            target = _sample_truncated_int(
                rng,
                payload_mean,
                E3B_PAYLOAD_SD,
                E3B_MIN_PLAIN_BYTES,
                E3B_MAX_PLAIN_BYTES,
            )
            relative_time_ns = int(round(t * 1_000_000_000))
            raw.append(
                (
                    relative_time_ns,
                    topic_id,
                    topic,
                    target,
                    topic_seq,
                )
            )
            topic_seq += 1

    raw.sort(key=lambda row: (row[0], row[1], row[4]))

    events: list[E3BEvent] = []
    interval_ns = rotation_interval_sec * 1_000_000_000
    for idx, (relative_time_ns, topic_id, topic, target, _topic_seq) in enumerate(raw):
        message_id = f"e3b-r{run_index:02d}-{idx:06d}"
        epoch_slot = relative_time_ns // interval_ns

        build_exact_payload(
            message_id=message_id,
            seq=idx,
            target_plain_bytes=target,
        )

        events.append(
            E3BEvent(
                event_index=idx,
                relative_time_ns=relative_time_ns,
                epoch_slot=int(epoch_slot),
                message_id=message_id,
                logical_topic_id=topic_id,
                logical_topic=topic,
                target_plain_bytes=target,
            )
        )
    return events


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_e3a_csv(events: Sequence[E3AEvent], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            [
                "event_index",
                "relative_time_ns",
                "message_id",
                "class_id",
                "logical_topic",
                "target_plain_bytes",
            ]
        )
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


def write_e3b_csv(events: Sequence[E3BEvent], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            [
                "event_index",
                "relative_time_ns",
                "epoch_slot",
                "message_id",
                "logical_topic_id",
                "logical_topic",
                "target_plain_bytes",
            ]
        )
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


def write_manifest(
    *,
    mode: str,
    run_index: int,
    seed: int,
    output_csv: Path,
    event_count: int,
    extra: dict,
    manifest_path: Path | None,
) -> Path:
    if manifest_path is None:
        manifest_path = output_csv.with_suffix(output_csv.suffix + ".manifest.json")

    manifest = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "mode": mode,
        "run_index": run_index,
        "seed": seed,
        "event_count": event_count,
        "output_csv": output_csv.name,
        "output_csv_sha256": _sha256_file(output_csv),
        **extra,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate deterministic AOMQTT E3 privacy event plans"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    a = sub.add_parser("e3a", help="generate E3-A payload-length plan")
    a.add_argument("--run-index", type=int, required=True)
    a.add_argument("--seed", type=int, required=True)
    a.add_argument("--messages-per-class", type=int, default=E3A_MESSAGES_PER_CLASS)
    a.add_argument("--interval-ns", type=int, default=E3A_INTERVAL_NS)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--manifest", type=Path, default=None)

    b = sub.add_parser("e3b", help="generate E3-B cross-epoch linkage plan")
    b.add_argument("--run-index", type=int, required=True)
    b.add_argument("--seed", type=int, required=True)
    b.add_argument("--duration-sec", type=float, default=E3B_DURATION_SEC)
    b.add_argument(
        "--rotation-interval-sec",
        type=int,
        default=E3B_ROTATION_INTERVAL_SEC,
    )
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--manifest", type=Path, default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.mode == "e3a":
        events = generate_e3a_events(
            run_index=args.run_index,
            seed=args.seed,
            messages_per_class=args.messages_per_class,
            interval_ns=args.interval_ns,
        )
        write_e3a_csv(events, args.out)
        manifest = write_manifest(
            mode="e3a",
            run_index=args.run_index,
            seed=args.seed,
            output_csv=args.out,
            event_count=len(events),
            extra={
                "logical_topic": E3A_TOPIC,
                "classes": E3A_CLASS_MEANS,
                "class_sd": E3A_CLASS_SD,
                "min_plain_bytes": E3A_MIN_PLAIN_BYTES,
                "max_plain_bytes": E3A_MAX_PLAIN_BYTES,
                "messages_per_class": args.messages_per_class,
                "interval_ns": args.interval_ns,
            },
            manifest_path=args.manifest,
        )
    else:
        events = generate_e3b_events(
            run_index=args.run_index,
            seed=args.seed,
            duration_sec=args.duration_sec,
            rotation_interval_sec=args.rotation_interval_sec,
        )
        write_e3b_csv(events, args.out)
        manifest = write_manifest(
            mode="e3b",
            run_index=args.run_index,
            seed=args.seed,
            output_csv=args.out,
            event_count=len(events),
            extra={
                "topics": [
                    {
                        "logical_topic_id": topic_id,
                        "logical_topic": topic,
                        "rate_msg_per_sec": rate,
                        "payload_mean_bytes": mean,
                    }
                    for topic_id, topic, rate, mean in E3B_TOPICS
                ],
                "payload_sd": E3B_PAYLOAD_SD,
                "min_plain_bytes": E3B_MIN_PLAIN_BYTES,
                "max_plain_bytes": E3B_MAX_PLAIN_BYTES,
                "duration_sec": args.duration_sec,
                "rotation_interval_sec": args.rotation_interval_sec,
            },
            manifest_path=args.manifest,
        )

    print(
        json.dumps(
            {
                "mode": args.mode,
                "events": len(events),
                "output": str(args.out),
                "sha256": _sha256_file(args.out),
                "manifest": str(manifest),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
