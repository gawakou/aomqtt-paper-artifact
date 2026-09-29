import json

from aomqtt.control_policy_trust import (
    load_ed25519_public_key_b64,
    normalize_policy_envelope,
    parse_control_policy_payload,
    verify_control_policy_payload,
)
from aomqtt.krl import build_krl
from aomqtt.policy_trust import sign_policy_envelope
from aomqtt.signing import LocalEd25519Signer


def test_control_policy_payload_accepts_signed_json_bytes():
    signer = LocalEd25519Signer.generate("controller-key-2026-001")
    policy = {"id": "p-control-ok", "sequence_no": 21, "encryption": {"enabled": True}}
    envelope = sign_policy_envelope(policy, signer)
    payload = json.dumps(envelope).encode("utf-8")

    evaluation = verify_control_policy_payload(
        payload,
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        client_id="subscriber-1",
    )

    assert evaluation.accepted
    assert evaluation.reason_code == "OK"
    assert evaluation.policy == policy
    assert evaluation.ack["status"] == "accepted"
    assert evaluation.ack["client_id"] == "subscriber-1"


def test_control_policy_payload_rejects_unknown_key_with_policy_metadata():
    signer = LocalEd25519Signer.generate("unknown-key")
    envelope = sign_policy_envelope({"id": "p-unknown-key", "sequence_no": 22}, signer)

    evaluation = verify_control_policy_payload(
        envelope,
        trusted_public_keys={},
        client_id="subscriber-2",
    )

    assert not evaluation.accepted
    assert evaluation.reason_code == "UNKNOWN_SIGNING_KEY"
    assert evaluation.ack["policy_id"] == "p-unknown-key"
    assert evaluation.ack["sequence_no"] == 22
    assert evaluation.ack["signer_key_id"] == "unknown-key"


def test_control_policy_payload_rejects_revoked_key():
    signer = LocalEd25519Signer.generate("controller-key-old")
    envelope = sign_policy_envelope({"id": "p-revoked-key", "sequence_no": 23}, signer)
    krl = build_krl(1, [{"key_id": "controller-key-old", "revoked_at": "2026-06-06T00:00:00Z"}])

    evaluation = verify_control_policy_payload(
        envelope,
        trusted_public_keys={"controller-key-old": signer.public_key()},
        krl=krl,
        client_id="subscriber-3",
    )

    assert not evaluation.accepted
    assert evaluation.reason_code == "REVOKED_SIGNING_KEY"
    assert evaluation.ack["status"] == "rejected"


def test_control_policy_payload_rejects_tampered_policy():
    signer = LocalEd25519Signer.generate("controller-key-2026-001")
    envelope = sign_policy_envelope({"id": "p-tampered", "sequence_no": 24, "padding": {"fixed_size": 512}}, signer)
    envelope["policy"]["padding"]["fixed_size"] = 2048

    evaluation = verify_control_policy_payload(
        envelope,
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        client_id="subscriber-4",
    )

    assert not evaluation.accepted
    assert evaluation.reason_code == "POLICY_SIGNATURE_INVALID"
    assert evaluation.ack["policy_id"] == "p-tampered"
    assert evaluation.ack["sequence_no"] == 24


def test_control_policy_payload_rejects_invalid_json_without_exception():
    evaluation = verify_control_policy_payload(
        b"{not-json",
        trusted_public_keys={},
        client_id="subscriber-5",
    )

    assert not evaluation.accepted
    assert evaluation.reason_code == "INVALID_CONTROL_POLICY_JSON"
    assert evaluation.ack["policy_id"] == "unknown"
    assert evaluation.ack["sequence_no"] == 0


def test_legacy_policy_can_be_wrapped_and_optionally_accepted_for_migration():
    legacy_policy = {"id": "p-legacy", "sequence_no": 25, "rotation": {"enabled": False}}

    assert normalize_policy_envelope(legacy_policy)["policy"] == legacy_policy

    strict = verify_control_policy_payload(
        legacy_policy,
        trusted_public_keys={},
        client_id="subscriber-6",
    )
    assert not strict.accepted
    assert strict.reason_code == "MISSING_SIGNING_KEY"
    assert strict.ack["policy_id"] == "p-legacy"
    assert strict.ack["sequence_no"] == 25

    transitional = verify_control_policy_payload(
        legacy_policy,
        trusted_public_keys={},
        client_id="subscriber-6",
        require_signature=False,
    )
    assert transitional.accepted
    assert transitional.reason_code == "LEGACY_UNSIGNED_POLICY"
    assert transitional.policy == legacy_policy


def test_load_public_key_b64_for_config_style_trusted_keys():
    signer = LocalEd25519Signer.generate("controller-key-2026-001")
    public_key = load_ed25519_public_key_b64(signer.public_key_b64())
    envelope = sign_policy_envelope({"id": "p-b64", "sequence_no": 26}, signer)

    evaluation = verify_control_policy_payload(
        envelope,
        trusted_public_keys={"controller-key-2026-001": public_key},
    )

    assert evaluation.accepted


def test_parse_control_policy_payload_rejects_non_object_json():
    try:
        parse_control_policy_payload("[]")
    except ValueError as exc:
        assert "must be an object" in str(exc)
    else:
        raise AssertionError("expected ValueError")
