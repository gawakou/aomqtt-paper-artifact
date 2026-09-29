"""Message builders for AOMQTT Policy ACK and status reporting."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional


ACK_ACCEPTED = "accepted"
ACK_REJECTED = "rejected"

STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"

VALID_ACK_STATUSES = {ACK_ACCEPTED, ACK_REJECTED}
VALID_APPLICATION_STATUSES = {STATUS_APPLIED, STATUS_FAILED}


def build_policy_ack(
    *,
    client_id: str,
    role: str,
    policy_id: str,
    sequence_no: int,
    status: str,
    received_at: Optional[float] = None,
    will_apply_at: Optional[float] = None,
    reason: Optional[str] = None,
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Policy ACK message."""
    if status not in VALID_ACK_STATUSES:
        raise ValueError(f"invalid ACK status: {status}")

    if not client_id:
        raise ValueError("client_id must not be empty")
    if not role:
        raise ValueError("role must not be empty")
    if not policy_id:
        raise ValueError("policy_id must not be empty")
    if sequence_no < 0:
        raise ValueError("sequence_no must be non-negative")

    msg: Dict[str, Any] = {
        "client_id": client_id,
        "role": role,
        "policy_id": policy_id,
        "sequence_no": sequence_no,
        "status": status,
        "received_at": time.time() if received_at is None else received_at,
    }

    if status == ACK_ACCEPTED and will_apply_at is not None:
        msg["will_apply_at"] = will_apply_at

    if reason:
        msg["reason"] = reason
    if reason_code:
        msg["reason_code"] = reason_code

    return msg


def build_policy_status(
    *,
    client_id: str,
    role: str,
    policy_id: str,
    sequence_no: int,
    status: str,
    event_time: Optional[float] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Policy application status message."""
    if status not in VALID_APPLICATION_STATUSES:
        raise ValueError(f"invalid application status: {status}")

    if not client_id:
        raise ValueError("client_id must not be empty")
    if not role:
        raise ValueError("role must not be empty")
    if not policy_id:
        raise ValueError("policy_id must not be empty")
    if sequence_no < 0:
        raise ValueError("sequence_no must be non-negative")

    now = time.time() if event_time is None else event_time

    msg: Dict[str, Any] = {
        "client_id": client_id,
        "role": role,
        "policy_id": policy_id,
        "sequence_no": sequence_no,
        "status": status,
    }

    if status == STATUS_APPLIED:
        msg["applied_at"] = now
    elif status == STATUS_FAILED:
        msg["failed_at"] = now

    if reason:
        msg["reason"] = reason

    return msg


def to_json_bytes(message: Dict[str, Any]) -> bytes:
    """Serialize a control message to UTF-8 JSON bytes."""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def from_json_bytes(payload: bytes) -> Dict[str, Any]:
    """Deserialize UTF-8 JSON bytes into a dictionary."""
    obj = json.loads(payload.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("control message must be a JSON object")
    return obj
