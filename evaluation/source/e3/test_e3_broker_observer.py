from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "e3"
    / "e3_broker_observer.py"
)
SPEC = importlib.util.spec_from_file_location("e3_broker_observer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_recorder_writes_exact_observer_schema_and_payload_length(tmp_path: Path):
    csv_path = tmp_path / "observer.csv"
    rec = mod.ObserverRecorder(
        output_csv=csv_path,
        run_id="r01",
        condition="A2",
        topic_filter="e3/a/r01/A2/#",
        client_id="observer-a2-r01",
    )
    rec.record_message(
        mqtt_topic="e3/a/r01/A2/t/abc123",
        payload=b"x" * 802,
        qos=1,
        retain=False,
        dup=True,
        recv_unix_ns=111,
        recv_monotonic_ns=222,
    )
    summary = rec.close()

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0] == {
        "run_id": "r01",
        "condition": "A2",
        "observer_seq": "0",
        "recv_unix_ns": "111",
        "recv_monotonic_ns": "222",
        "mqtt_topic": "e3/a/r01/A2/t/abc123",
        "mqtt_payload_bytes": "802",
        "qos": "1",
        "retain": "0",
        "dup": "1",
    }

    data = json.loads(summary.read_text())
    assert data["row_count"] == 1
    assert data["output_csv_sha256"] == mod.sha256_file(csv_path)


def test_ready_file_is_absent_until_mark_ready(tmp_path: Path):
    ready = tmp_path / "observer.ready"
    rec = mod.ObserverRecorder(
        output_csv=tmp_path / "observer.csv",
        run_id="r01",
        condition="B3",
        topic_filter="e3/b/r01/B3/#",
        client_id="observer-b3-r01",
        ready_file=ready,
    )
    assert not ready.exists()
    assert not rec.ready

    rec.mark_ready()
    assert ready.exists()
    assert rec.ready
    payload = json.loads(ready.read_text())
    assert payload["run_id"] == "r01"
    assert payload["condition"] == "B3"
    assert payload["topic_filter"] == "e3/b/r01/B3/#"
    rec.close()


def test_on_subscribe_is_the_ready_gate(tmp_path: Path, monkeypatch):
    # Avoid constructing a real Paho client by bypassing BrokerObserver.__init__.
    ready = tmp_path / "ready.json"
    rec = mod.ObserverRecorder(
        output_csv=tmp_path / "observer.csv",
        run_id="r01",
        condition="B2",
        topic_filter="e3/b/r01/B2/#",
        client_id="observer-b2-r01",
        ready_file=ready,
    )
    obs = object.__new__(mod.BrokerObserver)
    obs.recorder = rec

    assert not ready.exists()
    obs._on_subscribe(None, None, 1)
    assert ready.exists()
    rec.close()


def test_on_message_records_only_broker_visible_fields(tmp_path: Path):
    rec = mod.ObserverRecorder(
        output_csv=tmp_path / "observer.csv",
        run_id="r02",
        condition="B1",
        topic_filter="e3/b/r02/B1/#",
        client_id="observer-b1-r02",
    )
    obs = object.__new__(mod.BrokerObserver)
    obs.recorder = rec

    msg = SimpleNamespace(
        topic="e3/b/r02/B1/t/deadbeef",
        payload=b"ciphertext-envelope",
        qos=1,
        retain=False,
        dup=False,
        # This synthetic extra attribute must never be written to observer CSV.
        logical_topic="e3/site/temp",
    )
    obs._on_message(None, None, msg)
    rec.close()

    text = (tmp_path / "observer.csv").read_text()
    assert "deadbeef" in text
    assert "e3/site/temp" not in text
    assert "ciphertext-envelope" not in text
    assert str(len(b"ciphertext-envelope")) in text


