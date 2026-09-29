from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class TransportMessage:
    """MQTT message normalized for AOMQTT.

    The transport adapter hides the concrete MQTT client implementation from the
    privacy layer. For example, Paho's MQTTMessage is converted into this small
    representation before it reaches AOMQTTSubscriber.
    """

    topic: str
    payload: bytes
    raw: Any = None


@runtime_checkable
class PublishHandle(Protocol):
    """Transport-independent publish handle."""

    mid: int
    rc: int

    def wait_for_publish(self, timeout: Optional[float] = None) -> None:
        ...

    def is_published(self) -> bool:
        ...


OnConnectCallback = Callable[[Any, Any, Any, Any], None]
OnDisconnectCallback = Callable[[Any, Any, Any], None]
OnMessageCallback = Callable[[TransportMessage], None]


class TransportAdapter:
    """Abstract MQTT transport adapter.

    AOMQTT Core must not depend on a specific MQTT client library. Concrete
    adapters, such as PahoMQTTAdapter, implement this interface.
    """

    @property
    def reconnect_count(self) -> int:
        return 0

    def set_on_connect(self, callback: OnConnectCallback) -> None:
        raise NotImplementedError

    def set_on_disconnect(self, callback: OnDisconnectCallback) -> None:
        raise NotImplementedError

    def set_on_message(self, callback: OnMessageCallback) -> None:
        raise NotImplementedError

    def username_pw_set(self, username: str, password: Optional[str] = None) -> None:
        raise NotImplementedError

    def tls_set(self) -> None:
        raise NotImplementedError

    def connect(self, host: str, port: int, keepalive: int = 60) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def loop_start(self) -> None:
        raise NotImplementedError

    def loop_stop(self) -> None:
        raise NotImplementedError

    def loop_forever(self) -> None:
        raise NotImplementedError

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> PublishHandle:
        raise NotImplementedError

    def subscribe(self, topic_filter: str, qos: int = 0) -> tuple[int, int]:
        raise NotImplementedError
