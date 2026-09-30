#!/usr/bin/env python3
"""
Build controller-input snapshots from raw AOMQTT observation CSV files.

This evaluation-only adapter leaves AOMQTT v1.3.7 unchanged and resolves two
measurement issues in the raw CSV path:

1. The v1.3.7 auto-controller sequence inference checks string `message_id`
   before numeric `logical_seq`; normal IDs such as "client:run:123" therefore
   prevent fallback to `logical_seq`.  The adapter inserts numeric `seq`.

2. A gap in subscriber sequence numbers does not necessarily mean delivery
   loss when the corresponding publisher-side logical PUBLISH failed locally.
   The adapter computes explicit application-level loss using only logical
   messages for which at least one physical publisher row has success=true.
   It writes explicit `loss_rate` and `duplicate_rate` columns, which the
   unmodified v1.3.7 aggregator already prefers over sequence inference.

3. PublishMetric.reconnect_count is cumulative, while the v1.3.7 controller
   aggregator sums that CSV column. The controller-input snapshot therefore
   converts the cumulative counter to per-row increments; the raw CSV is never
   modified.

Outputs:
  publisher_controller_input.csv
  subscriber_controller_input.csv
  observation_manifest.json
  observation_summary.txt
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import statistics
from pathlib import Path
from typing import Iterable

TRUTHY = {"1", "true", "yes", "y", "ok", "success", "succeeded"}
FALSY = {"0", "false", "no", "n", "ng", "fail", "failed"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def parse_int(value: str | None, *, field: str, row_no: int) -> int:
    if value is None or str(value).strip() == "":
        raise ValueError(f"missing {field} at row {row_no}")
    s = str(value).strip()
    try:
        f = float(s)
    except Exception as exc:
        raise ValueError(f"non-numeric {field}={s!r} at row {row_no}") from exc
    if not f.is_integer():
        raise ValueError(f"non-integral {field}={s!r} at row {row_no}")
    return int(f)


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in TRUTHY:
        return True
    if s in FALSY:
        return False
    return None


def logical_id(row: dict[str, str]) -> str:
    return (row.get("message_id") or row.get("logical_seq") or "").strip()


def mean_present(rows: Iterable[dict[str, str]], fields: list[str]) -> float | None:
    vals: list[float] = []
    for row in rows:
        for field in fields:
            if field in row:
                v = parse_float(row.get(field))
                if v is not None:
                    vals.append(v)
                break
    return statistics.mean(vals) if vals else None


def sum_int_present(rows: Iterable[dict[str, str]], fields: list[str]) -> int | None:
    vals: list[int] = []
    for row_no, row in enumerate(rows, start=2):
        for field in fields:
            if field in row:
                v = row.get(field)
                if v is not None and str(v).strip() != "":
                    vals.append(parse_int(v, field=field, row_no=row_no))
                break
    return sum(vals) if vals else None


def choose_seq_source(fieldnames: list[str]) -> str:
    for candidate in ("logical_seq", "seq", "sequence", "sequence_no"):
        if candidate in fieldnames:
            return candidate
    raise ValueError(
        "subscriber CSV has no usable sequence column; expected logical_seq, "
        "seq, sequence, or sequence_no"
    )


def publisher_delivery_reference(rows: list[dict[str, str]]) -> dict:
    all_ids: set[str] = set()
    successful_ids: set[str] = set()

    for row in rows:
        mid = logical_id(row)
        if not mid:
            continue
        all_ids.add(mid)
        success = parse_bool(row.get("success"))
        if success is True:
            successful_ids.add(mid)

    failed_only_ids = all_ids - successful_ids
    return {
        "all_logical_ids": all_ids,
        "successful_logical_ids": successful_ids,
        "failed_logical_ids": failed_only_ids,
    }


def adapt_subscriber(
    src: Path,
    dst: Path,
    *,
    successful_publisher_ids: set[str],
) -> dict:
    fieldnames, rows = read_rows(src)
    seq_source = choose_seq_source(fieldnames)

    seqs: list[int] = []
    adapted_rows: list[dict[str, str]] = []
    received_success_ids: list[str] = []
    decrypt_values: list[bool] = []

    for row_no, row in enumerate(rows, start=2):
        seq = parse_int(row.get(seq_source), field=seq_source, row_no=row_no)
        seqs.append(seq)

        decrypt = parse_bool(row.get("decrypt_success"))
        if decrypt is not None:
            decrypt_values.append(decrypt)

        mid = logical_id(row)
        if decrypt is not False and mid:
            received_success_ids.append(mid)

        adapted_rows.append(dict(row, seq=str(seq)))

    unique_received = set(received_success_ids)
    total_received_success = len(received_success_ids)
    duplicate_extra_rows = total_received_success - len(unique_received)
    duplicate_rate = (
        duplicate_extra_rows / total_received_success
        if total_received_success
        else None
    )

    lost_ids = sorted(successful_publisher_ids - unique_received)
    loss_rate = (
        len(lost_ids) / len(successful_publisher_ids)
        if successful_publisher_ids
        else None
    )

    decrypt_success_rate = (
        sum(1 for b in decrypt_values if b) / len(decrypt_values)
        if decrypt_values
        else None
    )

    avg_delivery_latency_ms = mean_present(
        rows,
        [
            "avg_delivery_latency_ms",
            "delivery_latency_ms",
            "latency_ms",
            "end_to_end_latency_ms",
        ],
    )

    # v1.3.7 aggregate_subscriber_metrics() already prefers explicit
    # loss_rate / duplicate_rate over sequence-derived values.
    for out in adapted_rows:
        out["loss_rate"] = "" if loss_rate is None else f"{loss_rate:.12f}"
        out["duplicate_rate"] = (
            "" if duplicate_rate is None else f"{duplicate_rate:.12f}"
        )

    out_fields = ["seq"] + [f for f in fieldnames if f != "seq"]
    for extra in ("loss_rate", "duplicate_rate"):
        if extra not in out_fields:
            out_fields.append(extra)

    with dst.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(adapted_rows)

    return {
        "raw_rows": len(rows),
        "seq_source": seq_source,
        "unique_received_logical_messages": len(unique_received),
        "duplicate_extra_rows": duplicate_extra_rows,
        "duplicate_rate": duplicate_rate,
        "successful_publisher_logical_messages": len(successful_publisher_ids),
        "lost_successfully_published_messages": len(lost_ids),
        "loss_rate": loss_rate,
        "lost_ids": lost_ids,
        "decrypt_success_rate": decrypt_success_rate,
        "avg_delivery_latency_ms": avg_delivery_latency_ms,
    }


def copy_publisher(src: Path, dst: Path) -> tuple[dict, dict]:
    fieldnames, rows = read_rows(src)
    ref = publisher_delivery_reference(rows)

    # PublishMetric.reconnect_count is a cumulative process counter. The bundled
    # v1.3.7 auto-controller aggregator sums the CSV column, so copying the raw
    # cumulative value would over-count reconnects (e.g. one reconnect repeated
    # on 95 later rows appears as 95).  For the controller-input snapshot only,
    # convert the cumulative counter to non-negative per-row increments. The sum
    # then equals the actual cumulative reconnect count while the raw input file
    # remains untouched.
    transformed_rows: list[dict[str, str]] = []
    previous = 0
    reconnect_max = 0
    for row_no, row in enumerate(rows, start=2):
        out = dict(row)
        raw_value = row.get("reconnect_count")
        if raw_value is not None and str(raw_value).strip() != "":
            current = parse_int(
                raw_value,
                field="reconnect_count",
                row_no=row_no,
            )
            reconnect_max = max(reconnect_max, current)
            delta = max(0, current - previous)
            previous = max(previous, current)
            out["reconnect_count"] = str(delta)
        transformed_rows.append(out)

    with dst.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(transformed_rows)

    metrics = {
        "raw_rows": len(rows),
        "all_logical_messages": len(ref["all_logical_ids"]),
        "successfully_published_logical_messages": len(
            ref["successful_logical_ids"]
        ),
        "failed_logical_messages": len(ref["failed_logical_ids"]),
        "failed_logical_ids": sorted(ref["failed_logical_ids"]),
        "avg_publish_complete_ms": mean_present(
            rows,
            [
                "avg_publish_complete_ms",
                "publish_complete_ms",
                "publish_complete_latency_ms",
                "publish_ack_latency_ms",
                "ack_latency_ms",
            ],
        ),
        "avg_payload_total_overhead_bytes": mean_present(
            rows,
            [
                "avg_payload_total_overhead_bytes",
                "payload_total_overhead_bytes",
                "total_overhead_bytes",
                "overhead_bytes",
                "padding_added",
            ],
        ),
        "reconnect_count": reconnect_max,
        "reconnect_counter_semantics": (
            "raw PublishMetric.reconnect_count is cumulative; controller-input "
            "CSV stores per-row increments so the unmodified v1.3.7 aggregator "
            "sum equals the actual reconnect count"
        ),
    }
    return metrics, ref


def fmt(v) -> str:
    if v is None:
        return "None"
    if isinstance(v, float):
        return f"{v:.9f}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publisher-raw", required=True)
    ap.add_argument("--subscriber-raw", required=True)
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--label", default="observation")
    args = ap.parse_args()

    pub_raw = Path(args.publisher_raw).resolve()
    sub_raw = Path(args.subscriber_raw).resolve()
    out_root = Path(args.out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    if not pub_raw.is_file():
        raise SystemExit(f"publisher raw CSV not found: {pub_raw}")
    if not sub_raw.is_file():
        raise SystemExit(f"subscriber raw CSV not found: {sub_raw}")

    pub_out = out_root / "publisher_controller_input.csv"
    sub_out = out_root / "subscriber_controller_input.csv"

    pub_metrics, pub_ref = copy_publisher(pub_raw, pub_out)
    sub_metrics = adapt_subscriber(
        sub_raw,
        sub_out,
        successful_publisher_ids=pub_ref["successful_logical_ids"],
    )

    manifest = {
        "schema": "aomqtt-closed-loop-observation-adapter-v3",
        "label": args.label,
        "purpose": (
            "Evaluation-only adapter for the unmodified AOMQTT v1.3.7 "
            "AutoPolicyController metric input. Delivery loss is referenced "
            "only to successfully published logical messages."
        ),
        "inputs": {
            "publisher_raw": {
                "path": str(pub_raw),
                "sha256": sha256_file(pub_raw),
            },
            "subscriber_raw": {
                "path": str(sub_raw),
                "sha256": sha256_file(sub_raw),
            },
        },
        "outputs": {
            "publisher_controller_input": {
                "path": str(pub_out),
                "sha256": sha256_file(pub_out),
            },
            "subscriber_controller_input": {
                "path": str(sub_out),
                "sha256": sha256_file(sub_out),
            },
        },
        "independent_metrics": {
            "publisher": pub_metrics,
            "subscriber": sub_metrics,
        },
    }

    manifest_path = out_root / "observation_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "AOMQTT closed-loop observation snapshot",
        "=======================================",
        f"label: {args.label}",
        "",
        "publisher:",
        f"  raw_rows: {pub_metrics['raw_rows']}",
        f"  all_logical_messages: {pub_metrics['all_logical_messages']}",
        "  successfully_published_logical_messages: "
        f"{pub_metrics['successfully_published_logical_messages']}",
        f"  failed_logical_messages: {pub_metrics['failed_logical_messages']}",
        f"  failed_logical_ids: {pub_metrics['failed_logical_ids']}",
        f"  avg_publish_complete_ms: {fmt(pub_metrics['avg_publish_complete_ms'])}",
        "  avg_payload_total_overhead_bytes: "
        f"{fmt(pub_metrics['avg_payload_total_overhead_bytes'])}",
        f"  reconnect_count: {fmt(pub_metrics['reconnect_count'])}",
        "",
        "subscriber:",
        f"  raw_rows: {sub_metrics['raw_rows']}",
        f"  seq_source: {sub_metrics['seq_source']}",
        "  unique_received_logical_messages: "
        f"{sub_metrics['unique_received_logical_messages']}",
        f"  duplicate_extra_rows: {sub_metrics['duplicate_extra_rows']}",
        f"  duplicate_rate: {fmt(sub_metrics['duplicate_rate'])}",
        "  successful_publisher_logical_messages: "
        f"{sub_metrics['successful_publisher_logical_messages']}",
        "  lost_successfully_published_messages: "
        f"{sub_metrics['lost_successfully_published_messages']}",
        f"  loss_rate: {fmt(sub_metrics['loss_rate'])}",
        f"  lost_ids: {sub_metrics['lost_ids']}",
        f"  decrypt_success_rate: {fmt(sub_metrics['decrypt_success_rate'])}",
        f"  avg_delivery_latency_ms: {fmt(sub_metrics['avg_delivery_latency_ms'])}",
        "",
        "controller inputs:",
        f"  {pub_out}",
        f"  {sub_out}",
    ]

    summary_path = out_root / "observation_summary.txt"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print()
    print(f"manifest: {manifest_path}")
    print("OBSERVATION-ADAPTER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
