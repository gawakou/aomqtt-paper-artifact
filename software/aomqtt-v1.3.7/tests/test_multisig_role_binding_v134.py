"""v1.3.4: multisig role binding regression tests.

The verifier must not trust the unsigned role label inside each signature block.
Roles that satisfy required_roles must come from signature_policy["signer_roles"],
which is part of the signed multisig payload.
"""

from copy import deepcopy

from aomqtt.multisig_policy import (
    sign_multisig_policy_envelope,
    verify_multisig_policy_envelope,
)
from aomqtt.signing import LocalEd25519Signer


def _policy():
    return {
        "id": "p-role-binding",
        "sequence_no": 1,
        "encryption": {"enabled": True},
    }


def test_multisig_rejects_forged_unsigned_role_label():
    signer1 = LocalEd25519Signer.generate("ops-1")
    signer2 = LocalEd25519Signer.generate("ops-2")
    trusted = {
        signer1.key_id: signer1.public_key(),
        signer2.key_id: signer2.public_key(),
    }

    envelope = sign_multisig_policy_envelope(
        _policy(),
        [signer1, signer2],
        threshold=2,
        signer_roles={
            signer1.key_id: "ops",
            signer2.key_id: "ops",
        },
        required_roles=["security_officer"],
    )

    honest = verify_multisig_policy_envelope(envelope, trusted_public_keys=trusted)
    assert not honest.accepted
    assert honest.reason_code == "MULTISIG_REQUIRED_ROLE_MISSING"

    forged = deepcopy(envelope)
    forged["signatures"][1]["role"] = "security_officer"

    result = verify_multisig_policy_envelope(forged, trusted_public_keys=trusted)
    assert not result.accepted
    assert result.reason_code == "MULTISIG_REQUIRED_ROLE_MISSING"


def test_multisig_rejects_tampered_signed_signer_roles_map():
    signer1 = LocalEd25519Signer.generate("ops-1")
    signer2 = LocalEd25519Signer.generate("ops-2")
    trusted = {
        signer1.key_id: signer1.public_key(),
        signer2.key_id: signer2.public_key(),
    }

    envelope = sign_multisig_policy_envelope(
        _policy(),
        [signer1, signer2],
        threshold=2,
        signer_roles={
            signer1.key_id: "ops",
            signer2.key_id: "ops",
        },
        required_roles=["security_officer"],
    )

    tampered = deepcopy(envelope)
    tampered["signature_policy"]["signer_roles"][signer2.key_id] = "security_officer"

    result = verify_multisig_policy_envelope(tampered, trusted_public_keys=trusted)
    assert not result.accepted
    assert result.reason_code == "POLICY_SIGNATURE_INVALID"


def test_multisig_accepts_required_role_when_signed_role_map_has_it():
    signer1 = LocalEd25519Signer.generate("ops-1")
    signer2 = LocalEd25519Signer.generate("sec-1")
    trusted = {
        signer1.key_id: signer1.public_key(),
        signer2.key_id: signer2.public_key(),
    }

    envelope = sign_multisig_policy_envelope(
        _policy(),
        [signer1, signer2],
        threshold=2,
        signer_roles={
            signer1.key_id: "ops",
            signer2.key_id: "security_officer",
        },
        required_roles=["security_officer"],
    )

    result = verify_multisig_policy_envelope(envelope, trusted_public_keys=trusted)
    assert result.accepted
    assert result.reason_code == "OK"
    assert "security_officer" in result.roles
