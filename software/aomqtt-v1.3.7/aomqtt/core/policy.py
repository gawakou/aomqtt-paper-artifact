from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from ..exceptions import AOMQTTConfigurationError
from .config import AOMQTTConfig, PaddingMode, TokenMode


def _as_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on", "enabled"}:
            return True
        if lowered in {"false", "0", "no", "off", "disabled"}:
            return False
    raise AOMQTTConfigurationError(f"{field} must be a boolean")


def _as_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise AOMQTTConfigurationError(f"{field} must be an integer")
    try:
        return int(value)
    except Exception as exc:
        raise AOMQTTConfigurationError(f"{field} must be an integer") from exc


@dataclass(frozen=True)
class AOMQTTPolicy:
    """External operation policy for AOMQTT v0.7.

    A policy intentionally controls only runtime/privacy parameters. It does
    not contain topic_key or payload_key, so keys remain in the base
    ``AOMQTTConfig`` file while operators can switch the privacy/overhead
    policy independently.
    """

    policy_id: str = "default"
    name: str = "default"
    token_mode: Optional[TokenMode] = None
    mqtt_qos: Optional[int] = None
    retain: Optional[bool] = None
    rotation_enabled: Optional[bool] = None
    rotation_interval_sec: Optional[int] = None
    rotation_overlap_sec: Optional[int] = None
    padding_enabled: Optional[bool] = None
    padding_mode: Optional[PaddingMode] = None
    padding_fixed_size: Optional[int] = None
    padding_bucket_size: Optional[int] = None
    padding_random_min_bytes: Optional[int] = None
    padding_random_max_bytes: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AOMQTTPolicy":
        """Build a policy from either flat or nested YAML data.

        Supported forms include both::

            token_mode: whole
            mqtt_qos: 1
            rotation_enabled: true

        and::

            policy:
              token_mode: whole
              qos: 1
              rotation:
                enabled: true
                interval_sec: 30
                overlap_sec: 5
        """
        if "policy" in data and isinstance(data["policy"], dict):
            data = dict(data["policy"])
        else:
            data = dict(data)

        rotation = data.pop("rotation", {}) or {}
        padding = data.pop("padding", {}) or {}
        if not isinstance(rotation, dict):
            raise AOMQTTConfigurationError("policy.rotation must be a mapping")
        if not isinstance(padding, dict):
            raise AOMQTTConfigurationError("policy.padding must be a mapping")

        name = str(data.get("name", data.get("id", data.get("policy_id", "default"))))
        policy_id = str(data.get("id", data.get("policy_id", name)))
        token_mode = data.get("token_mode")
        if token_mode is not None and token_mode not in ("whole", "hierarchical"):
            raise AOMQTTConfigurationError("policy.token_mode must be 'whole' or 'hierarchical'")

        qos_value = data.get("mqtt_qos", data.get("qos"))
        mqtt_qos = None if qos_value is None else _as_int(qos_value, field="policy.qos")
        if mqtt_qos is not None and mqtt_qos not in (0, 1, 2):
            raise AOMQTTConfigurationError("policy.qos must be 0, 1, or 2")

        retain = data.get("retain")
        rotation_enabled = rotation.get("enabled", data.get("rotation_enabled"))
        rotation_interval_sec = rotation.get("interval_sec", data.get("rotation_interval_sec"))
        rotation_overlap_sec = rotation.get("overlap_sec", data.get("rotation_overlap_sec"))

        padding_enabled = padding.get("enabled", data.get("padding_enabled"))
        padding_mode = padding.get("mode", data.get("padding_mode"))
        if padding_mode is not None and padding_mode not in ("none", "fixed", "bucket", "random"):
            raise AOMQTTConfigurationError("policy.padding.mode must be 'none', 'fixed', 'bucket', or 'random'")

        return cls(
            policy_id=policy_id,
            name=name,
            token_mode=token_mode,  # type: ignore[arg-type]
            mqtt_qos=mqtt_qos,
            retain=None if retain is None else _as_bool(retain, field="policy.retain"),
            rotation_enabled=None if rotation_enabled is None else _as_bool(rotation_enabled, field="policy.rotation.enabled"),
            rotation_interval_sec=None if rotation_interval_sec is None else _as_int(rotation_interval_sec, field="policy.rotation.interval_sec"),
            rotation_overlap_sec=None if rotation_overlap_sec is None else _as_int(rotation_overlap_sec, field="policy.rotation.overlap_sec"),
            padding_enabled=None if padding_enabled is None else _as_bool(padding_enabled, field="policy.padding.enabled"),
            padding_mode=padding_mode,  # type: ignore[arg-type]
            padding_fixed_size=None if padding.get("fixed_size", data.get("padding_fixed_size")) is None else _as_int(padding.get("fixed_size", data.get("padding_fixed_size")), field="policy.padding.fixed_size"),
            padding_bucket_size=None if padding.get("bucket_size", data.get("padding_bucket_size")) is None else _as_int(padding.get("bucket_size", data.get("padding_bucket_size")), field="policy.padding.bucket_size"),
            padding_random_min_bytes=None if padding.get("random_min_bytes", data.get("padding_random_min_bytes")) is None else _as_int(padding.get("random_min_bytes", data.get("padding_random_min_bytes")), field="policy.padding.random_min_bytes"),
            padding_random_max_bytes=None if padding.get("random_max_bytes", data.get("padding_random_max_bytes")) is None else _as_int(padding.get("random_max_bytes", data.get("padding_random_max_bytes")), field="policy.padding.random_max_bytes"),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AOMQTTPolicy":
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    def apply_to_config(self, config: AOMQTTConfig) -> AOMQTTConfig:
        values: Dict[str, Any] = {}
        if self.token_mode is not None:
            values["token_mode"] = self.token_mode
        if self.mqtt_qos is not None:
            values["mqtt_qos"] = self.mqtt_qos
        if self.retain is not None:
            values["retain"] = self.retain
        if self.rotation_enabled is not None:
            values["rotation_enabled"] = self.rotation_enabled
        if self.rotation_interval_sec is not None:
            values["rotation_interval_sec"] = self.rotation_interval_sec
        if self.rotation_overlap_sec is not None:
            values["rotation_overlap_sec"] = self.rotation_overlap_sec
        if self.padding_enabled is not None:
            values["padding_enabled"] = self.padding_enabled
        if self.padding_mode is not None:
            values["padding_mode"] = self.padding_mode
            if self.padding_mode == "none" and self.padding_enabled is None:
                values["padding_enabled"] = False
            elif self.padding_mode != "none" and self.padding_enabled is None:
                values["padding_enabled"] = True
        if self.padding_fixed_size is not None:
            values["padding_fixed_size"] = self.padding_fixed_size
        if self.padding_bucket_size is not None:
            values["padding_bucket_size"] = self.padding_bucket_size
        if self.padding_random_min_bytes is not None:
            values["padding_random_min_bytes"] = self.padding_random_min_bytes
        if self.padding_random_max_bytes is not None:
            values["padding_random_max_bytes"] = self.padding_random_max_bytes

        values["policy_id"] = self.policy_id
        values["policy_name"] = self.name
        merged = AOMQTTConfig(**{**config.to_dict(redact=False), **values})
        merged.validate()
        return merged

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "token_mode": self.token_mode,
            "mqtt_qos": self.mqtt_qos,
            "retain": self.retain,
            "rotation_enabled": self.rotation_enabled,
            "rotation_interval_sec": self.rotation_interval_sec,
            "rotation_overlap_sec": self.rotation_overlap_sec,
            "padding_enabled": self.padding_enabled,
            "padding_mode": self.padding_mode,
            "padding_fixed_size": self.padding_fixed_size,
            "padding_bucket_size": self.padding_bucket_size,
            "padding_random_min_bytes": self.padding_random_min_bytes,
            "padding_random_max_bytes": self.padding_random_max_bytes,
        }


