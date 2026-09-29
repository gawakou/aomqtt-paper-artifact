from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .krl import KeyRevocationList, check_policy_key_allowed
from .policy_trust import extract_policy_metadata
from .signing import PolicySigner, canonical_json_bytes, verify_ed25519_signature


@dataclass(frozen=True)
class MultiSignaturePolicyResult:
    accepted: bool
    reason_code: str
    policy_id: str
    sequence_no: int
    threshold: int
    valid_signature_count: int
    signer_key_ids: List[str]
    roles: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _signature_policy_dict(
    *,
    threshold: int,
    required_roles: Optional[Iterable[str]] = None,
    signer_roles: Optional[Mapping[str, str]] = None,
    version: str = "v1.2.0",
) -> Dict[str, Any]:
    return {
        "version": version,
        "threshold": int(threshold),
        "required_roles": sorted({str(role) for role in (required_roles or []) if str(role)}),
        "signer_roles": {
            str(key_id): str(role)
            for key_id, role in sorted((signer_roles or {}).items())
            if str(key_id) and str(role)
        },
    }


def multisig_signing_payload(policy: Mapping[str, Any], signature_policy: Mapping[str, Any]) -> bytes:
    """Canonical payload signed by every v1.2.0 policy signer.

    Signatures are intentionally excluded from the signed payload. The signature
    policy is included so that attackers cannot lower the threshold or remove a
    required role without invalidating all signatures.
    """
    return canonical_json_bytes(
        {
            "policy": dict(policy),
            "signature_policy": dict(signature_policy),
        }
    )


