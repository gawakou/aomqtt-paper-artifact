from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .signing.signer import b64decode_text, b64encode_bytes, canonical_json_bytes


KRL_SIGNATURE_FIELD = "signature"
KRL_SIGNER_KEY_ID_FIELD = "signer_key_id"


@dataclass(frozen=True)
class RevokedKey:
    key_id: str
    revoked_at: str
    reason: str = "unspecified"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RevokedKey":
        return cls(
            key_id=str(value.get("key_id", "")),
            revoked_at=str(value.get("revoked_at", "")),
            reason=str(value.get("reason", "unspecified")),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "key_id": self.key_id,
            "revoked_at": self.revoked_at,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class KeyRevocationList:
    krl_version: int
    generated_at: str
    revoked_keys: List[RevokedKey]
    signature: Optional[str] = None
    signer_key_id: Optional[str] = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KeyRevocationList":
        revoked = [RevokedKey.from_dict(x) for x in value.get("revoked_keys", [])]
        return cls(
            krl_version=int(value.get("krl_version", 0)),
            generated_at=str(value.get("generated_at", "")),
            revoked_keys=revoked,
            signature=value.get(KRL_SIGNATURE_FIELD),
            signer_key_id=value.get(KRL_SIGNER_KEY_ID_FIELD),
        )

    def to_dict(self, include_signature: bool = True) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "krl_version": self.krl_version,
            "generated_at": self.generated_at,
            "revoked_keys": [x.to_dict() for x in self.revoked_keys],
        }
        if include_signature and self.signature:
            value[KRL_SIGNATURE_FIELD] = self.signature
        if include_signature and self.signer_key_id:
            value[KRL_SIGNER_KEY_ID_FIELD] = self.signer_key_id
        return value

    def unsigned_dict(self) -> Dict[str, Any]:
        return self.to_dict(include_signature=False)

    def is_revoked(self, key_id: str) -> bool:
        return any(x.key_id == key_id for x in self.revoked_keys)

    def revocation_reason(self, key_id: str) -> Optional[str]:
        for item in self.revoked_keys:
            if item.key_id == key_id:
                return item.reason
        return None


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_krl(krl_version: int, revoked_keys: Iterable[Mapping[str, Any]]) -> KeyRevocationList:
    return KeyRevocationList(
        krl_version=krl_version,
        generated_at=now_utc_iso(),
        revoked_keys=[RevokedKey.from_dict(x) for x in revoked_keys],
    )


def sign_krl(krl: KeyRevocationList, private_key: Ed25519PrivateKey, signer_key_id: str) -> KeyRevocationList:
    payload = canonical_json_bytes(krl.unsigned_dict())
    signature = b64encode_bytes(private_key.sign(payload))
    return KeyRevocationList(
        krl_version=krl.krl_version,
        generated_at=krl.generated_at,
        revoked_keys=krl.revoked_keys,
        signature=signature,
        signer_key_id=signer_key_id,
    )


def verify_krl_signature(krl: KeyRevocationList, public_key: Ed25519PublicKey) -> bool:
    if not krl.signature:
        return False
    try:
        public_key.verify(b64decode_text(krl.signature), canonical_json_bytes(krl.unsigned_dict()))
        return True
    except Exception:
        return False


def check_policy_key_allowed(
    key_id: str,
    *,
    trusted_key_ids: Optional[Iterable[str]] = None,
    krl: Optional[KeyRevocationList] = None,
) -> tuple[bool, str]:
    """Return (allowed, reason_code) for policy signer key validation."""
    if not key_id:
        return False, "MISSING_SIGNING_KEY"

    if trusted_key_ids is not None and key_id not in set(trusted_key_ids):
        return False, "UNKNOWN_SIGNING_KEY"

    if krl is not None and krl.is_revoked(key_id):
        return False, "REVOKED_SIGNING_KEY"

    return True, "OK"


class KRLValidationError(Exception):
    """Raised when a KRL fails signature or anti-rollback validation."""


def verify_and_load_krl(
    krl: Union[Mapping[str, Any], KeyRevocationList],
    public_key: Ed25519PublicKey,
    *,
    min_version: int = -1,
) -> KeyRevocationList:
    """Verify a KRL signature and reject rollback before trusting it.

    ``min_version`` is the highest accepted KRL version. A candidate KRL must
    have a strictly greater version to prevent replaying an old revocation list
    and re-enabling a revoked signing key.
    """
    obj = krl if isinstance(krl, KeyRevocationList) else KeyRevocationList.from_dict(krl)
    if not verify_krl_signature(obj, public_key):
        raise KRLValidationError("KRL signature invalid")
    if obj.krl_version <= min_version:
        raise KRLValidationError(
            f"KRL rollback rejected: version {obj.krl_version} <= last accepted {min_version}"
        )
    return obj

