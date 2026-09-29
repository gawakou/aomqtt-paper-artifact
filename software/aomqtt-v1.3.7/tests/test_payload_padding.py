from __future__ import annotations

from dataclasses import replace

import pytest

from aomqtt import AOMQTTConfig, PayloadCrypto
from aomqtt.core.padding import PayloadPadding
from aomqtt.exceptions import AOMQTTDecryptionError


def base_cfg(**kwargs):
    cfg = AOMQTTConfig(
        topic_key="topic-secret-1234567890",
        payload_key="payload-secret-1234567890",
        token_mode="whole",
        **kwargs,
    )
    cfg.validate()
    return cfg


def test_padding_disabled_preserves_v05_roundtrip():
    crypto = PayloadCrypto(base_cfg())
    encrypted, stats = crypto.encrypt_with_stats({"seq": 1}, aad=b"topic")
    assert stats.padding_enabled is False
    assert stats.padding_added_bytes == 0
    assert crypto.decrypt(encrypted, aad=b"topic") == {"seq": 1}


def test_fixed_padding_roundtrip_and_hides_plain_length_inside_ciphertext():
    cfg = base_cfg(padding_enabled=True, padding_mode="fixed", padding_fixed_size=512)
    crypto = PayloadCrypto(cfg)
    payload = {"message_id": "m1", "seq": 1, "value": "abc"}
    encrypted, stats = crypto.encrypt_with_stats(payload, aad=b"topic")
    assert stats.padding_enabled is True
    assert stats.padding_mode == "fixed"
    assert stats.padded_plain_bytes == 512
    assert stats.padding_added_bytes > 0
    assert b"message_id" not in encrypted
    # Do not check for a short token such as b"abc" in the whole encrypted
    # envelope. The ciphertext is Base64 encoded and may randomly contain short
    # character sequences. Instead, verify that the plaintext JSON field is not
    # exposed in the envelope.
    assert b'"value": "abc"' not in encrypted
    assert b'"value":"abc"' not in encrypted
    assert crypto.decrypt(encrypted, aad=b"topic") == payload


def test_bucket_padding_rounds_encrypted_plaintext_size():
    cfg = base_cfg(padding_enabled=True, padding_mode="bucket", padding_bucket_size=256)
    crypto = PayloadCrypto(cfg)
    encrypted, stats = crypto.encrypt_with_stats({"seq": 1, "x": "y"}, aad=b"topic")
    assert stats.padded_plain_bytes % 256 == 0
    assert crypto.decrypt(encrypted, aad=b"topic") == {"seq": 1, "x": "y"}


def test_random_padding_adds_bytes_within_configured_range_plus_header():
    cfg = base_cfg(
        padding_enabled=True,
        padding_mode="random",
        padding_random_min_bytes=10,
        padding_random_max_bytes=20,
    )
    crypto = PayloadCrypto(cfg)
    encrypted, stats = crypto.encrypt_with_stats({"seq": 1}, aad=b"topic")
    # stats.padding_added_bytes includes the encrypted internal padding header.
    assert stats.padding_added_bytes >= 10
    assert stats.padded_plain_bytes >= stats.original_plain_bytes + 10
    assert crypto.decrypt(encrypted, aad=b"topic") == {"seq": 1}


def test_aad_binding_still_detects_topic_relocation_with_padding():
    cfg = base_cfg(padding_enabled=True, padding_mode="bucket", padding_bucket_size=256)
    crypto = PayloadCrypto(cfg)
    encrypted = crypto.encrypt({"seq": 1}, aad=b"aomqtt/v1/t/topicA")
    with pytest.raises(AOMQTTDecryptionError):
        crypto.decrypt(encrypted, aad=b"aomqtt/v1/t/topicB")
