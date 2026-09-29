from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from .exceptions import AOMQTTConfigurationError

SIGNATURE_ALGORITHM = "Ed25519"

REJECTION_INVALID_POLICY = "invalid_policy"
REJECTION_EXPIRED_POLICY = "expired_policy"
REJECTION_INVALID_SIGNATURE = "invalid_signature"
REJECTION_STALE_SEQUENCE_NO = "stale_sequence_no"
REJECTION_UNSAFE_POLICY = "unsafe_policy"
REJECTION_UNKNOWN_KEY_ID = "unknown_key_id"


def classify_policy_rejection(reason: str) -> str:
    """Classify a rejected control Policy reason into a stable reason_code.

    The free-form ``reason`` field is kept for human debugging, while this
    machine-readable code is intended for Controller-side aggregation.
    """
    normalized = (reason or "").lower()

    if "key_id" in normalized or "key id" in normalized:
        return REJECTION_UNKNOWN_KEY_ID
    if "expired" in normalized:
        return REJECTION_EXPIRED_POLICY
    if "sequence_no" in normalized or "sequence no" in normalized or "replay" in normalized:
        return REJECTION_STALE_SEQUENCE_NO
    if "signature" in normalized:
        return REJECTION_INVALID_SIGNATURE
    if (
        "padding" in normalized
        or "rotation" in normalized
        or "safety" in normalized
        or "allowed" in normalized
        or "bucket" in normalized
        or "fixed_size" in normalized
    ):
        return REJECTION_UNSAFE_POLICY
    return REJECTION_INVALID_POLICY


def _b64decode(value: str, *, field: str) -> bytes:
    try:
        return base64.b64decode(value.strip(), validate=True)
    except Exception as exc:
        raise AOMQTTConfigurationError(f"{field} must be base64-encoded") from exc


