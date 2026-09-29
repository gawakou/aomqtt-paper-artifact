from __future__ import annotations

from pathlib import Path

from aomqtt import AOMQTTConfig, AOMQTTSubscriber, DeliveryCSVLogger, summarize_loss_and_duplicates
from aomqtt.client import AOMQTTPublisher
from aomqtt.transport import TransportAdapter, TransportMessage


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
        self.on_message = None
        self._mid = 0

    @property
    def reconnect_count(self) -> int:
        return 0

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


def cfg():
    return AOMQTTConfig(
        topic_key="topic-secret-1234567890",
        payload_key="payload-secret-1234567890",
        token_mode="whole",
        mqtt_qos=1,
    )


def test_subscriber_delivery_csv_detects_and_suppresses_duplicate(tmp_path: Path):
    config = cfg()
    pub_transport = FakeTransport()
    sub_transport = FakeTransport()
    pub = AOMQTTPublisher(broker_host="localhost", client_id="pub", config=config, transport=pub_transport)
    sub = AOMQTTSubscriber(broker_host="localhost", client_id="sub", config=config, transport=sub_transport)

    csv_path = tmp_path / "subscriber_metrics.csv"
    seen_payloads = []
    with DeliveryCSVLogger(csv_path) as logger:
        sub.subscribe_observed("shelter/siteA/starlink/rtt", callback=lambda t, p, r: seen_payloads.append(p), csv_logger=logger)
        payload = {"message_id": "m1", "seq": 1, "sent_time": 1.0}
        pub.publish_observed_rotating("shelter/siteA/starlink/rtt", payload, logical_seq="m1", wait_for_publish=False)
        token_topic, encrypted_payload, _, _ = pub_transport.published[0]
        sub._on_message(TransportMessage(topic=token_topic, payload=encrypted_payload))
        sub._on_message(TransportMessage(topic=token_topic, payload=encrypted_payload))
        summary = logger.summary()

    text = csv_path.read_text()
    assert "delivery_latency_ms" in text
    assert summary.total_received == 2
    assert summary.decrypt_success == 2
    assert summary.unique_messages == 1
    assert summary.duplicates == 1
    assert len(seen_payloads) == 1
    assert seen_payloads[0] == payload


def test_loss_and_duplicate_summary_from_csv_like_rows():
    pub_rows = [{"logical_seq": "m1"}, {"logical_seq": "m2"}, {"logical_seq": "m3"}]
    sub_rows = [{"message_id": "m1"}, {"message_id": "m1"}, {"message_id": "m3"}]
    summary = summarize_loss_and_duplicates(pub_rows, sub_rows)
    assert summary["published_logical_messages"] == 3
    assert summary["unique_received_messages"] == 2
    assert summary["lost_messages"] == 1
    assert summary["duplicate_message_ids"] == 1


def test_subscriber_preserves_zero_sequence_as_message_id(tmp_path: Path):
    config = cfg()
    pub_transport = FakeTransport()
    sub_transport = FakeTransport()
    pub = AOMQTTPublisher(broker_host="localhost", client_id="pub", config=config, transport=pub_transport)
    sub = AOMQTTSubscriber(broker_host="localhost", client_id="sub", config=config, transport=sub_transport)

    csv_path = tmp_path / "subscriber_metrics_zero.csv"
    with DeliveryCSVLogger(csv_path) as logger:
        sub.subscribe_observed("shelter/siteA/starlink/rtt", callback=lambda t, p, r: None, csv_logger=logger)
        payload = {"seq": 0, "timestamp": 1.0}
        pub.publish_observed_rotating("shelter/siteA/starlink/rtt", payload, logical_seq=0, wait_for_publish=False)
        token_topic, encrypted_payload, _, _ = pub_transport.published[0]
        sub._on_message(TransportMessage(topic=token_topic, payload=encrypted_payload))
        sub._on_message(TransportMessage(topic=token_topic, payload=encrypted_payload))
        summary = logger.summary()

    rows = csv_path.read_text().splitlines()
    assert summary.unique_messages == 1
    assert summary.duplicates == 1
    assert ",0,0," in rows[1]


def test_loss_summary_preserves_zero_ids():
    pub_rows = [{"logical_seq": 0}, {"logical_seq": 1}]
    sub_rows = [{"message_id": 0}, {"message_id": 0}, {"message_id": 1}]
    summary = summarize_loss_and_duplicates(pub_rows, sub_rows)
    assert summary["published_logical_messages"] == 2
    assert summary["unique_received_messages"] == 2
    assert summary["lost_messages"] == 0
    assert summary["duplicate_message_ids"] == 1

