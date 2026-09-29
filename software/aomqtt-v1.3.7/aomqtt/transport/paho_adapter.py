from __future__ import annotations

import logging
from typing import Optional

import paho.mqtt.client as mqtt

from .base import OnConnectCallback, OnDisconnectCallback, OnMessageCallback, TransportAdapter, TransportMessage

LOGGER = logging.getLogger(__name__)


def _make_paho_client(client_id: str, protocol: int = mqtt.MQTTv311) -> mqtt.Client:
    """Create a Paho client compatible with paho-mqtt 1.x and 2.x."""
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=protocol,
        )
    except Exception:
        return mqtt.Client(client_id=client_id, protocol=protocol)


class PahoMQTTAdapter(TransportAdapter):
    """Paho MQTT transport adapter.

    Paho is only one transport backend. AOMQTT topic tokenization, encryption,
    rotation, and observation are implemented above this adapter.
    """

    def __init__(self, client_id: str, protocol: int = mqtt.MQTTv311):
        self.client_id = client_id
        self.client = _make_paho_client(client_id=client_id, protocol=protocol)
        self._on_connect: Optional[OnConnectCallback] = None
        self._on_disconnect: Optional[OnDisconnectCallback] = None
        self._on_message: Optional[OnMessageCallback] = None
        self._ever_connected = False
        self._reconnect_count = 0

        self.client.on_connect = self._handle_connect
        self.client.on_disconnect = self._handle_disconnect
        self.client.on_message = self._handle_message

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    def set_on_connect(self, callback: OnConnectCallback) -> None:
        self._on_connect = callback

    def set_on_disconnect(self, callback: OnDisconnectCallback) -> None:
        self._on_disconnect = callback

    def set_on_message(self, callback: OnMessageCallback) -> None:
        self._on_message = callback

    def username_pw_set(self, username: str, password: Optional[str] = None) -> None:
        self.client.username_pw_set(username=username, password=password)

    def tls_set(self) -> None:
        self.client.tls_set()

    def connect(self, host: str, port: int, keepalive: int = 60) -> None:
        self.client.connect(host, port, keepalive=keepalive)

    def disconnect(self) -> None:
        self.client.disconnect()

    def loop_start(self) -> None:
        self.client.loop_start()

    def loop_stop(self) -> None:
        self.client.loop_stop()

    def loop_forever(self) -> None:
        self.client.loop_forever()

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False):
        return self.client.publish(topic, payload=payload, qos=qos, retain=retain)

    def subscribe(self, topic_filter: str, qos: int = 0) -> tuple[int, int]:
        return self.client.subscribe(topic_filter, qos=qos)

    def _handle_connect(self, client, userdata, flags, reason_code, properties=None):
        if self._ever_connected:
            self._reconnect_count += 1
        self._ever_connected = True
        if self._on_connect is not None:
            self._on_connect(flags, reason_code, properties, client)

    def _handle_disconnect(self, client, userdata, *args):
        reason_code = args[-2] if len(args) >= 2 else (args[0] if args else None)
        if self._on_disconnect is not None:
            self._on_disconnect(reason_code, args, client)

    def _handle_message(self, client, userdata, msg: mqtt.MQTTMessage):
        if self._on_message is not None:
            self._on_message(TransportMessage(topic=msg.topic, payload=msg.payload, raw=msg))
