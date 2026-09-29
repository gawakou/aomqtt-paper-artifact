#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from aomqtt import AOMQTTConfig, AOMQTTSubscriber, DeliveryCSVLogger, PolicyController
from aomqtt.evaluation import DEFAULT_EXPERIMENT_ID, ExperimentContext, generate_run_id, save_experiment_config


def load_config(args) -> AOMQTTConfig:
    cfg = AOMQTTConfig.from_yaml(args.config)
    if args.policy:
        controller = PolicyController.from_yaml(args.policy)
        cfg = controller.apply(cfg)
    if args.token_mode != "config":
        cfg = cfg.with_token_mode(args.token_mode)  # type: ignore[arg-type]
    if args.qos is not None:
        cfg = replace(cfg, mqtt_qos=args.qos)
    if args.rotation:
        cfg = replace(
            cfg,
            rotation_enabled=True,
            rotation_interval_sec=args.rotation_interval,
            rotation_overlap_sec=args.rotation_overlap,
        )
    if args.no_rotation:
        cfg = replace(cfg, rotation_enabled=False)
    cfg.validate()
    return cfg


def main() -> None:
    parser = argparse.ArgumentParser(description="AOMQTT encrypted subscriber example")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--client-id", default="c_sub_001")
    parser.add_argument("--config", default="examples/config.example.yaml")
    parser.add_argument("--policy", default=None, help="external policy YAML overlay")
    parser.add_argument("--enable-control-topic", action="store_true", help="receive runtime policy updates from MQTT control topic")
    parser.add_argument("--control-group-id", default="default", help="control-topic group id")
    parser.add_argument("--control-topic", default=None, help="override MQTT control policy topic")
    parser.add_argument("--control-qos", type=int, choices=[0, 1, 2], default=1, help="QoS for control-topic subscription")
    parser.add_argument("--control-client-id", default=None, help="client id for the control-topic listener")
    parser.add_argument("--control-policy-public-key", default=None, help="Ed25519 raw-base64/PEM public key or a file path for verifying control policies")
    parser.add_argument("--control-policy-public-key-file", default=None, help="file containing Ed25519 raw-base64/PEM public key for verifying control policies")
    parser.add_argument("--require-signed-control-policy", action="store_true", default=True, help="reject unsigned control-topic policies (default: enabled)")
    parser.add_argument("--allow-unsigned-control-policy", action="store_true", help="DANGEROUS: allow unsigned control-topic policies for isolated local experiments only")
    parser.add_argument("--topic", default="shelter/siteA/starlink/rtt")
    parser.add_argument(
        "--token-mode",
        choices=["config", "hierarchical", "whole"],
        default="config",
        help="override config token_mode",
    )
    parser.add_argument("--rotation", action="store_true", help="enable token rotation")
    parser.add_argument("--no-rotation", action="store_true", help="disable token rotation even if policy enables it")
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=None, help="override config/policy MQTT QoS")
    parser.add_argument("--rotation-interval", type=int, default=30, help="rotation interval in seconds")
    parser.add_argument("--rotation-overlap", type=int, default=5, help="overlap window in seconds")
    parser.add_argument("--refresh-interval", type=float, default=1.0, help="subscription refresh interval")
    parser.add_argument("--delivery-csv", default=None, help="write subscriber-side delivery/decryption metrics to CSV")
    parser.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID, help="experiment identifier for reproducible evaluation")
    parser.add_argument("--run-id", default=None, help="run identifier for reproducible evaluation")
    parser.add_argument("--save-experiment-config", action="store_true", help="save effective experiment configuration")
    parser.add_argument("--experiment-config-out", default=None, help="output path for experiment configuration JSON/YAML")
    args = parser.parse_args()
    args.run_id = args.run_id or generate_run_id()
    experiment_context = ExperimentContext(
        experiment_id=args.experiment_id,
        run_id=args.run_id,
    )

    cfg = load_config(args)
    sub = AOMQTTSubscriber(
        broker_host=args.broker,
        broker_port=args.port,
        client_id=args.client_id,
        config=cfg,
    )

    state = sub.current_rotation_state()
    current_epoch = state.current_epoch if cfg.rotation_enabled else None
    print(f"policy id:                  {cfg.policy_id}")
    print(f"policy name:                {cfg.policy_name}")
    print(f"token mode:                 {cfg.token_mode}")
    print(f"rotation enabled:           {cfg.rotation_enabled}")
    if args.policy:
        print(f"policy file:                {args.policy}")
    print(f"rotation interval:          {cfg.rotation_interval_sec}s")
    print(f"rotation overlap:           {cfg.rotation_overlap_sec}s")
    print(f"current epoch:              {state.current_epoch if cfg.rotation_enabled else '-'}")
    print(f"plaintext subscribe filter: {args.topic}")
    print(f"token subscribe filter:     {sub.tokenized_filter(args.topic, epoch=current_epoch)}")
    print(f"experiment id:              {experiment_context.experiment_id}")
    print(f"run id:                     {experiment_context.run_id}")
    if args.delivery_csv:
        print(f"delivery csv:               {args.delivery_csv}")
    if args.save_experiment_config:
        config_out = Path(args.experiment_config_out) if args.experiment_config_out else (
            Path(args.delivery_csv).parent / "experiment_config.json"
            if args.delivery_csv
            else Path("results") / args.run_id / "experiment_config.json"
        )
        save_experiment_config(
            output_path=config_out,
            context=experiment_context,
            config={
                "role": "subscriber",
                "broker": args.broker,
                "port": args.port,
                "client_id": args.client_id,
                "config": args.config,
                "policy": args.policy,
                "topic": args.topic,
                "qos": args.qos,
                "token_mode": args.token_mode,
                "rotation": args.rotation,
                "no_rotation": args.no_rotation,
                "rotation_interval": args.rotation_interval,
                "rotation_overlap": args.rotation_overlap,
                "refresh_interval": args.refresh_interval,
                "delivery_csv": args.delivery_csv,
                "effective_policy_id": cfg.policy_id,
                "effective_policy_name": cfg.policy_name,
            },
        )
        print(f"experiment config:          {config_out}")

    def on_message(token_topic, payload, raw_msg):
        print("received")
        print("  token_topic:", token_topic)
        print("  payload:    ", json.dumps(payload, ensure_ascii=False))

    sub.connect()
    if args.enable_control_topic:
        receiver = sub.start_policy_control(
            group_id=args.control_group_id,
            control_topic=args.control_topic,
            client_id=args.control_client_id,
            qos=args.control_qos,
            signing_public_key=args.control_policy_public_key_file or args.control_policy_public_key,
            require_signature=not args.allow_unsigned_control_policy,
        )
        print(f"control topic:              {receiver.control_topic}")
        print(f"control group id:           {args.control_group_id}")
    delivery_logger = (
        DeliveryCSVLogger(
            args.delivery_csv,
            experiment_id=experiment_context.experiment_id,
            run_id=experiment_context.run_id,
            metrics_schema_version=experiment_context.metrics_schema_version,
        )
        if args.delivery_csv
        else None
    )
    try:
        if cfg.rotation_enabled:
            sub.subscribe_rotating_observed(
                args.topic,
                callback=on_message,
                refresh_interval_sec=args.refresh_interval,
                csv_logger=delivery_logger,
            )
        else:
            sub.subscribe_observed(args.topic, callback=on_message, csv_logger=delivery_logger)
        sub.loop_forever()
    finally:
        if delivery_logger is not None:
            summary = delivery_logger.summary()
            delivery_logger.close()
            print("delivery summary:")
            print(f"  total received:       {summary.total_received}")
            print(f"  decrypt success:      {summary.decrypt_success}")
            print(f"  decrypt failed:       {summary.decrypt_failed}")
            print(f"  unique messages:      {summary.unique_messages}")
            print(f"  duplicates:           {summary.duplicates}")
            print(f"  duplicate_rate:       {summary.duplicate_rate:.3f}")
            print(f"  avg_delivery_ms:      {summary.avg_delivery_latency_ms:.3f}")
            print(f"  p95_delivery_ms:      {summary.p95_delivery_latency_ms:.3f}")


if __name__ == "__main__":
    main()
