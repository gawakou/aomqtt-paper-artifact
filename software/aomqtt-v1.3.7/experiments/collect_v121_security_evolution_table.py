#!/usr/bin/env python3
"""Generate a paper-ready security evolution table for AOMQTT v1.2.1.

This script is intentionally deterministic.  It does not require a broker and
does not depend on generated runtime logs.  It summarizes the security
capabilities introduced across v1.0.2, v1.1.0, and v1.2.0 so that the paper can
refer to a reproducible CSV/JSON artifact.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def build_security_evolution_rows() -> list[dict[str, Any]]:
    return [
        {
            "version": "v1.0.2",
            "release_theme": "Client-side Policy Guard",
            "primary_protection": "Reject unsafe policies from compromised or misconfigured controllers",
            "trust_model": "The client does not fully trust the Policy Controller",
            "decision_basis": "local safety invariants, sequence checks, validity checks, trusted key metadata when available",
            "covered_rejections": "unsafe padding; encryption disabled; topic obfuscation disabled; invalid rotation constraints; replayed policy",
            "auditability": "rejected ACK with policy_id, sequence_no, key_id, and reason_code where extractable",
            "paper_claim": "AOMQTT prevents a compromised controller from forcing clients into unsafe local policy states",
        },
        {
            "version": "v1.1.0",
            "release_theme": "Trusted Policy Delivery and Key Lifecycle Hardening",
            "primary_protection": "Validate signer identity and reject unknown, revoked, or invalid signatures",
            "trust_model": "Policies must be signed by a trusted non-revoked signing key",
            "decision_basis": "signer_key_id validation, Key Revocation List, Ed25519 signature validation, Policy Guard",
            "covered_rejections": "unknown signing key; revoked signing key; invalid signature; unsafe policy",
            "auditability": "ACK summary, reason_code summary, controller anomaly report",
            "paper_claim": "AOMQTT reduces trust in the controller signing environment by supporting signer validation and key revocation",
        },
        {
            "version": "v1.2.0",
            "release_theme": "Multi-Signature Policy and Transparency Log",
            "primary_protection": "Require multi-party policy authorization and record policy decisions in a verifiable log",
            "trust_model": "Policy acceptance can require threshold signatures and required signer roles",
            "decision_basis": "multi-signature threshold, required roles, KRL-aware signer validation, Policy Guard, hash-chain verification",
            "covered_rejections": "threshold not met; required role missing; revoked key; invalid signature; unsafe policy",
            "auditability": "hash-chain transparency log, transparency verification result, ACK/anomaly summaries, release table",
            "paper_claim": "AOMQTT extends trusted policy delivery from single-signer validation to multi-party authorization and auditable policy history",
        },
    ]


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "version",
        "release_theme",
        "primary_protection",
        "trust_model",
        "decision_basis",
        "covered_rejections",
        "auditability",
        "paper_claim",
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
    parser.add_argument("--out-dir", default="results/run-v121-evaluation-reproducibility-001")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    rows = build_security_evolution_rows()
    csv_path = out_dir / "security_evolution_table.csv"
    json_path = out_dir / "security_evolution_table.json"

    write_csv(rows, csv_path)
    write_json(rows, json_path)

    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

