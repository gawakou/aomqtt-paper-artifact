#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from aomqtt import AOMQTTConfig, AOMQTTPublisher, AOMQTTSubscriber, DeliveryCSVLogger, PolicyController, PublishCSVLogger
from run_evaluation import payload_for, write_comparison, write_mode_summary


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in name).strip("_") or "policy"


def apply_cli_rotation_overrides(cfg: AOMQTTConfig, args: argparse.Namespace) -> AOMQTTConfig:
    values: dict[str, int] = {}
    if args.rotation_interval is not None:
        values["rotation_interval_sec"] = args.rotation_interval
    if args.rotation_overlap is not None:
        values["rotation_overlap_sec"] = args.rotation_overlap
    if not values:
        return cfg
    overridden = replace(cfg, **values)
    overridden.validate()
    return overridden


def run_policy(args: argparse.Namespace, policy_name: str, cfg: AOMQTTConfig, mode_dir: Path) -> dict[str, Any]:
    mode_dir.mkdir(parents=True, exist_ok=True)
    pub_csv = PublishCSVLogger(mode_dir / "publisher_metrics.csv")
    sub_csv = DeliveryCSVLogger(mode_dir / "subscriber_metrics.csv")

    def on_message(token_topic, payload, raw_msg):
        return None

    sub = AOMQTTSubscriber(
        broker_host=args.broker,
        broker_port=args.port,
        client_id=f"aomqtt-v07-sub-{policy_name}",
        config=cfg,
    )
    pub = AOMQTTPublisher(
        broker_host=args.broker,
        broker_port=args.port,
        client_id=f"aomqtt-v07-pub-{policy_name}",
        config=cfg,
    )

    sub.connect()
    sub.loop_start()
    time.sleep(args.startup_wait)
    if cfg.rotation_enabled:
        sub.subscribe_rotating_observed(
            args.topic,
            callback=on_message,
            refresh_interval_sec=args.refresh_interval,
            csv_logger=sub_csv,
        )
    else:
        sub.subscribe_observed(args.topic, callback=on_message, csv_logger=sub_csv)
    time.sleep(args.startup_wait)

    pub.connect()
    pub.loop_start()
    time.sleep(args.startup_wait)
    try:
        for seq in range(args.count):
            payload = payload_for(policy_name, seq)
            pub.publish_observed_rotating(
                args.topic,
                payload,
                logical_seq=payload["message_id"],
                wait_for_publish=not args.no_wait,
                wait_timeout=args.wait_timeout,
                csv_logger=pub_csv,
            )
            time.sleep(args.interval)
        time.sleep(args.settle_wait)
    finally:
        pub.loop_stop()
        pub.disconnect()
        sub.loop_stop()
        sub.disconnect()
        pub_csv.close()
        sub_csv.close()
    return write_mode_summary(mode_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AOMQTT v0.7.1 external-policy evaluation")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="shelter/siteA/starlink/rtt")
    parser.add_argument("--config", default="examples/config.example.yaml")
    parser.add_argument("--policies", default="examples/policies.matrix.yaml", help="YAML file with policies: [...] or a single policy")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--rotation-interval", type=int, default=None, help="override rotation.interval_sec in each policy")
    parser.add_argument("--rotation-overlap", type=int, default=None, help="override rotation.overlap_sec in each policy")
    parser.add_argument("--refresh-interval", type=float, default=1.0)
    parser.add_argument("--startup-wait", type=float, default=0.5)
    parser.add_argument("--settle-wait", type=float, default=1.0)
    parser.add_argument("--wait-timeout", type=float, default=None)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--output", default="results/eval_v07_policy")
    args = parser.parse_args()

    base_config = AOMQTTConfig.from_yaml(args.config)
    policies = PolicyController.load_policies(args.policies)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: dict[str, dict[str, Any]] = {}
    for policy in policies:
        label = safe_name(policy.name)
        cfg = apply_cli_rotation_overrides(policy.apply_to_config(base_config), args)
        print(
            f"[v0.7.1] running policy: {label} "
            f"policy_id={cfg.policy_id} token_mode={cfg.token_mode} qos={cfg.mqtt_qos} "
            f"rotation={cfg.rotation_enabled} interval={cfg.rotation_interval_sec} "
            f"overlap={cfg.rotation_overlap_sec} padding={cfg.padding_mode}"
        )
        summaries[label] = run_policy(args, label, cfg, output_dir / label)

    write_comparison(output_dir, summaries)
    print(f"[v0.7.1] wrote results to: {output_dir}")
    print(f"[v0.7.1] comparison:       {output_dir / 'comparison_summary.csv'}")


if __name__ == "__main__":
    main()
