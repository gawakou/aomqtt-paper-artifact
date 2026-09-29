from __future__ import annotations

from pathlib import Path

from aomqtt import AOMQTTConfig, AOMQTTPublisher, PublishCSVLogger, TransportAdapter, TransportMessage


class FakePublishHandle:
    def __init__(self, mid: int = 1, rc: int = 0):
        self.mid = mid
        self.rc = rc
        self._published = False

    def wait_for_publish(self, timeout=None) -> None:
        self._published = True

    def is_published(self) -> bool:
        return self._published


class FakeTransport(TransportAdapter):
    def __init__(self):
        self.published = []
        self._mid = 0

    @property
    def reconnect_count(self) -> int:
        return 2

    def set_on_connect(self, callback):
        self.on_connect = callback

    def set_on_disconnect(self, callback):
        self.on_disconnect = callback

    def set_on_message(self, callback):
        self.on_message = callback

    def username_pw_set(self, username, password=None):
        pass

    def tls_set(self):
        pass

    def connect(self, host, port, keepalive=60):
        pass

    def disconnect(self):
        pass

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def loop_forever(self):
        pass

    def publish(self, topic, payload, qos=0, retain=False):
        self._mid += 1
        self.published.append((topic, payload, qos, retain))
        return FakePublishHandle(mid=self._mid, rc=0)

    def subscribe(self, topic_filter, qos=0):
        return (0, 1)


def cfg(rotation=True):
    return AOMQTTConfig(
        topic_key="topic-secret-1234567890",
        payload_key="payload-secret-1234567890",
        token_mode="whole",
        rotation_enabled=rotation,
        rotation_interval_sec=10,
        rotation_overlap_sec=3,
        mqtt_qos=1,
    )


def test_publisher_uses_transport_adapter_without_paho():
    transport = FakeTransport()
    pub = AOMQTTPublisher(
        broker_host="localhost",
        client_id="test-pub",
        config=cfg(rotation=False),
        transport=transport,
    )
    metrics = pub.publish_observed_rotating("shelter/siteA/starlink/rtt", {"seq": 1}, logical_seq=1)
    assert len(metrics) == 1
    assert len(transport.published) == 1
    assert transport.published[0][0].startswith("aomqtt/v1/t/")
    assert metrics[0].success is True
    assert metrics[0].qos == 1
    assert metrics[0].reconnect_count == 2


def test_overlap_window_creates_duplicate_publish_metrics():
    transport = FakeTransport()
    pub = AOMQTTPublisher(
        broker_host="localhost",
        client_id="test-pub",
        config=cfg(rotation=True),
        transport=transport,
    )
    metrics = pub.publish_observed_rotating(
        "shelter/siteA/starlink/rtt",
        {"seq": 1},
        logical_seq=1,
        timestamp=101.0,
    )
    assert len(metrics) == 2
    assert metrics[0].rotation_in_overlap is True
    assert metrics[0].overlap_duplicate is False
    assert metrics[1].overlap_duplicate is True
    assert metrics[0].token_topic != metrics[1].token_topic


def test_publish_csv_logger_writes_metrics(tmp_path: Path):
    transport = FakeTransport()
    pub = AOMQTTPublisher(
        broker_host="localhost",
        client_id="test-pub",
        config=cfg(rotation=False),
        transport=transport,
    )
    csv_path = tmp_path / "publish_metrics.csv"
    with PublishCSVLogger(csv_path) as logger:
        pub.publish_observed_rotating(
            "shelter/siteA/starlink/rtt",
            {"seq": 1},
            logical_seq=1,
            csv_logger=logger,
        )
        summary = logger.summary()
    text = csv_path.read_text()
    assert "publish_complete_ms" in text
    assert "aomqtt/v1/t/" in text
    assert summary.total == 1
    assert summary.success == 1
