from __future__ import annotations

import json
from aomqtt import AOMQTTConfig, AOMQTTPublisher, AOMQTTSubscriber, AOMQTTPolicy
from tests.test_transport_observation import FakeTransport
from aomqtt.control import build_control_policy_message, control_policy_topic, parse_control_policy_message


def base_config() -> AOMQTTConfig:
    return AOMQTTConfig(
        topic_key="replace-this-topic-key-32chars",
        payload_key="replace-this-payload-key-32chars",
        token_mode="hierarchical",
        mqtt_qos=0,
        rotation_enabled=False,
        padding_enabled=False,
        padding_mode="none",
    )


def test_control_policy_message_roundtrip() -> None:
    policy = AOMQTTPolicy(
        policy_id="p_runtime_bucket",
        name="runtime_bucket",
        token_mode="whole",
        mqtt_qos=1,
        rotation_enabled=True,
        rotation_interval_sec=10,
        rotation_overlap_sec=3,
        padding_enabled=True,
        padding_mode="bucket",
        padding_bucket_size=256,
    )
    msg = build_control_policy_message(policy, group_id="g1", valid_after_sec=1, grace_period_sec=2)
    parsed = parse_control_policy_message(msg.to_json_bytes(), source_topic=control_policy_topic("g1"))
    assert parsed.group_id == "g1"
    assert parsed.policy_id == "p_runtime_bucket"
    assert parsed.policy_name == "runtime_bucket"
    assert parsed.policy.token_mode == "whole"
    assert parsed.policy.padding_mode == "bucket"
    assert parsed.policy.padding_bucket_size == 256
    assert parsed.grace_period_sec == 2


def test_control_policy_topic_default() -> None:
    assert control_policy_topic("siteA") == "aomqtt/control/siteA/policy"
    assert control_policy_topic("/siteA/") == "aomqtt/control/siteA/policy"


def test_parse_nested_control_message() -> None:
    payload = {
        "schema_version": "aomqtt-policy-v1",
        "group_id": "siteA",
        "valid_from": 12345.0,
        "policy": {
            "id": "p1",
            "name": "whole_bucket",
            "token_mode": "whole",
            "qos": 1,
            "rotation": {"enabled": True, "interval_sec": 30, "overlap_sec": 5},
            "padding": {"enabled": True, "mode": "bucket", "bucket_size": 256},
        },
    }
    parsed = parse_control_policy_message(json.dumps(payload))
    assert parsed.valid_from == 12345.0
    assert parsed.policy.policy_id == "p1"
    assert parsed.policy.mqtt_qos == 1
    assert parsed.policy.rotation_enabled is True


def test_publisher_apply_control_policy_updates_runtime_config() -> None:
    pub = AOMQTTPublisher(broker_host="localhost", client_id="p", config=base_config(), transport=FakeTransport())
    policy = AOMQTTPolicy(
        policy_id="p_whole_fixed",
        name="whole_fixed",
        token_mode="whole",
        mqtt_qos=1,
        rotation_enabled=True,
        rotation_interval_sec=10,
        rotation_overlap_sec=3,
        padding_enabled=True,
        padding_mode="fixed",
        padding_fixed_size=512,
    )
    pub.apply_policy(policy)
    assert pub.config.policy_id == "p_whole_fixed"
    assert pub.config.token_mode == "whole"
    assert pub.config.mqtt_qos == 1
    assert pub.config.rotation_enabled is True
    assert pub.config.padding_mode == "fixed"


def test_subscriber_apply_policy_prepares_new_subscription_filters(monkeypatch) -> None:
    sub = AOMQTTSubscriber(broker_host="localhost", client_id="s", config=base_config(), transport=FakeTransport())
    calls: list[tuple[str, int]] = []

    def fake_subscribe(topic_filter: str, qos: int = 0):
        calls.append((topic_filter, qos))
        return (0, 1)

    monkeypatch.setattr(sub.transport, "subscribe", fake_subscribe)
    sub._plaintext_subscriptions["shelter/siteA/starlink/rtt"] = 1
    policy = AOMQTTPolicy(
        policy_id="p_whole_rotation",
        name="whole_rotation",
        token_mode="whole",
        mqtt_qos=1,
        rotation_enabled=True,
        rotation_interval_sec=10,
        rotation_overlap_sec=3,
    )
    sub.apply_policy(policy)
    try:
        assert sub.config.policy_id == "p_whole_rotation"
        assert calls
        assert all(topic.startswith("aomqtt/v1/t/") for topic, _ in calls)
        assert sub._refresh_thread is not None
        assert sub._refresh_thread.is_alive()
    finally:
        sub.stop_subscription_refresh()
