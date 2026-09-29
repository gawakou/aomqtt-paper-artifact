"""Rule-based Policy decision engine for AOMQTT v0.8.3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .metrics import ObservationMetrics


@dataclass
class RuleThresholds:
    loss_rate_threshold: float = 0.0
    duplicate_rate_threshold: float = 0.10
    overhead_bytes_threshold: float = 512.0
    latency_ms_threshold: float = 100.0
    decrypt_success_rate_threshold: float = 1.0

    overlap_step_sec: int = 5
    min_overlap_sec: int = 0
    max_overlap_sec: int = 60
    min_padding_bucket_size: int = 128
    min_fixed_padding_size: int = 128


@dataclass
class PolicyDecision:
    action: str
    reason: str
    changes: dict[str, Any] = field(default_factory=dict)

    def is_noop(self) -> bool:
        return self.action in {"keep", "hold_policy_switch"}


def _gt(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _lt(value: float | None, threshold: float) -> bool:
    return value is not None and value < threshold


def decide_policy_action(
    metrics: ObservationMetrics,
    thresholds: RuleThresholds | None = None,
) -> PolicyDecision:
    """Decide the next Policy action from observation metrics.

    Priority:
      1. decrypt failure -> hold policy switching
      2. loss -> increase overlap
      3. duplicate -> decrease overlap
      4. overhead -> reduce padding
      5. latency -> reduce padding
      6. otherwise keep
    """
    th = thresholds or RuleThresholds()

    if _lt(metrics.decrypt_success_rate, th.decrypt_success_rate_threshold):
        return PolicyDecision(
            action="hold_policy_switch",
            reason=(
                "decrypt_success_rate is below threshold: "
                f"{metrics.decrypt_success_rate} < {th.decrypt_success_rate_threshold}"
            ),
        )

    if _gt(metrics.loss_rate, th.loss_rate_threshold):
        return PolicyDecision(
            action="increase_overlap",
            reason=f"loss_rate is above threshold: {metrics.loss_rate} > {th.loss_rate_threshold}",
            changes={"rotation.overlap_sec": f"+{th.overlap_step_sec}"},
        )

    if _gt(metrics.duplicate_rate, th.duplicate_rate_threshold):
        return PolicyDecision(
            action="decrease_overlap",
            reason=(
                f"duplicate_rate is above threshold: "
                f"{metrics.duplicate_rate} > {th.duplicate_rate_threshold}"
            ),
            changes={"rotation.overlap_sec": f"-{th.overlap_step_sec}"},
        )

    if _gt(metrics.avg_payload_total_overhead_bytes, th.overhead_bytes_threshold):
        return PolicyDecision(
            action="reduce_padding",
            reason=(
                "avg_payload_total_overhead_bytes is above threshold: "
                f"{metrics.avg_payload_total_overhead_bytes} > {th.overhead_bytes_threshold}"
            ),
            changes={"padding": "reduce"},
        )

    latency_candidates = [
        metrics.avg_publish_complete_ms,
        metrics.avg_delivery_latency_ms,
    ]
    if any(_gt(v, th.latency_ms_threshold) for v in latency_candidates):
        return PolicyDecision(
            action="reduce_padding",
            reason=f"latency is above threshold: threshold={th.latency_ms_threshold}",
            changes={"padding": "reduce"},
        )

    return PolicyDecision(
        action="keep",
        reason="no rule matched",
    )
