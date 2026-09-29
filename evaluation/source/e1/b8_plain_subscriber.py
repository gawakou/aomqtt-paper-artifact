#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, ssl, time
from pathlib import Path
from typing import Any
import paho.mqtt.client as mqtt

def make_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except Exception:
        return mqtt.Client(client_id=client_id)

def extract(payload: bytes):
    try:
        obj: Any = json.loads(payload.decode("utf-8").strip())
    except Exception:
        return None, None
    seq = obj.get("seq")
    ts = obj.get("timestamp")
    if not isinstance(seq, int): seq = None
    if not isinstance(ts, (int,float)): ts = None
    return seq, float(ts) if ts is not None else None

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--broker", required=True)
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--topic", required=True)
    p.add_argument("--count", type=int, default=6000)
    p.add_argument("--qos", type=int, default=1, choices=[0,1,2])
    p.add_argument("--client-id", required=True)
    p.add_argument("--metrics-csv", required=True)
    p.add_argument("--timeout", type=float, default=120.0)
    args = p.parse_args()

    out = Path(args.metrics_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    seen = set()
    started = time.time()
    c = make_client(args.client_id)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(args.topic, qos=args.qos)
        print("READY", flush=True)

    def on_message(client, userdata, msg):
        received_at = time.time()
        seq, source_ts = extract(msg.payload)
        dup = 0
        if seq is not None:
            dup = int(seq in seen)
            seen.add(seq)
        lat = ""
        if source_ts is not None:
            lat = (received_at - source_ts) * 1000.0
        rows.append({
            "received_at": received_at,
            "seq": "" if seq is None else seq,
            "topic": msg.topic,
            "qos": msg.qos,
            "payload_bytes": len(msg.payload),
            "delivery_latency_ms": lat,
            "duplicate": dup,
        })
        if len(seen) >= args.count:
            c.disconnect()

    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(args.broker, args.port, keepalive=60)
    c.loop_start()
    try:
        while len(seen) < args.count and time.time() - started <= args.timeout:
            time.sleep(0.05)
    finally:
        c.loop_stop()
        try: c.disconnect()
        except Exception: pass

    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "received_at","seq","topic","qos","payload_bytes",
            "delivery_latency_ms","duplicate"
        ])
        w.writeheader(); w.writerows(rows)
    print(f"received={len(rows)} unique_seqs={len(seen)} duplicates={sum(int(r['duplicate']) for r in rows)} metrics={out}")

if __name__ == "__main__":
    main()
