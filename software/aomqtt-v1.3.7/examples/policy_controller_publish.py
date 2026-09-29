#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

from aomqtt import AOMQTTPolicy
from aomqtt.control import PolicyMessagePublisher, build_control_policy_message, control_policy_topic


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish an AOMQTT policy through an MQTT control topic")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--client-id", default="aomqtt_policy_controller")
    parser.add_argument("--policy", default="examples/policy.example.yaml", help="policy YAML to distribute")
    parser.add_argument("--group-id", default="default", help="target policy group id")
    parser.add_argument("--control-topic", default=None, help="override control topic; default is aomqtt/control/<group-id>/policy")
    parser.add_argument("--valid-after", type=float, default=5.0, help="seconds from now when clients should apply the policy")
    parser.add_argument("--valid-from", type=float, default=None, help="absolute Unix timestamp when clients should apply the policy")
    parser.add_argument("--grace-period", type=float, default=5.0, help="grace period for policy transition metadata")
    parser.add_argument("--sequence-no", type=int, default=None, help="monotonic control-policy sequence number; default is current Unix time")
    parser.add_argument("--expires-after", type=float, default=3600.0, help="seconds after issued_at when the control policy expires")
    parser.add_argument("--signing-private-key", default=None, help="Ed25519 raw-base64/PEM private key or a file path")
    parser.add_argument("--signing-private-key-file", default=None, help="file containing Ed25519 raw-base64/PEM private key")
    parser.add_argument("--signing-key-id", default="policy-signing-key-1", help="key identifier stored with the signature")
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=1)
    parser.add_argument("--retain", action="store_true", help="retain the control policy message")
    parser.add_argument("--dry-run", action="store_true", help="print the control message without publishing")
    args = parser.parse_args()

    policy = AOMQTTPolicy.from_yaml(args.policy)
    signing_key = args.signing_private_key_file or args.signing_private_key
    message = build_control_policy_message(
        policy,
        group_id=args.group_id,
        valid_from=args.valid_from,
        valid_after_sec=args.valid_after,
        grace_period_sec=args.grace_period,
        sequence_no=args.sequence_no if args.sequence_no is not None else int(time.time()),
        expires_after_sec=args.expires_after,
        signing_private_key=signing_key,
        signing_key_id=args.signing_key_id,
    )
    topic = args.control_topic or control_policy_topic(args.group_id)
    payload = message.to_dict()

    print("AOMQTT policy control message")
    print(f"  target topic:  {topic}")
    print(f"  group_id:      {message.group_id}")
    print(f"  policy_id:     {message.policy_id}")
    print(f"  policy_name:   {message.policy_name}")
    print(f"  issued_at:     {message.issued_at:.3f}")
    print(f"  valid_from:    {message.valid_from:.3f}")
    print(f"  valid_after:   {max(0.0, message.valid_from - time.time()):.3f}s")
    print(f"  grace_period:  {message.grace_period_sec:.3f}s")
    print(f"  sequence_no:   {message.sequence_no if message.sequence_no is not None else '-'}")
    print(f"  expires_at:    {message.expires_at if message.expires_at is not None else '-'}")
    print(f"  signed:        {'yes' if message.signature else 'no'}")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    if args.dry_run:
        return

    publisher = PolicyMessagePublisher(
        broker_host=args.broker,
        broker_port=args.port,
        client_id=args.client_id,
    )
    rc, mid = publisher.publish_message(
        message,
        topic=topic,
        qos=args.qos,
        retain=args.retain,
    )
    print(f"published control policy: rc={rc} mid={mid}")


if __name__ == "__main__":
    main()
