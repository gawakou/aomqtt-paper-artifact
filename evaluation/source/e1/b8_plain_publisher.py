#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, ssl, time
from pathlib import Path
import paho.mqtt.client as mqtt

def make_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
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
    return payload + (b" " * (payload_bytes - len(payload)))

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--broker", required=True)
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--topic", required=True)
    p.add_argument("--count", type=int, default=6000)
    p.add_argument("--interval", type=float, default=0.01)
    p.add_argument("--qos", type=int, default=1, choices=[0,1,2])
    p.add_argument("--client-id", required=True)
    p.add_argument("--payload-bytes", type=int, default=0)
    p.add_argument("--metrics-csv", required=True)
    p.add_argument("--publish-timeout", type=float, default=5.0)
    args = p.parse_args()

    out = Path(args.metrics_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    c = make_client(args.client_id)
    c.connect(args.broker, args.port, keepalive=60)
    c.loop_start()
    rows = []
    try:
        for seq in range(args.count):
            payload = make_payload(seq, args.payload_bytes)
            t0 = time.perf_counter()
            err = ""
            ok = False
            try:
                info = c.publish(args.topic, payload, qos=args.qos)
                try:
                    info.wait_for_publish(timeout=args.publish_timeout)
                except TypeError:
                    info.wait_for_publish()
                dt = (time.perf_counter() - t0) * 1000.0
                ok = info.rc == mqtt.MQTT_ERR_SUCCESS
                if args.qos > 0:
                    try:
                        ok = ok and info.is_published()
                    except Exception:
                        pass
            except Exception as exc:
                dt = (time.perf_counter() - t0) * 1000.0
                err = repr(exc)
            rows.append({
                "timestamp": time.time(),
                "seq": seq,
                "topic": args.topic,
                "qos": args.qos,
                "payload_bytes": len(payload),
                "success": int(ok),
                "publish_complete_ms": dt,
                "error": err,
            })
            if args.interval > 0:
                # Historical E1 semantics: sleep after each completed publish.
                time.sleep(args.interval)
    finally:
        c.loop_stop()
        c.disconnect()

    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp","seq","topic","qos","payload_bytes","success",
            "publish_complete_ms","error"
        ])
        w.writeheader(); w.writerows(rows)
    print(f"published={len(rows)} success={sum(int(r['success']) for r in rows)} metrics={out}")

if __name__ == "__main__":
    main()
