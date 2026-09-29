from __future__ import annotations

import json

from aomqtt.krl import build_krl
from aomqtt.policy_trust import sign_policy_envelope
from aomqtt.signing import LocalEd25519Signer
from aomqtt.trusted_control_processor import TrustedControlPolicyProcessor


def main() -> None:
    signer = LocalEd25519Signer.generate("controller-key-2026-001")

    def simple_policy_guard(policy):
        padding = policy.get("padding", {}) if isinstance(policy, dict) else {}
        if padding.get("fixed_size", 0) > 4096:
            return {"accepted": False, "reason_code": "PADDING_TOO_LARGE"}
        return None

    processor = TrustedControlPolicyProcessor(
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        client_id="subscriber-demo",
        policy_validator=simple_policy_guard,
    )

    safe_policy = {
        "id": "policy-v110-safe",
        "sequence_no": 1,
        "encryption": {"enabled": True},
        "topic_obfuscation": {"enabled": True},
        "padding": {"fixed_size": 512},
    }
    safe_result = processor.process_payload(sign_policy_envelope(safe_policy, signer))
    print("safe policy final ACK:")
    print(json.dumps(safe_result.ack, indent=2, sort_keys=True))

    unsafe_policy = dict(safe_policy)
    unsafe_policy["id"] = "policy-v110-unsafe-padding"
    unsafe_policy["sequence_no"] = 2
    unsafe_policy["padding"] = {"fixed_size": 999999}
    unsafe_result = processor.process_payload(sign_policy_envelope(unsafe_policy, signer))
    print("unsafe policy final ACK:")
    print(json.dumps(unsafe_result.ack, indent=2, sort_keys=True))

    revoked_krl = build_krl(
        1,
        [{"key_id": "controller-key-2026-001", "revoked_at": "2026-06-06T00:00:00Z", "reason": "demo"}],
    )
    revoked_processor = TrustedControlPolicyProcessor(
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        krl=revoked_krl,
        client_id="subscriber-demo",
        policy_validator=simple_policy_guard,
    )
    revoked_result = revoked_processor.process_payload(sign_policy_envelope(safe_policy, signer))
    print("revoked key final ACK:")
    print(json.dumps(revoked_result.ack, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
