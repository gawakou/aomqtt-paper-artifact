from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import AOMQTTConfig
from .padding import PaddingResult, PayloadPadding
from ..exceptions import AOMQTTDecryptionError


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


class PayloadCrypto:
    """AES-GCM payload encryption/decryption with optional v0.6 padding.

    The ciphertext envelope is JSON bytes so it can be sent as an MQTT payload.
    For research use, the payload key is derived as SHA-256(payload_key).
    Production systems should use a stronger key-management design.

    v0.6 optionally pads the serialized plaintext before AEAD encryption. The
    original plaintext length is kept inside the encrypted plaintext wrapper,
    not in the outer JSON envelope, so the broker cannot directly read it.
    """

    ENVELOPE_VERSION = 1

    def __init__(self, config: AOMQTTConfig):
        config.validate()
        self.config = config
        self._key = hashlib.sha256(config.payload_key.encode("utf-8")).digest()
        self._aesgcm = AESGCM(self._key)
        self._padding = PayloadPadding(config)

    def _serialize_plaintext(self, payload: Any) -> bytes:
        if self.config.payload_format == "json":
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if self.config.payload_format == "text":
            if not isinstance(payload, str):
                raise TypeError("payload_format='text' requires str payload")
            return payload.encode("utf-8")
        if self.config.payload_format == "bytes":
            if not isinstance(payload, (bytes, bytearray)):
                raise TypeError("payload_format='bytes' requires bytes payload")
            return bytes(payload)
        raise ValueError(f"unsupported payload_format: {self.config.payload_format}")

    def _deserialize_plaintext(self, data: bytes) -> Any:
        if self.config.payload_format == "json":
            return json.loads(data.decode("utf-8"))
        if self.config.payload_format == "text":
            return data.decode("utf-8")
        if self.config.payload_format == "bytes":
            return data
        raise ValueError(f"unsupported payload_format: {self.config.payload_format}")

    def plaintext_size(self, payload: Any) -> int:
        """Return serialized application plaintext size in bytes."""
        return len(self._serialize_plaintext(payload))

    def padded_plaintext_size(self, payload: Any) -> int:
        """Return the AEAD plaintext size after optional padding."""
        plaintext = self._serialize_plaintext(payload)
        _, stats = self._padding.apply(plaintext)
        return stats.padded_plain_bytes

    def encrypt_with_stats(self, payload: Any, *, aad: Optional[bytes] = None) -> tuple[bytes, PaddingResult]:
        plaintext = self._serialize_plaintext(payload)
        padded_plaintext, padding_stats = self._padding.apply(plaintext)
        nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
        ciphertext = self._aesgcm.encrypt(nonce, padded_plaintext, aad)
        envelope = {
            "v": self.ENVELOPE_VERSION,
            "alg": "AES-256-GCM",
            "kid": self.config.key_id,
            "fmt": self.config.payload_format,
            "pad": self.config.padding_mode if self.config.padding_enabled else "none",
            "n": _b64e(nonce),
            "ct": _b64e(ciphertext),
        }
        return json.dumps(envelope, separators=(",", ":")).encode("utf-8"), padding_stats

    def encrypt(self, payload: Any, *, aad: Optional[bytes] = None) -> bytes:
        encrypted, _ = self.encrypt_with_stats(payload, aad=aad)
        return encrypted

    def decrypt(self, encrypted_payload: bytes, *, aad: Optional[bytes] = None) -> Any:
        try:
            envelope = json.loads(encrypted_payload.decode("utf-8"))
            if envelope.get("v") != self.ENVELOPE_VERSION:
                raise AOMQTTDecryptionError("unsupported encrypted payload version")
            nonce = _b64d(envelope["n"])
            ciphertext = _b64d(envelope["ct"])
            padded_plaintext = self._aesgcm.decrypt(nonce, ciphertext, aad)
            plaintext = PayloadPadding.remove(padded_plaintext)
            return self._deserialize_plaintext(plaintext)
        except AOMQTTDecryptionError:
            raise
        except Exception as exc:
            raise AOMQTTDecryptionError("failed to decrypt payload") from exc
