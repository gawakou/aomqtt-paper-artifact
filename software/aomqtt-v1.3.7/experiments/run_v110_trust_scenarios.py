from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

# Allow direct execution with: python experiments/run_v110_trust_scenarios.py
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aomqtt.krl import build_krl
from aomqtt.policy_trust import sign_policy_envelope
from aomqtt.signing import LocalEd25519Signer
from aomqtt.trusted_control_processor import TrustedControlPolicyProcessor


def v110_policy_guard(policy: Mapping[str, Any]):
    """Minimal v1.1.0 scenario guard compatible with the existing v1.0.2 Policy Guard semantics.

    This guard is intentionally small. In production, pass an adapter around the
    existing Policy Guard instead of using this scenario helper.
    """
    encryption = policy.get("encryption")
    if isinstance(encryption, Mapping) and encryption.get("enabled") is False:
        return {"accepted": False, "reason_code": "ENCRYPTION_DISABLED"}

    topic_obfuscation = policy.get("topic_obfuscation")
    if isinstance(topic_obfuscation, Mapping) and topic_obfuscation.get("enabled") is False:
        return {"accepted": False, "reason_code": "TOPIC_OBFUSCATION_DISABLED"}

    padding = policy.get("padding")
    if isinstance(padding, Mapping):
        fixed_size = padding.get("fixed_size")
        if isinstance(fixed_size, (int, float)) and fixed_size > 4096:
            return {"accepted": False, "reason_code": "PADDING_TOO_LARGE"}

    rotation = policy.get("rotation")
    if isinstance(rotation, Mapping):
        interval = rotation.get("interval") or rotation.get("rotation_interval") or rotation.get("rotation_interval_seconds")
        if isinstance(interval, (int, float)) and interval < 10:
            return {"accepted": False, "reason_code": "ROTATION_INTERVAL_TOO_SHORT"}

    return None


def _base_policy(policy_id: str, sequence_no: int) -> Dict[str, Any]:
    return {
        "id": policy_id,
        "sequence_no": sequence_no,
        "encryption": {"enabled": True},
        "topic_obfuscation": {"enabled": True},
        "padding": {"fixed_size": 512},
        "rotation": {"interval": 30, "overlap": 5},
    }


def _write_ack_reports(records: List[Mapping[str, Any]], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "control_ack_summary.csv"
    json_path = output_dir / "control_ack_summary.json"

    fieldnames = [
        "scenario",
        "client_id",
        "policy_id",
        "sequence_no",
        "status",
        "reason_code",
        "stage",
        "signer_key_id",
        "signature_algorithm",
        "signing_method",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow({name: row.get(name, "") for name in fieldnames})

    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"acks": list(records)}, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return csv_path, json_path


def run_scenarios(output_dir: str | Path, *, client_id: str = "subscriber-v110-scenario") -> Dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    active_signer = LocalEd25519Signer.generate("controller-key-2026-active")
    revoked_signer = LocalEd25519Signer.generate("controller-key-2026-revoked")
    unknown_signer = LocalEd25519Signer.generate("controller-key-2026-unknown")

    trusted_public_keys = {
        active_signer.key_id: active_signer.public_key(),
        revoked_signer.key_id: revoked_signer.public_key(),
    }
    krl = build_krl(
        1,
        [
            {
                "key_id": revoked_signer.key_id,
                "revoked_at": "2026-06-06T00:00:00Z",
                "reason": "v1.1.0 scenario revoked key",
            }
        ],
    )

    processor = TrustedControlPolicyProcessor(
        trusted_public_keys=trusted_public_keys,
        krl=krl,
        client_id=client_id,
        require_signature=True,
        policy_validator=v110_policy_guard,
    )

    scenarios: List[tuple[str, Dict[str, Any]]] = []

    safe_policy = _base_policy("policy-v110-safe", 1)
    scenarios.append(("safe_signed_policy", sign_policy_envelope(safe_policy, active_signer)))

    unknown_policy = _base_policy("policy-v110-unknown-key", 2)
    scenarios.append(("unknown_signing_key", sign_policy_envelope(unknown_policy, unknown_signer)))

    revoked_policy = _base_policy("policy-v110-revoked-key", 3)
    scenarios.append(("revoked_signing_key", sign_policy_envelope(revoked_policy, revoked_signer)))

    invalid_signature_policy = _base_policy("policy-v110-invalid-signature", 4)
    invalid_envelope = sign_policy_envelope(invalid_signature_policy, active_signer)
    invalid_envelope["policy"] = dict(invalid_envelope["policy"])
    invalid_envelope["policy"]["sequence_no"] = 4004
    scenarios.append(("invalid_signature", invalid_envelope))

    unsafe_policy = _base_policy("policy-v110-unsafe-padding", 5)
    unsafe_policy["padding"] = {"fixed_size": 999999}
    scenarios.append(("unsafe_policy_guard", sign_policy_envelope(unsafe_policy, active_signer)))

    records: List[Dict[str, Any]] = []
    for scenario_name, envelope in scenarios:
        result = processor.process_payload(envelope)
        row = dict(result.ack)
        row["scenario"] = scenario_name
        row["stage"] = result.stage
        records.append(row)

    ack_csv, ack_json = _write_ack_reports(records, output)
    anomaly_csv, anomaly_json = processor.write_anomaly_reports(output)

    summary = {
        "total": len(records),
        "accepted": sum(1 for r in records if r.get("status") == "accepted"),
        "rejected": sum(1 for r in records if r.get("status") == "rejected"),
        "reason_counts": {},
        "artifacts": {
            "control_ack_summary_csv": str(ack_csv),
            "control_ack_summary_json": str(ack_json),
            "controller_anomaly_report_csv": str(anomaly_csv),
            "controller_anomaly_report_json": str(anomaly_json),
        },
    }
    for row in records:
        reason = str(row.get("reason_code") or "UNKNOWN")
        summary["reason_counts"][reason] = summary["reason_counts"].get(reason, 0) + 1

    summary_path = output / "v110_trust_scenario_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        f.write("\n")
    summary["artifacts"]["summary_json"] = str(summary_path)

    return {"records": records, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run v1.1.0 trusted policy delivery scenarios.")
    parser.add_argument("--run-id", default="run-v110-trust-scenarios-001")
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--client-id", default="subscriber-v110-scenario")
    args = parser.parse_args()

    output_dir = Path(args.results_root) / args.run_id
    result = run_scenarios(output_dir, client_id=args.client_id)

    print(json.dumps(result["summary"], indent=2, ensure_ascii=False, sort_keys=True))
    print(f"wrote v1.1.0 scenario artifacts under {output_dir}")


if __name__ == "__main__":
    main()
