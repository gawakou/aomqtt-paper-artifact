#!/usr/bin/env python3
"""AOMQTT v0.9.0 observation-driven Policy auto controller."""

from __future__ import annotations

import argparse
from pathlib import Path

from aomqtt.evaluation import DEFAULT_EXPERIMENT_ID, ExperimentContext, generate_run_id, save_experiment_config
from aomqtt.policy_auto.controller import AutoPolicyController, result_to_json
from aomqtt.policy_auto.rules import RuleThresholds


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--base-policy", required=True)
    parser.add_argument("--publisher-metrics", default=None)
    parser.add_argument("--subscriber-metrics", default=None)
    parser.add_argument("--sequence-no", type=int, required=True)
    parser.add_argument("--output-policy", default=None)

    parser.add_argument("--valid-after", type=float, default=10.0)
    parser.add_argument("--expires-after", type=float, default=3600.0)
    parser.add_argument("--signing-private-key-file", default=None)

    parser.add_argument("--expected-clients", default="")
    parser.add_argument("--ack-timeout-sec", type=float, default=10.0)
    parser.add_argument("--apply-timeout-sec", type=float, default=30.0)

    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait-ack-status", action="store_true")
    parser.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID, help="experiment identifier for reproducible evaluation")
    parser.add_argument("--run-id", default=None, help="run identifier for reproducible evaluation")
    parser.add_argument("--save-experiment-config", action="store_true", help="save effective auto-control experiment configuration")
    parser.add_argument("--experiment-config-out", default=None, help="output path for auto-control experiment configuration JSON/YAML")

    parser.add_argument("--loss-rate-threshold", type=float, default=0.0)
    parser.add_argument("--duplicate-rate-threshold", type=float, default=0.10)
    parser.add_argument("--overhead-bytes-threshold", type=float, default=512.0)
    parser.add_argument("--latency-ms-threshold", type=float, default=100.0)
    parser.add_argument("--overlap-step-sec", type=int, default=5)
    parser.add_argument("--max-overlap-sec", type=int, default=60)

    args = parser.parse_args()
    args.run_id = args.run_id or generate_run_id()
    experiment_context = ExperimentContext(
        experiment_id=args.experiment_id,
        run_id=args.run_id,
    )

    output_policy = args.output_policy
    if output_policy is None:
        output_policy = f"results/{args.run_id}/policy_auto_s{args.sequence_no}.yaml"

    Path(output_policy).parent.mkdir(parents=True, exist_ok=True)
    Path("results").mkdir(exist_ok=True)

    thresholds = RuleThresholds(
        loss_rate_threshold=args.loss_rate_threshold,
        duplicate_rate_threshold=args.duplicate_rate_threshold,
        overhead_bytes_threshold=args.overhead_bytes_threshold,
        latency_ms_threshold=args.latency_ms_threshold,
        overlap_step_sec=args.overlap_step_sec,
        max_overlap_sec=args.max_overlap_sec,
    )

    if args.save_experiment_config:
        config_out = Path(args.experiment_config_out) if args.experiment_config_out else Path(output_policy).parent / "policy_auto_experiment_config.json"
        save_experiment_config(
            output_path=config_out,
            context=experiment_context,
            config={
                "role": "controller",
                "broker": args.broker,
                "group_id": args.group_id,
                "base_policy": args.base_policy,
                "publisher_metrics": args.publisher_metrics,
                "subscriber_metrics": args.subscriber_metrics,
                "sequence_no": args.sequence_no,
                "output_policy": str(output_policy),
                "valid_after": args.valid_after,
                "expires_after": args.expires_after,
                "signing_private_key_file": args.signing_private_key_file,
                "expected_clients": args.expected_clients,
                "ack_timeout_sec": args.ack_timeout_sec,
                "apply_timeout_sec": args.apply_timeout_sec,
                "wait_ack_status": not args.no_wait_ack_status,
                "dry_run": args.dry_run,
                "experiment_id": experiment_context.experiment_id,
                "run_id": experiment_context.run_id,
                "thresholds": {
                    "loss_rate_threshold": args.loss_rate_threshold,
                    "duplicate_rate_threshold": args.duplicate_rate_threshold,
                    "overhead_bytes_threshold": args.overhead_bytes_threshold,
                    "latency_ms_threshold": args.latency_ms_threshold,
                    "overlap_step_sec": args.overlap_step_sec,
                    "max_overlap_sec": args.max_overlap_sec,
                },
            },
        )

    controller = AutoPolicyController(
        broker=args.broker,
        group_id=args.group_id,
        base_policy=args.base_policy,
        publisher_metrics=args.publisher_metrics,
        subscriber_metrics=args.subscriber_metrics,
        sequence_no=args.sequence_no,
        output_policy=output_policy,
        valid_after=args.valid_after,
        expires_after=args.expires_after,
        signing_private_key_file=args.signing_private_key_file,
        expected_clients=args.expected_clients,
        ack_timeout_sec=args.ack_timeout_sec,
        apply_timeout_sec=args.apply_timeout_sec,
        wait_ack_status=not args.no_wait_ack_status,
        dry_run=args.dry_run,
        thresholds=thresholds,
    )

    result = controller.run()

    print(result_to_json(result))
    if result.tracker_summary:
        print()
        print(result.tracker_summary)


if __name__ == "__main__":
    main()
