#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from aomqtt import AOMQTTConfig, PolicyController


SENSITIVE_KEYS = {"topic_key", "payload_key"}


def mask_config(data: dict[str, Any], *, show_keys: bool = False) -> dict[str, Any]:
    if show_keys:
        return dict(data)
    masked = dict(data)
    for key in SENSITIVE_KEYS:
        if key in masked and masked[key]:
            value = str(masked[key])
            if len(value) <= 8:
                masked[key] = "***"
            else:
                masked[key] = f"{value[:4]}...{value[-4:]}"
    return masked


def main() -> None:
    parser = argparse.ArgumentParser(description="Show effective AOMQTT v0.7.1 config after applying an external policy")
    parser.add_argument("--config", default="examples/config.example.yaml")
    parser.add_argument("--policy", default="examples/policy.example.yaml")
    parser.add_argument("--show-keys", action="store_true", help="show topic_key and payload_key instead of masking them")
    args = parser.parse_args()

    base = AOMQTTConfig.from_yaml(args.config)
    controller = PolicyController.from_yaml(args.policy)
    effective = controller.apply(base)

    print(f"policy_id: {controller.policy.policy_id}")
    print(f"policy: {controller.policy.name}")
    print(json.dumps(mask_config(effective.to_dict(redact=False), show_keys=args.show_keys), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