def sign_multisig_policy_envelope(
    policy: Mapping[str, Any],
    signers: Sequence[PolicySigner],
    *,
    threshold: Optional[int] = None,
    signer_roles: Optional[Mapping[str, str]] = None,
    required_roles: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Create a v1.2.0 multi-signature policy envelope.

    The default threshold is the number of signers, which gives conservative
    all-signers approval. Pass threshold=2, for example, for 2-of-N approval.
    """
    if not signers:
        raise ValueError("at least one signer is required")
    effective_threshold = int(threshold if threshold is not None else len(signers))
    if effective_threshold <= 0:
        raise ValueError("threshold must be positive")
    if effective_threshold > len(signers):
        raise ValueError("threshold must be <= number of signers")

    sig_policy = _signature_policy_dict(
        threshold=effective_threshold,
        required_roles=required_roles,
        signer_roles=signer_roles,
    )
    payload = multisig_signing_payload(policy, sig_policy)
    roles = dict(signer_roles or {})

    signatures: List[Dict[str, Any]] = []
    for signer in signers:
        sig = signer.sign(payload).to_dict()
        role = roles.get(signer.key_id)
        if role:
            sig["role"] = str(role)
        signatures.append(sig)

    return {
        "policy": dict(policy),
        "signature_policy": sig_policy,
        "signatures": signatures,
    }


def _envelope_signature_policy(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    value = envelope.get("signature_policy")
    return value if isinstance(value, Mapping) else {}


def _envelope_signatures(envelope: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    values = envelope.get("signatures")
    if isinstance(values, list):
        return [x for x in values if isinstance(x, Mapping)]

    # Compatibility bridge for a single v1.1-style signature block.
    sig = envelope.get("signature")
    if isinstance(sig, Mapping):
        return [sig]
    if isinstance(envelope.get("signature"), str):
        return [envelope]
    return []


def verify_multisig_policy_envelope(
    envelope: Mapping[str, Any],
    *,
    trusted_public_keys: Mapping[str, Ed25519PublicKey],
    krl: Optional[KeyRevocationList] = None,
    min_threshold: Optional[int] = None,
    required_roles: Optional[Iterable[str]] = None,
) -> MultiSignaturePolicyResult:
    """Validate a v1.2.0 multi-signature policy envelope.

    The implementation is intentionally strict: unknown, revoked, duplicate, or
    invalid signatures cause rejection even if the numeric threshold would have
    been met by other signatures. This prevents attackers from hiding suspicious
    signature material in an otherwise valid envelope.
    """
    policy = _as_mapping(envelope.get("policy"))
    policy_id, sequence_no = extract_policy_metadata(policy)
    sig_policy = _envelope_signature_policy(envelope)
    signatures = _envelope_signatures(envelope)

    try:
        envelope_threshold = int(sig_policy.get("threshold", 1))
    except (TypeError, ValueError):
        envelope_threshold = 1
    threshold = max(envelope_threshold, int(min_threshold or 1))

    required_role_set = {str(x) for x in sig_policy.get("required_roles", []) if str(x)}
    if required_roles is not None:
        required_role_set |= {str(x) for x in required_roles if str(x)}

    signed_signer_roles = {
        str(key_id): str(role)
        for key_id, role in _as_mapping(sig_policy.get("signer_roles")).items()
        if str(key_id) and str(role)
    }

    seen: set[str] = set()
    valid_signers: List[str] = []
    valid_roles: List[str] = []

    def reject(reason: str) -> MultiSignaturePolicyResult:
        return MultiSignaturePolicyResult(
            accepted=False,
            reason_code=reason,
            policy_id=policy_id,
            sequence_no=sequence_no,
            threshold=threshold,
            valid_signature_count=len(valid_signers),
            signer_key_ids=list(valid_signers),
            roles=sorted(set(valid_roles)),
        )

    if not signatures:
        return reject("MISSING_SIGNATURES")
    if threshold <= 0:
        return reject("INVALID_MULTISIG_THRESHOLD")
    if threshold > len(signatures):
        return reject("MULTISIG_THRESHOLD_NOT_MET")

    payload = multisig_signing_payload(policy, sig_policy)

    for sig in signatures:
        key_id = str(sig.get("key_id") or sig.get("signer_key_id") or "")
        algorithm = str(sig.get("algorithm") or "")
        signature = sig.get("signature")
        # Do not trust sig["role"] here. It is outside the signature payload and
        # can be modified after signing. Roles must be bound to key_id through
        # signature_policy["signer_roles"], which is signed by every signer.

        if key_id in seen:
            return reject("DUPLICATE_SIGNER")
        seen.add(key_id)

        allowed, reason = check_policy_key_allowed(
            key_id,
            trusted_key_ids=trusted_public_keys.keys(),
            krl=krl,
        )
        if not allowed:
            return reject(reason)

        if algorithm != "Ed25519":
            return reject("UNSUPPORTED_SIGNATURE_ALGORITHM")
        if not isinstance(signature, str) or not signature:
            return reject("MISSING_SIGNATURE")

        public_key = trusted_public_keys.get(key_id)
        if public_key is None:
            return reject("UNKNOWN_SIGNING_KEY")
        if not verify_ed25519_signature(public_key, payload, signature):
            return reject("POLICY_SIGNATURE_INVALID")

        valid_signers.append(key_id)
        role = signed_signer_roles.get(key_id, "")
        if role:
            valid_roles.append(role)

    if len(valid_signers) < threshold:
        return reject("MULTISIG_THRESHOLD_NOT_MET")

    missing_roles = required_role_set - set(valid_roles)
    if missing_roles:
        return reject("MULTISIG_REQUIRED_ROLE_MISSING")

    return MultiSignaturePolicyResult(
        accepted=True,
        reason_code="OK",
        policy_id=policy_id,
        sequence_no=sequence_no,
        threshold=threshold,
        valid_signature_count=len(valid_signers),
        signer_key_ids=list(valid_signers),
        roles=sorted(set(valid_roles)),
    )


def build_multisig_policy_ack(result: MultiSignaturePolicyResult, *, client_id: str = "unknown") -> Dict[str, Any]:
    return {
        "client_id": client_id,
        "policy_id": result.policy_id,
        "sequence_no": result.sequence_no,
        "status": "accepted" if result.accepted else "rejected",
        "reason_code": result.reason_code,
        "signature_mode": "multi-signature",
        "threshold": result.threshold,
        "valid_signature_count": result.valid_signature_count,
        "signer_key_ids": list(result.signer_key_ids),
        "signer_roles": list(result.roles),
    }
