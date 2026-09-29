#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from aomqtt import AOMQTTConfig, AOMQTTPublisher, PolicyController, PublishCSVLogger
from aomqtt.evaluation import DEFAULT_EXPERIMENT_ID, ExperimentContext, generate_run_id, save_experiment_config


def load_config(args) -> AOMQTTConfig:
    cfg = AOMQTTConfig.from_yaml(args.config)

    # v0.7: external policy is applied after the base key/config file.
    # Explicit CLI options below still take precedence for quick experiments.
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
    if args.padding_mode != "config":
        cfg = replace(
            cfg,
            padding_enabled=args.padding_mode != "none",
            padding_mode="none" if args.padding_mode == "none" else args.padding_mode,
            padding_fixed_size=args.padding_fixed_size,
            padding_bucket_size=args.padding_bucket_size,
            padding_random_min_bytes=args.padding_random_min_bytes,
            padding_random_max_bytes=args.padding_random_max_bytes,
        )
    cfg.validate()
    return cfg


def main() -> None:
    parser = argparse.ArgumentParser(description="AOMQTT encrypted publisher example")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--client-id", default="c_pub_001")
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
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument(
        "--pacing",
        choices=["post-sleep", "fixed-rate"],
        default="post-sleep",
        help=(
            "message pacing mode: 'post-sleep' sleeps for --interval after each "
            "logical publish (legacy behavior); 'fixed-rate' schedules logical "
            "messages against an absolute monotonic clock"
        ),
    )
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=None, help="override config/policy MQTT QoS")
    parser.add_argument(
        "--token-mode",
        choices=["config", "hierarchical", "whole"],
        default="config",
        help="override config token_mode",
    )
    parser.add_argument("--rotation", action="store_true", help="enable token rotation")
    parser.add_argument("--no-rotation", action="store_true", help="disable token rotation even if policy enables it")
    parser.add_argument("--rotation-interval", type=int, default=30, help="rotation interval in seconds")
    parser.add_argument("--rotation-overlap", type=int, default=5, help="overlap window in seconds")
    parser.add_argument("--padding-mode", choices=["config", "none", "fixed", "bucket", "random"], default="config", help="override payload padding mode")
    parser.add_argument("--padding-fixed-size", type=int, default=512, help="fixed padded plaintext size in bytes")
    parser.add_argument("--padding-bucket-size", type=int, default=256, help="bucket padding size in bytes")
    parser.add_argument("--padding-random-min-bytes", type=int, default=0, help="minimum random padding bytes")
    parser.add_argument("--padding-random-max-bytes", type=int, default=128, help="maximum random padding bytes")
    parser.add_argument("--metrics-csv", default=None, help="write publish observation metrics to CSV")
    parser.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID, help="experiment identifier for reproducible evaluation")
    parser.add_argument("--run-id", default=None, help="run identifier for reproducible evaluation")
    parser.add_argument("--save-experiment-config", action="store_true", help="save effective experiment configuration")
    parser.add_argument("--experiment-config-out", default=None, help="output path for experiment configuration JSON/YAML")
    parser.add_argument("--no-wait", action="store_true", help="do not wait for publish completion")
    args = parser.parse_args()
    args.run_id = args.run_id or generate_run_id()
    experiment_context = ExperimentContext(
        experiment_id=args.experiment_id,
        run_id=args.run_id,
    )

    cfg = load_config(args)
    pub = AOMQTTPublisher(
        broker_host=args.broker,
        broker_port=args.port,
        client_id=args.client_id,
        config=cfg,
    )

    state = pub.current_rotation_state()
    print(f"policy id:           {cfg.policy_id}")
    print(f"policy name:         {cfg.policy_name}")
    print(f"token mode:          {cfg.token_mode}")
    print(f"rotation enabled:    {cfg.rotation_enabled}")
    print(f"rotation interval:   {cfg.rotation_interval_sec}s")
    print(f"rotation overlap:    {cfg.rotation_overlap_sec}s")
    print(f"mqtt qos:            {cfg.mqtt_qos}")
    print(f"pacing mode:         {args.pacing}")
    print(f"configured interval: {args.interval}s")
    if args.policy:
        print(f"policy file:         {args.policy}")
    print(f"padding enabled:     {cfg.padding_enabled}")
    print(f"padding mode:        {cfg.padding_mode}")
    print(f"current epoch:       {state.current_epoch if cfg.rotation_enabled else '-'}")
    print(f"plaintext topic:     {args.topic}")
    print(f"token topic current: {pub.tokenized_topic(args.topic, epoch=state.current_epoch if cfg.rotation_enabled else None)}")
    print(f"experiment id:       {experiment_context.experiment_id}")
    print(f"run id:              {experiment_context.run_id}")
    if args.metrics_csv:
        print(f"metrics csv:         {args.metrics_csv}")
    if args.save_experiment_config:
        config_out = Path(args.experiment_config_out) if args.experiment_config_out else (
            Path(args.metrics_csv).parent / "experiment_config.json"
            if args.metrics_csv
            else Path("results") / args.run_id / "experiment_config.json"
        )
        save_experiment_config(
            output_path=config_out,
            context=experiment_context,
            config={
                "role": "publisher",
                "broker": args.broker,
                "port": args.port,
                "client_id": args.client_id,
                "config": args.config,
                "policy": args.policy,
                "topic": args.topic,
                "count": args.count,
                "interval": args.interval,
                "pacing": args.pacing,
                "qos": args.qos,
                "token_mode": args.token_mode,
                "rotation": args.rotation,
                "no_rotation": args.no_rotation,
                "rotation_interval": args.rotation_interval,
                "rotation_overlap": args.rotation_overlap,
                "padding_mode": args.padding_mode,
                "metrics_csv": args.metrics_csv,
                "effective_policy_id": cfg.policy_id,
                "effective_policy_name": cfg.policy_name,
            },
        )
        print(f"experiment config:   {config_out}")

    pub.connect()
    pub.loop_start()
    if args.enable_control_topic:
        receiver = pub.start_policy_control(
            group_id=args.control_group_id,
            control_topic=args.control_topic,
            client_id=args.control_client_id,
            qos=args.control_qos,
            signing_public_key=args.control_policy_public_key_file or args.control_policy_public_key,
            require_signature=not args.allow_unsigned_control_policy,
        )
        print(f"control topic:       {receiver.control_topic}")
        print(f"control group id:    {args.control_group_id}")
    time.sleep(0.5)

    logger = (
        PublishCSVLogger(
            args.metrics_csv,
            experiment_id=experiment_context.experiment_id,
            run_id=experiment_context.run_id,
            metrics_schema_version=experiment_context.metrics_schema_version,
        )
        if args.metrics_csv
        else None
    )
    all_metrics = []
    pacing_deadline_misses = 0
    pacing_lateness_max_ms = 0.0
    pacing_start = time.monotonic()
    try:
        for i in range(args.count):
            if args.pacing == "fixed-rate" and i > 0:
                target = pacing_start + i * args.interval
                remaining = target - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                else:
                    pacing_deadline_misses += 1
                    pacing_lateness_max_ms = max(
                        pacing_lateness_max_ms,
                        -remaining * 1000.0,
                    )

            message_id = f"{args.client_id}:{experiment_context.run_id}:{i}"
            payload = {
                "message_id": message_id,
                "seq": i,
                "metric": "rtt",
                "value": 42.1 + i,
                "timestamp": time.time(),
            }
            if logger is not None:
                metrics = pub.publish_observed_rotating(
                    args.topic,
                    payload,
                    logical_seq=i,
                    message_id=message_id,
                    wait_for_publish=not args.no_wait,
                    csv_logger=logger,
                )
                all_metrics.extend(metrics)
                success_count = sum(1 for m in metrics if m.success)
                avg_ms = sum(m.publish_complete_ms for m in metrics) / len(metrics)
                print(
                    "published",
                    json.dumps(payload, ensure_ascii=False),
                    f"mqtt_messages={len(metrics)}",
                    f"success={success_count}/{len(metrics)}",
                    f"avg_publish_complete_ms={avg_ms:.3f}",
                    f"padding_added={sum(m.padding_added_bytes for m in metrics)}",
                    f"epoch_state={pub.current_rotation_state().current_epoch if pub.config.rotation_enabled else '-'}",
                )
            else:
                infos = pub.publish_rotating(args.topic, payload)
                for info in infos:
                    info.wait_for_publish()
                print(
                    "published",
                    json.dumps(payload, ensure_ascii=False),
                    f"mqtt_messages={len(infos)}",
                    f"epoch_state={pub.current_rotation_state().current_epoch if pub.config.rotation_enabled else '-'}",
                )
            if args.pacing == "post-sleep":
                time.sleep(args.interval)
    finally:
        if logger is not None:
            summary = logger.summary()
            logger.close()
            print("publish summary:")
            print(f"  total MQTT messages: {summary.total}")
            print(f"  success:             {summary.success}")
            print(f"  failed:              {summary.failed}")
            print(f"  success_rate:        {summary.success_rate:.3f}")
            print(f"  avg_complete_ms:     {summary.avg_publish_complete_ms:.3f}")
            print(f"  p95_complete_ms:     {summary.p95_publish_complete_ms:.3f}")
            print(f"  reconnect_count:     {summary.reconnect_count}")
            print(f"  pacing_mode:         {args.pacing}")
            print(f"  pacing_deadline_miss:{pacing_deadline_misses}")
            print(f"  pacing_late_max_ms:  {pacing_lateness_max_ms:.3f}")
        pub.loop_stop()
        pub.disconnect()


if __name__ == "__main__":
    main()
