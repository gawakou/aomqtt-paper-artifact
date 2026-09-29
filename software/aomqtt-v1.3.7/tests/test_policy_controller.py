from __future__ import annotations

import pytest

from aomqtt import AOMQTTConfig, AOMQTTPolicy, PolicyController
from aomqtt.exceptions import AOMQTTConfigurationError


def base_config() -> AOMQTTConfig:
    return AOMQTTConfig(
        topic_key="topic-key-for-tests-123456",
        payload_key="payload-key-for-tests-123456",
        token_mode="hierarchical",
        mqtt_qos=0,
        rotation_enabled=False,
        padding_enabled=False,
        padding_mode="none",
    )


def test_nested_policy_applies_runtime_controls() -> None:
    policy = AOMQTTPolicy.from_dict(
        {
            "policy": {
                "name": "whole_bucket_rotation",
                "token_mode": "whole",
                "qos": 1,
                "rotation": {"enabled": True, "interval_sec": 30, "overlap_sec": 5},
                "padding": {"enabled": True, "mode": "bucket", "bucket_size": 256},
            }
        }
    )
    cfg = policy.apply_to_config(base_config())
    assert cfg.token_mode == "whole"
    assert cfg.mqtt_qos == 1
    assert cfg.rotation_enabled is True
    assert cfg.rotation_interval_sec == 30
    assert cfg.rotation_overlap_sec == 5
    assert cfg.padding_enabled is True
    assert cfg.padding_mode == "bucket"
    assert cfg.padding_bucket_size == 256


def test_policy_mode_none_disables_padding() -> None:
    cfg = AOMQTTPolicy.from_dict({"padding": {"mode": "none"}}).apply_to_config(
        base_config().with_token_mode("whole")
    )
    assert cfg.padding_enabled is False
    assert cfg.padding_mode == "none"


def test_policy_validation_catches_invalid_rotation() -> None:
    policy = AOMQTTPolicy.from_dict(
        {"rotation": {"enabled": True, "interval_sec": 10, "overlap_sec": 10}}
    )
    with pytest.raises(AOMQTTConfigurationError):
        policy.apply_to_config(base_config())


def test_policy_controller_loads_policy_matrix(tmp_path) -> None:
    path = tmp_path / "policies.yaml"
    path.write_text(
        """
policies:
  - name: p1
    token_mode: whole
  - name: p2
    token_mode: hierarchical
    padding:
      enabled: true
      mode: fixed
      fixed_size: 512
""",
        encoding="utf-8",
    )
    policies = PolicyController.load_policies(path)
    assert [p.name for p in policies] == ["p1", "p2"]
    cfg = policies[1].apply_to_config(base_config())
    assert cfg.padding_enabled is True
    assert cfg.padding_mode == "fixed"
    assert cfg.padding_fixed_size == 512


def test_policy_id_and_name_are_applied_to_config() -> None:
    policy = AOMQTTPolicy.from_dict(
        {
            "policy": {
                "id": "p_whole_bucket",
                "name": "whole_bucket",
                "token_mode": "whole",
            }
        }
    )
    cfg = policy.apply_to_config(base_config())
    assert policy.policy_id == "p_whole_bucket"
    assert cfg.policy_id == "p_whole_bucket"
    assert cfg.policy_name == "whole_bucket"


def test_policy_id_defaults_to_name_for_compatibility() -> None:
    policy = AOMQTTPolicy.from_dict({"name": "legacy_policy", "token_mode": "whole"})
    cfg = policy.apply_to_config(base_config())
    assert policy.policy_id == "legacy_policy"
    assert cfg.policy_id == "legacy_policy"
    assert cfg.policy_name == "legacy_policy"
