from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


from .core.config import AOMQTTConfig
from .core.policy import AOMQTTPolicy
from .exceptions import AOMQTTConfigurationError
from .control_security import (
    PolicySafetyLimits,
    sign_control_message_dict,
    validate_policy_message_time_and_replay,
    verify_control_message_dict,
)
from .control_plane.client_reporter import PolicyAckStatusReporter
from .policy_guard import PolicyGuard

LOGGER = logging.getLogger(__name__)

PolicyApplyCallback = Callable[[AOMQTTPolicy, "ControlPolicyMessage"], None]
PolicyEventCallback = Callable[[str, "ControlPolicyMessage"], None]


def control_policy_topic(group_id: str, *, prefix: str = "aomqtt/control") -> str:
    """Return the MQTT control topic used to distribute policies."""
    group = group_id.strip().strip("/")
    if not group:
        raise AOMQTTConfigurationError("group_id must not be empty")
    return f"{prefix.strip().strip('/')}/{group}/policy"


@dataclass(frozen=True)
class ControlPolicyMessage:
    """Policy update distributed through an MQTT control topic.

    v0.8.0 intentionally focuses on distribution and synchronized application.
    ACK, rollback, and automatic policy selection are planned for v0.8.1+.
    """

    policy: AOMQTTPolicy
    group_id: str
    valid_from: float
    grace_period_sec: float = 5.0
    schema_version: str = "aomqtt-policy-v1"
    issued_at: float = 0.0
    source_topic: str = ""
    sequence_no: int | None = None
    expires_at: float | None = None
    signature: dict[str, Any] | None = None

    @property
    def policy_id(self) -> str:
        return self.policy.policy_id

    @property
    def policy_name(self) -> str:
        return self.policy.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "group_id": self.group_id,
            "issued_at": self.issued_at or time.time(),
            "valid_from": self.valid_from,
            "grace_period_sec": self.grace_period_sec,
            "sequence_no": self.sequence_no,
            "expires_at": self.expires_at,
            "policy": policy_to_wire_dict(self.policy),
            "signature": self.signature,
        }

    def to_json_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")



def _optional(value: Any) -> Any:
    return value if value is not None else None



def policy_to_wire_dict(policy: AOMQTTPolicy) -> dict[str, Any]:
    """Convert an AOMQTTPolicy into a compact nested control-message form."""
    return {
        "id": policy.policy_id,
        "name": policy.name,
        "token_mode": policy.token_mode,
        "qos": policy.mqtt_qos,
        "retain": policy.retain,
        "rotation": {
            "enabled": policy.rotation_enabled,
            "interval_sec": policy.rotation_interval_sec,
            "overlap_sec": policy.rotation_overlap_sec,
        },
        "padding": {
            "enabled": policy.padding_enabled,
            "mode": policy.padding_mode,
            "fixed_size": policy.padding_fixed_size,
            "bucket_size": policy.padding_bucket_size,
            "random_min_bytes": policy.padding_random_min_bytes,
            "random_max_bytes": policy.padding_random_max_bytes,
        },
    }



def _strip_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj]
    return obj



def build_control_policy_message(
    policy: AOMQTTPolicy,
    *,
    group_id: str,
    valid_from: Optional[float] = None,
    valid_after_sec: float = 5.0,
    grace_period_sec: float = 5.0,
    sequence_no: int | None = None,
    expires_at: float | None = None,
    expires_after_sec: float | None = None,
    signing_private_key: str | None = None,
    signing_key_id: str = "policy-signing-key-1",
) -> ControlPolicyMessage:
    now = time.time()
    exp = expires_at
    if exp is None and expires_after_sec is not None:
        exp = now + float(expires_after_sec)
    msg = ControlPolicyMessage(
        policy=policy,
        group_id=group_id,
        valid_from=float(valid_from if valid_from is not None else now + valid_after_sec),
        grace_period_sec=float(grace_period_sec),
        issued_at=now,
        sequence_no=sequence_no,
        expires_at=exp,
    )
    if signing_private_key:
        signed = sign_control_message_dict(_strip_none(msg.to_dict()), signing_private_key, key_id=signing_key_id)
        msg = ControlPolicyMessage(
            policy=msg.policy,
            group_id=msg.group_id,
            valid_from=msg.valid_from,
            grace_period_sec=msg.grace_period_sec,
            schema_version=msg.schema_version,
            issued_at=msg.issued_at,
            sequence_no=msg.sequence_no,
            expires_at=msg.expires_at,
            signature=signed.get("signature"),
        )
    return msg



