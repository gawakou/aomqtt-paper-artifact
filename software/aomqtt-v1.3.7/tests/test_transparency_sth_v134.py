"""v1.3.4: Signed Tree Head tests for the transparency log."""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aomqtt.transparency_log import (
    SignedTreeHead,
    TransparencyLog,
    sign_tree_head,
    verify_consistency,
    verify_tree_head,
)


def _log_key():
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def _log_with(n):
    log = TransparencyLog()
    for i in range(1, n + 1):
        log.append_policy(
            {"id": f"p{i}", "sequence_no": i},
            signer_key_ids=["k1"],
            threshold=1,
        )
    return log


def test_honest_sth_verifies():
    private_key, public_key = _log_key()
    log = _log_with(3)

    sth = sign_tree_head(log, private_key, "log-key")

    assert sth.log_size == 3
    assert verify_tree_head(log, sth, public_key)


def test_sth_round_trips_through_dict():
    private_key, public_key = _log_key()
    log = _log_with(2)

    sth = sign_tree_head(log, private_key, "log-key")
    restored = SignedTreeHead.from_dict(sth.to_dict())

    assert restored == sth
    assert verify_tree_head(log, restored, public_key)


def test_wrong_authority_is_rejected():
    private_key, _ = _log_key()
    _, other_public_key = _log_key()
    log = _log_with(2)

    assert not verify_tree_head(log, sign_tree_head(log, private_key, "log-key"), other_public_key)


def test_tampered_signature_is_rejected():
    private_key, public_key = _log_key()
    log = _log_with(2)

    sth = sign_tree_head(log, private_key, "log-key")
    bad = SignedTreeHead(
        log_size=sth.log_size,
        root_hash=sth.root_hash,
        key_id=sth.key_id,
        signature="AAAA",
    )

    assert not verify_tree_head(log, bad, public_key)


def test_full_chain_rewrite_is_detected_by_old_sth():
    private_key, public_key = _log_key()
    log = _log_with(3)
    trusted_sth = sign_tree_head(log, private_key, "log-key")

    forged = TransparencyLog()
    for i in range(1, 4):
        forged.append_policy(
            {"id": f"evil{i}", "sequence_no": i},
            signer_key_ids=["k1"],
            threshold=1,
        )

    assert forged.verify().accepted
    assert not verify_tree_head(forged, trusted_sth, public_key)


def test_consistency_accepts_append_only_extension():
    private_key, public_key = _log_key()
    log = _log_with(2)
    old_sth = sign_tree_head(log, private_key, "log-key")

    log.append_policy(
        {"id": "p3", "sequence_no": 3},
        signer_key_ids=["k1"],
        threshold=1,
    )

    assert verify_consistency(log, old_sth, public_key)


def test_consistency_rejects_prefix_rewrite():
    private_key, public_key = _log_key()
    log = _log_with(2)
    old_sth = sign_tree_head(log, private_key, "log-key")

    rewritten = TransparencyLog()
    rewritten.append_policy({"id": "p1", "sequence_no": 1}, signer_key_ids=["k1"], threshold=1)
    rewritten.append_policy({"id": "TAMPERED", "sequence_no": 2}, signer_key_ids=["k1"], threshold=1)
    rewritten.append_policy({"id": "p3", "sequence_no": 3}, signer_key_ids=["k1"], threshold=1)

    assert rewritten.verify().accepted
    assert not verify_consistency(rewritten, old_sth, public_key)


def test_consistency_rejects_shrink():
    private_key, public_key = _log_key()
    old_sth = sign_tree_head(_log_with(4), private_key, "log-key")

    assert not verify_consistency(_log_with(2), old_sth, public_key)


def test_consistency_from_empty_sth():
    private_key, public_key = _log_key()
    empty_sth = sign_tree_head(TransparencyLog(), private_key, "log-key")

    assert empty_sth.log_size == 0
    assert verify_consistency(_log_with(3), empty_sth, public_key)