def test_subscriber_suppresses_duplicate_without_delivery_logger():
    config = cfg()
    pub_transport = FakeTransport()
    sub_transport = FakeTransport()

    pub = AOMQTTPublisher(
        broker_host="localhost",
        client_id="pub",
        config=config,
        transport=pub_transport,
    )
    sub = AOMQTTSubscriber(
        broker_host="localhost",
        client_id="sub",
        config=config,
        transport=sub_transport,
    )

    seen_payloads = []
    sub.subscribe(
        "shelter/siteA/starlink/rtt",
        callback=lambda topic, payload, raw: seen_payloads.append(payload),
    )

    payload = {
        "message_id": "m1",
        "seq": 1,
        "sent_time": 1.0,
    }
    pub.publish_observed_rotating(
        "shelter/siteA/starlink/rtt",
        payload,
        logical_seq="m1",
        wait_for_publish=False,
    )

    token_topic, encrypted_payload, _, _ = pub_transport.published[0]
    message = TransportMessage(
        topic=token_topic,
        payload=encrypted_payload,
    )

    sub._on_message(message)
    sub._on_message(message)

    assert len(seen_payloads) == 1
    assert seen_payloads[0] == payload



def test_subscriber_prefers_message_id_over_zero_logical_seq_for_dedup():
    config = cfg()
    pub_transport = FakeTransport()
    sub_transport = FakeTransport()

    pub = AOMQTTPublisher(
        broker_host="localhost",
        client_id="pub",
        config=config,
        transport=pub_transport,
    )
    sub = AOMQTTSubscriber(
        broker_host="localhost",
        client_id="sub",
        config=config,
        transport=sub_transport,
    )

    seen_payloads = []
    sub.subscribe(
        "shelter/siteA/starlink/rtt",
        callback=lambda topic, payload, raw: seen_payloads.append(payload),
    )

    # Two independent publishers may legitimately reuse seq=0.
    # Distinct globally unique message_id values must therefore both be delivered.
    first_payload = {
        "message_id": "publisher-1:run-001:0",
        "seq": 0,
        "sent_time": 1.0,
    }
    second_payload = {
        "message_id": "publisher-2:run-001:0",
        "seq": 0,
        "sent_time": 1.0,
    }

    pub.publish_observed_rotating(
        "shelter/siteA/starlink/rtt",
        first_payload,
        logical_seq=0,
        wait_for_publish=False,
    )
    pub.publish_observed_rotating(
        "shelter/siteA/starlink/rtt",
        second_payload,
        logical_seq=0,
        wait_for_publish=False,
    )

    first_topic, first_encrypted_payload, _, _ = pub_transport.published[0]
    second_topic, second_encrypted_payload, _, _ = pub_transport.published[1]

    sub._on_message(
        TransportMessage(
            topic=first_topic,
            payload=first_encrypted_payload,
        )
    )
    sub._on_message(
        TransportMessage(
            topic=second_topic,
            payload=second_encrypted_payload,
        )
    )

    assert len(seen_payloads) == 2
    assert seen_payloads[0]["message_id"] == "publisher-1:run-001:0"
    assert seen_payloads[1]["message_id"] == "publisher-2:run-001:0"


def test_subscriber_suppresses_same_message_id_duplicate():
    config = cfg()
    pub_transport = FakeTransport()
    sub_transport = FakeTransport()

    pub = AOMQTTPublisher(
        broker_host="localhost",
        client_id="pub",
        config=config,
        transport=pub_transport,
    )
    sub = AOMQTTSubscriber(
        broker_host="localhost",
        client_id="sub",
        config=config,
        transport=sub_transport,
    )

    seen_payloads = []
    sub.subscribe(
        "shelter/siteA/starlink/rtt",
        callback=lambda topic, payload, raw: seen_payloads.append(payload),
    )

    payload = {
        "message_id": "publisher-1:run-001:0",
        "seq": 0,
        "sent_time": 1.0,
    }

    # Two physical MQTT copies of the same logical message share message_id.
    pub.publish_observed_rotating(
        "shelter/siteA/starlink/rtt",
        payload,
        logical_seq=0,
        wait_for_publish=False,
    )
    pub.publish_observed_rotating(
        "shelter/siteA/starlink/rtt",
        payload,
        logical_seq=0,
        wait_for_publish=False,
    )

    first_topic, first_encrypted_payload, _, _ = pub_transport.published[0]
    second_topic, second_encrypted_payload, _, _ = pub_transport.published[1]

    sub._on_message(
        TransportMessage(
            topic=first_topic,
            payload=first_encrypted_payload,
        )
    )
    sub._on_message(
        TransportMessage(
            topic=second_topic,
            payload=second_encrypted_payload,
        )
    )

    assert len(seen_payloads) == 1
    assert seen_payloads[0]["message_id"] == "publisher-1:run-001:0"
    assert seen_payloads[0] == payload
