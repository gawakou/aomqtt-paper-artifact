#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aomqtt import AOMQTTConfig, AOMQTTPublisher, AOMQTTPolicy, TransportAdapter
from aomqtt.control import ControlTopicPolicyReceiver, build_control_policy_message, control_policy_topic
from aomqtt.control_plane.client_reporter import PolicyAckStatusReporter
from aomqtt.control_security import PolicySafetyLimits as ParserSafetyLimits, generate_keypair, sign_control_message_dict
from aomqtt.policy_guard import PolicyGuard

GROUP_ID = "pg-eval"
TRUSTED_KEY_ID = "trusted-key"
UNTRUSTED_KEY_ID = "old-key"


class FakePublishHandle:
    def __init__(self, mid: int = 1, rc: int = 0):
        self.mid = mid
        self.rc = rc
        self._published = False

    def wait_for_publish(self, timeout=None) -> None:
        self._published = True

    def is_published(self) -> bool:
        return self._published


class NoopTransport(TransportAdapter):
    def __init__(self):
        self.published = []
        self._mid = 0

    @property
    def reconnect_count(self) -> int:
        return 0

    def set_on_connect(self, callback):
        self.on_connect = callback

    def set_on_disconnect(self, callback):
        self.on_disconnect = callback

    def set_on_message(self, callback):
        self.on_message = callback

    def username_pw_set(self, username, password=None):
        pass

    def tls_set(self):
        pass

    def connect(self, host, port, keepalive=60):
        pass

    def disconnect(self):
        pass

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def loop_forever(self):
        pass

    def publish(self, topic, payload, qos=0, retain=False):
        self._mid += 1
        self.published.append((topic, payload, qos, retain))
        return FakePublishHandle(mid=self._mid, rc=0)

    def subscribe(self, topic_filter, qos=0):
        return (0, 1)


class CaptureMQTTClient:
    def __init__(self):
        self.published: list[dict[str, Any]] = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append(
            {"topic": topic, "payload": payload, "qos": qos, "retain": retain}
        )
        return None


class FakeMsg:
    def __init__(self, payload: bytes):
        self.topic = control_policy_topic(GROUP_ID)
        self.payload = payload


@dataclass(frozen=True)
class Case:
    case_id: str
    description: str
    expected_outcome: str
    expected_reason_code: str


CASES = [
    Case("PG0", "valid signed policy", "accepted", "accepted"),
    Case("PG1", "tampered after signing", "rejected", "invalid_signature"),
    Case("PG2", "expired signed policy", "rejected", "expired_policy"),
    Case("PG3", "replayed sequence number", "rejected", "stale_sequence_no"),
    Case("PG4", "untrusted signing key identifier", "rejected", "unknown_key_id"),
    Case(
        "PG5",
        "signed policy disables payload encryption",
        "rejected",
        "payload_encryption_disable_forbidden",
    ),
]


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def base_config() -> AOMQTTConfig:
    return AOMQTTConfig(
        topic_key="pg-eval-topic-secret-0123456789",
        payload_key="pg-eval-payload-secret-0123456789",
        token_mode="whole",
        mqtt_qos=1,
        rotation_enabled=True,
        rotation_interval_sec=30,
        rotation_overlap_sec=5,
        padding_enabled=True,
        padding_mode="fixed",
        padding_fixed_size=512,
    )


def safe_policy(policy_id: str, *, fixed_size: int = 512) -> AOMQTTPolicy:
    return AOMQTTPolicy(
        policy_id=policy_id,
        name=policy_id,
        token_mode="whole",
        mqtt_qos=1,
        rotation_enabled=True,
        rotation_interval_sec=30,
        rotation_overlap_sec=5,
        padding_enabled=True,
        padding_mode="fixed",
        padding_fixed_size=fixed_size,
    )


def signed_message_bytes(
    private_key: str,
    *,
    policy_id: str,
    sequence_no: int,
    fixed_size: int = 1024,
    key_id: str = TRUSTED_KEY_ID,
    expires_at: float | None = None,
) -> bytes:
    msg = build_control_policy_message(
        safe_policy(policy_id, fixed_size=fixed_size),
        group_id=GROUP_ID,
        valid_after_sec=0.0,
        grace_period_sec=0.0,
        sequence_no=sequence_no,
        expires_at=expires_at,
        expires_after_sec=None if expires_at is not None else 3600.0,
        signing_private_key=private_key,
        signing_key_id=key_id,
    )
    return msg.to_json_bytes()


