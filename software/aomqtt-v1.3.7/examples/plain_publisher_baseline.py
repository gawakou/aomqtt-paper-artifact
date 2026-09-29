from __future__ import annotations

import argparse
import csv
import json
import ssl
import time
from pathlib import Path

import paho.mqtt.client as mqtt


def make_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
    except Exception:
        return mqtt.Client(client_id=client_id)


def make_payload(seq: int, payload_bytes: int) -> bytes:
    base = {
        "seq": seq,
        "metric": "baseline",
        "value": seq,
        "timestamp": time.time(),
    }
    payload = json.dumps(base, separators=(",", ":")).encode("utf-8")

    if payload_bytes <= 0:
        return payload

    if len(payload) >= payload_bytes:
        return payload[:payload_bytes]

    padding_len = payload_bytes - len(payload)
    return payload + (b" " * padding_len)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plain MQTT publisher baseline for AOMQTT evaluation."
    )
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="baseline/plain")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--interval", type=float, default=0.0)
    parser.add_argument("--qos", type=int, default=1, choices=[0, 1, 2])
    parser.add_argument("--client-id", default="plain-publisher-baseline")
    parser.add_argument("--payload-bytes", type=int, default=0)
    parser.add_argument("--metrics-csv", default="results/plain_publisher_metrics.csv")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--publish-timeout", type=float, default=5.0)
    args = parser.parse_args()

    metrics_path = Path(args.metrics_csv)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    client = make_client(args.client_id)

    if args.username is not None:
        client.username_pw_set(args.username, args.password)

    if args.tls:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    rows: list[dict[str, object]] = []

    try:
        for seq in range(args.count):
            payload = make_payload(seq, args.payload_bytes)

            started = time.perf_counter()
            error = ""
            success = False
            publish_complete_ms = None

            try:
                info = client.publish(args.topic, payload, qos=args.qos)

                try:
                    info.wait_for_publish(timeout=args.publish_timeout)
                except TypeError:
                    info.wait_for_publish()

                publish_complete_ms = (time.perf_counter() - started) * 1000.0
                success = info.rc == mqtt.MQTT_ERR_SUCCESS

                if args.qos > 0:
                    try:
                        success = success and info.is_published()
                    except Exception:
                        pass

            except Exception as exc:
                publish_complete_ms = (time.perf_counter() - started) * 1000.0
                error = repr(exc)
                success = False

            rows.append(
                {
                    "timestamp": time.time(),
                    "seq": seq,
                    "topic": args.topic,
                    "qos": args.qos,
                    "payload_bytes": len(payload),
                    "success": int(success),
                    "publish_complete_ms": publish_complete_ms,
                    "error": error,
                }
            )

            if args.interval > 0:
                time.sleep(args.interval)

    finally:
        client.loop_stop()
        client.disconnect()

    with metrics_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "seq",
                "topic",
                "qos",
                "payload_bytes",
                "success",
                "publish_complete_ms",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    success_count = sum(int(row["success"]) for row in rows)
    print(f"published={len(rows)} success={success_count} metrics={metrics_path}")


if __name__ == "__main__":
    main()
