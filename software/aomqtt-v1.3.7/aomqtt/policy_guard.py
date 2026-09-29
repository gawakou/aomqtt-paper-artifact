from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class PolicyRejectReason(str, Enum):
    SECURITY_INVARIANT_VIOLATION = "security_invariant_violation"
    PAYLOAD_ENCRYPTION_DISABLE_FORBIDDEN = "payload_encryption_disable_forbidden"
    TOPIC_OBFUSCATION_DISABLE_FORBIDDEN = "topic_obfuscation_disable_forbidden"
    PADDING_LIMIT_EXCEEDED = "padding_limit_exceeded"
    ROTATION_INTERVAL_TOO_SHORT = "rotation_interval_too_short"
    ROTATION_OVERLAP_TOO_LARGE = "rotation_overlap_too_large"
    POLICY_LIFETIME_TOO_LONG = "policy_lifetime_too_long"
    TOKEN_MODE_NOT_ALLOWED = "token_mode_not_allowed"
    UNKNOWN_KEY_ID = "unknown_key_id"
    REPLAYED_SEQUENCE = "replayed_sequence"
    INVALID_POLICY = "invalid_policy"


@dataclass(frozen=True)
class PolicySafetyLimits:
    """
    Client-side safety limits.

    These limits are enforced locally by each AOMQTT client.
    Even if a Policy Controller is compromised and sends a signed policy,
    the client must reject policies that violate these constraints.
    """

    max_padding_fixed_size: int = 4096
    min_rotation_interval_sec: int = 30
    max_rotation_overlap_sec: int = 10
    max_policy_lifetime_sec: int = 3600
    allowed_token_modes: set[str] = field(
        default_factory=lambda: {"whole", "hierarchical"}
    )
    trusted_key_ids: set[str] = field(default_factory=set)

    # Security invariants.
    require_payload_encryption: bool = True
    require_topic_obfuscation: bool = True


@dataclass(frozen=True)
class PolicyGuardResult:
    accepted: bool
    reason_code: str = "accepted"
    detail: str = ""


