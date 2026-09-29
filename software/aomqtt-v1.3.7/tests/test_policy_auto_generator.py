from aomqtt.policy_auto.generator import generate_next_policy_dict
from aomqtt.policy_auto.rules import PolicyDecision


def base_policy():
    return {
        "id": "p_whole_bucket_rotation",
        "name": "whole_bucket_rotation",
        "token_mode": "whole",
        "qos": 1,
        "retain": False,
        "rotation": {
            "enabled": True,
            "interval_sec": 30,
            "overlap_sec": 5,
        },
        "padding": {
            "enabled": True,
            "mode": "bucket",
            "bucket_size": 256,
            "fixed_size": 512,
            "random_min_bytes": 0,
            "random_max_bytes": 128,
        },
    }


def test_generate_next_policy_increase_overlap():
    generated = generate_next_policy_dict(
        base_policy(),
        PolicyDecision(action="increase_overlap", reason="loss"),
        sequence_no=200,
    )

    assert generated["id"] == "p_whole_bucket_rotation_auto_s200"
    assert generated["rotation"]["overlap_sec"] == 10
    assert generated["auto_control"]["decision_action"] == "increase_overlap"


def test_generate_next_policy_decrease_overlap():
    generated = generate_next_policy_dict(
        base_policy(),
        PolicyDecision(action="decrease_overlap", reason="duplicate"),
        sequence_no=201,
    )

    assert generated["rotation"]["overlap_sec"] == 0


def test_generate_next_policy_reduce_padding():
    generated = generate_next_policy_dict(
        base_policy(),
        PolicyDecision(action="reduce_padding", reason="overhead"),
        sequence_no=202,
    )

    assert generated["padding"]["bucket_size"] == 128
