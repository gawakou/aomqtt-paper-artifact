from __future__ import annotations

import argparse
import csv
import json
import ssl
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt


def make_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
    except Exception:
        return mqtt.Client(client_id=client_id)


def extract_seq_and_source_timestamp(payload: bytes) -> tuple[int | None, float | None]:
    try:
        obj: Any = json.loads(payload.decode("utf-8").strip())
    except Exception:
        return None, None

    seq = obj.get("seq")
    timestamp = obj.get("timestamp")

    if not isinstance(seq, int):
        seq = None

    if not isinstance(timestamp, int | float):
        timestamp = None

    return seq, float(timestamp) if timestamp is not None else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plain MQTT subscriber baseline for AOMQTT evaluation."
    )
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="baseline/plain")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--qos", type=int, default=1, choices=[0, 1, 2])
    parser.add_argument("--client-id", default="plain-subscriber-baseline")
    parser.add_argument("--metrics-csv", default="results/plain_subscriber_metrics.csv")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    metrics_path = Path(args.metrics_csv)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    seen_seqs: set[int] = set()
    started = time.time()

    client = make_client(args.client_id)

    if args.username is not None:
        client.username_pw_set(args.username, args.password)

    if args.tls:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(args.topic, qos=args.qos)

    def on_message(client, userdata, msg):
        received_at = time.time()
        seq, source_timestamp = extract_seq_and_source_timestamp(msg.payload)

        duplicate = 0
        if seq is not None:
            duplicate = int(seq in seen_seqs)
            seen_seqs.add(seq)

        delivery_latency_ms = ""
        if source_timestamp is not None:
            delivery_latency_ms = (received_at - source_timestamp) * 1000.0

        rows.append(
            {
                "received_at": received_at,
                "seq": "" if seq is None else seq,
                "topic": msg.topic,
                "qos": msg.qos,
                "payload_bytes": len(msg.payload),
                "delivery_latency_ms": delivery_latency_ms,
                "duplicate": duplicate,
            }
        )

        if len(rows) >= args.count:
            client.disconnect()

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    try:
        while len(rows) < args.count:
            if time.time() - started > args.timeout:
                break
            time.sleep(0.05)
    finally:
        client.loop_stop()
        try:
            client.disconnect()
        except Exception:
            pass

    with metrics_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "received_at",
                "seq",
                "topic",
                "qos",
                "payload_bytes",
                "delivery_latency_ms",
                "duplicate",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    duplicate_count = sum(int(row["duplicate"]) for row in rows)
    print(
        f"received={len(rows)} unique_seqs={len(seen_seqs)} "
        f"duplicates={duplicate_count} metrics={metrics_path}"
    )


if __name__ == "__main__":
    main()
