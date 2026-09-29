from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aomqtt.multisig_policy import sign_multisig_policy_envelope
from aomqtt.signing import LocalEd25519Signer
from aomqtt.trusted_multisig_processor import TrustedMultiSignaturePolicyProcessor


policy = {
    "id": "policy-v120-runtime-demo",
    "sequence_no": 1,
    "encryption": {"enabled": True},
    "topic_obfuscation": {"enabled": True},
    "padding": {"fixed_size": 512},
    "rotation": {"interval": 30, "overlap": 5},
}

controller = LocalEd25519Signer.generate("controller-key")
security = LocalEd25519Signer.generate("security-officer-key")

envelope = sign_multisig_policy_envelope(
    policy,
    [controller, security],
    threshold=2,
    signer_roles={controller.key_id: "controller", security.key_id: "security"},
    required_roles=["controller", "security"],
)

processor = TrustedMultiSignaturePolicyProcessor(
    trusted_public_keys={controller.key_id: controller.public_key(), security.key_id: security.public_key()},
    client_id="subscriber-demo",
    required_roles=["controller", "security"],
)
result = processor.process_payload(envelope)

print("trusted multi-signature processor ACK:")
print(json.dumps(result.ack, indent=2, ensure_ascii=False, sort_keys=True))
print("transparency log verification:")
print(json.dumps(processor.verify_transparency_log().to_dict(), indent=2, ensure_ascii=False, sort_keys=True))
if result.transparency_entry is not None:
    print("transparency entry hash:")
    print(result.transparency_entry.entry_hash)
