from aomqtt.signing import LocalEd25519Signer, MockKMSSigner, canonical_json_bytes, verify_ed25519_signature


def test_local_ed25519_signer_signs_canonical_policy():
    signer = LocalEd25519Signer.generate("controller-key-2026-001")
    payload = canonical_json_bytes({"policy": {"id": "p1", "sequence_no": 1, "encryption": {"enabled": True}}})

    envelope = signer.sign(payload)

    assert envelope.key_id == "controller-key-2026-001"
    assert envelope.algorithm == "Ed25519"
    assert envelope.signing_method == "local"
    assert verify_ed25519_signature(signer.public_key(), payload, envelope.signature)


def test_mock_kms_signer_uses_kms_metadata():
    signer = MockKMSSigner.generate("kms-policy-key-001")
    payload = canonical_json_bytes({"policy": {"id": "p2", "sequence_no": 2}})

    envelope = signer.sign(payload)

    assert envelope.key_id == "kms-policy-key-001"
    assert envelope.signing_method == "mock-kms"
    assert verify_ed25519_signature(signer.public_key(), payload, envelope.signature)
