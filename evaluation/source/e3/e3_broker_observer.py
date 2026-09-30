#!/usr/bin/env python3
"""Broker-visible MQTT observer for the AOMQTT E3 privacy evaluation.

The observer deliberately records only fields available to an ordinary MQTT
subscriber at the broker side.  It does not load AOMQTT keys, decrypt payloads,
or parse application data.

Output CSV schema:
    run_id, condition, observer_seq, recv_unix_ns, recv_monotonic_ns,
    mqtt_topic, mqtt_payload_bytes, qos, retain, dup

A ready file is created only after SUBACK is received, allowing E3 runners to
start the publisher only after the observer subscription is active.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import signal
import threading
import time
from pathlib import Path
from typing import Any, Sequence



OBSERVER_SCHEMA_VERSION = "e3-observer-v1"
CSV_FIELDS = [
    "run_id",
    "condition",
    "observer_seq",
    "recv_unix_ns",
    "recv_monotonic_ns",
    "mqtt_topic",
    "mqtt_payload_bytes",
    "qos",
    "retain",
    "dup",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_paho_client(client_id: str):
    """Create a Paho MQTT v3.1.1 client compatible with paho-mqtt 1.x/2.x.

    Import is intentionally lazy so unit tests for CSV/ready-gate behavior do
    not require a live MQTT dependency.  Runtime execution still requires the
    paho-mqtt package, which is already an AOMQTT v1.3.7 dependency.
    """
    import paho.mqtt.client as mqtt

    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
    except Exception:
        return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)


class ObserverRecorder:
    """Thread-safe CSV recorder and lifecycle metadata writer."""

    def __init__(
        self,
        *,
        output_csv: Path,
        run_id: str,
        condition: str,
        topic_filter: str,
        client_id: str,
        ready_file: Path | None = None,
        summary_file: Path | None = None,
    ) -> None:
        self.output_csv = output_csv
        self.run_id = run_id
        self.condition = condition
        self.topic_filter = topic_filter
        self.client_id = client_id
        self.ready_file = ready_file
        self.summary_file = summary_file or output_csv.with_suffix(
            output_csv.suffix + ".summary.json"
        )

        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.output_csv.open("w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(
            self._fh,
            fieldnames=CSV_FIELDS,
            lineterminator="\n",
        )
        self._writer.writeheader()
        self._fh.flush()

        self._lock = threading.Lock()
        self._row_count = 0
        self._started_unix_ns = time.time_ns()
        self._ready_unix_ns: int | None = None
        self._closed = False

    @property
    def row_count(self) -> int:
        return self._row_count

    @property
    def ready(self) -> bool:
        return self._ready_unix_ns is not None

    def mark_ready(self) -> None:
        """Record successful subscription readiness and create ready file."""
        with self._lock:
            if self._ready_unix_ns is None:
                self._ready_unix_ns = time.time_ns()
            ready_ns = self._ready_unix_ns

        if self.ready_file is not None:
            self.ready_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": OBSERVER_SCHEMA_VERSION,
                "run_id": self.run_id,
                "condition": self.condition,
                "client_id": self.client_id,
                "topic_filter": self.topic_filter,
                "ready_unix_ns": ready_ns,
            }
            self.ready_file.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    def record_message(
        self,
        *,
        mqtt_topic: str,
        payload: bytes,
        qos: int,
        retain: bool,
        dup: bool,
        recv_unix_ns: int | None = None,
        recv_monotonic_ns: int | None = None,
    ) -> None:
        if recv_unix_ns is None:
            recv_unix_ns = time.time_ns()
        if recv_monotonic_ns is None:
            recv_monotonic_ns = time.monotonic_ns()

        with self._lock:
            if self._closed:
                raise RuntimeError("observer recorder is already closed")
            seq = self._row_count
            self._writer.writerow(
                {
                    "run_id": self.run_id,
                    "condition": self.condition,
                    "observer_seq": seq,
                    "recv_unix_ns": recv_unix_ns,
                    "recv_monotonic_ns": recv_monotonic_ns,
                    "mqtt_topic": mqtt_topic,
                    "mqtt_payload_bytes": len(payload),
                    "qos": int(qos),
                    "retain": int(bool(retain)),
                    "dup": int(bool(dup)),
                }
            )
            # Flush every row so a terminated experiment still leaves an
            # analyzable prefix of the broker-visible trace.
            self._fh.flush()
            self._row_count += 1

    def close(self, *, exit_reason: str = "normal") -> Path:
        with self._lock:
            if self._closed:
                return self.summary_file
            self._fh.flush()
            self._fh.close()
            self._closed = True
            row_count = self._row_count
            ready_unix_ns = self._ready_unix_ns

        ended_unix_ns = time.time_ns()
        digest = sha256_file(self.output_csv)
        summary = {
            "schema_version": OBSERVER_SCHEMA_VERSION,
            "run_id": self.run_id,
            "condition": self.condition,
            "client_id": self.client_id,
            "topic_filter": self.topic_filter,
            "row_count": row_count,
            "started_unix_ns": self._started_unix_ns,
            "ready_unix_ns": ready_unix_ns,
            "ended_unix_ns": ended_unix_ns,
            "exit_reason": exit_reason,
            "output_csv": self.output_csv.name,
            "output_csv_sha256": digest,
        }
        self.summary_file.parent.mkdir(parents=True, exist_ok=True)
        self.summary_file.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.summary_file


def _reason_code_is_failure(reason_code: Any) -> bool:
    """Return whether a Paho v1/v2 reason code represents failure.

    paho-mqtt 2.x uses ReasonCode objects that are not int-convertible in all
    callback paths.  Prefer their ``is_failure`` / ``value`` attributes and
    fall back to legacy integer semantics.
    """
    if reason_code is None:
        return False

    flag = getattr(reason_code, "is_failure", None)
    if flag is not None:
        return bool(flag)

    value = getattr(reason_code, "value", None)
    if value is not None:
        try:
            return int(value) != 0
        except (TypeError, ValueError):
            pass

    try:
        return int(reason_code) != 0
    except (TypeError, ValueError):
        return str(reason_code).strip().lower() not in {"success", "0"}


def _suback_is_failure(reason_codes: Any) -> bool:
    """Validate SUBACK for paho-mqtt 1.x and 2.x callback shapes."""
    if reason_codes is None:
        return False

    # Both Callback API v2 reason_code_list and v1 granted_qos are sequences.
    if isinstance(reason_codes, (list, tuple)):
        for code in reason_codes:
            flag = getattr(code, "is_failure", None)
            if flag is not None:
                if bool(flag):
                    return True
                continue

            value = getattr(code, "value", code)
            try:
                # MQTT 3.x SUBACK failure code is 0x80.
                if int(value) >= 0x80:
                    return True
            except (TypeError, ValueError):
                return True
        return False

    flag = getattr(reason_codes, "is_failure", None)
    if flag is not None:
        return bool(flag)

    value = getattr(reason_codes, "value", reason_codes)
    try:
        return int(value) >= 0x80
    except (TypeError, ValueError):
        return True


class BrokerObserver:
    def __init__(
        self,
        *,
        broker: str,
        port: int,
        qos: int,
        recorder: ObserverRecorder,
    ) -> None:
        self.broker = broker
        self.port = port
        self.qos = qos
        self.recorder = recorder
        self.client = make_paho_client(recorder.client_id)
        self.stop_event = threading.Event()
        self.exit_reason = "normal"

        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        # paho-mqtt 2.x passes a ReasonCode object; paho 1.x may pass an int.
        if _reason_code_is_failure(reason_code):
            self.exit_reason = f"connect_failed:{reason_code}"
            self.stop_event.set()
            return
        result, _mid = client.subscribe(self.recorder.topic_filter, qos=self.qos)
        try:
            request_failed = int(result) != 0
        except (TypeError, ValueError):
            request_failed = bool(result)
        if request_failed:
            self.exit_reason = f"subscribe_request_failed:{result}"
            self.stop_event.set()

    def _on_subscribe(self, client, userdata, mid, *args):
        # Callback API v2: args[0] is reason_code_list, args[1] is properties.
        # Callback API v1: args[0] is granted_qos.
        reason_codes = args[0] if args else None
        if _suback_is_failure(reason_codes):
            self.exit_reason = f"suback_failed:{reason_codes}"
            self.stop_event.set()
            return
        # Ready is deliberately signaled only after a successful SUBACK.
        self.recorder.mark_ready()

    def _on_message(self, client, userdata, msg):
        self.recorder.record_message(
            mqtt_topic=str(msg.topic),
            payload=bytes(msg.payload),
            qos=int(getattr(msg, "qos", 0)),
            retain=bool(getattr(msg, "retain", False)),
            dup=bool(getattr(msg, "dup", False)),
        )

    def _on_disconnect(self, client, userdata, *args):
        # Do not turn a normal shutdown into an error. Unexpected disconnects
        # are recorded by the outer process if they terminate observation.
        return None

    def request_stop(self, reason: str) -> None:
        if not self.stop_event.is_set():
            self.exit_reason = reason
            self.stop_event.set()

    def run(self) -> int:
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_start()
        try:
            self.stop_event.wait()
        finally:
            try:
                self.client.disconnect()
            finally:
                self.client.loop_stop()
                self.recorder.close(exit_reason=self.exit_reason)
        return 0 if not self.exit_reason.startswith(("connect_failed", "subscribe_request_failed")) else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record broker-visible MQTT metadata for AOMQTT E3"
    )
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--filter", required=True, dest="topic_filter")
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=1)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ready-file", type=Path, default=None)
    parser.add_argument("--summary-file", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    recorder = ObserverRecorder(
        output_csv=args.output,
        run_id=args.run_id,
        condition=args.condition,
        topic_filter=args.topic_filter,
        client_id=args.client_id,
        ready_file=args.ready_file,
        summary_file=args.summary_file,
    )
    observer = BrokerObserver(
        broker=args.broker,
        port=args.port,
        qos=args.qos,
        recorder=recorder,
    )

    def handle_signal(signum, frame):
        name = signal.Signals(signum).name
        observer.request_stop(f"signal:{name}")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        return observer.run()
    except KeyboardInterrupt:
        observer.request_stop("keyboard_interrupt")
        recorder.close(exit_reason=observer.exit_reason)
        return 130
    except Exception as exc:
        observer.request_stop(f"error:{type(exc).__name__}")
        recorder.close(exit_reason=observer.exit_reason)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
