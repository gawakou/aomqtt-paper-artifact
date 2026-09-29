import json

from aomqtt.control_plane.client_reporter import PolicyAckStatusReporter


class FakeMQTTClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )


def decode_payload(payload):
    return json.loads(payload.decode("utf-8"))


def test_publish_ack_accepted():
    mqtt = FakeMQTTClient()
    reporter = PolicyAckStatusReporter(
        mqtt_client=mqtt,
        group_id="g1",
        client_id="c_sub_001",
        role="subscriber",
        qos=1,
    )

    reporter.publish_ack_accepted(
        policy_id="p1",
        sequence_no=12,
        received_at=100.0,
        will_apply_at=110.0,
    )

    assert len(mqtt.published) == 1
    item = mqtt.published[0]

    assert item["topic"] == "aomqtt/control/g1/ack"
    assert item["qos"] == 1
    assert item["retain"] is False

    payload = decode_payload(item["payload"])
    assert payload["client_id"] == "c_sub_001"
    assert payload["role"] == "subscriber"
    assert payload["policy_id"] == "p1"
    assert payload["sequence_no"] == 12
    assert payload["status"] == "accepted"
    assert payload["received_at"] == 100.0
    assert payload["will_apply_at"] == 110.0


def test_publish_ack_rejected():
    mqtt = FakeMQTTClient()
    reporter = PolicyAckStatusReporter(
        mqtt_client=mqtt,
        group_id="g1",
        client_id="c_sub_001",
        role="subscriber",
    )

    reporter.publish_ack_rejected(
        policy_id="p1",
        sequence_no=12,
        received_at=100.0,
        reason="invalid policy",
    )

    item = mqtt.published[0]
    assert item["topic"] == "aomqtt/control/g1/ack"

    payload = decode_payload(item["payload"])
    assert payload["status"] == "rejected"
    assert payload["reason"] == "invalid policy"
    assert payload["reason_code"] == "invalid_policy"


def test_publish_status_applied():
    mqtt = FakeMQTTClient()
    reporter = PolicyAckStatusReporter(
        mqtt_client=mqtt,
        group_id="g1",
        client_id="c_pub_001",
        role="publisher",
    )

    reporter.publish_status_applied(
        policy_id="p1",
        sequence_no=12,
        event_time=120.0,
    )

    item = mqtt.published[0]
    assert item["topic"] == "aomqtt/control/g1/status"

    payload = decode_payload(item["payload"])
    assert payload["status"] == "applied"
    assert payload["applied_at"] == 120.0


def test_publish_status_failed():
    mqtt = FakeMQTTClient()
    reporter = PolicyAckStatusReporter(
        mqtt_client=mqtt,
        group_id="g1",
        client_id="c_pub_001",
        role="publisher",
    )

    reporter.publish_status_failed(
        policy_id="p1",
        sequence_no=12,
        event_time=120.0,
        reason="apply failed",
    )

    item = mqtt.published[0]
    assert item["topic"] == "aomqtt/control/g1/status"

    payload = decode_payload(item["payload"])
    assert payload["status"] == "failed"
    assert payload["failed_at"] == 120.0
    assert payload["reason"] == "apply failed"


def test_publish_ack_rejected_with_explicit_reason_code():
    mqtt = FakeMQTTClient()
    reporter = PolicyAckStatusReporter(
        mqtt_client=mqtt,
        group_id="g1",
        client_id="c_sub_001",
        role="subscriber",
    )

    reporter.publish_ack_rejected(
        policy_id="p1",
        sequence_no=12,
        received_at=100.0,
        reason="control policy has expired",
        reason_code="expired_policy",
    )

    payload = decode_payload(mqtt.published[0]["payload"])

    assert payload["status"] == "rejected"
    assert payload["reason"] == "control policy has expired"
    assert payload["reason_code"] == "expired_policy"
