from aomqtt.krl import build_krl
from aomqtt.multisig_policy import sign_multisig_policy_envelope
from aomqtt.signing import LocalEd25519Signer
from aomqtt.trusted_multisig_processor import TrustedMultiSignaturePolicyProcessor


def _policy(policy_id="policy-v120", sequence_no=1, padding_size=512):
    return {
        "id": policy_id,
        "sequence_no": sequence_no,
        "encryption": {"enabled": True},
        "topic_obfuscation": {"enabled": True},
        "padding": {"fixed_size": padding_size},
    }


def _signers():
    controller = LocalEd25519Signer.generate("controller-key")
    security = LocalEd25519Signer.generate("security-officer-key")
    return controller, security


def _trusted(*signers):
    return {s.key_id: s.public_key() for s in signers}


def _envelope(policy=None, threshold=2, required_roles=("controller", "security")):
    controller, security = _signers()
    envelope = sign_multisig_policy_envelope(
        policy or _policy(),
        [controller, security],
        threshold=threshold,
        signer_roles={controller.key_id: "controller", security.key_id: "security"},
        required_roles=required_roles,
    )
    return controller, security, envelope


def test_processor_accepts_multisig_policy_and_appends_transparency_entry():
    controller, security, envelope = _envelope()
    published = []
    processor = TrustedMultiSignaturePolicyProcessor(
        trusted_public_keys=_trusted(controller, security),
        client_id="subscriber-v120",
        required_roles=["controller", "security"],
        ack_publisher=published.append,
    )

    result = processor.process_envelope(envelope)

    assert result.accepted
    assert result.stage == "accepted"
    assert result.ack["status"] == "accepted"
    assert result.ack["signature_mode"] == "multi-signature"
    assert result.transparency_entry is not None
    assert result.transparency_entry.decision == "accepted"
    assert processor.verify_transparency_log().accepted
    assert published == [result.ack]


def test_processor_rejects_missing_required_role_and_logs_rejection():
    controller, security, envelope = _envelope(required_roles=("controller",))
    processor = TrustedMultiSignaturePolicyProcessor(
        trusted_public_keys=_trusted(controller, security),
        client_id="subscriber-v120",
        required_roles=["controller", "security", "auditor"],
    )

    result = processor.process_payload(envelope)

    assert not result.accepted
    assert result.stage == "multisig"
    assert result.reason_code == "MULTISIG_REQUIRED_ROLE_MISSING"
    assert result.transparency_entry is not None
    assert result.transparency_entry.decision == "rejected"
    assert result.transparency_entry.reason_code == "MULTISIG_REQUIRED_ROLE_MISSING"
    assert processor.verify_transparency_log().accepted


def test_processor_rejects_revoked_signer():
    controller, security, envelope = _envelope()
    krl = build_krl(1, [{"key_id": security.key_id, "revoked_at": "2026-06-06T00:00:00Z"}])
    processor = TrustedMultiSignaturePolicyProcessor(
        trusted_public_keys=_trusted(controller, security),
        krl=krl,
    )

    result = processor.process_payload(envelope)

    assert not result.accepted
    assert result.reason_code == "REVOKED_SIGNING_KEY"
    assert result.ack["status"] == "rejected"


def test_processor_converts_policy_guard_rejection_to_final_ack():
    controller, security, envelope = _envelope(policy=_policy("unsafe", 3, padding_size=999999))
    processor = TrustedMultiSignaturePolicyProcessor(
        trusted_public_keys=_trusted(controller, security),
        policy_validator=lambda policy: {"accepted": False, "reason_code": "PADDING_TOO_LARGE"},
    )

    result = processor.process_payload(envelope)

    assert not result.accepted
    assert result.stage == "policy_guard"
    assert result.reason_code == "PADDING_TOO_LARGE"
    assert result.ack["reason_code"] == "PADDING_TOO_LARGE"
    assert result.transparency_entry.reason_code == "PADDING_TOO_LARGE"


def test_processor_rejects_invalid_json_payload():
    processor = TrustedMultiSignaturePolicyProcessor(trusted_public_keys={})

    result = processor.process_payload(b"not-json")

    assert not result.accepted
    assert result.stage == "payload"
    assert result.reason_code == "INVALID_POLICY_JSON"
    assert result.ack["status"] == "rejected"


def test_processor_writes_transparency_and_anomaly_reports(tmp_path):
    controller, security, envelope = _envelope(policy=_policy("unsafe", 4, padding_size=999999))
    processor = TrustedMultiSignaturePolicyProcessor(
        trusted_public_keys=_trusted(controller, security),
        policy_validator=lambda policy: "PADDING_TOO_LARGE",
    )
    processor.process_payload(envelope)

    log_path = processor.write_transparency_log(tmp_path)
    csv_path, json_path = processor.write_anomaly_reports(tmp_path)

    assert log_path.exists()
    assert "policy_transparency_log" in log_path.name
    assert csv_path.exists()
    assert json_path.exists()
    assert any(a.reason_code == "PADDING_TOO_LARGE" for a in processor.detect_anomalies())
