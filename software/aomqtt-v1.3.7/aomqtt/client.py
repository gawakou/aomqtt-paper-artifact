from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

from .core.config import AOMQTTConfig
from .core.policy import AOMQTTPolicy
from .control import ControlPolicyMessage, ControlTopicPolicyReceiver
from .core.crypto import PayloadCrypto
from .core.rotation import TokenRotation
from .core.topic_tokenizer import TopicTokenizer
from .observation import DeliveryCSVLogger, DeliveryMetric, PublishCSVLogger, PublishMetric
from .transport import TransportAdapter, TransportMessage

LOGGER = logging.getLogger(__name__)
MessageCallback = Callable[[str, Any, TransportMessage], None]


class _BaseAOMQTTClient:
    def __init__(
        self,
        *,
        broker_host: str,
        broker_port: int = 1883,
        client_id: str,
        config: Optional[AOMQTTConfig] = None,
        topic_key: Optional[str] = None,
        payload_key: Optional[str] = None,
        token_mode: str = "hierarchical",
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls: bool = False,
        transport: Optional[TransportAdapter] = None,
    ):
        if config is None:
            if topic_key is None or payload_key is None:
                raise ValueError("either config or both topic_key and payload_key must be provided")
            config = AOMQTTConfig(topic_key=topic_key, payload_key=payload_key, token_mode=token_mode)  # type: ignore[arg-type]
        config.validate()

        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id
        self.config = config
        self.tokenizer = TopicTokenizer(config)
        self.crypto = PayloadCrypto(config)
        self.rotation = TokenRotation(config)
        if transport is None:
            from .transport.paho_adapter import PahoMQTTAdapter
            transport = PahoMQTTAdapter(client_id=client_id)
        self.transport = transport
        self.connected = False
        self._control_receiver: ControlTopicPolicyReceiver | None = None
        self._policy_lock = threading.Lock()

        if username is not None:
            self.transport.username_pw_set(username=username, password=password)
        if tls:
            self.transport.tls_set()

        self.transport.set_on_connect(self._on_connect)
        self.transport.set_on_disconnect(self._on_disconnect)

    @property
    def reconnect_count(self) -> int:
        return self.transport.reconnect_count

    def _on_connect(self, flags, reason_code, properties=None, raw_client=None):
        self.connected = True
        LOGGER.info("connected to MQTT broker: reason_code=%s", reason_code)

    def _on_disconnect(self, reason_code, raw_args=None, raw_client=None):
        self.connected = False
        LOGGER.info("disconnected from MQTT broker: reason_code=%s", reason_code)

    def connect(self, keepalive: int = 60) -> None:
        self.transport.connect(self.broker_host, self.broker_port, keepalive=keepalive)

    def loop_start(self) -> None:
        self.transport.loop_start()

    def loop_stop(self) -> None:
        self.transport.loop_stop()

    def loop_forever(self) -> None:
        self.transport.loop_forever()

    def disconnect(self) -> None:
        self.transport.disconnect()

    def tokenized_topic(self, topic: str, *, epoch: Optional[str] = None) -> str:
        return self.tokenizer.tokenize(topic, epoch=epoch)

    def tokenized_filter(self, topic_filter: str, *, epoch: Optional[str] = None) -> str:
        return self.tokenizer.tokenize_filter(topic_filter, epoch=epoch)

    def current_rotation_state(self):
        return self.rotation.state()

    def apply_policy(self, policy: AOMQTTPolicy, message: ControlPolicyMessage | None = None) -> AOMQTTConfig:
        """Apply a runtime policy update to this client.

        v0.8.0 uses this hook when a Policy Controller distributes a new
        policy through an MQTT control topic.  The update intentionally keeps
        base cryptographic keys from the current config and changes only the
        runtime policy fields defined by AOMQTTPolicy.
        """
        with self._policy_lock:
            new_config = policy.apply_to_config(self.config)
            self.config = new_config
            self.tokenizer = TopicTokenizer(new_config)
            self.crypto = PayloadCrypto(new_config)
            self.rotation = TokenRotation(new_config)
            LOGGER.info(
                "applied policy update: policy_id=%s policy_name=%s valid_from=%s",
                new_config.policy_id,
                new_config.policy_name,
                "-" if message is None else f"{message.valid_from:.3f}",
            )
            return new_config

    def start_policy_control(
        self,
        *,
        group_id: str,
        control_topic: str | None = None,
        client_id: str | None = None,
        qos: int = 1,
        role: str | None = None,
        username: str | None = None,
        password: str | None = None,
        tls: bool = False,
        signing_public_key: str | None = None,
        require_signature: bool = True,
    ) -> ControlTopicPolicyReceiver:
        """Start an MQTT control-topic listener for runtime policy updates."""
        if self._control_receiver is not None:
            raise RuntimeError("policy control receiver is already running")
        if role is not None:
            control_role = role
        elif self.__class__.__name__ == "AOMQTTPublisher":
            control_role = "publisher"
        elif self.__class__.__name__ == "AOMQTTSubscriber":
            control_role = "subscriber"
        else:
            control_role = "client"

        receiver = ControlTopicPolicyReceiver(
            broker_host=self.broker_host,
            broker_port=self.broker_port,
            client_id=client_id or f"{self.client_id}_policy",
            group_id=group_id,
            control_topic=control_topic,
            qos=qos,
            control_role=control_role,
            report_client_id=self.client_id,
            username=username,
            password=password,
            tls=tls,
            apply_callback=self.apply_policy,
            on_event=self._on_control_policy_event,
            signing_public_key=signing_public_key,
            require_signature=require_signature,
        )
        receiver.start()
        self._control_receiver = receiver
        return receiver

    def stop_policy_control(self) -> None:
        if self._control_receiver is not None:
            self._control_receiver.stop()
            self._control_receiver = None

    def _on_control_policy_event(self, event: str, message: ControlPolicyMessage) -> None:
        LOGGER.info(
            "control policy event=%s policy_id=%s policy_name=%s",
            event,
            message.policy_id,
            message.policy_name,
        )

    def disconnect(self) -> None:
        self.stop_policy_control()
        self.transport.disconnect()


