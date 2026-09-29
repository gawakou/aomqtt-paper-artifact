from aomqtt.policy_auto.metrics import ObservationMetrics
from aomqtt.policy_auto.rules import RuleThresholds, decide_policy_action


def test_decide_increase_overlap_on_loss():
    metrics = ObservationMetrics(loss_rate=0.01, duplicate_rate=0.0)
    decision = decide_policy_action(metrics)

    assert decision.action == "increase_overlap"


def test_decide_decrease_overlap_on_duplicate():
    metrics = ObservationMetrics(loss_rate=0.0, duplicate_rate=0.5)
    decision = decide_policy_action(metrics)

    assert decision.action == "decrease_overlap"


def test_decide_reduce_padding_on_overhead():
    metrics = ObservationMetrics(
        loss_rate=0.0,
        duplicate_rate=0.0,
        avg_payload_total_overhead_bytes=2048,
    )
    decision = decide_policy_action(metrics)

    assert decision.action == "reduce_padding"


def test_decide_hold_on_decrypt_failure():
    metrics = ObservationMetrics(
        decrypt_success_rate=0.9,
        loss_rate=0.0,
        duplicate_rate=0.0,
    )
    decision = decide_policy_action(
        metrics,
        RuleThresholds(decrypt_success_rate_threshold=1.0),
    )

    assert decision.action == "hold_policy_switch"
