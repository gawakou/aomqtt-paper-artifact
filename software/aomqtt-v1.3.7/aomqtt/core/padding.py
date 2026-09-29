from __future__ import annotations

import os
import secrets
import struct
from dataclasses import dataclass
from typing import Literal

from .config import AOMQTTConfig

PaddingMode = Literal["none", "fixed", "bucket", "random"]

_MAGIC = b"AOPAD1\x00"
_HEADER_LEN = len(_MAGIC) + 8


@dataclass(frozen=True)
class PaddingResult:
    """Observation record for payload padding.

    ``original_plain_bytes`` is the serialized application payload size before
    padding. ``padded_plain_bytes`` is the number of bytes encrypted by AEAD.
    For padding disabled, both values are identical and ``padding_added_bytes``
    is zero.
    """

    padding_enabled: bool
    padding_mode: str
    original_plain_bytes: int
    padded_plain_bytes: int
    padding_added_bytes: int
    padding_target_bytes: int

    @property
    def overhead_ratio(self) -> float:
        if self.original_plain_bytes <= 0:
            return 0.0
        return self.padding_added_bytes / self.original_plain_bytes


class PayloadPadding:
    """Payload padding helper used before AEAD encryption.

    The original plaintext length is stored inside the encrypted plaintext, not
    in the outer JSON envelope. This avoids directly exposing the original
    payload length to the MQTT broker.
    """

    def __init__(self, config: AOMQTTConfig):
        self.config = config

    @staticmethod
    def is_wrapped(data: bytes) -> bool:
        return data.startswith(_MAGIC) and len(data) >= _HEADER_LEN

    def _target_size(self, protected_len: int) -> int:
        if not self.config.padding_enabled or self.config.padding_mode == "none":
            return protected_len
        if self.config.padding_mode == "fixed":
            return max(protected_len, self.config.padding_fixed_size)
        if self.config.padding_mode == "bucket":
            bucket = self.config.padding_bucket_size
            return ((protected_len + bucket - 1) // bucket) * bucket
        if self.config.padding_mode == "random":
            span = self.config.padding_random_max_bytes - self.config.padding_random_min_bytes + 1
            add = self.config.padding_random_min_bytes + secrets.randbelow(span)
            return protected_len + add
        raise ValueError(f"unsupported padding mode: {self.config.padding_mode}")

    def apply(self, plaintext: bytes) -> tuple[bytes, PaddingResult]:
        original_len = len(plaintext)
        if not self.config.padding_enabled or self.config.padding_mode == "none":
            return plaintext, PaddingResult(
                padding_enabled=False,
                padding_mode="none",
                original_plain_bytes=original_len,
                padded_plain_bytes=original_len,
                padding_added_bytes=0,
                padding_target_bytes=original_len,
            )

        protected_len = _HEADER_LEN + original_len
        target = self._target_size(protected_len)
        pad_len = max(0, target - protected_len)
        wrapped = _MAGIC + struct.pack("!Q", original_len) + plaintext + os.urandom(pad_len)
        return wrapped, PaddingResult(
            padding_enabled=True,
            padding_mode=self.config.padding_mode,
            original_plain_bytes=original_len,
            padded_plain_bytes=len(wrapped),
            padding_added_bytes=len(wrapped) - original_len,
            padding_target_bytes=target,
        )

    @staticmethod
    def remove(padded_plaintext: bytes) -> bytes:
        if not PayloadPadding.is_wrapped(padded_plaintext):
            return padded_plaintext
        original_len = struct.unpack("!Q", padded_plaintext[len(_MAGIC):_HEADER_LEN])[0]
        start = _HEADER_LEN
        end = start + original_len
        if end > len(padded_plaintext):
            raise ValueError("invalid padded payload length")
        return padded_plaintext[start:end]
