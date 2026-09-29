from aomqtt.krl import KeyRevocationList, build_krl, check_policy_key_allowed, sign_krl, verify_krl_signature
from aomqtt.signing import LocalEd25519Signer


def test_krl_rejects_revoked_key():
    krl = build_krl(1, [{"key_id": "controller-key-old", "revoked_at": "2026-06-06T00:00:00Z", "reason": "suspected_compromise"}])

    allowed, reason = check_policy_key_allowed("controller-key-old", trusted_key_ids={"controller-key-old", "controller-key-new"}, krl=krl)

    assert not allowed
    assert reason == "REVOKED_SIGNING_KEY"


def test_krl_rejects_unknown_key():
    krl = build_krl(1, [])

    allowed, reason = check_policy_key_allowed("unknown-key", trusted_key_ids={"controller-key-new"}, krl=krl)

    assert not allowed
    assert reason == "UNKNOWN_SIGNING_KEY"


def test_krl_signature_verification():
    signer = LocalEd25519Signer.generate("krl-root-key-001")
    unsigned = build_krl(2, [{"key_id": "controller-key-old", "revoked_at": "2026-06-06T00:00:00Z", "reason": "rotation_complete"}])

    signed = sign_krl(unsigned, signer._private_key, signer_key_id="krl-root-key-001")

    assert verify_krl_signature(signed, signer.public_key())

    tampered = KeyRevocationList.from_dict({
        **signed.to_dict(),
        "revoked_keys": [{"key_id": "controller-key-new", "revoked_at": "2026-06-06T00:00:00Z", "reason": "tampered"}],
    })
    assert not verify_krl_signature(tampered, signer.public_key())
