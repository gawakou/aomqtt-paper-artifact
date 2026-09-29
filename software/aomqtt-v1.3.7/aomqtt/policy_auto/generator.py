"""Policy generation for observation-driven Policy control."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from .rules import PolicyDecision, RuleThresholds


def load_policy_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("policy YAML must contain a mapping")
    return data


def save_policy_yaml(policy: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(policy, f, sort_keys=False, allow_unicode=True)


def _extract_policy_dict(data: dict[str, Any]) -> dict[str, Any]:
    if "policy" in data and isinstance(data["policy"], dict):
        return data["policy"]
    return data


def _clamp(value: int | float, minimum: int | float, maximum: int | float) -> int | float:
    return max(minimum, min(maximum, value))


def _ensure_rotation(policy: dict[str, Any]) -> dict[str, Any]:
    rotation = policy.setdefault("rotation", {})
    if not isinstance(rotation, dict):
        rotation = {}
        policy["rotation"] = rotation
    rotation.setdefault("enabled", True)
    rotation.setdefault("interval_sec", 30)
    rotation.setdefault("overlap_sec", 0)
    return rotation


def _ensure_padding(policy: dict[str, Any]) -> dict[str, Any]:
    padding = policy.setdefault("padding", {})
    if not isinstance(padding, dict):
        padding = {}
        policy["padding"] = padding
    padding.setdefault("enabled", False)
    padding.setdefault("mode", "none")
    return padding


def _policy_id(policy: dict[str, Any]) -> str:
    return str(policy.get("id") or policy.get("policy_id") or "policy")


def _set_policy_id(policy: dict[str, Any], policy_id: str) -> None:
    if "id" in policy or "policy_id" not in policy:
        policy["id"] = policy_id
    else:
        policy["policy_id"] = policy_id


def _reduce_padding(policy: dict[str, Any], thresholds: RuleThresholds) -> None:
    padding = _ensure_padding(policy)
    mode = str(padding.get("mode", "none"))

    if not padding.get("enabled", False):
        return

    if mode == "fixed":
        fixed_size = int(padding.get("fixed_size", 512))
        if fixed_size > thresholds.min_fixed_padding_size:
            padding["fixed_size"] = max(thresholds.min_fixed_padding_size, fixed_size // 2)
        else:
            padding["mode"] = "bucket"
            padding["bucket_size"] = max(
                thresholds.min_padding_bucket_size,
                int(padding.get("bucket_size", thresholds.min_padding_bucket_size)),
            )

    elif mode == "bucket":
        bucket_size = int(padding.get("bucket_size", 256))
        padding["bucket_size"] = max(thresholds.min_padding_bucket_size, bucket_size // 2)

    elif mode == "random":
        random_max = int(padding.get("random_max_bytes", 128))
        padding["random_max_bytes"] = max(0, random_max // 2)

    else:
        padding["enabled"] = False


def generate_next_policy_dict(
    base_policy_data: dict[str, Any],
    decision: PolicyDecision,
    *,
    sequence_no: int,
    thresholds: RuleThresholds | None = None,
    auto_policy_id: str | None = None,
) -> dict[str, Any]:
    """Generate a next Policy YAML dictionary from a base Policy and decision."""
    th = thresholds or RuleThresholds()

    data = copy.deepcopy(base_policy_data)
    policy = _extract_policy_dict(data)

    old_id = _policy_id(policy)
    new_id = auto_policy_id or f"{old_id}_auto_s{sequence_no}"
    _set_policy_id(policy, new_id)

    old_name = str(policy.get("name") or old_id)
    policy["name"] = f"{old_name}_auto_s{sequence_no}"

    policy.setdefault("token_mode", "whole")
    policy.setdefault("qos", policy.get("mqtt_qos", 1))
    policy.setdefault("retain", False)

    if decision.action == "increase_overlap":
        rotation = _ensure_rotation(policy)
        current = int(rotation.get("overlap_sec", 0))
        rotation["overlap_sec"] = int(
            _clamp(
                current + th.overlap_step_sec,
                th.min_overlap_sec,
                th.max_overlap_sec,
            )
        )

    elif decision.action == "decrease_overlap":
        rotation = _ensure_rotation(policy)
        current = int(rotation.get("overlap_sec", 0))
        rotation["overlap_sec"] = int(
            _clamp(
                current - th.overlap_step_sec,
                th.min_overlap_sec,
                th.max_overlap_sec,
            )
        )

    elif decision.action == "reduce_padding":
        _reduce_padding(policy, th)

    elif decision.action in {"keep", "hold_policy_switch"}:
        pass

    else:
        raise ValueError(f"unsupported policy decision action: {decision.action}")

    metadata = data.setdefault("auto_control", {})
    metadata["source_policy_id"] = old_id
    metadata["generated_policy_id"] = new_id
    metadata["sequence_no"] = sequence_no
    metadata["decision_action"] = decision.action
    metadata["decision_reason"] = decision.reason
    metadata["decision_changes"] = decision.changes

    return data
