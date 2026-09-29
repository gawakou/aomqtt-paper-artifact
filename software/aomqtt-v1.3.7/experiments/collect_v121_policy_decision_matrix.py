#!/usr/bin/env python3
"""Generate a policy decision matrix from v1.1.0 and v1.2.0 scenario summaries."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


DEFAULT_V110_SUMMARY = "results/run-v110-trust-scenarios-001/v110_trust_scenario_summary.json"
DEFAULT_V120_SUMMARY = "results/run-v120-multisig-transparency-001/v120_multisig_transparency_summary.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def count_reason(summary: dict[str, Any], reason_code: str) -> int:
    return int(summary.get("reason_counts", {}).get(reason_code, 0))


def build_policy_decision_rows(v110: dict[str, Any], v120: dict[str, Any]) -> list[dict[str, Any]]:
    tlog = v120.get("transparency_log", {})
    return [
        {
            "case_id": "v110_valid_trusted_policy",
            "introduced_in": "v1.1.0",
            "policy_condition": "trusted signed policy",
            "expected_decision": "accepted",
            "expected_reason_code": "OK",
            "observed_count": count_reason(v110, "OK"),
            "evidence_source": "v110_trust_scenario_summary.json",
            "paper_interpretation": "A valid trusted policy is accepted.",
        },
        {
            "case_id": "v110_unknown_signing_key",
            "introduced_in": "v1.1.0",
            "policy_condition": "policy signed by an unknown key",
            "expected_decision": "rejected",
            "expected_reason_code": "UNKNOWN_SIGNING_KEY",
            "observed_count": count_reason(v110, "UNKNOWN_SIGNING_KEY"),
            "evidence_source": "v110_trust_scenario_summary.json",
            "paper_interpretation": "A policy signed by an untrusted key is rejected.",
        },
        {
            "case_id": "v110_revoked_signing_key",
            "introduced_in": "v1.1.0",
            "policy_condition": "policy signed by a revoked key",
            "expected_decision": "rejected",
            "expected_reason_code": "REVOKED_SIGNING_KEY",
            "observed_count": count_reason(v110, "REVOKED_SIGNING_KEY"),
            "evidence_source": "v110_trust_scenario_summary.json",
            "paper_interpretation": "A policy signed by a revoked key is rejected.",
        },
        {
            "case_id": "v110_invalid_signature",
            "introduced_in": "v1.1.0",
            "policy_condition": "policy with invalid signature",
            "expected_decision": "rejected",
            "expected_reason_code": "POLICY_SIGNATURE_INVALID",
            "observed_count": count_reason(v110, "POLICY_SIGNATURE_INVALID"),
            "evidence_source": "v110_trust_scenario_summary.json",
            "paper_interpretation": "A tampered or incorrectly signed policy is rejected.",
        },
        {
            "case_id": "v110_unsafe_padding_policy",
            "introduced_in": "v1.0.2",
            "policy_condition": "unsafe padding policy",
            "expected_decision": "rejected",
            "expected_reason_code": "PADDING_TOO_LARGE",
            "observed_count": count_reason(v110, "PADDING_TOO_LARGE"),
            "evidence_source": "v110_trust_scenario_summary.json",
            "paper_interpretation": "A signed but unsafe policy is still rejected by the client-side Policy Guard.",
        },
        {
            "case_id": "v120_valid_multisig_policy",
            "introduced_in": "v1.2.0",
            "policy_condition": "valid multi-signature policy satisfying threshold and role requirements",
            "expected_decision": "accepted",
            "expected_reason_code": "OK",
            "observed_count": count_reason(v120, "OK"),
            "evidence_source": "v120_multisig_transparency_summary.json",
            "paper_interpretation": "A policy authorized by the required parties is accepted.",
        },
        {
            "case_id": "v120_threshold_not_met",
            "introduced_in": "v1.2.0",
            "policy_condition": "multi-signature threshold not met",
            "expected_decision": "rejected",
            "expected_reason_code": "MULTISIG_THRESHOLD_NOT_MET",
            "observed_count": count_reason(v120, "MULTISIG_THRESHOLD_NOT_MET"),
            "evidence_source": "v120_multisig_transparency_summary.json",
            "paper_interpretation": "A policy without enough valid signatures is rejected.",
        },
        {
            "case_id": "v120_required_role_missing",
            "introduced_in": "v1.2.0",
            "policy_condition": "required signer role missing",
            "expected_decision": "rejected",
            "expected_reason_code": "MULTISIG_REQUIRED_ROLE_MISSING",
            "observed_count": count_reason(v120, "MULTISIG_REQUIRED_ROLE_MISSING"),
            "evidence_source": "v120_multisig_transparency_summary.json",
            "paper_interpretation": "A policy lacking a required signer role is rejected even if it has signatures.",
        },
        {
            "case_id": "v120_revoked_signing_key",
            "introduced_in": "v1.2.0",
            "policy_condition": "multi-signature policy includes a revoked signing key",
            "expected_decision": "rejected",
            "expected_reason_code": "REVOKED_SIGNING_KEY",
            "observed_count": count_reason(v120, "REVOKED_SIGNING_KEY"),
            "evidence_source": "v120_multisig_transparency_summary.json",
            "paper_interpretation": "KRL-aware multi-signature verification rejects policies signed by revoked keys.",
        },
        {
            "case_id": "v120_invalid_signature",
            "introduced_in": "v1.2.0",
            "policy_condition": "multi-signature policy with invalid signature",
            "expected_decision": "rejected",
            "expected_reason_code": "POLICY_SIGNATURE_INVALID",
            "observed_count": count_reason(v120, "POLICY_SIGNATURE_INVALID"),
            "evidence_source": "v120_multisig_transparency_summary.json",
            "paper_interpretation": "Invalid multi-signature evidence is rejected.",
        },
        {
            "case_id": "v120_unsafe_padding_policy",
            "introduced_in": "v1.0.2",
            "policy_condition": "multi-signature policy that is cryptographically valid but unsafe",
            "expected_decision": "rejected",
            "expected_reason_code": "PADDING_TOO_LARGE",
            "observed_count": count_reason(v120, "PADDING_TOO_LARGE"),
            "evidence_source": "v120_multisig_transparency_summary.json",
            "paper_interpretation": "Policy Guard remains effective after multi-signature authorization.",
        },
        {
            "case_id": "v120_transparency_log_verification",
            "introduced_in": "v1.2.0",
            "policy_condition": "hash-chain transparency log verification",
            "expected_decision": "accepted",
            "expected_reason_code": "OK",
            "observed_count": int(tlog.get("verified_entries", 0)),
            "evidence_source": "transparency_log_verification.json",
            "paper_interpretation": "The generated policy decision history is verifiable as an intact hash chain.",
        },
    ]


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "introduced_in",
        "policy_condition",
        "expected_decision",
        "expected_reason_code",
        "observed_count",
        "evidence_source",
        "paper_interpretation",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump({"rows": rows}, f, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v110-summary", default=DEFAULT_V110_SUMMARY)
    parser.add_argument("--v120-summary", default=DEFAULT_V120_SUMMARY)
    parser.add_argument("--out-dir", default="results/run-v121-evaluation-reproducibility-001")
    args = parser.parse_args(argv)

    v110_summary = load_json(Path(args.v110_summary))
    v120_summary = load_json(Path(args.v120_summary))
    rows = build_policy_decision_rows(v110_summary, v120_summary)

    out_dir = Path(args.out_dir)
    csv_path = out_dir / "policy_decision_matrix.csv"
    json_path = out_dir / "policy_decision_matrix.json"

    write_csv(rows, csv_path)
    write_json(rows, json_path)

    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

