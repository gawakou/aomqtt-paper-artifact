"""MQTT control topic helpers for AOMQTT."""

from __future__ import annotations


def _validate_group_id(group_id: str) -> None:
    if not group_id:
        raise ValueError("group_id must not be empty")
    if "+" in group_id or "#" in group_id:
        raise ValueError("group_id must not contain MQTT wildcard characters")


def control_policy_topic(group_id: str) -> str:
    """Return the Policy distribution topic for a group."""
    _validate_group_id(group_id)
    return f"aomqtt/control/{group_id}/policy"


def control_ack_topic(group_id: str) -> str:
    """Return the Policy ACK topic for a group."""
    _validate_group_id(group_id)
    return f"aomqtt/control/{group_id}/ack"


def control_status_topic(group_id: str) -> str:
    """Return the Policy application status topic for a group."""
    _validate_group_id(group_id)
    return f"aomqtt/control/{group_id}/status"


def control_all_topic(group_id: str) -> str:
    """Return the wildcard topic for observing all control messages in a group."""
    _validate_group_id(group_id)
    return f"aomqtt/control/{group_id}/#"
