from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Literal

import yaml

from ..exceptions import AOMQTTConfigurationError

TokenMode = Literal["whole", "hierarchical"]
PayloadFormat = Literal["json", "bytes", "text"]
PaddingMode = Literal["none", "fixed", "bucket", "random"]


@dataclass(frozen=True, repr=False)
class AOMQTTConfig:
    """Configuration for AOMQTT client-side protection.

    topic_key and payload_key are shared by authorized publishers/subscribers.
    In production, these keys should be generated and distributed by a proper
    key-management mechanism. For this prototype, pass them as strings.

    v0.3 supports:
      - whole / hierarchical topic tokenization
      - optional time-window based token rotation
      - overlap window for safer rotation across publisher/subscriber clocks
    """

    topic_key: str
    payload_key: str
    topic_prefix: str = "aomqtt/v1"
    token_mode: TokenMode = "hierarchical"
    token_hex_len: int = 16
    payload_format: PayloadFormat = "json"
    mqtt_qos: int = 0
    retain: bool = False
    key_id: str = "k001"
    aad_bind_topic: bool = True
    rotation_enabled: bool = False
    rotation_interval_sec: int = 300
    rotation_overlap_sec: int = 15
    padding_enabled: bool = False
    padding_mode: PaddingMode = "none"
    padding_fixed_size: int = 512
    padding_bucket_size: int = 256
    padding_random_min_bytes: int = 0
    padding_random_max_bytes: int = 128
    policy_id: str = "default"
    policy_name: str = "default"

    def validate(self) -> None:
        if not self.topic_key or len(self.topic_key) < 12:
            raise AOMQTTConfigurationError("topic_key must be at least 12 characters for this prototype")
        if not self.payload_key or len(self.payload_key) < 12:
            raise AOMQTTConfigurationError("payload_key must be at least 12 characters for this prototype")
        if self.token_mode not in ("whole", "hierarchical"):
            raise AOMQTTConfigurationError("token_mode must be 'whole' or 'hierarchical'")
        if self.token_hex_len < 8 or self.token_hex_len > 64:
            raise AOMQTTConfigurationError("token_hex_len must be between 8 and 64")
        if self.payload_format not in ("json", "bytes", "text"):
            raise AOMQTTConfigurationError("payload_format must be 'json', 'bytes', or 'text'")
        if self.mqtt_qos not in (0, 1, 2):
            raise AOMQTTConfigurationError("mqtt_qos must be 0, 1, or 2")
        if "+" in self.topic_prefix or "#" in self.topic_prefix:
            raise AOMQTTConfigurationError("topic_prefix must not contain MQTT wildcards")
        if self.topic_prefix.startswith("/") or self.topic_prefix.endswith("/"):
            raise AOMQTTConfigurationError("topic_prefix must not start or end with '/'")
        if "//" in self.topic_prefix:
            raise AOMQTTConfigurationError("topic_prefix must not contain empty topic levels")
        if self.rotation_interval_sec <= 0:
            raise AOMQTTConfigurationError("rotation_interval_sec must be positive")
        if self.rotation_overlap_sec < 0:
            raise AOMQTTConfigurationError("rotation_overlap_sec must be zero or positive")
        if self.rotation_overlap_sec >= self.rotation_interval_sec:
            raise AOMQTTConfigurationError("rotation_overlap_sec must be smaller than rotation_interval_sec")
        if self.padding_mode not in ("none", "fixed", "bucket", "random"):
            raise AOMQTTConfigurationError("padding_mode must be 'none', 'fixed', 'bucket', or 'random'")
        if not self.padding_enabled and self.padding_mode != "none":
            # Allow config files to state a preferred mode while disabled, but
            # keep runtime interpretation explicit by not raising here.
            pass
        if self.padding_enabled and self.padding_mode == "none":
            raise AOMQTTConfigurationError("padding_enabled requires padding_mode other than 'none'")
        if self.padding_fixed_size < 0:
            raise AOMQTTConfigurationError("padding_fixed_size must be zero or positive")
        if self.padding_bucket_size <= 0:
            raise AOMQTTConfigurationError("padding_bucket_size must be positive")
        if self.padding_random_min_bytes < 0 or self.padding_random_max_bytes < 0:
            raise AOMQTTConfigurationError("padding_random_min_bytes/max_bytes must be zero or positive")
        if self.padding_random_max_bytes < self.padding_random_min_bytes:
            raise AOMQTTConfigurationError("padding_random_max_bytes must be greater than or equal to padding_random_min_bytes")
        if not isinstance(self.policy_id, str):
            raise AOMQTTConfigurationError("policy_id must be a string")
        if not isinstance(self.policy_name, str):
            raise AOMQTTConfigurationError("policy_name must be a string")

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AOMQTTConfig":
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = yaml.safe_load(f) or {}
        cfg = cls(**data)
        cfg.validate()
        return cfg

    def with_token_mode(self, token_mode: TokenMode) -> "AOMQTTConfig":
        """Return a copy with a different tokenization mode."""
        cfg = replace(self, token_mode=token_mode)
        cfg.validate()
        return cfg

    def with_rotation(self, enabled: bool) -> "AOMQTTConfig":
        """Return a copy with token rotation enabled/disabled."""
        cfg = replace(self, rotation_enabled=enabled)
        cfg.validate()
        return cfg

    @staticmethod
    def _redact_secret(value: str) -> str:
        if not value:
            return ""
        return "<redacted>"

    def __repr__(self) -> str:
        values = self.to_dict(redact=True)
        args = ", ".join(f"{key}={value!r}" for key, value in values.items())
        return f"{self.__class__.__name__}({args})"

    def to_dict(self, *, redact: bool = True) -> Dict[str, Any]:
        """Return configuration as a dictionary.

        By default, secret material is redacted so that casual logging such as
        ``logger.info("config=%s", config.to_dict())`` does not leak shared
        topic or payload keys.  Internal code that needs to reconstruct a full
        ``AOMQTTConfig`` must call ``to_dict(redact=False)`` explicitly.
        """
        return {
            "topic_key": self._redact_secret(self.topic_key) if redact else self.topic_key,
            "payload_key": self._redact_secret(self.payload_key) if redact else self.payload_key,
            "topic_prefix": self.topic_prefix,
            "token_mode": self.token_mode,
            "token_hex_len": self.token_hex_len,
            "payload_format": self.payload_format,
            "mqtt_qos": self.mqtt_qos,
            "retain": self.retain,
            "key_id": self.key_id,
            "aad_bind_topic": self.aad_bind_topic,
            "rotation_enabled": self.rotation_enabled,
            "rotation_interval_sec": self.rotation_interval_sec,
            "rotation_overlap_sec": self.rotation_overlap_sec,
            "padding_enabled": self.padding_enabled,
            "padding_mode": self.padding_mode,
            "padding_fixed_size": self.padding_fixed_size,
            "padding_bucket_size": self.padding_bucket_size,
            "padding_random_min_bytes": self.padding_random_min_bytes,
            "padding_random_max_bytes": self.padding_random_max_bytes,
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
        }