def test_observer_sequence_increments(tmp_path: Path):
    rec = mod.ObserverRecorder(
        output_csv=tmp_path / "observer.csv",
        run_id="r01",
        condition="A1",
        topic_filter="e3/a/r01/A1/#",
        client_id="observer-a1-r01",
    )
    for i in range(3):
        rec.record_message(
            mqtt_topic=f"e3/a/r01/A1/t/{i}",
            payload=b"123",
            qos=1,
            retain=False,
            dup=False,
            recv_unix_ns=100 + i,
            recv_monotonic_ns=200 + i,
        )
    rec.close()

    with (tmp_path / "observer.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [row["observer_seq"] for row in rows] == ["0", "1", "2"]


def test_close_is_idempotent(tmp_path: Path):
    rec = mod.ObserverRecorder(
        output_csv=tmp_path / "observer.csv",
        run_id="r01",
        condition="A0",
        topic_filter="e3/a/r01/A0/#",
        client_id="observer-a0-r01",
    )
    p1 = rec.close(exit_reason="first")
    p2 = rec.close(exit_reason="second")
    assert p1 == p2
    data = json.loads(p1.read_text())
    assert data["exit_reason"] == "first"


def test_record_after_close_is_rejected(tmp_path: Path):
    rec = mod.ObserverRecorder(
        output_csv=tmp_path / "observer.csv",
        run_id="r01",
        condition="A0",
        topic_filter="e3/a/r01/A0/#",
        client_id="observer-a0-r01",
    )
    rec.close()
    with pytest.raises(RuntimeError):
        rec.record_message(
            mqtt_topic="x/y",
            payload=b"x",
            qos=1,
            retain=False,
            dup=False,
        )


class _ReasonCodeLike:
    def __init__(self, *, is_failure: bool, value=None, label="Success"):
        self.is_failure = is_failure
        self.value = value
        self.label = label

    def __int__(self):
        raise TypeError("ReasonCode is intentionally not int-convertible")

    def __str__(self):
        return self.label


def test_reason_code_v2_object_does_not_require_int_conversion():
    assert mod._reason_code_is_failure(
        _ReasonCodeLike(is_failure=False, value=0, label="Success")
    ) is False
    assert mod._reason_code_is_failure(
        _ReasonCodeLike(is_failure=True, value=128, label="Not authorized")
    ) is True


def test_on_connect_accepts_paho_v2_reason_code_and_requests_subscription(tmp_path: Path):
    rec = mod.ObserverRecorder(
        output_csv=tmp_path / "observer.csv",
        run_id="r01",
        condition="SMOKE",
        topic_filter="e3/smoke/#",
        client_id="observer-smoke",
    )
    obs = object.__new__(mod.BrokerObserver)
    obs.recorder = rec
    obs.qos = 1
    import threading
    obs.stop_event = threading.Event()
    obs.exit_reason = "normal"

    calls = []
    client = SimpleNamespace(
        subscribe=lambda topic, qos: (calls.append((topic, qos)) or (0, 7))
    )
    rc = _ReasonCodeLike(is_failure=False, value=0, label="Success")
    obs._on_connect(client, None, {}, rc)

    assert calls == [("e3/smoke/#", 1)]
    assert not obs.stop_event.is_set()
    rec.close()


def test_failed_suback_does_not_create_ready_file(tmp_path: Path):
    ready = tmp_path / "observer.ready"
    rec = mod.ObserverRecorder(
        output_csv=tmp_path / "observer.csv",
        run_id="r01",
        condition="SMOKE",
        topic_filter="e3/smoke/#",
        client_id="observer-smoke",
        ready_file=ready,
    )
    obs = object.__new__(mod.BrokerObserver)
    obs.recorder = rec
    import threading
    obs.stop_event = threading.Event()
    obs.exit_reason = "normal"

    failure = _ReasonCodeLike(
        is_failure=True,
        value=128,
        label="Unspecified error",
    )
    obs._on_subscribe(None, None, 1, [failure], None)

    assert not ready.exists()
    assert obs.stop_event.is_set()
    assert obs.exit_reason.startswith("suback_failed:")
    rec.close()
