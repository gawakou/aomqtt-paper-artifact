from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


@dataclass(frozen=True)
class AnomalyRuleConfig:
    rejected_count_threshold: int = 5
    rejected_ratio_threshold: float = 0.5
    min_rotation_interval_seconds: int = 10
    max_padding_fixed_size: int = 4096


@dataclass(frozen=True)
class ControllerAnomaly:
    anomaly_type: str
    severity: str
    reason_code: str
    count: int
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DANGEROUS_REASON_CODES = {
    "ENCRYPTION_DISABLED",
    "TOPIC_OBFUSCATION_DISABLED",
    "PADDING_TOO_LARGE",
    "ROTATION_INTERVAL_TOO_SHORT",
    "SEQUENCE_REPLAY",
    "UNKNOWN_SIGNING_KEY",
    "REVOKED_SIGNING_KEY",
    "KRL_SIGNATURE_INVALID",
    "KRL_TOO_OLD",
}


def _status_of(record: Mapping[str, Any]) -> str:
    return str(record.get("status") or record.get("ack_status") or record.get("result") or "").lower()


def _reason_of(record: Mapping[str, Any]) -> str:
    return str(record.get("reason_code") or record.get("reason") or "UNKNOWN")


def detect_controller_anomalies(
    records: Iterable[Mapping[str, Any]],
    config: Optional[AnomalyRuleConfig] = None,
) -> List[ControllerAnomaly]:
    cfg = config or AnomalyRuleConfig()
    rows = list(records)
    anomalies: List[ControllerAnomaly] = []
    if not rows:
        return anomalies

    rejected_rows = [r for r in rows if "reject" in _status_of(r) or _reason_of(r) in DANGEROUS_REASON_CODES]
    rejected_count = len(rejected_rows)
    rejected_ratio = rejected_count / len(rows)

    if rejected_count >= cfg.rejected_count_threshold and rejected_ratio >= cfg.rejected_ratio_threshold:
        anomalies.append(
            ControllerAnomaly(
                anomaly_type="HIGH_REJECTION_RATE",
                severity="high",
                reason_code="REJECTED_ACK_SPIKE",
                count=rejected_count,
                detail=f"rejected={rejected_count}, total={len(rows)}, ratio={rejected_ratio:.3f}",
            )
        )

    reason_counts: Dict[str, int] = {}
    for row in rejected_rows:
        reason = _reason_of(row)
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for reason, count in sorted(reason_counts.items()):
        if reason in DANGEROUS_REASON_CODES:
            severity = "critical" if reason in {"REVOKED_SIGNING_KEY", "UNKNOWN_SIGNING_KEY", "ENCRYPTION_DISABLED"} else "high"
            anomalies.append(
                ControllerAnomaly(
                    anomaly_type="DANGEROUS_POLICY_REJECTION",
                    severity=severity,
                    reason_code=reason,
                    count=count,
                    detail=f"dangerous rejection reason observed: {reason}",
                )
            )

    for row in rows:
        policy = row.get("policy")
        if not isinstance(policy, Mapping):
            continue
        rotation = policy.get("rotation")
        if isinstance(rotation, Mapping):
            interval = rotation.get("interval") or rotation.get("rotation_interval") or rotation.get("rotation_interval_seconds")
            if isinstance(interval, (int, float)) and interval < cfg.min_rotation_interval_seconds:
                anomalies.append(
                    ControllerAnomaly(
                        anomaly_type="SUSPICIOUS_POLICY_VALUE",
                        severity="high",
                        reason_code="ROTATION_INTERVAL_TOO_SHORT",
                        count=1,
                        detail=f"rotation interval {interval} < {cfg.min_rotation_interval_seconds}",
                    )
                )
        padding = policy.get("padding")
        if isinstance(padding, Mapping):
            fixed_size = padding.get("fixed_size")
            if isinstance(fixed_size, (int, float)) and fixed_size > cfg.max_padding_fixed_size:
                anomalies.append(
                    ControllerAnomaly(
                        anomaly_type="SUSPICIOUS_POLICY_VALUE",
                        severity="high",
                        reason_code="PADDING_TOO_LARGE",
                        count=1,
                        detail=f"padding fixed_size {fixed_size} > {cfg.max_padding_fixed_size}",
                    )
                )

    return anomalies


def write_anomaly_reports(anomalies: Iterable[ControllerAnomaly], output_dir: str | Path) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [a.to_dict() for a in anomalies]

    csv_path = out / "controller_anomaly_report.csv"
    json_path = out / "controller_anomaly_report.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["anomaly_type", "severity", "reason_code", "count", "detail"])
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"anomalies": rows}, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return csv_path, json_path
