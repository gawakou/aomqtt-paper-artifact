from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .krl import KeyRevocationList, check_policy_key_allowed
from .signing import PolicySigner, canonical_json_bytes, verify_ed25519_signature


@dataclass(frozen=True)
class PolicyTrustResult:
    accepted: bool
    reason_code: str
    policy_id: str
    sequence_no: int
    signer_key_id: str
    algorithm: str
    signing_method: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def extract_policy_metadata(policy: Mapping[str, Any]) -> tuple[str, int]:
    """Extract policy.id and sequence_no without requiring a concrete policy class."""
    policy_id = str(policy.get("id") or policy.get("policy_id") or "unknown")
    try:
        sequence_no = int(policy.get("sequence_no", 0))
    except (TypeError, ValueError):
        sequence_no = 0
    return policy_id, sequence_no


def _signature_block(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    # Preferred v1.1.0 shape:
    #   {"policy": {...}, "signature": {"key_id": ..., "signature": ...}}
    # Compatibility shape:
    #   {"policy": {...}, "key_id": ..., "signature": ...}
    sig = envelope.get("signature")
    if isinstance(sig, Mapping):
        return sig
    return envelope


def policy_signing_payload(policy: Mapping[str, Any]) -> bytes:
    """Canonical bytes that v1.1.0 signs and verifies."""
    return canonical_json_bytes({"policy": dict(policy)})


def sign_policy_envelope(policy: Mapping[str, Any], signer: PolicySigner) -> Dict[str, Any]:
    """Return a signed policy envelope with signer metadata.

    The Controller can use this helper with a local signer, remote signer, KMS,
    or HSM-backed signer without changing the policy payload format.
    """
    signature = signer.sign(policy_signing_payload(policy))
    return {
        "policy": dict(policy),
        "signature": signature.to_dict(),
    }


def verify_signed_policy_envelope(
    envelope: Mapping[str, Any],
    *,
    trusted_public_keys: Mapping[str, Ed25519PublicKey],
    krl: Optional[KeyRevocationList] = None,
) -> PolicyTrustResult:
    """Validate a signed policy envelope.

    Validation order is intentionally conservative:
      1. extract policy_id / sequence_no for traceable rejection ACKs
      2. require signer key metadata
      3. reject unknown or revoked keys
      4. verify the Ed25519 signature over canonical policy bytes
    """
    policy = _as_mapping(envelope.get("policy"))
    policy_id, sequence_no = extract_policy_metadata(policy)
    sig = _signature_block(envelope)

    signer_key_id = str(sig.get("key_id") or sig.get("signer_key_id") or "")
    algorithm = str(sig.get("algorithm") or "")
    signing_method = str(sig.get("signing_method") or "")
    signature = sig.get("signature")

    def reject(reason: str) -> PolicyTrustResult:
        return PolicyTrustResult(
            accepted=False,
            reason_code=reason,
            policy_id=policy_id,
            sequence_no=sequence_no,
            signer_key_id=signer_key_id or "unknown",
            algorithm=algorithm or "unknown",
            signing_method=signing_method or "unknown",
        )

    allowed, reason = check_policy_key_allowed(
        signer_key_id,
        trusted_key_ids=trusted_public_keys.keys(),
        krl=krl,
    )
    if not allowed:
        return reject(reason)

    if algorithm != "Ed25519":
        return reject("UNSUPPORTED_SIGNATURE_ALGORITHM")
    if not isinstance(signature, str) or not signature:
        return reject("MISSING_SIGNATURE")

    public_key = trusted_public_keys.get(signer_key_id)
    if public_key is None:
        return reject("UNKNOWN_SIGNING_KEY")

    if not verify_ed25519_signature(public_key, policy_signing_payload(policy), signature):
        return reject("POLICY_SIGNATURE_INVALID")

    return PolicyTrustResult(
        accepted=True,
        reason_code="OK",
        policy_id=policy_id,
        sequence_no=sequence_no,
        signer_key_id=signer_key_id,
        algorithm=algorithm,
        signing_method=signing_method or "unknown",
    )


def build_policy_trust_ack(result: PolicyTrustResult, *, client_id: str = "unknown") -> Dict[str, Any]:
    """Build an ACK/status payload that can be published by Control Receiver.

    Existing ACK code can either use this dictionary directly or map these
    fields into its current ACK dataclass.
    """
    return {
        "client_id": client_id,
        "policy_id": result.policy_id,
        "sequence_no": result.sequence_no,
        "status": "accepted" if result.accepted else "rejected",
        "reason_code": result.reason_code,
        "signer_key_id": result.signer_key_id,
        "signature_algorithm": result.algorithm,
        "signing_method": result.signing_method,
    }
