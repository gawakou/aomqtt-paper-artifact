from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyTraceFields:
    policy_id: str = "unknown"
    sequence_no: int = 0
    key_id: str = "unknown"
    controller_id: str = "unknown"


def extract_policy_trace_fields(raw_payload: bytes | str | dict[str, Any]) -> PolicyTraceFields:
    """
    Best-effort extraction for rejected ACK traceability.

    Even when a control policy is rejected before full ControlPolicyMessage
    construction, the receiver should preserve policy_id, sequence_no, key_id,
    and controller_id whenever possible.
    """

    obj: Any

    if isinstance(raw_payload, dict):
        obj = raw_payload
    else:
        if isinstance(raw_payload, bytes):
            text = raw_payload.decode("utf-8", errors="replace")
        else:
            text = raw_payload

        try:
            obj = json.loads(text)
        except Exception:
            return PolicyTraceFields()

    if not isinstance(obj, dict):
        return PolicyTraceFields()

    policy_obj = obj.get("policy")
    if not isinstance(policy_obj, dict):
        policy_obj = {}

    metadata_obj = obj.get("metadata")
    if not isinstance(metadata_obj, dict):
        metadata_obj = {}

    policy_id = _first_str(
        policy_obj.get("id"),
        policy_obj.get("policy_id"),
        obj.get("policy_id"),
        obj.get("id"),
    )

    sequence_no = _first_int(
        obj.get("sequence_no"),
        policy_obj.get("sequence_no"),
        metadata_obj.get("sequence_no"),
    )

    key_id = _first_str(
        obj.get("key_id"),
        obj.get("signing_key_id"),
        policy_obj.get("key_id"),
        metadata_obj.get("key_id"),
    )

    controller_id = _first_str(
        obj.get("controller_id"),
        policy_obj.get("controller_id"),
        metadata_obj.get("controller_id"),
    )

    return PolicyTraceFields(
        policy_id=policy_id or "unknown",
        sequence_no=sequence_no if sequence_no is not None else 0,
        key_id=key_id or "unknown",
        controller_id=controller_id or "unknown",
    )


def _first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                continue
    return None