class PolicyController:
    """Load and apply external AOMQTT policies.

    v0.7 deliberately keeps this controller deterministic and operator-driven.
    Automatic policy selection based on observed metrics is planned for v0.8.
    """

    def __init__(self, policy: AOMQTTPolicy, *, source: str = ""):
        self.policy = policy
        self.source = source

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PolicyController":
        return cls(AOMQTTPolicy.from_yaml(path), source=str(path))

    def apply(self, config: AOMQTTConfig) -> AOMQTTConfig:
        return self.policy.apply_to_config(config)

    @staticmethod
    def load_policies(path: str | Path) -> list[AOMQTTPolicy]:
        """Load a policy matrix file.

        A file with ``policies: [...]`` returns each item as an AOMQTTPolicy. A
        single-policy file is accepted and returned as a one-element list.
        """
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = yaml.safe_load(f) or {}
        if "policies" not in data:
            return [AOMQTTPolicy.from_dict(data)]
        policies = data["policies"]
        if not isinstance(policies, Iterable) or isinstance(policies, (str, bytes)):
            raise AOMQTTConfigurationError("policies must be a list")
        result: list[AOMQTTPolicy] = []
        for item in policies:
            if not isinstance(item, dict):
                raise AOMQTTConfigurationError("each policy entry must be a mapping")
            result.append(AOMQTTPolicy.from_dict(item))
        return result
