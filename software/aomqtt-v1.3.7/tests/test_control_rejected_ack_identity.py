import json

from aomqtt import AOMQTTPolicy
from aomqtt.control import (
    ControlTopicPolicyReceiver,
    build_control_policy_message,
    extract_control_policy_identity_from_payload,
)


def test_extract_control_policy_identity_from_payload():
    payload = json.dumps(
        {
            "policy": {"id": "p_whole_bucket_rotation"},
            "sequence_no": 100,
        }
    ).encode("utf-8")

    policy_id, sequence_no = extract_control_policy_identity_from_payload(payload)

    assert policy_id == "p_whole_bucket_rotation"
    assert sequence_no == 100


def test_extract_control_policy_identity_from_malformed_payload():
    policy_id, sequence_no = extract_control_policy_identity_from_payload(b"{bad json")

    assert policy_id == "unknown"
    assert sequence_no == 0


def test_rejected_ack_includes_policy_identity_on_replay(monkeypatch):
    import aomqtt.control as control_module

    class FakeClient:
        def __init__(self):
            self.published = []

        def username_pw_set(self, *args, **kwargs):
            pass

        def tls_set(self, *args, **kwargs):
            pass

        def subscribe(self, *args, **kwargs):
            pass

        def publish(self, topic, payload=None, qos=0, retain=False):
            self.published.append(
                {
                    "topic": topic,
                    "payload": payload,
                    "qos": qos,
                    "retain": retain,
                }
            )

    fake_client = FakeClient()
    monkeypatch.setattr(control_module, "_make_paho_client", lambda client_id: fake_client)

    receiver = ControlTopicPolicyReceiver(
        broker_host="localhost",
        client_id="test_receiver",
        group_id="shelter-siteA",
        apply_callback=lambda policy, message: None,
        require_signature=False,
    )

    receiver._latest_sequence_no = 100

    message = build_control_policy_message(
        AOMQTTPolicy(
            policy_id="p_whole_bucket_rotation",
            name="whole_bucket_rotation",
            token_mode="whole",
            mqtt_qos=1,
        ),
        group_id="shelter-siteA",
        sequence_no=100,
        expires_after_sec=3600,
    )

    class Msg:
        topic = "aomqtt/control/shelter-siteA/policy"
        payload = message.to_json_bytes()

    receiver._on_message(None, None, Msg())

    assert len(fake_client.published) == 1

    item = fake_client.published[0]
    assert item["topic"] == "aomqtt/control/shelter-siteA/ack"

    payload = json.loads(item["payload"].decode("utf-8"))

    assert payload["status"] == "rejected"
    assert payload["policy_id"] == "p_whole_bucket_rotation"
    assert payload["sequence_no"] == 100
    assert "sequence_no" in payload["reason"]
    assert payload["reason_code"] == "stale_sequence_no"
