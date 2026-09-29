from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aomqtt.multisig_policy import build_multisig_policy_ack, sign_multisig_policy_envelope, verify_multisig_policy_envelope
from aomqtt.signing import LocalEd25519Signer
from aomqtt.transparency_log import TransparencyLog


policy = {
    "id": "policy-v120-demo",
    "sequence_no": 1,
    "encryption": {"enabled": True},
    "topic_obfuscation": {"enabled": True},
    "padding": {"fixed_size": 512},
    "rotation": {"interval": 30, "overlap": 5},
}

security = LocalEd25519Signer.generate("security-officer-key")
controller = LocalEd25519Signer.generate("controller-key")
trusted = {
    security.key_id: security.public_key(),
    controller.key_id: controller.public_key(),
}

envelope = sign_multisig_policy_envelope(
    policy,
    [security, controller],
    threshold=2,
    signer_roles={security.key_id: "security", controller.key_id: "controller"},
    required_roles=["security", "controller"],
)

result = verify_multisig_policy_envelope(envelope, trusted_public_keys=trusted)
ack = build_multisig_policy_ack(result, client_id="subscriber-demo")

log = TransparencyLog()
entry = log.append_policy(
    policy,
    signer_key_ids=result.signer_key_ids,
    threshold=result.threshold,
    decision=ack["status"],
    reason_code=ack["reason_code"],
)
log_result = log.verify()

print("multi-signature ACK:")
print(json.dumps(ack, indent=2, ensure_ascii=False))
print("transparency log entry:")
print(json.dumps(entry.to_dict(), indent=2, ensure_ascii=False))
print("transparency log verification:")
print(json.dumps(log_result.to_dict(), indent=2, ensure_ascii=False))
