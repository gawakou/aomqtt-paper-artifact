from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aomqtt.krl import build_krl
from aomqtt.multisig_policy import sign_multisig_policy_envelope
from aomqtt.signing import LocalEd25519Signer
from aomqtt.trusted_multisig_processor import TrustedMultiSignaturePolicyProcessor


def _policy(policy_id: str, sequence_no: int, padding_size: int = 512) -> Dict[str, Any]:
    return {
        "id": policy_id,
        "sequence_no": sequence_no,
        "encryption": {"enabled": True},
        "topic_obfuscation": {"enabled": True},
        "padding": {"fixed_size": padding_size},
        "rotation": {"interval": 30, "overlap": 5},
    }


def _write_ack_summary(records: List[Dict[str, Any]], output_dir: Path) -> tuple[Path, Path]:
    csv_path = output_dir / "control_ack_summary.csv"
    json_path = output_dir / "control_ack_summary.json"
    fieldnames = [
        "client_id",
        "policy_id",
        "sequence_no",
        "status",
        "reason_code",
        "signature_mode",
        "threshold",
        "valid_signature_count",
        "signer_key_ids",
        "signer_roles",
        "stage",
        "transparency_log_index",
        "transparency_entry_hash",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            out = dict(row)
            if isinstance(out.get("signer_key_ids"), list):
                out["signer_key_ids"] = ";".join(out["signer_key_ids"])
            if isinstance(out.get("signer_roles"), list):
                out["signer_roles"] = ";".join(out["signer_roles"])
            writer.writerow(out)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"acks": records}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return csv_path, json_path


def main() -> None:
    run_id = os.environ.get("RUN_ID", "run-v120-multisig-transparency-001")
    output_dir = Path("results") / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    controller = LocalEd25519Signer.generate("controller-key")
    security = LocalEd25519Signer.generate("security-officer-key")
    auditor = LocalEd25519Signer.generate("auditor-key")
    revoked = LocalEd25519Signer.generate("revoked-security-key")
    trusted = {
        controller.key_id: controller.public_key(),
        security.key_id: security.public_key(),
        auditor.key_id: auditor.public_key(),
        revoked.key_id: revoked.public_key(),
    }
    krl = build_krl(1, [{"key_id": revoked.key_id, "revoked_at": "2026-06-06T00:00:00Z", "reason": "v1.2.0 scenario"}])

    def guard(policy):
        padding = policy.get("padding", {}) if isinstance(policy, dict) else {}
        if padding.get("fixed_size", 0) > 4096:
            return "PADDING_TOO_LARGE"
        return None

    processor = TrustedMultiSignaturePolicyProcessor(
        trusted_public_keys=trusted,
        krl=krl,
        client_id="subscriber-v120-scenario",
        required_roles=["controller", "security"],
        policy_validator=guard,
    )

    # 1. accepted 2-of-2 controller + security
    accepted = sign_multisig_policy_envelope(
        _policy("policy-v120-accepted", 1),
        [controller, security],
        threshold=2,
        signer_roles={controller.key_id: "controller", security.key_id: "security"},
        required_roles=["controller", "security"],
    )
    processor.process_payload(accepted)

    # 2. threshold not met: only one signature, but threshold is tampered to 2
    threshold_not_met = sign_multisig_policy_envelope(
        _policy("policy-v120-threshold-not-met", 2),
        [controller],
        threshold=1,
        signer_roles={controller.key_id: "controller"},
        required_roles=["controller"],
    )
    threshold_not_met["signature_policy"]["threshold"] = 2
    processor.process_payload(threshold_not_met)

    # 3. required role missing: controller + auditor, no security role
    role_missing = sign_multisig_policy_envelope(
        _policy("policy-v120-role-missing", 3),
        [controller, auditor],
        threshold=2,
        signer_roles={controller.key_id: "controller", auditor.key_id: "auditor"},
        required_roles=["controller", "auditor"],
    )
    processor.process_payload(role_missing)

    # 4. revoked signer
    revoked_policy = sign_multisig_policy_envelope(
        _policy("policy-v120-revoked", 4),
        [controller, revoked],
        threshold=2,
        signer_roles={controller.key_id: "controller", revoked.key_id: "security"},
        required_roles=["controller", "security"],
    )
    processor.process_payload(revoked_policy)

    # 5. invalid signature by tampering with signed policy body
    tampered = sign_multisig_policy_envelope(
        _policy("policy-v120-invalid-signature", 5),
        [controller, security],
        threshold=2,
        signer_roles={controller.key_id: "controller", security.key_id: "security"},
        required_roles=["controller", "security"],
    )
    tampered["policy"]["padding"]["fixed_size"] = 2048
    processor.process_payload(tampered)

    # 6. valid multi-signature but rejected by Policy Guard
    unsafe_padding = sign_multisig_policy_envelope(
        _policy("policy-v120-unsafe-padding", 6, padding_size=999999),
        [controller, security],
        threshold=2,
        signer_roles={controller.key_id: "controller", security.key_id: "security"},
        required_roles=["controller", "security"],
    )
    processor.process_payload(unsafe_padding)

    records = processor.records
    accepted_count = sum(1 for r in records if r.get("status") == "accepted")
    rejected_count = sum(1 for r in records if r.get("status") == "rejected")
    reason_counts: Dict[str, int] = {}
    for row in records:
        reason = str(row.get("reason_code") or "UNKNOWN")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    ack_csv, ack_json = _write_ack_summary(records, output_dir)
    anomaly_csv, anomaly_json = processor.write_anomaly_reports(output_dir)
    tlog_path = processor.write_transparency_log(output_dir)
    tlog_verify = processor.verify_transparency_log()
    tlog_verify_path = output_dir / "transparency_log_verification.json"
    with tlog_verify_path.open("w", encoding="utf-8") as f:
        json.dump(tlog_verify.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")

    summary = {
        "accepted": accepted_count,
        "rejected": rejected_count,
        "total": len(records),
        "reason_counts": dict(sorted(reason_counts.items())),
        "transparency_log": tlog_verify.to_dict(),
        "artifacts": {
            "control_ack_summary_csv": str(ack_csv),
            "control_ack_summary_json": str(ack_json),
            "controller_anomaly_report_csv": str(anomaly_csv),
            "controller_anomaly_report_json": str(anomaly_json),
            "policy_transparency_log_jsonl": str(tlog_path),
            "transparency_log_verification_json": str(tlog_verify_path),
            "summary_json": str(output_dir / "v120_multisig_transparency_summary.json"),
        },
    }
    summary_path = output_dir / "v120_multisig_transparency_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")

    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    print(f"wrote v1.2.0 scenario artifacts under {output_dir}")


if __name__ == "__main__":
    main()
