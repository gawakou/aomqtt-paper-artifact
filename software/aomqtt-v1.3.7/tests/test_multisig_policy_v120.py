from aomqtt.krl import build_krl
from aomqtt.multisig_policy import (
    build_multisig_policy_ack,
    sign_multisig_policy_envelope,
    verify_multisig_policy_envelope,
)
from aomqtt.signing import LocalEd25519Signer


def _policy(policy_id="policy-v120", sequence_no=1):
    return {
        "id": policy_id,
        "sequence_no": sequence_no,
        "encryption": {"enabled": True},
        "topic_obfuscation": {"enabled": True},
        "padding": {"fixed_size": 512},
    }


def _trusted(signers):
    return {s.key_id: s.public_key() for s in signers}


def test_two_of_three_multisig_policy_is_accepted():
    security = LocalEd25519Signer.generate("security-officer-key")
    controller = LocalEd25519Signer.generate("controller-key")
    auditor = LocalEd25519Signer.generate("auditor-key")
    envelope = sign_multisig_policy_envelope(
        _policy(),
        [security, controller],
        threshold=2,
        signer_roles={security.key_id: "security", controller.key_id: "controller"},
        required_roles=["security", "controller"],
    )

    result = verify_multisig_policy_envelope(
        envelope,
        trusted_public_keys=_trusted([security, controller, auditor]),
    )

    assert result.accepted
    assert result.reason_code == "OK"
    assert result.threshold == 2
    assert result.valid_signature_count == 2
    assert set(result.roles) == {"security", "controller"}


def test_multisig_threshold_not_met_is_rejected():
    signer = LocalEd25519Signer.generate("controller-key")
    envelope = sign_multisig_policy_envelope(_policy(), [signer], threshold=1)
    envelope["signature_policy"]["threshold"] = 2

    result = verify_multisig_policy_envelope(
        envelope,
        trusted_public_keys=_trusted([signer]),
    )

    assert not result.accepted
    assert result.reason_code == "MULTISIG_THRESHOLD_NOT_MET"


def test_unknown_multisig_signer_is_rejected():
    signer = LocalEd25519Signer.generate("unknown-key")
    envelope = sign_multisig_policy_envelope(_policy(), [signer], threshold=1)

    result = verify_multisig_policy_envelope(envelope, trusted_public_keys={})

    assert not result.accepted
    assert result.reason_code == "UNKNOWN_SIGNING_KEY"


def test_revoked_multisig_signer_is_rejected():
    signer = LocalEd25519Signer.generate("revoked-key")
    envelope = sign_multisig_policy_envelope(_policy(), [signer], threshold=1)
    krl = build_krl(
        1,
        [
            {
                "key_id": "revoked-key",
                "revoked_at": "2026-06-06T00:00:00Z",
                "reason": "v1.2.0 test",
            }
        ],
    )

    result = verify_multisig_policy_envelope(
        envelope,
        trusted_public_keys=_trusted([signer]),
        krl=krl,
    )

    assert not result.accepted
    assert result.reason_code == "REVOKED_SIGNING_KEY"


def test_tampered_multisig_policy_is_rejected():
    signer1 = LocalEd25519Signer.generate("signer-1")
    signer2 = LocalEd25519Signer.generate("signer-2")
    envelope = sign_multisig_policy_envelope(_policy(), [signer1, signer2], threshold=2)
    envelope["policy"]["padding"]["fixed_size"] = 8192

    result = verify_multisig_policy_envelope(
        envelope,
        trusted_public_keys=_trusted([signer1, signer2]),
    )

    assert not result.accepted
    assert result.reason_code == "POLICY_SIGNATURE_INVALID"


def test_duplicate_multisig_signer_is_rejected():
    signer = LocalEd25519Signer.generate("controller-key")
    envelope = sign_multisig_policy_envelope(_policy(), [signer], threshold=1)
    envelope["signatures"].append(dict(envelope["signatures"][0]))

    result = verify_multisig_policy_envelope(
        envelope,
        trusted_public_keys=_trusted([signer]),
    )

    assert not result.accepted
    assert result.reason_code == "DUPLICATE_SIGNER"


def test_required_role_missing_is_rejected():
    controller = LocalEd25519Signer.generate("controller-key")
    envelope = sign_multisig_policy_envelope(
        _policy(),
        [controller],
        threshold=1,
        signer_roles={controller.key_id: "controller"},
        required_roles=["controller", "security"],
    )

    result = verify_multisig_policy_envelope(
        envelope,
        trusted_public_keys=_trusted([controller]),
    )

    assert not result.accepted
    assert result.reason_code == "MULTISIG_REQUIRED_ROLE_MISSING"


def test_multisig_ack_contains_threshold_and_signers():
    signer = LocalEd25519Signer.generate("controller-key")
    envelope = sign_multisig_policy_envelope(_policy("p-ack", 7), [signer], threshold=1)
    result = verify_multisig_policy_envelope(envelope, trusted_public_keys=_trusted([signer]))
    ack = build_multisig_policy_ack(result, client_id="subscriber-1")

    assert ack["status"] == "accepted"
    assert ack["policy_id"] == "p-ack"
    assert ack["sequence_no"] == 7
    assert ack["signature_mode"] == "multi-signature"
    assert ack["threshold"] == 1
    assert ack["valid_signature_count"] == 1
    assert ack["signer_key_ids"] == ["controller-key"]