class PolicyGuard:
    """
    Client-side Policy Guard.

    The Policy Controller is treated as a policy proposal entity, not as a
    fully trusted authority. The client independently validates policy safety
    before applying it.
    """

    def __init__(self, limits: PolicySafetyLimits | None = None):
        self.limits = limits or PolicySafetyLimits()

    def validate(
        self,
        policy: Any,
        *,
        last_sequence_no: int | None = None,
    ) -> PolicyGuardResult:
        try:
            return self._validate(policy, last_sequence_no=last_sequence_no)
        except Exception as exc:
            return PolicyGuardResult(
                accepted=False,
                reason_code=PolicyRejectReason.INVALID_POLICY.value,
                detail=f"policy guard exception: {exc}",
            )

    def _validate(
        self,
        policy: Any,
        *,
        last_sequence_no: int | None = None,
    ) -> PolicyGuardResult:
        sequence_no = _get_int(policy, ["sequence_no"])
        if last_sequence_no is not None and sequence_no is not None:
            if sequence_no <= last_sequence_no:
                return _reject(
                    PolicyRejectReason.REPLAYED_SEQUENCE,
                    f"sequence_no={sequence_no} <= last_sequence_no={last_sequence_no}",
                )

        # Payload encryption must not be disabled by controller policy.
        payload_encryption_enabled = _get_bool_any(
            policy,
            [
                ["payload_encryption", "enabled"],
                ["encryption", "enabled"],
                ["security", "payload_encryption", "enabled"],
            ],
        )
        if self.limits.require_payload_encryption and payload_encryption_enabled is False:
            return _reject(
                PolicyRejectReason.PAYLOAD_ENCRYPTION_DISABLE_FORBIDDEN,
                "payload encryption cannot be disabled by policy",
            )

        # Topic obfuscation must not be disabled by controller policy.
        topic_obfuscation_enabled = _get_bool_any(
            policy,
            [
                ["topic_obfuscation", "enabled"],
                ["topic", "obfuscation_enabled"],
                ["security", "topic_obfuscation", "enabled"],
            ],
        )
        if self.limits.require_topic_obfuscation and topic_obfuscation_enabled is False:
            return _reject(
                PolicyRejectReason.TOPIC_OBFUSCATION_DISABLE_FORBIDDEN,
                "topic obfuscation cannot be disabled by policy",
            )

        token_mode = _get_str_any(
            policy,
            [
                ["token_mode"],
                ["topic", "token_mode"],
                ["topic_obfuscation", "token_mode"],
            ],
        )
        if token_mode is not None and token_mode not in self.limits.allowed_token_modes:
            return _reject(
                PolicyRejectReason.TOKEN_MODE_NOT_ALLOWED,
                f"token_mode={token_mode} is not allowed",
            )

        key_id = _get_str_any(
            policy,
            [
                ["key_id"],
                ["crypto", "key_id"],
                ["security", "key_id"],
            ],
        )
        if self.limits.trusted_key_ids and key_id is not None:
            if key_id not in self.limits.trusted_key_ids:
                return _reject(
                    PolicyRejectReason.UNKNOWN_KEY_ID,
                    f"key_id={key_id} is not trusted",
                )

        fixed_size = _get_int_any(
            policy,
            [
                ["padding", "fixed_size"],
                ["padding", "fixed_size_bytes"],
            ],
        )
        if fixed_size is not None:
            if fixed_size > self.limits.max_padding_fixed_size:
                return _reject(
                    PolicyRejectReason.PADDING_LIMIT_EXCEEDED,
                    f"padding fixed_size={fixed_size} exceeds max={self.limits.max_padding_fixed_size}",
                )

        rotation_interval = _get_int_any(
            policy,
            [
                ["rotation", "interval_sec"],
                ["rotation", "rotation_interval_sec"],
            ],
        )
        if rotation_interval is not None:
            if rotation_interval < self.limits.min_rotation_interval_sec:
                return _reject(
                    PolicyRejectReason.ROTATION_INTERVAL_TOO_SHORT,
                    f"rotation interval={rotation_interval} is shorter than min={self.limits.min_rotation_interval_sec}",
                )

        rotation_overlap = _get_int_any(
            policy,
            [
                ["rotation", "overlap_sec"],
                ["rotation", "overlap_window_sec"],
            ],
        )
        if rotation_overlap is not None:
            if rotation_overlap > self.limits.max_rotation_overlap_sec:
                return _reject(
                    PolicyRejectReason.ROTATION_OVERLAP_TOO_LARGE,
                    f"rotation overlap={rotation_overlap} exceeds max={self.limits.max_rotation_overlap_sec}",
                )

        valid_from = _get_int_any(policy, [["valid_from"], ["policy", "valid_from"]])
        valid_until = _get_int_any(policy, [["valid_until"], ["policy", "valid_until"]])
        if valid_from is not None and valid_until is not None:
            lifetime = valid_until - valid_from
            if lifetime > self.limits.max_policy_lifetime_sec:
                return _reject(
                    PolicyRejectReason.POLICY_LIFETIME_TOO_LONG,
                    f"policy lifetime={lifetime} exceeds max={self.limits.max_policy_lifetime_sec}",
                )

        return PolicyGuardResult(accepted=True)


def _reject(reason: PolicyRejectReason, detail: str) -> PolicyGuardResult:
    return PolicyGuardResult(
        accepted=False,
        reason_code=reason.value,
        detail=detail,
    )


def _get_bool_any(obj: Any, paths: list[list[str]]) -> bool | None:
    for path in paths:
        value = _get(obj, path)
        if isinstance(value, bool):
            return value
    return None


def _get_str_any(obj: Any, paths: list[list[str]]) -> str | None:
    for path in paths:
        value = _get(obj, path)
        if isinstance(value, str):
            return value
    return None


def _get_int_any(obj: Any, paths: list[list[str]]) -> int | None:
    for path in paths:
        value = _get_int(obj, path)
        if value is not None:
            return value
    return None


def _get_int(obj: Any, path: list[str]) -> int | None:
    value = _get(obj, path)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _get(obj: Any, path: list[str]) -> Any:
    cur = obj
    for key in path:
        if isinstance(cur, Mapping):
            if key not in cur:
                return None
            cur = cur[key]
        else:
            if not hasattr(cur, key):
                return None
            cur = getattr(cur, key)
    return cur