def load_private_key(value: str) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from raw-base64, PEM text, or a file path."""
    text = _read_value_or_file(value)
    if "BEGIN" in text:
        key = serialization.load_pem_private_key(text.encode("utf-8"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise AOMQTTConfigurationError("private key must be an Ed25519 private key")
        return key
    raw = _b64decode(text, field="Ed25519 private key")
    if len(raw) != 32:
        raise AOMQTTConfigurationError("Ed25519 raw private key must be 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def load_public_key(value: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from raw-base64, PEM text, or a file path."""
    text = _read_value_or_file(value)
    if "BEGIN" in text:
        key = serialization.load_pem_public_key(text.encode("utf-8"))
        if not isinstance(key, Ed25519PublicKey):
            raise AOMQTTConfigurationError("public key must be an Ed25519 public key")
        return key
    raw = _b64decode(text, field="Ed25519 public key")
    if len(raw) != 32:
        raise AOMQTTConfigurationError("Ed25519 raw public key must be 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def _read_value_or_file(value: str) -> str:
    p = Path(value)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return value.strip()


def generate_keypair() -> tuple[str, str]:
    """Return raw-base64 private/public Ed25519 keys for prototype use."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(private_raw).decode("ascii"), base64.b64encode(public_raw).decode("ascii")


def _strip_none_for_signature(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_none_for_signature(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none_for_signature(v) for v in obj]
    return obj


def canonical_control_message_bytes(message: dict[str, Any]) -> bytes:
    """Canonical bytes for signing/verifying a control policy message.

    The top-level ``signature`` field is excluded. ``None`` values are also
    removed so signatures remain stable even if the MQTT publisher strips nulls
    from the JSON payload before sending it.
    """
    unsigned = {k: v for k, v in message.items() if k != "signature"}
    unsigned = _strip_none_for_signature(unsigned)
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_control_message_dict(
    message: dict[str, Any],
    private_key: Ed25519PrivateKey | str,
    *,
    key_id: str = "policy-signing-key-1",
) -> dict[str, Any]:
    key = load_private_key(private_key) if isinstance(private_key, str) else private_key
    signed = dict(message)
    signed.pop("signature", None)
    signature = key.sign(canonical_control_message_bytes(signed))
    signed["signature"] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "key_id": key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return signed


def verify_control_message_dict(
    message: dict[str, Any],
    public_key: Ed25519PublicKey | str,
    *,
    require_signature: bool = True,
    allowed_signature_key_ids: Iterable[str] | None = None,
) -> bool:
    sig = message.get("signature")
    if sig is None:
        if require_signature:
            raise AOMQTTConfigurationError("control policy signature is required")
        return False
    if not isinstance(sig, dict):
        raise AOMQTTConfigurationError("control policy signature must be an object")
    if sig.get("algorithm") != SIGNATURE_ALGORITHM:
        raise AOMQTTConfigurationError("unsupported control policy signature algorithm")
    key_id = sig.get("key_id")
    if allowed_signature_key_ids is not None:
        allowed = set(allowed_signature_key_ids)
        if not isinstance(key_id, str) or not key_id:
            raise AOMQTTConfigurationError("control policy signature key_id is required")
        if key_id not in allowed:
            raise AOMQTTConfigurationError(f"unknown control policy signature key_id: {key_id}")
    value = sig.get("value")
    if not isinstance(value, str) or not value:
        raise AOMQTTConfigurationError("control policy signature value is required")
    signature = _b64decode(value, field="control policy signature")
    key = load_public_key(public_key) if isinstance(public_key, str) else public_key
    try:
        key.verify(signature, canonical_control_message_bytes(message))
    except InvalidSignature as exc:
        raise AOMQTTConfigurationError("control policy signature verification failed") from exc
    return True


@dataclass(frozen=True)
class PolicySafetyLimits:
    """Client-side guardrails for runtime policy messages.

    These limits protect clients from obviously unsafe or mistaken policies even
    when a control topic is writable by the wrong entity, or when an operator
    accidentally signs a harmful policy.
    """

    min_rotation_interval_sec: int = 5
    max_rotation_interval_sec: int = 86400
    max_rotation_overlap_ratio: float = 0.5
    max_rotation_overlap_sec: int = 3600
    max_padding_fixed_size: int = 4096
    allowed_padding_bucket_sizes: tuple[int, ...] = (64, 128, 256, 512, 1024, 2048, 4096)
    max_padding_random_bytes: int = 4096

    def validate_policy(self, policy: Any) -> None:
        # token_mode, qos, and base config validation are handled by AOMQTTPolicy/AOMQTTConfig.
        if policy.rotation_enabled:
            interval = policy.rotation_interval_sec
            overlap = policy.rotation_overlap_sec
            if interval is not None:
                if interval < self.min_rotation_interval_sec:
                    raise AOMQTTConfigurationError(
                        f"policy.rotation.interval_sec must be >= {self.min_rotation_interval_sec}"
                    )
                if interval > self.max_rotation_interval_sec:
                    raise AOMQTTConfigurationError(
                        f"policy.rotation.interval_sec must be <= {self.max_rotation_interval_sec}"
                    )
            if overlap is not None:
                if overlap < 0:
                    raise AOMQTTConfigurationError("policy.rotation.overlap_sec must be >= 0")
                if overlap > self.max_rotation_overlap_sec:
                    raise AOMQTTConfigurationError(
                        f"policy.rotation.overlap_sec must be <= {self.max_rotation_overlap_sec}"
                    )
                if interval is not None and overlap > int(interval * self.max_rotation_overlap_ratio):
                    raise AOMQTTConfigurationError(
                        "policy.rotation.overlap_sec exceeds allowed ratio of rotation interval"
                    )
        if policy.padding_enabled:
            mode = policy.padding_mode
            if mode == "fixed" and policy.padding_fixed_size is not None:
                if policy.padding_fixed_size > self.max_padding_fixed_size:
                    raise AOMQTTConfigurationError(
                        f"policy.padding.fixed_size must be <= {self.max_padding_fixed_size}"
                    )
            if mode == "bucket" and policy.padding_bucket_size is not None:
                if policy.padding_bucket_size not in self.allowed_padding_bucket_sizes:
                    raise AOMQTTConfigurationError(
                        "policy.padding.bucket_size is not in the allowed bucket list"
                    )
            if mode == "random":
                if policy.padding_random_max_bytes is not None and policy.padding_random_max_bytes > self.max_padding_random_bytes:
                    raise AOMQTTConfigurationError(
                        f"policy.padding.random_max_bytes must be <= {self.max_padding_random_bytes}"
                    )


def validate_policy_message_time_and_replay(
    message: Any,
    *,
    now: Optional[float] = None,
    latest_sequence_no: Optional[int] = None,
    require_sequence_no: bool = False,
) -> None:
    current = time.time() if now is None else now
    if message.expires_at is not None and current > message.expires_at:
        raise AOMQTTConfigurationError("control policy has expired")
    if require_sequence_no and message.sequence_no is None:
        raise AOMQTTConfigurationError("control policy sequence_no is required")
    if message.sequence_no is not None and latest_sequence_no is not None:
        if int(message.sequence_no) <= int(latest_sequence_no):
            raise AOMQTTConfigurationError("control policy sequence_no is not newer than the latest accepted policy")