def parse_control_policy_message(
    payload: bytes | str,
    *,
    source_topic: str = "",
    signing_public_key: str | None = None,
    require_signature: bool = False,
    allowed_signature_key_ids: set[str] | None = None,
    latest_sequence_no: int | None = None,
    safety_limits: PolicySafetyLimits | None = None,
) -> ControlPolicyMessage:
    """Parse and validate a control-topic policy message."""
    if isinstance(payload, bytes):
        text = payload.decode("utf-8")
    else:
        text = payload
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AOMQTTConfigurationError("control policy payload must be JSON") from exc
    if not isinstance(data, dict):
        raise AOMQTTConfigurationError("control policy payload must be a JSON object")

    if signing_public_key is not None or require_signature:
        if signing_public_key is None:
            raise AOMQTTConfigurationError("a signing public key is required when require_signature is enabled")
        verify_control_message_dict(
            data,
            signing_public_key,
            require_signature=require_signature,
            allowed_signature_key_ids=allowed_signature_key_ids,
        )

    policy_data = data.get("policy", data)
    if not isinstance(policy_data, dict):
        raise AOMQTTConfigurationError("control policy message must contain a policy object")
    policy = AOMQTTPolicy.from_dict({"policy": policy_data})
    group_id = str(data.get("group_id", "default"))
    valid_from = float(data.get("valid_from", time.time()))
    grace_period_sec = float(data.get("grace_period_sec", data.get("grace_period", 5.0)))
    schema_version = str(data.get("schema_version", "aomqtt-policy-v1"))
    issued_at = float(data.get("issued_at", 0.0) or 0.0)
    raw_sequence = data.get("sequence_no")
    sequence_no = None if raw_sequence is None else int(raw_sequence)
    raw_expires = data.get("expires_at")
    expires_at = None if raw_expires is None else float(raw_expires)
    signature = data.get("signature") if isinstance(data.get("signature"), dict) else None
    msg = ControlPolicyMessage(
        policy=policy,
        group_id=group_id,
        valid_from=valid_from,
        grace_period_sec=grace_period_sec,
        schema_version=schema_version,
        issued_at=issued_at,
        source_topic=source_topic,
        sequence_no=sequence_no,
        expires_at=expires_at,
        signature=signature,
    )
    if safety_limits is not None:
        safety_limits.validate_policy(policy)
    validate_policy_message_time_and_replay(
        msg,
        latest_sequence_no=latest_sequence_no,
        require_sequence_no=require_signature,
    )
    return msg



def _make_paho_client(client_id: str, protocol: int | None = None):
    try:
        import paho.mqtt.client as mqtt
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("paho-mqtt is required for MQTT control-topic communication") from exc
    if protocol is None:
        protocol = mqtt.MQTTv311
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=protocol,
        )
    except Exception:
        return mqtt.Client(client_id=client_id, protocol=protocol)



def extract_control_policy_identity_from_payload(payload: bytes | str) -> tuple[str, int]:
    """Extract policy_id and sequence_no from a raw control-policy payload.

    This function is used when parse_control_policy_message() rejects a
    message before a ControlPolicyMessage object is constructed.
    It is best-effort and never raises.
    """
    try:
        if isinstance(payload, bytes):
            data = json.loads(payload.decode("utf-8"))
        else:
            data = json.loads(payload)

        if not isinstance(data, dict):
            return "unknown", 0

        policy = data.get("policy", {})
        if isinstance(policy, dict):
            policy_id = str(policy.get("id") or policy.get("policy_id") or "unknown")
        else:
            policy_id = str(data.get("policy_id") or "unknown")

        try:
            sequence_no = int(data.get("sequence_no", 0))
        except Exception:
            sequence_no = 0

        if sequence_no < 0:
            sequence_no = 0

        return policy_id or "unknown", sequence_no

    except Exception:
        return "unknown", 0



def extract_policy_guard_input_from_payload(payload: bytes | str) -> dict[str, Any]:
    """Extract a best-effort policy dictionary for client-side PolicyGuard.

    This function intentionally uses the raw control-policy payload instead of
    ControlPolicyMessage.policy because unsafe controller-supplied fields may
    be ignored during policy object construction.
    """
    if isinstance(payload, bytes):
        text_payload = payload.decode("utf-8", errors="replace")
    else:
        text_payload = payload

    try:
        data = json.loads(text_payload)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    policy_obj = data.get("policy")
    if isinstance(policy_obj, dict):
        guard_input = dict(policy_obj)
    else:
        guard_input = {}

    # Preserve top-level control-plane fields for guard checks.
    for key in (
        "sequence_no",
        "valid_from",
        "valid_until",
        "expires_at",
        "key_id",
        "signing_key_id",
        "controller_id",
    ):
        if key in data and key not in guard_input:
            guard_input[key] = data[key]

    # PolicyGuard expects valid_until. ControlPolicyMessage uses expires_at.
    if "valid_until" not in guard_input and "expires_at" in guard_input:
        guard_input["valid_until"] = guard_input["expires_at"]

    return guard_input