class AOMQTTPublisher(_BaseAOMQTTClient):
    """Publisher that uses transport-independent AOMQTT Core."""

    def _encrypt_for_topic(self, token_topic: str, payload: Any):
        aad = token_topic.encode("utf-8") if self.config.aad_bind_topic else None
        encrypted_payload, padding_stats = self.crypto.encrypt_with_stats(payload, aad=aad)
        return encrypted_payload, padding_stats

    def publish(
        self,
        topic: str,
        payload: Any,
        *,
        qos: Optional[int] = None,
        retain: Optional[bool] = None,
        epoch: Optional[str] = None,
    ):
        token_topic = self.tokenizer.tokenize(topic, epoch=epoch)
        encrypted_payload, _padding_stats = self._encrypt_for_topic(token_topic, payload)
        return self.transport.publish(
            token_topic,
            payload=encrypted_payload,
            qos=self.config.mqtt_qos if qos is None else qos,
            retain=self.config.retain if retain is None else retain,
        )

    def publish_rotating(
        self,
        topic: str,
        payload: Any,
        *,
        qos: Optional[int] = None,
        retain: Optional[bool] = None,
        timestamp: Optional[float] = None,
    ) -> list[Any]:
        infos: list[Any] = []
        for epoch in self.rotation.publish_epochs(timestamp):
            infos.append(self.publish(topic, payload, qos=qos, retain=retain, epoch=epoch))
        return infos

    def publish_observed_rotating(
        self,
        topic: str,
        payload: Any,
        *,
        qos: Optional[int] = None,
        retain: Optional[bool] = None,
        timestamp: Optional[float] = None,
        logical_seq: Optional[str | int] = None,
        message_id: Optional[str] = None,
        wait_for_publish: bool = True,
        wait_timeout: Optional[float] = None,
        csv_logger: Optional[PublishCSVLogger] = None,
    ) -> list[PublishMetric]:
        """Publish with rotation and return/write per-MQTT-message metrics.

        One logical publish may generate two MQTT PUBLISH packets during the
        overlap window. Each packet receives one PublishMetric row.
        """
        now = time.time() if timestamp is None else timestamp
        state = self.rotation.state(now)
        epochs = self.rotation.publish_epochs(now)
        effective_qos = self.config.mqtt_qos if qos is None else qos
        effective_retain = self.config.retain if retain is None else retain
        metrics: list[PublishMetric] = []

        for idx, epoch in enumerate(epochs):
            token_topic = self.tokenizer.tokenize(topic, epoch=epoch)
            encrypted_payload, padding_stats = self._encrypt_for_topic(token_topic, payload)
            start = time.perf_counter()
            error = ""
            handle = None
            success = False
            rc = -1
            mid = -1
            try:
                handle = self.transport.publish(
                    token_topic,
                    payload=encrypted_payload,
                    qos=effective_qos,
                    retain=effective_retain,
                )
                rc = int(getattr(handle, "rc", 0))
                mid = int(getattr(handle, "mid", -1))
                if wait_for_publish:
                    handle.wait_for_publish(timeout=wait_timeout)
                    success = bool(handle.is_published())
                else:
                    success = rc == 0
            except Exception as exc:  # pragma: no cover - integration safety
                error = repr(exc)
                success = False
            end = time.perf_counter()

            metric = PublishMetric(
                timestamp=time.time(),
                client_id=self.client_id,
                policy_id=self.config.policy_id,
                policy_name=self.config.policy_name,
                plaintext_topic=topic,
                token_topic=token_topic,
                token_mode=self.config.token_mode,
                rotation_enabled=self.config.rotation_enabled,
                rotation_epoch="" if epoch is None else str(epoch),
                rotation_in_overlap=state.in_overlap if self.config.rotation_enabled else False,
                overlap_duplicate=idx > 0,
                mqtt_messages_for_logical=len(epochs),
                logical_seq="" if logical_seq is None else str(logical_seq),
                message_id="" if message_id is None else str(message_id),
                qos=effective_qos,
                retain=effective_retain,
                payload_plain_bytes=padding_stats.original_plain_bytes,
                payload_padded_bytes=padding_stats.padded_plain_bytes,
                payload_encrypted_bytes=len(encrypted_payload),
                padding_enabled=padding_stats.padding_enabled,
                padding_mode=padding_stats.padding_mode,
                padding_added_bytes=padding_stats.padding_added_bytes,
                padding_overhead_ratio=padding_stats.overhead_ratio,
                payload_total_overhead_bytes=len(encrypted_payload) - padding_stats.original_plain_bytes,
                mid=mid,
                rc=rc,
                success=success,
                wait_for_publish=wait_for_publish,
                publish_complete_ms=(end - start) * 1000.0,
                reconnect_count=self.reconnect_count,
                error=error,
            )
            metrics.append(metric)
            if csv_logger is not None:
                csv_logger.write(metric)

        return metrics



