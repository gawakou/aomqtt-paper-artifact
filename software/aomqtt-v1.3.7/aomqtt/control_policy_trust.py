from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Union

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .krl import KeyRevocationList
from .policy_trust import (
    PolicyTrustResult,
    build_policy_trust_ack,
    extract_policy_metadata,
    verify_signed_policy_envelope,
)
from .signing.signer import b64decode_text

JsonPayload = Union[str, bytes, bytearray, Mapping[str, Any]]


@dataclass(frozen=True)
class ControlPolicyTrustEvaluation:
    """Result of v1.1.0 trust validation for a received control-policy payload.

    This object is designed as a bridge between the MQTT Control Receiver and the
    existing Policy Guard. If accepted is False, the receiver can publish `ack`
    and stop before constructing a concrete ControlPolicyMessage. If accepted is
    True, the receiver can pass `policy` to the existing parser/guard.
    """

    accepted: bool
    reason_code: str
    policy_id: str
    sequence_no: int
    signer_key_id: str
    ack: Dict[str, Any]
    envelope: Optional[Mapping[str, Any]] = None
    policy: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_ed25519_public_key_b64(public_key_b64: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from raw Base64 bytes.

    This helper lets examples/config files store trusted controller public keys
    without adding a new serialization dependency to the receiver path.
    """

    return Ed25519PublicKey.from_public_bytes(b64decode_text(public_key_b64))


def parse_control_policy_payload(payload: JsonPayload) -> Dict[str, Any]:
    """Parse a received control-policy payload into a dictionary.

    Accepts bytes from MQTT callbacks, JSON strings, or already-decoded mapping
    objects used in tests and internal callers.
    """

    if isinstance(payload, Mapping):
        return dict(payload)
    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8")
    if isinstance(payload, str):
        value = json.loads(payload)
        if not isinstance(value, Mapping):
            raise ValueError("control policy JSON must be an object")
        return dict(value)
    raise TypeError(f"unsupported control policy payload type: {type(payload)!r}")


def normalize_policy_envelope(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize a received payload into the v1.1.0 signed-envelope shape.

    Preferred v1.1.0 format:
        {"policy": {...}, "signature": {...}}

    Migration compatibility:
        If a legacy top-level policy object is received, it is wrapped as
        {"policy": legacy_policy}. This keeps rejected ACKs traceable because
        policy.id and sequence_no are still extracted before concrete parsing.
    """

    if isinstance(value.get("policy"), Mapping):
        return dict(value)
    return {"policy": dict(value)}


def _reject_evaluation(
    reason_code: str,
    *,
    policy_id: str = "unknown",
    sequence_no: int = 0,
    signer_key_id: str = "unknown",
    algorithm: str = "unknown",
    signing_method: str = "unknown",
    client_id: str = "unknown",
    envelope: Optional[Mapping[str, Any]] = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> ControlPolicyTrustEvaluation:
    result = PolicyTrustResult(
        accepted=False,
        reason_code=reason_code,
        policy_id=policy_id,
        sequence_no=sequence_no,
        signer_key_id=signer_key_id,
        algorithm=algorithm,
        signing_method=signing_method,
    )
    return ControlPolicyTrustEvaluation(
        accepted=False,
        reason_code=reason_code,
        policy_id=policy_id,
        sequence_no=sequence_no,
        signer_key_id=signer_key_id,
        ack=build_policy_trust_ack(result, client_id=client_id),
        envelope=envelope,
        policy=policy,
    )


def verify_control_policy_payload(
    payload: JsonPayload,
    *,
    trusted_public_keys: Mapping[str, Ed25519PublicKey],
    krl: Optional[KeyRevocationList] = None,
    client_id: str = "unknown",
    require_signature: bool = True,
) -> ControlPolicyTrustEvaluation:
    """Verify a raw MQTT control-policy payload before policy construction.

    Intended receiver integration pattern:

        evaluation = verify_control_policy_payload(msg.payload, ...)
        publish_ack(evaluation.ack)
        if not evaluation.accepted:
            return
        policy = build_existing_ControlPolicyMessage(evaluation.policy)

    The function is deliberately safe for malformed inputs. It always returns a
    structured rejection ACK rather than raising for invalid JSON or trust errors.
    """

    try:
        parsed = parse_control_policy_payload(payload)
    except Exception:
        return _reject_evaluation("INVALID_CONTROL_POLICY_JSON", client_id=client_id)

    envelope = normalize_policy_envelope(parsed)
    policy = envelope.get("policy") if isinstance(envelope.get("policy"), Mapping) else {}
    policy_id, sequence_no = extract_policy_metadata(policy)

    # Transitional mode for deployments that need to keep accepting legacy
    # unsigned policies while rolling out v1.1.0 signed envelopes.
    sig = envelope.get("signature")
    has_signature = isinstance(sig, Mapping) or isinstance(envelope.get("signature"), str)
    if not require_signature and not has_signature:
        result = PolicyTrustResult(
            accepted=True,
            reason_code="LEGACY_UNSIGNED_POLICY",
            policy_id=policy_id,
            sequence_no=sequence_no,
            signer_key_id="legacy-unsigned",
            algorithm="none",
            signing_method="legacy",
        )
        return ControlPolicyTrustEvaluation(
            accepted=True,
            reason_code=result.reason_code,
            policy_id=policy_id,
            sequence_no=sequence_no,
            signer_key_id=result.signer_key_id,
            ack=build_policy_trust_ack(result, client_id=client_id),
            envelope=envelope,
            policy=policy,
        )

    result = verify_signed_policy_envelope(
        envelope,
        trusted_public_keys=trusted_public_keys,
        krl=krl,
    )
    return ControlPolicyTrustEvaluation(
        accepted=result.accepted,
        reason_code=result.reason_code,
        policy_id=result.policy_id,
        sequence_no=result.sequence_no,
        signer_key_id=result.signer_key_id,
        ack=build_policy_trust_ack(result, client_id=client_id),
        envelope=envelope,
        policy=policy if result.accepted else policy,
    )