class ControlTopicPolicyReceiver:
    """Subscribe to an MQTT control topic and apply policy updates.

    This receiver is intentionally independent from the data-plane MQTT client.
    That keeps v0.8.0 minimally invasive: a Publisher/Subscriber can run its
    normal AOMQTT transport while a lightweight control client listens for
    policy updates.
    """

    def __init__(
        self,
        *,
        broker_host: str,
        broker_port: int = 1883,
        client_id: str,
        group_id: str,
        apply_callback: PolicyApplyCallback,
        control_topic: Optional[str] = None,
        qos: int = 1,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls: bool = False,
        on_event: Optional[PolicyEventCallback] = None,
        signing_public_key: str | None = None,
        require_signature: bool = True,
        allowed_signature_key_ids: set[str] | None = None,
        safety_limits: PolicySafetyLimits | None = None,
        policy_reporter=None,
        control_role: str = "client",
        report_client_id: str | None = None,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id
        self.group_id = group_id
        self.control_topic = control_topic or control_policy_topic(group_id)
        self.qos = qos
        self.apply_callback = apply_callback
        self.on_event = on_event
        self.signing_public_key = signing_public_key
        self.require_signature = require_signature
        self.allowed_signature_key_ids = allowed_signature_key_ids
        if require_signature and signing_public_key is None:
            raise AOMQTTConfigurationError("signing_public_key is required when require_signature=True")
        self.safety_limits = safety_limits or PolicySafetyLimits()
        self.client = _make_paho_client(client_id=client_id)
        self.policy_reporter = policy_reporter
        if self.policy_reporter is None:
            self.policy_reporter = PolicyAckStatusReporter(
                mqtt_client=self.client,
                group_id=self.group_id,
                client_id=report_client_id or self.client_id,
                role=control_role,
                qos=self.qos,
            )
        self._timers: list[threading.Timer] = []
        self._lock = threading.Lock()
        self._latest_policy_id: str = ""
        self._latest_sequence_no: int | None = None
        self._policy_guard = PolicyGuard()
        self._last_known_good_message: ControlPolicyMessage | None = None

        if username is not None:
            self.client.username_pw_set(username=username, password=password)
        if tls:
            self.client.tls_set()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    @property
    def latest_policy_id(self) -> str:
        return self._latest_policy_id

    def start(self, *, keepalive: int = 60) -> None:
        self.client.connect(self.broker_host, self.broker_port, keepalive=keepalive)
        self.client.loop_start()

    def stop(self) -> None:
        with self._lock:
            for timer in self._timers:
                timer.cancel()
            self._timers.clear()
        self.client.loop_stop()
        self.client.disconnect()

    def _emit(self, event: str, message: ControlPolicyMessage) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event, message)
            except Exception:  # pragma: no cover - observer safety
                LOGGER.exception("control policy event callback failed")

    def _report_ack_accepted(self, message: ControlPolicyMessage) -> None:
        if self.policy_reporter is None:
            return
        try:
            self.policy_reporter.publish_ack_accepted(
                policy_id=message.policy_id,
                sequence_no=int(message.sequence_no or 0),
                received_at=time.time(),
                will_apply_at=message.valid_from,
            )
        except Exception as exc:  # pragma: no cover - observer safety
            LOGGER.warning("failed to publish policy ACK accepted: %s", exc)

    def _report_ack_rejected(
        self,
        policy_id: str,
        sequence_no: int,
        reason: str,
        reason_code: str | None = None,
    ) -> None:
        if self.policy_reporter is None:
            return
        try:
            self.policy_reporter.publish_ack_rejected(
                policy_id=policy_id or "unknown",
                sequence_no=max(int(sequence_no or 0), 0),
                received_at=time.time(),
                reason=reason,
                reason_code=reason_code,
            )
        except Exception as exc:  # pragma: no cover - observer safety
            LOGGER.warning("failed to publish policy ACK rejected: %s", exc)

    def _report_status_applied(self, message: ControlPolicyMessage) -> None:
        if self.policy_reporter is None:
            return
        try:
            self.policy_reporter.publish_status_applied(
                policy_id=message.policy_id,
                sequence_no=int(message.sequence_no or 0),
            )
        except Exception as exc:  # pragma: no cover - observer safety
            LOGGER.warning("failed to publish policy status applied: %s", exc)

    def _report_status_failed(self, message: ControlPolicyMessage, reason: str) -> None:
        if self.policy_reporter is None:
            return
        try:
            self.policy_reporter.publish_status_failed(
                policy_id=message.policy_id,
                sequence_no=int(message.sequence_no or 0),
                reason=reason,
            )
        except Exception as exc:  # pragma: no cover - observer safety
            LOGGER.warning("failed to publish policy status failed: %s", exc)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        LOGGER.info("control receiver connected: reason_code=%s topic=%s", reason_code, self.control_topic)
        client.subscribe(self.control_topic, qos=self.qos)

    def _on_message(self, client, userdata, msg):
        try:
            message = parse_control_policy_message(
                msg.payload,
                source_topic=msg.topic,
                signing_public_key=self.signing_public_key,
                require_signature=self.require_signature,
                allowed_signature_key_ids=self.allowed_signature_key_ids,
                latest_sequence_no=self._latest_sequence_no,
                safety_limits=self.safety_limits,
            )
        except AOMQTTConfigurationError as exc:
            LOGGER.warning("rejected control policy on %s: %s", msg.topic, exc)
            policy_id, sequence_no = extract_control_policy_identity_from_payload(msg.payload)
            self._report_ack_rejected(policy_id, sequence_no, str(exc))
            return
        except Exception as exc:
            LOGGER.exception("ignored malformed control policy message on %s", msg.topic)
            policy_id, sequence_no = extract_control_policy_identity_from_payload(msg.payload)
            self._report_ack_rejected(policy_id, sequence_no, str(exc))
            return
        if message.group_id != self.group_id:
            LOGGER.info("ignored policy for group_id=%s on receiver group_id=%s", message.group_id, self.group_id)
            return

        guard_input = extract_policy_guard_input_from_payload(msg.payload)
        guard_result = self._policy_guard.validate(
            guard_input,
            last_sequence_no=self._latest_sequence_no,
        )
        if not guard_result.accepted:
            self._report_ack_rejected(
                message.policy_id,
                int(message.sequence_no or 0),
                guard_result.detail or guard_result.reason_code,
                reason_code=guard_result.reason_code,
            )
            self._emit("rejected", message)
            return

        self._report_ack_accepted(message)
        delay = max(0.0, message.valid_from - time.time())
        LOGGER.info(
            "scheduled policy_id=%s name=%s valid_from=%.3f delay=%.3fs",
            message.policy_id,
            message.policy_name,
            message.valid_from,
            delay,
        )
        self._latest_policy_id = message.policy_id
        if message.sequence_no is not None:
            self._latest_sequence_no = message.sequence_no
        self._emit("scheduled", message)
        timer = threading.Timer(delay, self._apply_message, args=(message,))
        timer.daemon = True
        with self._lock:
            self._timers.append(timer)
        timer.start()

    def _apply_message(self, message: ControlPolicyMessage) -> None:
        try:
            self.apply_callback(message.policy, message)
            self._last_known_good_message = message
            self._report_status_applied(message)
            self._emit("applied", message)
            LOGGER.info("applied control policy_id=%s name=%s", message.policy_id, message.policy_name)
        except Exception as exc:  # pragma: no cover - integration safety
            LOGGER.exception("failed to apply control policy_id=%s", message.policy_id)
            self._report_status_failed(message, str(exc))
            self._emit("failed", message)


class PolicyMessagePublisher:
    """Small MQTT publisher used by policy_controller_publish.py."""

    def __init__(
        self,
        *,
        broker_host: str,
        broker_port: int = 1883,
        client_id: str = "aomqtt_policy_controller",
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls: bool = False,
    ):
        self.client = _make_paho_client(client_id=client_id)
        self.broker_host = broker_host
        self.broker_port = broker_port
        if username is not None:
            self.client.username_pw_set(username=username, password=password)
        if tls:
            self.client.tls_set()

    def publish_message(
        self,
        message: ControlPolicyMessage,
        *,
        topic: Optional[str] = None,
        qos: int = 1,
        retain: bool = False,
        wait_timeout: float = 5.0,
    ) -> tuple[int, int]:
        target = topic or control_policy_topic(message.group_id)
        payload = json.dumps(_strip_none(message.to_dict()), ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.client.connect(self.broker_host, self.broker_port)
        self.client.loop_start()
        try:
            info = self.client.publish(target, payload=payload, qos=qos, retain=retain)
            info.wait_for_publish(timeout=wait_timeout)
            return int(getattr(info, "rc", 0)), int(getattr(info, "mid", -1))
        finally:
            self.client.loop_stop()
            self.client.disconnect()
