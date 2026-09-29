"""Client-side Policy ACK/status reporter for AOMQTT v0.8.2."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..control_security import classify_policy_rejection
from .messages import (
    ACK_ACCEPTED,
    ACK_REJECTED,
    STATUS_APPLIED,
    STATUS_FAILED,
    build_policy_ack,
    build_policy_status,
    to_json_bytes,
)
from .topics import control_ack_topic, control_status_topic


class PolicyAckStatusReporter:
    """Publish Policy ACK and application status messages.

    The mqtt_client object is expected to provide a publish(topic, payload, qos, retain)
    method compatible with paho-mqtt.
    """

    def __init__(
        self,
        *,
        mqtt_client: Any,
        group_id: str,
        client_id: str,
        role: str,
        qos: int = 1,
    ) -> None:
        if not group_id:
            raise ValueError("group_id must not be empty")
        if not client_id:
            raise ValueError("client_id must not be empty")
        if not role:
            raise ValueError("role must not be empty")

        self.mqtt_client = mqtt_client
        self.group_id = group_id
        self.client_id = client_id
        self.role = role
        self.qos = qos

    def publish_ack_accepted(
        self,
        *,
        policy_id: str,
        sequence_no: int,
        received_at: Optional[float] = None,
        will_apply_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        msg = build_policy_ack(
            client_id=self.client_id,
            role=self.role,
            policy_id=policy_id,
            sequence_no=sequence_no,
            status=ACK_ACCEPTED,
            received_at=received_at,
            will_apply_at=will_apply_at,
        )
        self._publish(control_ack_topic(self.group_id), msg)
        return msg

    def publish_ack_rejected(
        self,
        *,
        policy_id: str,
        sequence_no: int,
        received_at: Optional[float] = None,
        reason: str,
        reason_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        msg = build_policy_ack(
            client_id=self.client_id,
            role=self.role,
            policy_id=policy_id,
            sequence_no=sequence_no,
            status=ACK_REJECTED,
            received_at=received_at,
            reason=reason,
            reason_code=reason_code or classify_policy_rejection(reason),
        )
        self._publish(control_ack_topic(self.group_id), msg)
        return msg

    def publish_status_applied(
        self,
        *,
        policy_id: str,
        sequence_no: int,
        event_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        msg = build_policy_status(
            client_id=self.client_id,
            role=self.role,
            policy_id=policy_id,
            sequence_no=sequence_no,
            status=STATUS_APPLIED,
            event_time=event_time,
        )
        self._publish(control_status_topic(self.group_id), msg)
        return msg

    def publish_status_failed(
        self,
        *,
        policy_id: str,
        sequence_no: int,
        event_time: Optional[float] = None,
        reason: str,
    ) -> Dict[str, Any]:
        msg = build_policy_status(
            client_id=self.client_id,
            role=self.role,
            policy_id=policy_id,
            sequence_no=sequence_no,
            status=STATUS_FAILED,
            event_time=event_time,
            reason=reason,
        )
        self._publish(control_status_topic(self.group_id), msg)
        return msg

    def _publish(self, topic: str, msg: Dict[str, Any]) -> None:
        self.mqtt_client.publish(
            topic,
            to_json_bytes(msg),
            qos=self.qos,
            retain=False,
        )
