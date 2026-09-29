from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .local_signer import LocalEd25519Signer


class MockKMSSigner(LocalEd25519Signer):
    """KMS-like signer for reproducible local tests."""

    signing_method = "mock-kms"

    @classmethod
    def generate(cls, key_id: str) -> "MockKMSSigner":
        return cls(key_id=key_id, private_key=Ed25519PrivateKey.generate())
