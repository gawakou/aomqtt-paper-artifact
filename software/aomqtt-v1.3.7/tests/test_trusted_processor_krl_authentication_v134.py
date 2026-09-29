"""v1.3.4: KRL authentication and anti-rollback wiring tests."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aomqtt.krl import KRLValidationError, build_krl, sign_krl, verify_and_load_krl
from aomqtt.policy_trust import sign_policy_envelope
from aomqtt.signing import LocalEd25519Signer
from aomqtt.trusted_control_processor import TrustedControlPolicyProcessor


def _krl_authority():
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def _revoke(version, key_id="bad-key"):
    return build_krl(
        version,
        [
            {
                "key_id": key_id,
                "revoked_at": "2026-06-06T00:00:00Z",
                "reason": "test",
            }
        ],
    )


def _signed_policy_envelope(signer, policy_id="p1", sequence_no=1):
    return sign_policy_envelope(
        {
            "id": policy_id,
            "sequence_no": sequence_no,
            "encryption": {"enabled": True},
        },
        signer,
    )


def test_verify_and_load_krl_accepts_signed_newer_krl():
    private_key, public_key = _krl_authority()
    loaded = verify_and_load_krl(
        sign_krl(_revoke(2), private_key, "krl-key").to_dict(),
        public_key,
        min_version=1,
    )
    assert loaded.krl_version == 2
    assert loaded.is_revoked("bad-key")


def test_verify_and_load_krl_rejects_unsigned_krl():
    private_key, public_key = _krl_authority()
    signed = sign_krl(_revoke(2), private_key, "krl-key")
    with pytest.raises(KRLValidationError):
        verify_and_load_krl(signed.to_dict(include_signature=False), public_key, min_version=1)


def test_verify_and_load_krl_rejects_wrong_authority():
    private_key, _ = _krl_authority()
    _, other_public_key = _krl_authority()
    with pytest.raises(KRLValidationError):
        verify_and_load_krl(
            sign_krl(_revoke(2), private_key, "krl-key").to_dict(),
            other_public_key,
            min_version=1,
        )


def test_verify_and_load_krl_rejects_rollback():
    private_key, public_key = _krl_authority()
    with pytest.raises(KRLValidationError):
        verify_and_load_krl(
            sign_krl(_revoke(2), private_key, "krl-key").to_dict(),
            public_key,
            min_version=2,
        )


def test_processor_loads_signed_krl_and_tracks_version():
    private_key, public_key = _krl_authority()
    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={},
        krl=sign_krl(_revoke(3), private_key, "krl-key").to_dict(),
        krl_public_key=public_key,
    )
    assert processor.krl is not None
    assert processor.krl_version == 3
    assert processor.krl.is_revoked("bad-key")


def test_processor_rejects_unverified_mapping_without_public_key():
    private_key, _ = _krl_authority()
    signed_dict = sign_krl(_revoke(1), private_key, "krl-key").to_dict()
    with pytest.raises(KRLValidationError):
        TrustedControlPolicyProcessor(trusted_public_keys={}, krl=signed_dict)


def test_processor_rejects_tampered_initial_krl():
    private_key, public_key = _krl_authority()
    forged = sign_krl(_revoke(2), private_key, "krl-key").to_dict()
    forged["revoked_keys"] = []
    with pytest.raises(KRLValidationError):
        TrustedControlPolicyProcessor(
            trusted_public_keys={},
            krl=forged,
            krl_public_key=public_key,
        )


def test_update_krl_accepts_newer_and_rejects_rollback():
    private_key, public_key = _krl_authority()
    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={},
        krl=sign_krl(_revoke(2), private_key, "krl-key").to_dict(),
        krl_public_key=public_key,
    )
    assert processor.krl_version == 2

    processor.update_krl(sign_krl(_revoke(5, "other-bad"), private_key, "krl-key").to_dict())
    assert processor.krl_version == 5
    assert processor.krl.is_revoked("other-bad")

    with pytest.raises(KRLValidationError):
        processor.update_krl(sign_krl(_revoke(2), private_key, "krl-key").to_dict())
    assert processor.krl_version == 5


def test_update_krl_requires_public_key():
    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={},
        krl=_revoke(4),
    )
    assert processor.krl_version == 4
    with pytest.raises(KRLValidationError):
        processor.update_krl(_revoke(5))


def test_processor_blocks_policy_signed_by_revoked_key():
    private_key, public_key = _krl_authority()
    signer = LocalEd25519Signer.generate("bad-key")
    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={"bad-key": signer.public_key()},
        krl=sign_krl(_revoke(1, "bad-key"), private_key, "krl-key").to_dict(),
        krl_public_key=public_key,
    )

    result = processor.process_payload(_signed_policy_envelope(signer))

    assert not result.accepted
    assert result.reason_code == "REVOKED_SIGNING_KEY"
