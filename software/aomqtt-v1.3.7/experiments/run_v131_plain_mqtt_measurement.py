#!/usr/bin/env python3
"""Local plain MQTT measurement helper for v1.3.1.

This helper is intentionally limited to local or explicitly authorized brokers.
It uses paho-mqtt if available.  The v1.3.1 tests do not require a running
broker; actual execution is optional and operator-controlled.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
    return float(values[idx])


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "avg": float(statistics.mean(values)) if values else 0.0,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def run_plain_mqtt_measurement(args: argparse.Namespace) -> dict[str, Any]:
    try:
        import paho.mqtt.client as mqtt
    except Exception as exc:  # pragma: no cover - depends on optional runtime environment
        raise SystemExit(f"paho-mqtt is required for execute mode: {exc}") from exc

    topic = args.topic
    run_id = args.run_id
    received: dict[int, float] = {}
    delivery_latencies: list[float] = []
    publish_complete: list[float] = []
    lock = threading.Lock()
    done = threading.Event()

    sub_client = mqtt.Client(client_id=f"v131-sub-{uuid.uuid4()}")

    def on_connect(client, userdata, flags, rc):  # type: ignore[no-untyped-def]
        if rc == 0:
            client.subscribe(topic, qos=args.qos)

    def on_message(client, userdata, msg):  # type: ignore[no-untyped-def]
        now = time.time()
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            seq = int(payload["seq"])
            sent_ts = float(payload["sent_ts"])
        except Exception:
            return
        with lock:
            if seq not in received:
                received[seq] = now
                delivery_latencies.append((now - sent_ts) * 1000.0)
                if len(received) >= args.count:
                    done.set()

    sub_client.on_connect = on_connect
    sub_client.on_message = on_message
    sub_client.connect(args.broker, args.port, keepalive=30)
    sub_client.loop_start()

    pub_client = mqtt.Client(client_id=f"v131-pub-{uuid.uuid4()}")
    pub_client.connect(args.broker, args.port, keepalive=30)
    pub_client.loop_start()

    # Give the subscriber time to subscribe.
    time.sleep(args.subscribe_wait)

    raw_rows = []
    for seq in range(args.count):
        payload = {
            "run_id": run_id,
            "scenario_id": "plain_mqtt_baseline",
            "seq": seq,
            "sent_ts": time.time(),
            "value": args.payload_value,
        }
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        t0 = time.perf_counter()
        info = pub_client.publish(topic, encoded, qos=args.qos)
        if args.qos > 0:
            info.wait_for_publish(timeout=args.publish_timeout)
        t1 = time.perf_counter()
        publish_ms = (t1 - t0) * 1000.0
        publish_complete.append(publish_ms)
        raw_rows.append(
            {
                "run_id": run_id,
                "scenario_id": "plain_mqtt_baseline",
                "seq": seq,
                "payload_bytes": len(encoded),
                "publish_complete_ms": publish_ms,
                "success": int(info.rc == mqtt.MQTT_ERR_SUCCESS),
            }
        )
        if args.interval > 0:
            time.sleep(args.interval)

    done.wait(timeout=args.receive_timeout)
    pub_client.loop_stop()
    sub_client.loop_stop()
    pub_client.disconnect()
    sub_client.disconnect()

    publish_summary = summarize(publish_complete)
    delivery_summary = summarize(delivery_latencies)
    success_messages = len(received)
    missing_messages = max(0, args.count - success_messages)

    raw_csv = Path(args.raw_csv)
    raw_csv.parent.mkdir(parents=True, exist_ok=True)
    with raw_csv.open("w", newline="") as f:
        fieldnames = ["run_id", "scenario_id", "seq", "payload_bytes", "publish_complete_ms", "success"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(raw_rows)

    return {
        "run_id": run_id,
        "scenario_id": "plain_mqtt_baseline",
        "scenario_type": "plain_mqtt",
        "environment": "local_broker",
        "broker": f"{args.broker}:{args.port}",
        "qos": args.qos,
        "logical_messages": args.count,
        "mqtt_messages": args.count,
        "success_messages": success_messages,
        "failed_messages": missing_messages,
        "duplicates": 0,
        "missing_messages": missing_messages,
        "publish_complete_ms_avg": publish_summary["avg"],
        "publish_complete_ms_p50": publish_summary["p50"],
        "publish_complete_ms_p95": publish_summary["p95"],
        "publish_complete_ms_p99": publish_summary["p99"],
        "delivery_latency_ms_avg": delivery_summary["avg"],
        "delivery_latency_ms_p50": delivery_summary["p50"],
        "delivery_latency_ms_p95": delivery_summary["p95"],
        "delivery_latency_ms_p99": delivery_summary["p99"],
        "payload_plain_bytes_avg": statistics.mean([r["payload_bytes"] for r in raw_rows]) if raw_rows else 0.0,
        "payload_padded_bytes_avg": "",
        "payload_encrypted_bytes_avg": "",
        "padding_added_bytes_avg": "",
        "rotation_overlap_duplicates": 0,
        "control_accepted": "",
        "control_rejected": "",
        "transparency_entries": "",
        "transparency_verified_entries": "",
        "status": "measured",
        "notes": "plain MQTT local broker measurement",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="run-v131-local-measurements-001")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="aomqtt/v131/plain/baseline")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval", type=float, default=0.0)
    parser.add_argument("--qos", type=int, default=1)
    parser.add_argument("--payload-value", default="v131")
    parser.add_argument("--subscribe-wait", type=float, default=0.5)
    parser.add_argument("--publish-timeout", type=float, default=5.0)
    parser.add_argument("--receive-timeout", type=float, default=10.0)
    parser.add_argument("--raw-csv", default="results/run-v131-local-measurements-001/raw/plain_mqtt_baseline.csv")
    parser.add_argument("--summary-json", default="")
    args = parser.parse_args(argv)

    summary = run_plain_mqtt_measurement(args)
    if args.summary_json:
        path = Path(args.summary_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, sort_keys=True))
        print(f"wrote {path}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