def tampered_signature_bytes(private_key: str, *, policy_id: str) -> bytes:
    msg = build_control_policy_message(
        safe_policy(policy_id, fixed_size=1024),
        group_id=GROUP_ID,
        valid_after_sec=0.0,
        grace_period_sec=0.0,
        sequence_no=2,
        expires_after_sec=3600.0,
        signing_private_key=private_key,
        signing_key_id=TRUSTED_KEY_ID,
    )
    data = msg.to_dict()
    data["policy"] = dict(data["policy"])
    data["policy"]["name"] = "tampered-after-signing"
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def guard_rejection_bytes(private_key: str, *, policy_id: str) -> bytes:
    unsigned = build_control_policy_message(
        safe_policy(policy_id, fixed_size=1024),
        group_id=GROUP_ID,
        valid_after_sec=0.0,
        grace_period_sec=0.0,
        sequence_no=2,
        expires_after_sec=3600.0,
    ).to_dict()
    unsigned["policy"] = dict(unsigned["policy"])
    unsigned["policy"]["payload_encryption"] = {"enabled": False}
    signed = sign_control_message_dict(
        unsigned, private_key, key_id=TRUSTED_KEY_ID
    )
    return json.dumps(
        signed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def candidate_payload(case_id: str, private_key: str, trial: int) -> bytes:
    pid = f"{case_id.lower()}-candidate-r{trial:02d}"

    if case_id == "PG0":
        return signed_message_bytes(
            private_key, policy_id=pid, sequence_no=2, fixed_size=1024
        )
    if case_id == "PG1":
        return tampered_signature_bytes(private_key, policy_id=pid)
    if case_id == "PG2":
        return signed_message_bytes(
            private_key,
            policy_id=pid,
            sequence_no=2,
            fixed_size=1024,
            expires_at=time.time() - 1.0,
        )
    if case_id == "PG3":
        return signed_message_bytes(
            private_key, policy_id=pid, sequence_no=1, fixed_size=1024
        )
    if case_id == "PG4":
        return signed_message_bytes(
            private_key,
            policy_id=pid,
            sequence_no=2,
            fixed_size=1024,
            key_id=UNTRUSTED_KEY_ID,
        )
    if case_id == "PG5":
        return guard_rejection_bytes(private_key, policy_id=pid)

    raise ValueError(case_id)


def make_receiver(public_key: str):
    publisher = AOMQTTPublisher(
        broker_host="localhost",
        client_id="pg-eval-publisher",
        config=base_config(),
        transport=NoopTransport(),
    )

    capture = CaptureMQTTClient()
    reporter = PolicyAckStatusReporter(
        mqtt_client=capture,
        group_id=GROUP_ID,
        client_id="pg-eval-client",
        role="publisher",
        qos=1,
    )

    events: list[dict[str, Any]] = []

    def on_event(event: str, message) -> None:
        events.append(
            {
                "event": event,
                "policy_id": message.policy_id,
                "sequence_no": message.sequence_no,
            }
        )

    receiver = object.__new__(ControlTopicPolicyReceiver)
    receiver.group_id = GROUP_ID
    receiver.signing_public_key = public_key
    receiver.require_signature = True
    receiver.allowed_signature_key_ids = {TRUSTED_KEY_ID}
    receiver.safety_limits = ParserSafetyLimits()
    receiver.policy_reporter = reporter
    receiver.on_event = on_event
    receiver._policy_guard = PolicyGuard()
    receiver._latest_sequence_no = None
    receiver._latest_policy_id = ""
    receiver._last_known_good_message = None
    receiver._timers = []
    receiver._lock = threading.Lock()
    receiver.apply_callback = lambda policy, message: publisher.apply_policy(policy)

    return receiver, publisher, capture, events


def send_and_wait(receiver, payload: bytes) -> float:
    before = len(receiver._timers)
    t0 = time.perf_counter_ns()
    receiver._on_message(None, None, FakeMsg(payload))

    for timer in list(receiver._timers[before:]):
        timer.join(timeout=2.0)
        if timer.is_alive():
            raise RuntimeError("policy-application timer did not complete")

    return (time.perf_counter_ns() - t0) / 1000.0


def decode_captured(capture: CaptureMQTTClient) -> list[dict[str, Any]]:
    result = []
    for item in capture.published:
        payload = item["payload"]
        obj = json.loads(
            payload.decode("utf-8") if isinstance(payload, bytes) else payload
        )
        result.append(
            {
                "topic": item["topic"],
                "qos": item["qos"],
                "retain": item["retain"],
                "body": obj,
            }
        )
    return result


def run_trial(
    case: Case,
    trial: int,
    private_key: str,
    public_key: str,
) -> dict[str, Any]:
    receiver, publisher, capture, events = make_receiver(public_key)

    baseline_id = f"pg-baseline-r{trial:02d}"
    baseline_payload = signed_message_bytes(
        private_key,
        policy_id=baseline_id,
        sequence_no=1,
        fixed_size=512,
    )
    send_and_wait(receiver, baseline_payload)

    baseline_lkg = receiver._last_known_good_message
    if baseline_lkg is None or baseline_lkg.policy_id != baseline_id:
        raise AssertionError(f"{case.case_id} r{trial}: baseline LKG not applied")
    if receiver._latest_sequence_no != 1:
        raise AssertionError(f"{case.case_id} r{trial}: baseline sequence not installed")
    if publisher.config.policy_id != baseline_id:
        raise AssertionError(f"{case.case_id} r{trial}: baseline config not applied")
    if publisher.config.padding_fixed_size != 512:
        raise AssertionError(f"{case.case_id} r{trial}: baseline padding mismatch")

    capture.published.clear()
    events.clear()

    lkg_before = receiver._last_known_good_message.policy_id
    seq_before = receiver._latest_sequence_no
    config_before = publisher.config.policy_id
    padding_before = publisher.config.padding_fixed_size

    payload = candidate_payload(case.case_id, private_key, trial)
    elapsed_us = send_and_wait(receiver, payload)

    reports = decode_captured(capture)
    ack_bodies = [x["body"] for x in reports if x["topic"].endswith("/ack")]
    status_bodies = [x["body"] for x in reports if x["topic"].endswith("/status")]

    if len(ack_bodies) != 1:
        raise AssertionError(
            f"{case.case_id} r{trial}: expected one ACK, got {len(ack_bodies)}"
        )

    ack = ack_bodies[0]
    observed_outcome = str(ack.get("status", "unknown"))
    reason_code = (
        "accepted"
        if observed_outcome == "accepted"
        else str(ack.get("reason_code", ""))
    )

    lkg_after_obj = receiver._last_known_good_message
    lkg_after = lkg_after_obj.policy_id if lkg_after_obj is not None else ""
    seq_after = receiver._latest_sequence_no
    config_after = publisher.config.policy_id
    padding_after = publisher.config.padding_fixed_size
    status_value = (
        ",".join(str(x.get("status", "")) for x in status_bodies)
        if status_bodies
        else ""
    )

    if case.expected_outcome == "accepted":
        candidate_id = f"{case.case_id.lower()}-candidate-r{trial:02d}"
        passed = (
            observed_outcome == "accepted"
            and reason_code == "accepted"
            and status_value == "applied"
            and lkg_after == candidate_id
            and seq_after == 2
            and config_after == candidate_id
            and padding_after == 1024
        )
        lkg_retained = False
        config_retained = False
    else:
        passed = (
            observed_outcome == "rejected"
            and reason_code == case.expected_reason_code
            and not status_bodies
            and lkg_after == lkg_before
            and seq_after == seq_before
            and config_after == config_before
            and padding_after == padding_before
        )
        lkg_retained = lkg_after == lkg_before
        config_retained = (
            config_after == config_before and padding_after == padding_before
        )

    row = {
        "case": case.case_id,
        "description": case.description,
        "trial": trial,
        "expected_outcome": case.expected_outcome,
        "observed_outcome": observed_outcome,
        "expected_reason_code": case.expected_reason_code,
        "reason_code": reason_code,
        "status": status_value,
        "lkg_before": lkg_before,
        "lkg_after": lkg_after,
        "lkg_retained": lkg_retained,
        "sequence_before": seq_before,
        "sequence_after": seq_after,
        "config_policy_before": config_before,
        "config_policy_after": config_after,
        "padding_before": padding_before,
        "padding_after": padding_after,
        "config_retained": config_retained,
        "elapsed_us": round(elapsed_us, 3),
        "events": "|".join(x["event"] for x in events),
        "pass": passed,
    }

    if not passed:
        raise AssertionError(
            f"{case.case_id} r{trial}: formal gate failed: "
            + json.dumps(row, ensure_ascii=False, default=str)
        )

    return row


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for case in CASES:
        cr = [r for r in rows if r["case"] == case.case_id]
        elapsed = [float(r["elapsed_us"]) for r in cr]
        rejected = [r for r in cr if r["observed_outcome"] == "rejected"]
        summary.append(
            {
                "case": case.case_id,
                "description": case.description,
                "expected_outcome": case.expected_outcome,
                "expected_reason_code": case.expected_reason_code,
                "trials": len(cr),
                "passes": sum(bool(r["pass"]) for r in cr),
                "accepted": sum(r["observed_outcome"] == "accepted" for r in cr),
                "rejected": sum(r["observed_outcome"] == "rejected" for r in cr),
                "lkg_retained_on_rejection": (
                    sum(bool(r["lkg_retained"]) for r in rejected)
                    if rejected
                    else ""
                ),
                "config_retained_on_rejection": (
                    sum(bool(r["config_retained"]) for r in rejected)
                    if rejected
                    else ""
                ),
                "elapsed_us_mean": round(statistics.mean(elapsed), 3),
                "elapsed_us_sd": round(
                    statistics.stdev(elapsed) if len(elapsed) > 1 else 0.0, 3
                ),
                "elapsed_us_min": round(min(elapsed), 3),
                "elapsed_us_max": round(max(elapsed), 3),
            }
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument(
        "--out-root", default="results/analysis/policy-guard-micro"
    )
    args = parser.parse_args()

    if args.trials < 1:
        raise SystemExit("--trials must be >= 1")

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    private_key, public_key = generate_keypair()

    metadata = {
        "evaluation": "AOMQTT guarded control-policy enforcement micro-evaluation",
        "scope": "in-process control path; no live broker or network RTT",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_head": git_value("rev-parse", "HEAD"),
        "git_status_short": git_value("status", "--short"),
        "trials_per_condition": args.trials,
        "conditions": [c.__dict__ for c in CASES],
        "trusted_signature_key_id": TRUSTED_KEY_ID,
        "untrusted_signature_key_id": UNTRUSTED_KEY_ID,
    }

    rows: list[dict[str, Any]] = []
    print("AOMQTT Policy Guard micro-evaluation")
    print("====================================")
    print(f"git: {metadata['git_head']}")
    print(f"Python: {metadata['python']}")
    print(f"trials/condition: {args.trials}")
    print()

    for case in CASES:
        for trial in range(1, args.trials + 1):
            row = run_trial(case, trial, private_key, public_key)
            rows.append(row)
            print(
                f"{case.case_id} r{trial:02d}: "
                f"{row['observed_outcome']:<8} "
                f"reason={row['reason_code']:<38} "
                f"elapsed={row['elapsed_us']:9.3f} us "
                f"PASS"
            )

    summary = summarize(rows)

    trials_csv = out_root / "policy_guard_trials.csv"
    summary_csv = out_root / "policy_guard_summary.csv"
    summary_json = out_root / "policy_guard_summary.json"

    write_csv(trials_csv, rows)
    write_csv(summary_csv, summary)
    summary_json.write_text(
        json.dumps({"metadata": metadata, "summary": summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print("Summary")
    print("-------")
    for item in summary:
        print(
            f"{item['case']}: "
            f"{item['passes']}/{item['trials']} PASS, "
            f"mean={item['elapsed_us_mean']:.3f} us, "
            f"SD={item['elapsed_us_sd']:.3f} us"
        )

    print()
    print(f"artifacts: {out_root}")
    print("POLICY-GUARD-MICRO-EVAL=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
