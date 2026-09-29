from __future__ import annotations

import pytest

from aomqtt import AOMQTTConfig, AOMQTTSubscriber
from aomqtt.control import ControlTopicPolicyReceiver
from aomqtt.core.padding import PayloadPadding
from aomqtt.exceptions import AOMQTTConfigurationError
from tests.test_transport_observation import FakeTransport


def base_config(**kwargs):
    cfg = AOMQTTConfig(
        topic_key="super-secret-topic-key",
        payload_key="super-secret-payload-key",
        token_mode="whole",
        **kwargs,
    )
    cfg.validate()
    return cfg


def test_config_repr_and_default_to_dict_redact_keys():
    cfg = base_config()

    text = repr(cfg)
    public = cfg.to_dict()
    private = cfg.to_dict(redact=False)

    assert "super-secret-topic-key" not in text
    assert "super-secret-payload-key" not in text
    assert public["topic_key"] == "<redacted>"
    assert public["payload_key"] == "<redacted>"
    assert private["topic_key"] == "super-secret-topic-key"
    assert private["payload_key"] == "super-secret-payload-key"


def test_random_padding_uses_full_configured_span(monkeypatch):
    cfg = base_config(
        padding_enabled=True,
        padding_mode="random",
        padding_random_min_bytes=10,
        padding_random_max_bytes=2000,
    )
    padding = PayloadPadding(cfg)

    monkeypatch.setattr("aomqtt.core.padding.secrets.randbelow", lambda span: span - 1)
    wrapped, stats = padding.apply(b"abc")

    assert len(wrapped) == len(b"abc") + 15 + 2000
    assert stats.padding_added_bytes == 15 + 2000
    assert PayloadPadding.remove(wrapped) == b"abc"


def test_subscriber_resubscribes_remembered_filters_on_reconnect(monkeypatch):
    cfg = base_config(mqtt_qos=1)
    transport = FakeTransport()
    sub = AOMQTTSubscriber(broker_host="localhost", client_id="sub", config=cfg, transport=transport)
    calls: list[tuple[str, int]] = []

    def fake_subscribe(topic_filter: str, qos: int = 0):
        calls.append((topic_filter, qos))
        return (0, len(calls))

    monkeypatch.setattr(sub.transport, "subscribe", fake_subscribe)

    sub.subscribe("shelter/siteA/starlink/rtt", callback=lambda t, p, r: None, qos=1)
    assert len(calls) == 1
    first_filter = calls[0][0]

    sub._on_connect(flags=None, reason_code=0)

    assert len(calls) == 2
    assert calls[1] == (first_filter, 1)


def test_seen_message_ids_are_bounded_lru_window():
    cfg = base_config()
    sub = AOMQTTSubscriber(
        broker_host="localhost",
        client_id="sub",
        config=cfg,
        transport=FakeTransport(),
        seen_message_ids_max=2,
    )

    assert sub._mark_message_id_seen("m1") is False
    assert sub._mark_message_id_seen("m2") is False
    assert sub._mark_message_id_seen("m3") is False
    assert len(sub._seen_message_ids) == 2
    assert "m1" not in sub._seen_message_ids
    assert sub._mark_message_id_seen("m2") is True


def test_control_receiver_requires_signature_key_by_default(monkeypatch):
    import aomqtt.control as control_module

    class FakeClient:
        def username_pw_set(self, *args, **kwargs):
            pass

        def tls_set(self, *args, **kwargs):
            pass

    monkeypatch.setattr(control_module, "_make_paho_client", lambda client_id: FakeClient())

    with pytest.raises(AOMQTTConfigurationError, match="signing_public_key is required"):
        ControlTopicPolicyReceiver(
            broker_host="localhost",
            client_id="receiver",
            group_id="g1",
            apply_callback=lambda policy, message: None,
        )
