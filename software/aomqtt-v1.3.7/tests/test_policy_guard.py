from aomqtt.policy_guard import (
    PolicyGuard,
    PolicySafetyLimits,
    PolicyRejectReason,
)


def test_policy_accepts_safe_policy():
    guard = PolicyGuard()
    policy = {
        "sequence_no": 10,
        "token_mode": "whole",
        "payload_encryption": {"enabled": True},
        "topic_obfuscation": {"enabled": True},
        "padding": {"fixed_size": 512},
        "rotation": {"interval_sec": 30, "overlap_sec": 5},
        "valid_from": 1000,
        "valid_until": 1300,
    }

    result = guard.validate(policy, last_sequence_no=9)

    assert result.accepted is True
    assert result.reason_code == "accepted"


def test_policy_rejects_payload_encryption_disabled():
    guard = PolicyGuard()
    policy = {
        "sequence_no": 1,
        "payload_encryption": {"enabled": False},
    }

    result = guard.validate(policy)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.PAYLOAD_ENCRYPTION_DISABLE_FORBIDDEN.value


def test_policy_rejects_topic_obfuscation_disabled():
    guard = PolicyGuard()
    policy = {
        "sequence_no": 1,
        "topic_obfuscation": {"enabled": False},
    }

    result = guard.validate(policy)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.TOPIC_OBFUSCATION_DISABLE_FORBIDDEN.value


def test_policy_rejects_oversized_padding():
    guard = PolicyGuard(PolicySafetyLimits(max_padding_fixed_size=4096))
    policy = {
        "sequence_no": 1,
        "padding": {"fixed_size": 8192},
    }

    result = guard.validate(policy)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.PADDING_LIMIT_EXCEEDED.value


def test_policy_rejects_too_short_rotation_interval():
    guard = PolicyGuard(PolicySafetyLimits(min_rotation_interval_sec=30))
    policy = {
        "sequence_no": 1,
        "rotation": {"interval_sec": 1},
    }

    result = guard.validate(policy)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.ROTATION_INTERVAL_TOO_SHORT.value


def test_policy_rejects_too_large_rotation_overlap():
    guard = PolicyGuard(PolicySafetyLimits(max_rotation_overlap_sec=10))
    policy = {
        "sequence_no": 1,
        "rotation": {"overlap_sec": 30},
    }

    result = guard.validate(policy)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.ROTATION_OVERLAP_TOO_LARGE.value


def test_policy_rejects_too_long_lifetime():
    guard = PolicyGuard(PolicySafetyLimits(max_policy_lifetime_sec=3600))
    policy = {
        "sequence_no": 1,
        "valid_from": 1000,
        "valid_until": 1000 + 7200,
    }

    result = guard.validate(policy)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.POLICY_LIFETIME_TOO_LONG.value


def test_policy_rejects_untrusted_key_id_when_trust_store_is_set():
    guard = PolicyGuard(PolicySafetyLimits(trusted_key_ids={"policy-key-1"}))
    policy = {
        "sequence_no": 1,
        "key_id": "attacker-key",
    }

    result = guard.validate(policy)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.UNKNOWN_KEY_ID.value


def test_policy_rejects_replayed_sequence():
    guard = PolicyGuard()
    policy = {
        "sequence_no": 10,
    }

    result = guard.validate(policy, last_sequence_no=10)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.REPLAYED_SEQUENCE.value


def test_policy_rejects_disallowed_token_mode():
    guard = PolicyGuard(PolicySafetyLimits(allowed_token_modes={"whole", "hierarchical"}))
    policy = {
        "sequence_no": 1,
        "token_mode": "plain",
    }

    result = guard.validate(policy)

    assert result.accepted is False
    assert result.reason_code == PolicyRejectReason.TOKEN_MODE_NOT_ALLOWED.value
