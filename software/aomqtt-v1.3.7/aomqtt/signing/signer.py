from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Mapping


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return stable JSON bytes for signing and verification."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class SignatureEnvelope:
    key_id: str
    algorithm: str
    signature: str
    signing_method: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "signature": self.signature,
            "signing_method": self.signing_method,
        }


class PolicySigner(ABC):
    """Abstract signer for policy canonical bytes."""

    key_id: str
    algorithm: str = "Ed25519"
    signing_method: str

    @abstractmethod
    def sign(self, canonical_policy: bytes) -> SignatureEnvelope:
        """Sign canonical policy bytes and return a signature envelope."""


def b64encode_bytes(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64decode_text(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"), validate=True)
