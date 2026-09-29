from __future__ import annotations

import time

import pytest

from aomqtt import AOMQTTPolicy
from aomqtt.control import build_control_policy_message, parse_control_policy_message
from aomqtt.control_security import (
    PolicySafetyLimits,
    classify_policy_rejection,
    generate_keypair,
    sign_control_message_dict,
    verify_control_message_dict,
)
from aomqtt.exceptions import AOMQTTConfigurationError


def test_signed_control_policy_roundtrip_and_verification():
    private_key, public_key = generate_keypair()
    policy = AOMQTTPolicy(
        policy_id="p_signed_bucket",
        name="signed_bucket",
        token_mode="whole",
        mqtt_qos=1,
        rotation_enabled=True,
        rotation_interval_sec=30,
        rotation_overlap_sec=5,
        padding_enabled=True,
        padding_mode="bucket",
        padding_bucket_size=256,
    )
    message = build_control_policy_message(
        policy,
        group_id="g1",
        valid_after_sec=1,
        sequence_no=10,
        expires_after_sec=3600,
        signing_private_key=private_key,
    )
    parsed = parse_control_policy_message(
        message.to_json_bytes(),
        signing_public_key=public_key,
        require_signature=True,
    )
    assert parsed.policy_id == "p_signed_bucket"
    assert parsed.sequence_no == 10
    assert parsed.signature is not None


def test_tampered_signed_policy_is_rejected():
    private_key, public_key = generate_keypair()
    message = build_control_policy_message(
        AOMQTTPolicy(policy_id="p1", name="p1", token_mode="whole", mqtt_qos=1),
        group_id="g1",
        sequence_no=1,
        expires_after_sec=3600,
        signing_private_key=private_key,
    )
    data = message.to_dict()
    data["policy"] = dict(data["policy"])
    data["policy"]["token_mode"] = "hierarchical"
    with pytest.raises(AOMQTTConfigurationError, match="signature verification failed"):
        parse_control_policy_message(
            __import__("json").dumps(data).encode(),
            signing_public_key=public_key,
            require_signature=True,
        )


def test_unsigned_policy_rejected_when_signature_required():
    message = build_control_policy_message(
        AOMQTTPolicy(policy_id="p1", name="p1", token_mode="whole", mqtt_qos=1),
        group_id="g1",
        sequence_no=1,
        expires_after_sec=3600,
    )
    _private, public_key = generate_keypair()
    with pytest.raises(AOMQTTConfigurationError, match="signature is required"):
        parse_control_policy_message(
            message.to_json_bytes(),
            signing_public_key=public_key,
            require_signature=True,
        )


def test_replayed_sequence_number_is_rejected():
    private_key, public_key = generate_keypair()
    message = build_control_policy_message(
        AOMQTTPolicy(policy_id="p1", name="p1", token_mode="whole", mqtt_qos=1),
        group_id="g1",
        sequence_no=5,
        expires_after_sec=3600,
        signing_private_key=private_key,
    )
    with pytest.raises(AOMQTTConfigurationError, match="not newer"):
        parse_control_policy_message(
            message.to_json_bytes(),
            signing_public_key=public_key,
            require_signature=True,
            latest_sequence_no=5,
        )


def test_expired_control_policy_is_rejected():
    private_key, public_key = generate_keypair()
    message = build_control_policy_message(
        AOMQTTPolicy(policy_id="p1", name="p1", token_mode="whole", mqtt_qos=1),
        group_id="g1",
        sequence_no=1,
        expires_at=time.time() - 1,
        signing_private_key=private_key,
    )
    with pytest.raises(AOMQTTConfigurationError, match="expired"):
        parse_control_policy_message(
            message.to_json_bytes(),
            signing_public_key=public_key,
            require_signature=True,
        )


def test_policy_safety_limits_reject_oversized_fixed_padding():
    private_key, public_key = generate_keypair()
    policy = AOMQTTPolicy(
        policy_id="p_bad_fixed",
        name="bad_fixed",
        token_mode="whole",
        mqtt_qos=1,
        padding_enabled=True,
        padding_mode="fixed",
        padding_fixed_size=65536,
    )
    message = build_control_policy_message(
        policy,
        group_id="g1",
        sequence_no=1,
        expires_after_sec=3600,
        signing_private_key=private_key,
    )
    with pytest.raises(AOMQTTConfigurationError, match="fixed_size"):
        parse_control_policy_message(
            message.to_json_bytes(),
            signing_public_key=public_key,
            require_signature=True,
            safety_limits=PolicySafetyLimits(max_padding_fixed_size=4096),
        )


def test_control_receiver_rejects_expected_policy_errors_without_traceback(caplog, monkeypatch):
    _private_key, public_key = generate_keypair()
    control_module = __import__("aomqtt.control", fromlist=["ControlTopicPolicyReceiver"])

    class FakeClient:
        def username_pw_set(self, *args, **kwargs):
            pass
        def tls_set(self, *args, **kwargs):
            pass
        def subscribe(self, *args, **kwargs):
            pass

    monkeypatch.setattr(control_module, "_make_paho_client", lambda client_id: FakeClient())
    receiver = control_module.ControlTopicPolicyReceiver(
        broker_host="localhost",
        client_id="test_receiver",
        group_id="g1",
        apply_callback=lambda policy, message: None,
        signing_public_key=public_key,
        require_signature=True,
    )
    message = build_control_policy_message(
        AOMQTTPolicy(policy_id="p_unsigned", name="unsigned", token_mode="whole", mqtt_qos=1),
        group_id="g1",
        sequence_no=1,
        expires_after_sec=3600,
    )

    class Msg:
        topic = "aomqtt/control/g1/policy"
        payload = message.to_json_bytes()

    with caplog.at_level("WARNING", logger="aomqtt.control"):
        receiver._on_message(None, None, Msg())

    assert "rejected control policy" in caplog.text
    assert "signature is required" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_classify_policy_rejection_reason_codes():
    assert classify_policy_rejection("control policy has expired") == "expired_policy"
    assert classify_policy_rejection("control policy signature verification failed") == "invalid_signature"
    assert classify_policy_rejection("control policy sequence_no is not newer than the latest accepted policy") == "stale_sequence_no"
    assert classify_policy_rejection("policy.padding.fixed_size must be <= 4096") == "unsafe_policy"
    assert classify_policy_rejection("unknown control policy signature key_id: old-key") == "unknown_key_id"
    assert classify_policy_rejection("malformed JSON") == "invalid_policy"


def test_unknown_signature_key_id_is_rejected():
    private_key, public_key = generate_keypair()
    message = build_control_policy_message(
        AOMQTTPolicy(policy_id="p1", name="p1", token_mode="whole", mqtt_qos=1),
        group_id="g1",
        sequence_no=1,
        expires_after_sec=3600,
        signing_private_key=private_key,
        signing_key_id="old-key",
    )

    with pytest.raises(AOMQTTConfigurationError, match="unknown control policy signature key_id"):
        parse_control_policy_message(
            message.to_json_bytes(),
            signing_public_key=public_key,
            require_signature=True,
            allowed_signature_key_ids={"new-key"},
        )
