from aomqtt.transparency_log import (
    GENESIS_HASH,
    TransparencyLog,
    TransparencyLogEntry,
    build_transparency_entry,
    policy_digest,
)


def _policy(policy_id="policy-v120", sequence_no=1):
    return {"id": policy_id, "sequence_no": sequence_no, "padding": {"fixed_size": 512}}


def test_transparency_log_appends_and_verifies_hash_chain():
    log = TransparencyLog()
    first = log.append_policy(_policy("p1", 1), signer_key_ids=["k1", "k2"], threshold=2)
    second = log.append_policy(_policy("p2", 2), signer_key_ids=["k1", "k3"], threshold=2)

    assert first.index == 0
    assert first.previous_hash == GENESIS_HASH
    assert second.index == 1
    assert second.previous_hash == first.entry_hash

    result = log.verify()
    assert result.accepted
    assert result.reason_code == "OK"
    assert result.verified_entries == 2


def test_transparency_entry_policy_digest_is_stable():
    policy = _policy("p-digest", 3)
    entry = build_transparency_entry(
        policy,
        index=0,
        previous_hash=GENESIS_HASH,
        signer_key_ids=["k1"],
        threshold=1,
    )

    assert entry.policy_digest == policy_digest(policy)
    assert len(entry.entry_hash) == 64


def test_transparency_log_detects_entry_hash_tampering():
    log = TransparencyLog()
    entry = log.append_policy(_policy("p1", 1), signer_key_ids=["k1"], threshold=1)
    tampered = TransparencyLogEntry.from_dict({**entry.to_dict(), "reason_code": "TAMPERED"})
    tampered_log = TransparencyLog([tampered])

    result = tampered_log.verify()

    assert not result.accepted
    assert result.reason_code == "TRANSPARENCY_LOG_ENTRY_HASH_MISMATCH"


def test_transparency_log_detects_previous_hash_tampering():
    log = TransparencyLog()
    first = log.append_policy(_policy("p1", 1), signer_key_ids=["k1"], threshold=1)
    second = log.append_policy(_policy("p2", 2), signer_key_ids=["k1"], threshold=1)
    tampered_second = TransparencyLogEntry.from_dict({**second.to_dict(), "previous_hash": GENESIS_HASH})
    tampered_log = TransparencyLog([first, tampered_second])

    result = tampered_log.verify()

    assert not result.accepted
    assert result.reason_code == "TRANSPARENCY_LOG_PREVIOUS_HASH_MISMATCH"


def test_transparency_log_jsonl_roundtrip(tmp_path):
    path = tmp_path / "policy_transparency_log.jsonl"
    log = TransparencyLog()
    log.append_policy(_policy("p1", 1), signer_key_ids=["k1"], threshold=1)
    log.append_policy(_policy("p2", 2), signer_key_ids=["k1", "k2"], threshold=2)
    log.write_jsonl(path)

    loaded = TransparencyLog.read_jsonl(path)

    assert len(loaded.entries) == 2
    assert loaded.entries[0].policy_id == "p1"
    assert loaded.entries[1].threshold == 2
    assert loaded.verify().accepted
