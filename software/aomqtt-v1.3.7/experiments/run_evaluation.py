#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

import paho.mqtt.client as mqtt

from aomqtt import (
    AOMQTTConfig,
    AOMQTTPublisher,
    AOMQTTSubscriber,
    DeliveryCSVLogger,
    DeliveryMetric,
    PayloadCrypto,
    PublishCSVLogger,
    PublishMetric,
    summarize_loss_and_duplicates,
)


def make_paho_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
    except Exception:
        return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)


def bool_from_csv(value: str) -> bool:
    return str(value).lower() in {"true", "1", "yes"}


def first_present(payload: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Return first present payload value while preserving valid 0 values."""
    for key in keys:
        if key in payload and payload[key] is not None and payload[key] != "":
            return payload[key]
    return default


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(p * (len(values) - 1)))
    return values[idx]


def _int(row: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key) or default))
    except Exception:
        return default


def write_mode_summary(mode_dir: Path) -> dict[str, Any]:
    pub_rows = read_csv(mode_dir / "publisher_metrics.csv")
    sub_rows = read_csv(mode_dir / "subscriber_metrics.csv")
    pub_lat = [float(r["publish_complete_ms"]) for r in pub_rows if bool_from_csv(r.get("success", ""))]
    sub_lat = [
        float(r["delivery_latency_ms"])
        for r in sub_rows
        if bool_from_csv(r.get("decrypt_success", "")) and float(r.get("delivery_latency_ms") or -1) >= 0
    ]
    loss = summarize_loss_and_duplicates(pub_rows, sub_rows)
    total_pub = len(pub_rows)
    pub_success = sum(1 for r in pub_rows if bool_from_csv(r.get("success", "")))
    decrypt_success = sum(1 for r in sub_rows if bool_from_csv(r.get("decrypt_success", "")))
    duplicates = sum(1 for r in sub_rows if bool_from_csv(r.get("duplicate", "")))
    plain_sizes = [_int(r, "payload_plain_bytes") for r in pub_rows]
    padded_sizes = [_int(r, "payload_padded_bytes", _int(r, "payload_plain_bytes")) for r in pub_rows]
    encrypted_sizes = [_int(r, "payload_encrypted_bytes") for r in pub_rows]
    padding_added = [_int(r, "padding_added_bytes") for r in pub_rows]
    total_overhead = [_int(r, "payload_total_overhead_bytes", _int(r, "payload_encrypted_bytes") - _int(r, "payload_plain_bytes")) for r in pub_rows]
    first_policy_id = (pub_rows[0].get("policy_id") if pub_rows else "") or (sub_rows[0].get("policy_id") if sub_rows else "") or ""
    first_policy_name = (pub_rows[0].get("policy_name") if pub_rows else "") or (sub_rows[0].get("policy_name") if sub_rows else "") or ""
    summary = {
        "policy_id": first_policy_id,
        "policy_name": first_policy_name,
        "mqtt_publish_rows": total_pub,
        "publish_success": pub_success,
        "publish_success_rate": (pub_success / total_pub) if total_pub else 0.0,
        "avg_publish_complete_ms": (sum(pub_lat) / len(pub_lat)) if pub_lat else 0.0,
        "p95_publish_complete_ms": percentile(pub_lat, 0.95),
        "subscriber_rows": len(sub_rows),
        "decrypt_success": decrypt_success,
        "decrypt_success_rate": (decrypt_success / len(sub_rows)) if sub_rows else 0.0,
        "duplicate_rows": duplicates,
        "avg_delivery_latency_ms": (sum(sub_lat) / len(sub_lat)) if sub_lat else 0.0,
        "p95_delivery_latency_ms": percentile(sub_lat, 0.95),
        "avg_payload_plain_bytes": (sum(plain_sizes) / len(plain_sizes)) if plain_sizes else 0.0,
        "avg_payload_padded_bytes": (sum(padded_sizes) / len(padded_sizes)) if padded_sizes else 0.0,
        "avg_payload_encrypted_bytes": (sum(encrypted_sizes) / len(encrypted_sizes)) if encrypted_sizes else 0.0,
        "avg_padding_added_bytes": (sum(padding_added) / len(padding_added)) if padding_added else 0.0,
        "avg_payload_total_overhead_bytes": (sum(total_overhead) / len(total_overhead)) if total_overhead else 0.0,
        **loss,
    }
    with (mode_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return summary


def write_comparison(output_dir: Path, summaries: dict[str, dict[str, Any]]) -> None:
    fields = [
        "mode",
        "policy_id",
        "policy_name",
        "mqtt_publish_rows",
        "published_logical_messages",
        "unique_received_messages",
        "publish_success_rate",
        "loss_rate",
        "duplicate_rate_per_unique_received",
        "decrypt_success_rate",
        "avg_publish_complete_ms",
        "p95_publish_complete_ms",
        "avg_delivery_latency_ms",
        "p95_delivery_latency_ms",
        "avg_payload_plain_bytes",
        "avg_payload_padded_bytes",
        "avg_payload_encrypted_bytes",
        "avg_padding_added_bytes",
        "avg_payload_total_overhead_bytes",
    ]
    with (output_dir / "comparison_summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for mode, summary in summaries.items():
            row = {"mode": mode}
            row.update({k: summary.get(k, "") for k in fields if k != "mode"})
            writer.writerow(row)


def apply_padding(
    cfg: AOMQTTConfig,
    *,
    padding_mode: str,
    fixed_size: int,
    bucket_size: int,
    random_min: int,
    random_max: int,
) -> AOMQTTConfig:
    if padding_mode == "none":
        return replace(cfg, padding_enabled=False, padding_mode="none")
    new_cfg = replace(
        cfg,
        padding_enabled=True,
        padding_mode=padding_mode,  # type: ignore[arg-type]
        padding_fixed_size=fixed_size,
        padding_bucket_size=bucket_size,
        padding_random_min_bytes=random_min,
        padding_random_max_bytes=random_max,
    )
    new_cfg.validate()
    return new_cfg


def make_config(
    base: AOMQTTConfig,
    *,
    mode: str,
    qos: int,
    rotation_interval: int,
    rotation_overlap: int,
    padding_mode: str,
    args: argparse.Namespace,
) -> AOMQTTConfig:
    token_mode = "hierarchical" if "hierarchical" in mode else "whole"
    rotation_enabled = "rotation" in mode
    cfg = replace(
        base,
        token_mode=token_mode,  # type: ignore[arg-type]
        mqtt_qos=qos,
        rotation_enabled=rotation_enabled,
        rotation_interval_sec=rotation_interval,
        rotation_overlap_sec=rotation_overlap,
        policy_id=mode,
        policy_name=mode,
    )
    cfg = apply_padding(
        cfg,
        padding_mode=padding_mode,
        fixed_size=args.padding_fixed_size,
        bucket_size=args.padding_bucket_size,
        random_min=args.padding_random_min_bytes,
        random_max=args.padding_random_max_bytes,
    )
    cfg.validate()
    return cfg


def payload_for(mode_label: str, seq: int) -> dict[str, Any]:
    sent_time = time.time()
    return {
        "message_id": f"{mode_label}-{seq:08d}",
        "seq": seq,
        "metric": "rtt",
        "value": 42.1 + seq,
        "sent_time": sent_time,
    }


def run_aomqtt_mode(
    args: argparse.Namespace,
    mode: str,
    mode_label: str,
    mode_dir: Path,
    base_config: AOMQTTConfig,
    padding_mode: str,
) -> dict[str, Any]:
    cfg = make_config(
        base_config,
        mode=mode,
        qos=args.qos,
        rotation_interval=args.rotation_interval,
        rotation_overlap=args.rotation_overlap,
        padding_mode=padding_mode,
        args=args,
    )
    pub_csv = PublishCSVLogger(mode_dir / "publisher_metrics.csv")
    sub_csv = DeliveryCSVLogger(mode_dir / "subscriber_metrics.csv")

    def on_message(token_topic, payload, raw_msg):
        return None

    sub = AOMQTTSubscriber(
        broker_host=args.broker,
        broker_port=args.port,
        client_id=f"aomqtt-v06-sub-{mode_label}",
        config=cfg,
    )
    pub = AOMQTTPublisher(
        broker_host=args.broker,
        broker_port=args.port,
        client_id=f"aomqtt-v06-pub-{mode_label}",
        config=cfg,
    )

    sub.connect()
    sub.loop_start()
    time.sleep(args.startup_wait)
    if cfg.rotation_enabled:
        sub.subscribe_rotating_observed(
            args.topic,
            callback=on_message,
            refresh_interval_sec=args.refresh_interval,
            csv_logger=sub_csv,
        )
    else:
        sub.subscribe_observed(args.topic, callback=on_message, csv_logger=sub_csv)
    time.sleep(args.startup_wait)

    pub.connect()
    pub.loop_start()
    time.sleep(args.startup_wait)
    try:
        for seq in range(args.count):
            pub.publish_observed_rotating(
                args.topic,
                payload_for(mode_label, seq),
                logical_seq=f"{mode_label}-{seq:08d}",
                wait_for_publish=not args.no_wait,
                wait_timeout=args.wait_timeout,
                csv_logger=pub_csv,
            )
            time.sleep(args.interval)
        time.sleep(args.settle_wait)
    finally:
        pub.loop_stop()
        pub.disconnect()
        sub.loop_stop()
        sub.disconnect()
        pub_csv.close()
        sub_csv.close()
    return write_mode_summary(mode_dir)


def run_baseline_mode(
    args: argparse.Namespace,
    mode: str,
    mode_label: str,
    mode_dir: Path,
    base_config: AOMQTTConfig,
    padding_mode: str,
) -> dict[str, Any]:
    pub_csv = PublishCSVLogger(mode_dir / "publisher_metrics.csv")
    sub_csv = DeliveryCSVLogger(mode_dir / "subscriber_metrics.csv")
    cfg = apply_padding(
        base_config,
        padding_mode=padding_mode if mode == "payload_only" else "none",
        fixed_size=args.padding_fixed_size,
        bucket_size=args.padding_bucket_size,
        random_min=args.padding_random_min_bytes,
        random_max=args.padding_random_max_bytes,
    )
    cfg = replace(cfg, policy_id=mode_label, policy_name=mode_label)
    crypto = PayloadCrypto(cfg)
    seen: set[str] = set()

    sub = make_paho_client(f"aomqtt-v06-sub-{mode_label}")
    pub = make_paho_client(f"aomqtt-v06-pub-{mode_label}")
    if mode == "tls":
        sub.tls_set()
        pub.tls_set()
    broker_port = args.tls_port if mode == "tls" else args.port

    def decode_payload(raw_payload: bytes) -> tuple[Optional[dict[str, Any]], bool, str]:
        try:
            if mode == "payload_only":
                aad = args.topic.encode("utf-8") if cfg.aad_bind_topic else None
                data = crypto.decrypt(raw_payload, aad=aad)
            else:
                data = json.loads(raw_payload.decode("utf-8"))
            if not isinstance(data, dict):
                data = {"value": data}
            return data, True, ""
        except Exception as exc:
            return None, False, repr(exc)

    def handle_message(client, userdata, msg):
        received_time = time.time()
        payload, ok, error = decode_payload(msg.payload)
        message_id = ""
        logical_seq = ""
        publisher_ts = 0.0
        if payload is not None:
            message_id = str(first_present(payload, "message_id", "seq", default=""))
            logical_seq = str(first_present(payload, "seq", "logical_seq", default=message_id))
            try:
                publisher_ts = float(first_present(payload, "sent_time", "publisher_timestamp", "timestamp", default=0.0))
            except Exception:
                publisher_ts = 0.0
        duplicate = bool(message_id and message_id in seen)
        if message_id:
            seen.add(message_id)
        sub_csv.write(
            DeliveryMetric(
                timestamp=received_time,
                client_id=f"aomqtt-v06-sub-{mode_label}",
                policy_id=cfg.policy_id,
                policy_name=cfg.policy_name,
                plaintext_filter=args.topic,
                token_topic=msg.topic,
                token_mode=mode_label,
                rotation_enabled=False,
                message_id=message_id,
                logical_seq=logical_seq,
                publisher_timestamp=publisher_ts,
                delivery_latency_ms=(received_time - publisher_ts) * 1000.0 if publisher_ts > 0 else -1.0,
                decrypt_success=ok,
                duplicate=duplicate,
                payload_bytes=len(msg.payload),
                error=error,
            )
        )

    sub.on_message = handle_message
    sub.connect(args.broker, broker_port, keepalive=60)
    sub.subscribe(args.topic, qos=args.qos)
    sub.loop_start()
    time.sleep(args.startup_wait)

    pub.connect(args.broker, broker_port, keepalive=60)
    pub.loop_start()
    time.sleep(args.startup_wait)
    try:
        for seq in range(args.count):
            payload = payload_for(mode_label, seq)
            logical_id = payload["message_id"]
            plain_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if mode == "payload_only":
                aad = args.topic.encode("utf-8") if cfg.aad_bind_topic else None
                send_payload, padding_stats = crypto.encrypt_with_stats(payload, aad=aad)
            else:
                send_payload = plain_bytes
                padding_stats = type("NoPadding", (), {
                    "original_plain_bytes": len(plain_bytes),
                    "padded_plain_bytes": len(plain_bytes),
                    "padding_enabled": False,
                    "padding_mode": "none",
                    "padding_added_bytes": 0,
                    "overhead_ratio": 0.0,
                })()
            start = time.perf_counter()
            error = ""
            mid = -1
            rc = -1
            success = False
            try:
                handle = pub.publish(args.topic, payload=send_payload, qos=args.qos, retain=False)
                rc = int(getattr(handle, "rc", 0))
                mid = int(getattr(handle, "mid", -1))
                if not args.no_wait:
                    handle.wait_for_publish(timeout=args.wait_timeout)
                    success = bool(handle.is_published())
                else:
                    success = rc == 0
            except Exception as exc:
                error = repr(exc)
                success = False
            end = time.perf_counter()
            pub_csv.write(
                PublishMetric(
                    timestamp=time.time(),
                    client_id=f"aomqtt-v06-pub-{mode_label}",
                    policy_id=cfg.policy_id,
                    policy_name=cfg.policy_name,
                    plaintext_topic=args.topic,
                    token_topic=args.topic,
                    token_mode=mode_label,
                    rotation_enabled=False,
                    rotation_epoch="",
                    rotation_in_overlap=False,
                    overlap_duplicate=False,
                    mqtt_messages_for_logical=1,
                    logical_seq=logical_id,
                    message_id=logical_id,
                    qos=args.qos,
                    retain=False,
                    payload_plain_bytes=padding_stats.original_plain_bytes,
                    payload_padded_bytes=padding_stats.padded_plain_bytes,
                    payload_encrypted_bytes=len(send_payload),
                    padding_enabled=padding_stats.padding_enabled,
                    padding_mode=padding_stats.padding_mode,
                    padding_added_bytes=padding_stats.padding_added_bytes,
                    padding_overhead_ratio=padding_stats.overhead_ratio,
                    payload_total_overhead_bytes=len(send_payload) - padding_stats.original_plain_bytes,
                    mid=mid,
                    rc=rc,
                    success=success,
                    wait_for_publish=not args.no_wait,
                    publish_complete_ms=(end - start) * 1000.0,
                    reconnect_count=0,
                    error=error,
                )
            )
            time.sleep(args.interval)
        time.sleep(args.settle_wait)
    finally:
        pub.loop_stop()
        pub.disconnect()
        sub.loop_stop()
        sub.disconnect()
        pub_csv.close()
        sub_csv.close()
    return write_mode_summary(mode_dir)


def run_mode(
    args: argparse.Namespace,
    mode: str,
    mode_label: str,
    output_dir: Path,
    base_config: AOMQTTConfig,
    padding_mode: str,
) -> dict[str, Any]:
    mode_dir = output_dir / mode_label
    mode_dir.mkdir(parents=True, exist_ok=True)
    print(f"[v0.7.1] running mode: {mode_label}")
    if mode in {"plain", "tls", "payload_only"}:
        return run_baseline_mode(args, mode, mode_label, mode_dir, base_config, padding_mode)
    return run_aomqtt_mode(args, mode, mode_label, mode_dir, base_config, padding_mode)


def expanded_modes(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    padding_modes = [p.strip() for p in args.padding_modes.split(",") if p.strip()]
    result: list[tuple[str, str, str]] = []
    for mode in modes:
        for padding_mode in padding_modes:
            if padding_mode != "none" and mode in {"plain", "tls"}:
                continue
            label = mode if padding_mode == "none" else f"{mode}_pad_{padding_mode}"
            result.append((mode, label, padding_mode))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AOMQTT v0.7.1 evaluation modes")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--tls-port", type=int, default=8883)
    parser.add_argument("--topic", default="shelter/siteA/starlink/rtt")
    parser.add_argument("--config", default="examples/config.example.yaml")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=1)
    parser.add_argument("--rotation-interval", type=int, default=30)
    parser.add_argument("--rotation-overlap", type=int, default=5)
    parser.add_argument("--refresh-interval", type=float, default=1.0)
    parser.add_argument("--startup-wait", type=float, default=0.5)
    parser.add_argument("--settle-wait", type=float, default=1.0)
    parser.add_argument("--wait-timeout", type=float, default=None)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument(
        "--modes",
        default="plain,payload_only,aomqtt_whole,aomqtt_hierarchical,aomqtt_whole_rotation,aomqtt_hierarchical_rotation",
        help="comma-separated base modes",
    )
    parser.add_argument(
        "--padding-modes",
        default="none,bucket,fixed,random",
        help="comma-separated padding modes applied to payload_only and AOMQTT modes: none,fixed,bucket,random",
    )
    parser.add_argument("--padding-fixed-size", type=int, default=512)
    parser.add_argument("--padding-bucket-size", type=int, default=256)
    parser.add_argument("--padding-random-min-bytes", type=int, default=0)
    parser.add_argument("--padding-random-max-bytes", type=int, default=128)
    parser.add_argument("--output", default="results/eval_v06")
    args = parser.parse_args()

    base_config = AOMQTTConfig.from_yaml(args.config)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, Any]] = {}
    for mode, mode_label, padding_mode in expanded_modes(args):
        summaries[mode_label] = run_mode(args, mode, mode_label, output_dir, base_config, padding_mode)
    write_comparison(output_dir, summaries)
    print(f"[v0.7.1] wrote results to: {output_dir}")
    print(f"[v0.7.1] comparison:       {output_dir / 'comparison_summary.csv'}")


if __name__ == "__main__":
    main()
