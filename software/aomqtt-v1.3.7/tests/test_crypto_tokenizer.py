import time

import pytest

from aomqtt import AOMQTTConfig, PayloadCrypto, TokenRotation, TopicTokenizer
from aomqtt.exceptions import AOMQTTConfigurationError


def cfg(mode="hierarchical", rotation=False):
    return AOMQTTConfig(
        topic_key="topic-secret-1234567890",
        payload_key="payload-secret-1234567890",
        token_mode=mode,
        rotation_enabled=rotation,
        rotation_interval_sec=10,
        rotation_overlap_sec=2,
    )


def test_topic_tokenizer_hierarchical_is_deterministic():
    tok = TopicTokenizer(cfg("hierarchical"))
    t1 = tok.tokenize("shelter/siteA/starlink/rtt")
    t2 = tok.tokenize("shelter/siteA/starlink/rtt")
    assert t1 == t2
    assert t1.startswith("aomqtt/v1/h/")
    assert "shelter" not in t1
    assert "siteA" not in t1
    assert len(t1.split("/")) == 7  # aomqtt/v1/h + 4 tokenized levels


def test_topic_filter_wildcard_hierarchical_hashes_known_levels():
    tok = TopicTokenizer(cfg("hierarchical"))
    f = tok.tokenize_filter("shelter/+/starlink/#")
    assert f.startswith("aomqtt/v1/h/")
    assert f.endswith("/#")
    assert "/+/" in f
    assert "shelter" not in f
    assert "starlink" not in f


def test_topic_tokenizer_whole_hides_hierarchy():
    tok = TopicTokenizer(cfg("whole"))
    t = tok.tokenize("shelter/siteA/starlink/rtt")
    assert t.startswith("aomqtt/v1/t/")
    assert len(t.split("/")) == 4
    assert "shelter" not in t
    assert "siteA" not in t


def test_whole_mode_rejects_wildcard_filter():
    tok = TopicTokenizer(cfg("whole"))
    with pytest.raises(AOMQTTConfigurationError):
        tok.tokenize_filter("shelter/siteA/starlink/#")


def test_compare_modes_returns_two_distinct_forms():
    tok = TopicTokenizer(cfg("hierarchical"))
    out = tok.compare_modes("shelter/siteA/starlink/rtt")
    assert set(out) == {"hierarchical", "whole"}
    assert out["hierarchical"].startswith("aomqtt/v1/h/")
    assert out["whole"].startswith("aomqtt/v1/t/")
    assert out["hierarchical"] != out["whole"]


def test_payload_crypto_roundtrip_json():
    crypto = PayloadCrypto(cfg("hierarchical"))
    aad = b"aomqtt/v1/h/example"
    payload = {"rtt": 42.1, "location": "siteA"}
    encrypted = crypto.encrypt(payload, aad=aad)
    decrypted = crypto.decrypt(encrypted, aad=aad)
    assert decrypted == payload
    assert b"siteA" not in encrypted
    assert b"42.1" not in encrypted


def test_epoch_changes_topic_token():
    tok = TopicTokenizer(cfg("whole", rotation=True))
    t1 = tok.tokenize("shelter/siteA/starlink/rtt", epoch="100")
    t2 = tok.tokenize("shelter/siteA/starlink/rtt", epoch="101")
    assert t1 != t2
    assert t1.startswith("aomqtt/v1/t/")
    assert t2.startswith("aomqtt/v1/t/")


def test_rotation_state_overlap_window():
    rot = TokenRotation(cfg(rotation=True))
    s = rot.state(timestamp=101.0)  # epoch 10, 1 sec into epoch, overlap enabled
    assert s.current_epoch == "10"
    assert s.previous_epoch == "9"
    assert s.in_overlap is True
    assert rot.publish_epochs(timestamp=101.0) == ["10", "9"]


def test_rotation_state_outside_overlap_window():
    rot = TokenRotation(cfg(rotation=True))
    s = rot.state(timestamp=105.0)  # epoch 10, 5 sec into epoch, outside 2 sec overlap
    assert s.current_epoch == "10"
    assert s.previous_epoch is None
    assert s.in_overlap is False
    assert rot.publish_epochs(timestamp=105.0) == ["10"]


def test_rotation_disabled_returns_none_epoch():
    rot = TokenRotation(cfg(rotation=False))
    assert rot.epoch(time.time()) is None
    assert rot.publish_epochs(time.time()) == [None]
