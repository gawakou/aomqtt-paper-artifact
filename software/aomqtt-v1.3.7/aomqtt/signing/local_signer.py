from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .signer import PolicySigner, SignatureEnvelope, b64decode_text, b64encode_bytes


class LocalEd25519Signer(PolicySigner):
    """Local Ed25519 signer used for tests and non-production deployments."""

    algorithm = "Ed25519"
    signing_method = "local"

    def __init__(self, key_id: str, private_key: Ed25519PrivateKey):
        if not key_id:
            raise ValueError("key_id must not be empty")
        self.key_id = key_id
        self._private_key = private_key

    @classmethod
    def generate(cls, key_id: str) -> "LocalEd25519Signer":
        return cls(key_id=key_id, private_key=Ed25519PrivateKey.generate())

    @classmethod
    def from_private_key_b64(cls, key_id: str, private_key_b64: str) -> "LocalEd25519Signer":
        private_key = Ed25519PrivateKey.from_private_bytes(b64decode_text(private_key_b64))
        return cls(key_id=key_id, private_key=private_key)

    def private_key_b64(self) -> str:
        raw = self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return b64encode_bytes(raw)

    def public_key(self) -> Ed25519PublicKey:
        return self._private_key.public_key()

    def public_key_b64(self) -> str:
        raw = self.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return b64encode_bytes(raw)

    def sign(self, canonical_policy: bytes) -> SignatureEnvelope:
        signature = self._private_key.sign(canonical_policy)
        return SignatureEnvelope(
            key_id=self.key_id,
            algorithm=self.algorithm,
            signature=b64encode_bytes(signature),
            signing_method=self.signing_method,
        )


def verify_ed25519_signature(public_key: Ed25519PublicKey, canonical_policy: bytes, signature_b64: str) -> bool:
    try:
        public_key.verify(b64decode_text(signature_b64), canonical_policy)
        return True
    except Exception:
        return False