def _first_present(payload: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Return the first present value while preserving valid falsy values.

    ``dict.get(...) or ...`` incorrectly drops values such as ``0``.  In the
    evaluation payloads, sequence number 0 is a valid logical message ID, so we
    treat only missing keys and ``None`` as absent.  Empty strings are also
    skipped because they are not useful as IDs in CSV-based analysis.
    """
    for key in keys:
        if key in payload and payload[key] is not None and payload[key] != "":
            return payload[key]
    return default


def _extract_delivery_fields(payload: Any) -> tuple[str, str, float]:
    """Extract message_id, logical_seq, and publisher timestamp from payload.

    v0.5/v0.6 evaluation scripts use ``message_id``, ``seq``, and ``sent_time``.
    The fallback to ``timestamp`` preserves compatibility with earlier examples.
    Sequence number 0 is preserved as a valid ID.
    """
    if isinstance(payload, dict):
        message_id = _first_present(payload, "message_id", "_aomqtt_message_id", "seq", default="")
        logical_seq = _first_present(payload, "seq", "logical_seq", default=message_id)
        ts = _first_present(payload, "sent_time", "publisher_timestamp", "timestamp", default=0.0)
        try:
            publisher_timestamp = float(ts)
        except Exception:
            publisher_timestamp = 0.0
        return str(message_id), str(logical_seq), publisher_timestamp
    return "", "", 0.0


class AOMQTTSubscriber(_BaseAOMQTTClient):
    """Subscriber that tokenizes filters and decrypts received payloads."""

    def __init__(self, *args, **kwargs):
        self._seen_message_ids_max = int(kwargs.pop("seen_message_ids_max", 10000))
        super().__init__(*args, **kwargs)
        self._callback: Optional[MessageCallback] = None
        self.transport.set_on_message(self._on_message)
        self._subscription_filters: set[str] = set()
        self._subscription_qos: dict[str, int] = {}
        self._subscription_lock = threading.RLock()
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_stop = threading.Event()
        self._delivery_logger: Optional[DeliveryCSVLogger] = None
        self._delivery_plaintext_filter: str = ""
        self._seen_message_ids: OrderedDict[str, None] = OrderedDict()
        self._plaintext_subscriptions: dict[str, int] = {}

    def _remember_subscription(self, token_filter: str, qos: int) -> None:
        with self._subscription_lock:
            self._subscription_filters.add(token_filter)
            self._subscription_qos[token_filter] = qos

    def _resubscribe_current_filters(self) -> None:
        """Re-subscribe stored token filters after a broker reconnect.

        Paho MQTT v3.1.1 uses clean sessions by default.  If the broker or
        network drops the connection, broker-side subscriptions may disappear
        even though the process continues running.  This method is called from
        ``_on_connect`` and deliberately re-sends SUBSCRIBE for every remembered
        token filter, rather than only adding filters that are missing locally.
        """
        with self._subscription_lock:
            subscriptions = list(self._subscription_qos.items())
        for token_filter, qos in subscriptions:
            self.transport.subscribe(token_filter, qos=qos)
            LOGGER.info("re-subscribed token filter after reconnect: %s", token_filter)

    def _on_connect(self, flags, reason_code, properties=None, raw_client=None):
        super()._on_connect(flags, reason_code, properties, raw_client)
        self._resubscribe_current_filters()
        self._refresh_policy_subscriptions()

    def subscribe(
        self,
        topic_filter: str,
        *,
        callback: MessageCallback,
        qos: Optional[int] = None,
        epoch: Optional[str] = None,
    ) -> tuple[int, int]:
        self._callback = callback
        effective_qos = self.config.mqtt_qos if qos is None else qos
        self._plaintext_subscriptions[topic_filter] = effective_qos
        token_filter = self.tokenizer.tokenize_filter(topic_filter, epoch=epoch)
        self._remember_subscription(token_filter, effective_qos)
        return self.transport.subscribe(token_filter, qos=effective_qos)

    def enable_delivery_observation(
        self,
        *,
        csv_logger: Optional[DeliveryCSVLogger] = None,
        plaintext_filter: str = "",
        reset_seen: bool = True,
    ) -> None:
        """Enable subscriber-side delivery/decryption metrics.

        Delivery metrics are written when ``csv_logger`` is provided. Duplicate
        detection and application-delivery suppression are always active.
        ``logical_seq`` is used as the duplicate key when available, with
        ``message_id`` used as a fallback.
        """
        self._delivery_logger = csv_logger
        self._delivery_plaintext_filter = plaintext_filter
        if reset_seen:
            self._seen_message_ids.clear()

    def subscribe_observed(
        self,
        topic_filter: str,
        *,
        callback: MessageCallback,
        qos: Optional[int] = None,
        epoch: Optional[str] = None,
        csv_logger: Optional[DeliveryCSVLogger] = None,
    ) -> tuple[int, int]:
        self.enable_delivery_observation(csv_logger=csv_logger, plaintext_filter=topic_filter)
        return self.subscribe(topic_filter, callback=callback, qos=qos, epoch=epoch)

    def subscribe_rotating(
        self,
        topic_filter: str,
        *,
        callback: MessageCallback,
        qos: Optional[int] = None,
        refresh_interval_sec: float = 1.0,
    ) -> None:
        self._callback = callback
        effective_qos = self.config.mqtt_qos if qos is None else qos
        self._plaintext_subscriptions[topic_filter] = effective_qos

        def refresh_once() -> None:
            for epoch in self.rotation.subscribe_epochs():
                token_filter = self.tokenizer.tokenize_filter(topic_filter, epoch=epoch)
                with self._subscription_lock:
                    already_subscribed = token_filter in self._subscription_filters
                if not already_subscribed:
                    self.transport.subscribe(token_filter, qos=effective_qos)
                    self._remember_subscription(token_filter, effective_qos)
                    LOGGER.info("subscribed token filter: %s", token_filter)

        refresh_once()

        if not self.rotation.enabled:
            return

        def refresher() -> None:
            while not self._refresh_stop.wait(refresh_interval_sec):
                refresh_once()

        self._refresh_stop.clear()
        self._refresh_thread = threading.Thread(target=refresher, daemon=True)
        self._refresh_thread.start()

    def subscribe_rotating_observed(
        self,
        topic_filter: str,
        *,
        callback: MessageCallback,
        qos: Optional[int] = None,
        refresh_interval_sec: float = 1.0,
        csv_logger: Optional[DeliveryCSVLogger] = None,
    ) -> None:
        self.enable_delivery_observation(csv_logger=csv_logger, plaintext_filter=topic_filter)
        self.subscribe_rotating(
            topic_filter,
            callback=callback,
            qos=qos,
            refresh_interval_sec=refresh_interval_sec,
        )

    def stop_subscription_refresh(self) -> None:
        if self._refresh_thread is not None:
            self._refresh_stop.set()
            self._refresh_thread.join(timeout=2.0)
            self._refresh_thread = None

    def apply_policy(self, policy: AOMQTTPolicy, message: ControlPolicyMessage | None = None) -> AOMQTTConfig:
        new_config = super().apply_policy(policy, message)
        self._refresh_policy_subscriptions()
        self._ensure_policy_subscription_refresher()
        return new_config

    def _refresh_policy_subscriptions(self) -> None:
        """Subscribe to filters required by the current effective policy."""
        for topic_filter, qos in list(self._plaintext_subscriptions.items()):
            epochs = self.rotation.subscribe_epochs() if self.config.rotation_enabled else [None]
            for epoch in epochs:
                token_filter = self.tokenizer.tokenize_filter(topic_filter, epoch=epoch)
                with self._subscription_lock:
                    already_subscribed = token_filter in self._subscription_filters
                if not already_subscribed:
                    self.transport.subscribe(token_filter, qos=qos)
                    self._remember_subscription(token_filter, qos)
                    LOGGER.info("subscribed token filter after policy update: %s", token_filter)

    def _ensure_policy_subscription_refresher(self, refresh_interval_sec: float = 1.0) -> None:
        """Keep rotating subscriptions fresh after runtime Policy updates.

        In v0.8.0, a client that started with rotation disabled and later
        received a rotation-enabled policy subscribed only to the epochs that
        were active at the instant of the policy update.  Once the next epoch
        started, the subscriber could miss messages.  This helper starts the
        same lightweight refresh loop used by subscribe_rotating() whenever a
        runtime policy enables rotation after initial subscription.
        """
        if not self.config.rotation_enabled:
            # If a runtime policy disables rotation, no new rotating filters are
            # needed. Existing subscriptions are intentionally left in place for
            # compatibility during transitions, but the refresher can be stopped.
            self.stop_subscription_refresh()
            return
        if not self._plaintext_subscriptions:
            return
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            return

        def refresher() -> None:
            while not self._refresh_stop.wait(refresh_interval_sec):
                self._refresh_policy_subscriptions()

        self._refresh_stop.clear()
        self._refresh_thread = threading.Thread(target=refresher, daemon=True)
        self._refresh_thread.start()
        LOGGER.info("started subscription refresher after runtime policy update")

    def disconnect(self) -> None:
        self.stop_subscription_refresh()
        super().disconnect()


    def _mark_message_id_seen(self, message_id: str) -> bool:
        """Record a message id in a bounded LRU-style duplicate window."""
        if message_id in self._seen_message_ids:
            self._seen_message_ids.move_to_end(message_id)
            return True
        self._seen_message_ids[message_id] = None
        while self._seen_message_ids_max > 0 and len(self._seen_message_ids) > self._seen_message_ids_max:
            self._seen_message_ids.popitem(last=False)
        return False

    def _write_delivery_metric(
        self,
        *,
        received_time: float,
        msg: TransportMessage,
        payload: Any = None,
        decrypt_success: bool,
        error: str = "",
    ) -> bool:
        """Record delivery metrics and return whether the message is a duplicate.

        Duplicate detection is part of subscriber delivery behavior, so it is
        performed even when delivery metric logging is disabled. ``message_id``
        is preferred as the duplicate key so independent publishers may reuse
        the same logical sequence number; ``logical_seq`` is used as a
        backward-compatible fallback.
        """
        message_id, logical_seq, publisher_timestamp = _extract_delivery_fields(payload)

        dedup_key = (
            message_id
            if message_id is not None and message_id != ""
            else logical_seq
        )
        duplicate = False
        if (
            decrypt_success
            and dedup_key is not None
            and dedup_key != ""
        ):
            duplicate = self._mark_message_id_seen(dedup_key)

        if self._delivery_logger is None:
            return duplicate

        delivery_latency_ms = (
            (received_time - publisher_timestamp) * 1000.0
            if publisher_timestamp > 0
            else -1.0
        )
        metric = DeliveryMetric(
            timestamp=received_time,
            client_id=self.client_id,
            policy_id=self.config.policy_id,
            policy_name=self.config.policy_name,
            plaintext_filter=self._delivery_plaintext_filter,
            token_topic=msg.topic,
            token_mode=self.config.token_mode,
            rotation_enabled=self.config.rotation_enabled,
            message_id=message_id,
            logical_seq=logical_seq,
            publisher_timestamp=publisher_timestamp,
            delivery_latency_ms=delivery_latency_ms,
            decrypt_success=decrypt_success,
            duplicate=duplicate,
            payload_bytes=len(msg.payload),
            error=error,
        )
        self._delivery_logger.write(metric)
        return duplicate

    def _on_message(self, msg: TransportMessage):
        received_time = time.time()
        aad = msg.topic.encode("utf-8") if self.config.aad_bind_topic else None
        try:
            payload = self.crypto.decrypt(msg.payload, aad=aad)
        except Exception as exc:
            self._write_delivery_metric(
                received_time=received_time,
                msg=msg,
                payload=None,
                decrypt_success=False,
                error=repr(exc),
            )
            LOGGER.warning(
                "failed to decrypt received AOMQTT payload on %s: %r",
                msg.topic,
                exc,
            )
            return

        duplicate = self._write_delivery_metric(
            received_time=received_time,
            msg=msg,
            payload=payload,
            decrypt_success=True,
        )
        if duplicate:
            LOGGER.debug(
                "suppressed duplicate AOMQTT payload on topic %s",
                msg.topic,
            )
            return

        if self._callback is not None:
            self._callback(msg.topic, payload, msg)

