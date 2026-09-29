import json
import time

from aomqtt import control as control_mod
from aomqtt.control import ControlPolicyMessage, ControlTopicPolicyReceiver
from aomqtt.control_security import PolicySafetyLimits
from aomqtt.policy_guard import PolicyGuard


class DummyPolicy:
    policy_id = "dangerous-policy-001"
    name = "dangerous-policy"


class DummyTopicOffPolicy:
    policy_id = "dangerous-policy-002"
    name = "dangerous-topic-off-policy"


class FakePolicyReporter:
    def __init__(self):
        self.accepted = []
        self.rejected = []
        self.applied = []
        self.failed = []

    def publish_ack_accepted(self, **kwargs):
        self.accepted.append(kwargs)

    def publish_ack_rejected(self, **kwargs):
        self.rejected.append(kwargs)

    def publish_status_applied(self, **kwargs):
        self.applied.append(kwargs)

    def publish_status_failed(self, **kwargs):
        self.failed.append(kwargs)


class FakeMsg:
    topic = "aomqtt/control/test-group/policy"

    def __init__(self, payload: bytes):
        self.payload = payload


def make_receiver():
    receiver = object.__new__(ControlTopicPolicyReceiver)
    receiver.group_id = "test-group"
    receiver.signing_public_key = None
    receiver.require_signature = False
    receiver.allowed_signature_key_ids = None
    receiver._latest_sequence_no = 9
    receiver._latest_policy_id = "safe-policy-001"
    receiver._last_known_good_message = object()
    receiver.safety_limits = PolicySafetyLimits()
    receiver.policy_reporter = FakePolicyReporter()
    receiver.on_event = None
    receiver._policy_guard = PolicyGuard()
    receiver._timers = []
    receiver._lock = None
    return receiver


def test_control_receiver_rejects_payload_encryption_off_policy(monkeypatch):
    receiver = make_receiver()
    original_last_known_good = receiver._last_known_good_message

    def fake_parse(*args, **kwargs):
        return ControlPolicyMessage(
            policy=DummyPolicy(),
            group_id="test-group",
            valid_from=time.time() + 60,
            sequence_no=10,
        )

    monkeypatch.setattr(control_mod, "parse_control_policy_message", fake_parse)

    raw_payload = json.dumps(
        {
            "group_id": "test-group",
            "sequence_no": 10,
            "valid_from": time.time() + 60,
            "policy": {
                "id": "dangerous-policy-001",
                "payload_encryption": {"enabled": False},
            },
        }
    ).encode("utf-8")

    receiver._on_message(None, None, FakeMsg(raw_payload))

    assert receiver.policy_reporter.accepted == []
    assert len(receiver.policy_reporter.rejected) == 1
    assert receiver.policy_reporter.rejected[0]["policy_id"] == "dangerous-policy-001"
    assert receiver.policy_reporter.rejected[0]["sequence_no"] == 10
    assert receiver.policy_reporter.rejected[0]["reason_code"] == "payload_encryption_disable_forbidden"

    assert receiver._latest_sequence_no == 9
    assert receiver._last_known_good_message is original_last_known_good
    assert receiver._timers == []


def test_control_receiver_rejects_topic_obfuscation_off_policy(monkeypatch):
    receiver = make_receiver()
    original_last_known_good = receiver._last_known_good_message

    def fake_parse(*args, **kwargs):
        return ControlPolicyMessage(
            policy=DummyTopicOffPolicy(),
            group_id="test-group",
            valid_from=time.time() + 60,
            sequence_no=10,
        )

    monkeypatch.setattr(control_mod, "parse_control_policy_message", fake_parse)

    raw_payload = json.dumps(
        {
            "group_id": "test-group",
            "sequence_no": 10,
            "valid_from": time.time() + 60,
            "policy": {
                "id": "dangerous-policy-002",
                "topic_obfuscation": {"enabled": False},
            },
        }
    ).encode("utf-8")

    receiver._on_message(None, None, FakeMsg(raw_payload))

    assert receiver.policy_reporter.accepted == []
    assert len(receiver.policy_reporter.rejected) == 1
    assert receiver.policy_reporter.rejected[0]["policy_id"] == "dangerous-policy-002"
    assert receiver.policy_reporter.rejected[0]["sequence_no"] == 10
    assert receiver.policy_reporter.rejected[0]["reason_code"] == "topic_obfuscation_disable_forbidden"

    assert receiver._latest_sequence_no == 9
    assert receiver._last_known_good_message is original_last_known_good
    assert receiver._timers == []
