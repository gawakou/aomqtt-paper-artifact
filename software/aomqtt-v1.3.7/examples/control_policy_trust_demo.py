from __future__ import annotations

import json

from aomqtt.control_policy_trust import verify_control_policy_payload
from aomqtt.krl import build_krl
from aomqtt.policy_trust import sign_policy_envelope
from aomqtt.signing import LocalEd25519Signer


def main() -> None:
    signer = LocalEd25519Signer.generate("controller-key-2026-001")
    policy = {
        "id": "policy-v110-demo",
        "sequence_no": 1,
        "encryption": {"enabled": True},
        "topic_obfuscation": {"enabled": True},
    }
    envelope = sign_policy_envelope(policy, signer)
    payload = json.dumps(envelope).encode("utf-8")

    accepted = verify_control_policy_payload(
        payload,
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        client_id="subscriber-demo",
    )
    print("accepted ACK:")
    print(json.dumps(accepted.ack, indent=2, sort_keys=True))

    krl = build_krl(
        1,
        [
            {
                "key_id": "controller-key-2026-001",
                "revoked_at": "2026-06-06T00:00:00Z",
                "reason": "demo_revocation",
            }
        ],
    )
    rejected = verify_control_policy_payload(
        payload,
        trusted_public_keys={"controller-key-2026-001": signer.public_key()},
        krl=krl,
        client_id="subscriber-demo",
    )
    print("revoked-key ACK:")
    print(json.dumps(rejected.ack, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
