from aomqtt.krl import build_krl
from aomqtt.policy_trust import sign_policy_envelope
from aomqtt.signing import LocalEd25519Signer
from aomqtt.trusted_control_processor import (
    TrustedControlPolicyProcessor,
    _guard_result_to_rejection_reason,
    load_trusted_public_keys_b64,
)


def _signed_policy(policy=None, key_id="controller-key-2026-001"):
    signer = LocalEd25519Signer.generate(key_id)
    policy = policy or {"id": "p-processor", "sequence_no": 1, "encryption": {"enabled": True}}
    return signer, sign_policy_envelope(policy, signer)


def test_processor_accepts_signed_policy_and_publishes_ack():
    signer, envelope = _signed_policy()
    published = []
    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        client_id="subscriber-processor",
        ack_publisher=published.append,
    )

    result = processor.process_payload(envelope)

    assert result.accepted
    assert result.stage == "accepted"
    assert result.reason_code == "OK"
    assert result.ack["status"] == "accepted"
    assert published == [result.ack]
    assert len(processor.records) == 1


def test_processor_blocks_unknown_key_before_policy_guard_is_called():
    signer, envelope = _signed_policy(key_id="unknown-key")
    called = {"guard": False}

    def guard(policy):
        called["guard"] = True
        return None

    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={},
        client_id="subscriber-processor",
        policy_validator=guard,
    )

    result = processor.process_payload(envelope)

    assert not result.accepted
    assert result.stage == "trust"
    assert result.reason_code == "UNKNOWN_SIGNING_KEY"
    assert called["guard"] is False
    assert result.ack["status"] == "rejected"
    assert result.ack["signer_key_id"] == "unknown-key"


def test_processor_blocks_revoked_key_before_policy_guard_is_called():
    signer, envelope = _signed_policy(key_id="controller-key-old")
    krl = build_krl(1, [{"key_id": "controller-key-old", "revoked_at": "2026-06-06T00:00:00Z"}])
    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={"controller-key-old": signer.public_key()},
        krl=krl,
    )

    result = processor.process_payload(envelope)

    assert not result.accepted
    assert result.reason_code == "REVOKED_SIGNING_KEY"
    assert result.stage == "trust"


def test_processor_converts_policy_guard_rejection_to_final_rejected_ack():
    policy = {"id": "p-unsafe", "sequence_no": 7, "padding": {"fixed_size": 999999}}
    signer, envelope = _signed_policy(policy=policy)

    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        policy_validator=lambda p: {"accepted": False, "reason_code": "PADDING_TOO_LARGE"},
    )

    result = processor.process_payload(envelope)

    assert not result.accepted
    assert result.stage == "policy_guard"
    assert result.reason_code == "PADDING_TOO_LARGE"
    assert result.ack["status"] == "rejected"
    assert result.ack["policy_id"] == "p-unsafe"
    assert result.ack["sequence_no"] == 7


def test_processor_maps_policy_guard_exception_to_rejected_ack():
    signer, envelope = _signed_policy()

    def broken_guard(policy):
        raise RuntimeError("guard failed")

    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        policy_validator=broken_guard,
    )

    result = processor.process_payload(envelope)

    assert not result.accepted
    assert result.stage == "policy_guard"
    assert result.reason_code == "POLICY_GUARD_EXCEPTION:RuntimeError"
    assert result.ack["status"] == "rejected"


def test_processor_detects_anomalies_from_recorded_acks(tmp_path):
    signer, envelope = _signed_policy(key_id="controller-key-old")
    krl = build_krl(1, [{"key_id": "controller-key-old", "revoked_at": "2026-06-06T00:00:00Z"}])
    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={"controller-key-old": signer.public_key()},
        krl=krl,
    )

    processor.process_payload(envelope)
    anomalies = processor.detect_anomalies()

    assert any(a.reason_code == "REVOKED_SIGNING_KEY" for a in anomalies)
    csv_path, json_path = processor.write_anomaly_reports(tmp_path)
    assert csv_path.exists()
    assert json_path.exists()


def test_load_trusted_public_keys_b64_for_processor_config():
    signer, envelope = _signed_policy()
    keys = load_trusted_public_keys_b64({"controller-key-2026-001": signer.public_key_b64()})
    processor = TrustedControlPolicyProcessor(trusted_public_keys=keys)

    assert processor.process_payload(envelope).accepted


def test_guard_result_normalization_variants():
    assert _guard_result_to_rejection_reason(None) is None
    assert _guard_result_to_rejection_reason(True) is None
    assert _guard_result_to_rejection_reason("OK") is None
    assert _guard_result_to_rejection_reason(False) == "POLICY_GUARD_REJECTED"
    assert _guard_result_to_rejection_reason("ENCRYPTION_DISABLED") == "ENCRYPTION_DISABLED"
    assert _guard_result_to_rejection_reason((False, "ROTATION_INTERVAL_TOO_SHORT")) == "ROTATION_INTERVAL_TOO_SHORT"
    assert _guard_result_to_rejection_reason({"accepted": False, "reason_code": "TOPIC_OBFUSCATION_DISABLED"}) == "TOPIC_OBFUSCATION_DISABLED"
