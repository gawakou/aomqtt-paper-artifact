from aomqtt.krl import build_krl
from aomqtt.policy_trust import (
    build_policy_trust_ack,
    sign_policy_envelope,
    verify_signed_policy_envelope,
)
from aomqtt.signing import LocalEd25519Signer


def test_signed_policy_envelope_is_accepted():
    signer = LocalEd25519Signer.generate("controller-key-2026-001")
    policy = {"id": "p-v110", "sequence_no": 7, "encryption": {"enabled": True}}
    envelope = sign_policy_envelope(policy, signer)

    result = verify_signed_policy_envelope(
        envelope,
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
    )

    assert result.accepted
    assert result.reason_code == "OK"
    assert result.policy_id == "p-v110"
    assert result.sequence_no == 7
    assert result.signer_key_id == "controller-key-2026-001"


def test_unknown_signing_key_is_rejected_with_traceable_metadata():
    signer = LocalEd25519Signer.generate("unknown-controller-key")
    envelope = sign_policy_envelope({"id": "p-unknown", "sequence_no": 8}, signer)

    result = verify_signed_policy_envelope(
        envelope,
        trusted_public_keys={},
    )

    assert not result.accepted
    assert result.reason_code == "UNKNOWN_SIGNING_KEY"
    assert result.policy_id == "p-unknown"
    assert result.sequence_no == 8


def test_revoked_signing_key_is_rejected_before_signature_acceptance():
    signer = LocalEd25519Signer.generate("controller-key-old")
    envelope = sign_policy_envelope({"id": "p-revoked", "sequence_no": 9}, signer)
    krl = build_krl(
        1,
        [
            {
                "key_id": "controller-key-old",
                "revoked_at": "2026-06-06T00:00:00Z",
                "reason": "suspected_compromise",
            }
        ],
    )

    result = verify_signed_policy_envelope(
        envelope,
        trusted_public_keys={"controller-key-old": signer.public_key()},
        krl=krl,
    )

    assert not result.accepted
    assert result.reason_code == "REVOKED_SIGNING_KEY"


def test_tampered_policy_is_rejected():
    signer = LocalEd25519Signer.generate("controller-key-2026-001")
    envelope = sign_policy_envelope({"id": "p-safe", "sequence_no": 10, "padding": {"fixed_size": 512}}, signer)
    envelope["policy"]["padding"]["fixed_size"] = 8192

    result = verify_signed_policy_envelope(
        envelope,
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
    )

    assert not result.accepted
    assert result.reason_code == "POLICY_SIGNATURE_INVALID"
    assert result.policy_id == "p-safe"
    assert result.sequence_no == 10


def test_policy_trust_ack_contains_rejection_reason_and_key_id():
    signer = LocalEd25519Signer.generate("controller-key-old")
    envelope = sign_policy_envelope({"id": "p-ack", "sequence_no": 11}, signer)
    krl = build_krl(1, [{"key_id": "controller-key-old", "revoked_at": "2026-06-06T00:00:00Z"}])
    result = verify_signed_policy_envelope(
        envelope,
        trusted_public_keys={"controller-key-old": signer.public_key()},
        krl=krl,
    )

    ack = build_policy_trust_ack(result, client_id="subscriber-1")

    assert ack["client_id"] == "subscriber-1"
    assert ack["status"] == "rejected"
    assert ack["reason_code"] == "REVOKED_SIGNING_KEY"
    assert ack["policy_id"] == "p-ack"
    assert ack["sequence_no"] == 11
    assert ack["signer_key_id"] == "controller-key-old"
