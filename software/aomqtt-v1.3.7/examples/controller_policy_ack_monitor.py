#!/usr/bin/env python3
"""AOMQTT v0.8.2 Policy ACK/status monitor example.

This example subscribes to:

  aomqtt/control/<group_id>/ack
  aomqtt/control/<group_id>/status

and displays Controller-side Policy deployment status.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import List

import paho.mqtt.client as mqtt

from aomqtt.control_plane.messages import from_json_bytes
from aomqtt.control_plane.topics import control_ack_topic, control_status_topic
from aomqtt.control_plane.tracker import PolicyDeploymentTracker


def parse_expected_clients(value: str) -> List[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--sequence-no", type=int, required=True)
    parser.add_argument("--expected-clients", default="")
    parser.add_argument("--ack-timeout-sec", type=float, default=5.0)
    parser.add_argument("--apply-timeout-sec", type=float, default=20.0)
    parser.add_argument("--duration-sec", type=float, default=30.0)
    args = parser.parse_args()

    expected_clients = parse_expected_clients(args.expected_clients)

    tracker = PolicyDeploymentTracker(
        policy_id=args.policy_id,
        sequence_no=args.sequence_no,
        expected_clients=expected_clients,
        ack_timeout_sec=args.ack_timeout_sec,
        apply_timeout_sec=args.apply_timeout_sec,
    )

    ack_topic = control_ack_topic(args.group_id)
    status_topic = control_status_topic(args.group_id)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            print(f"connect failed: rc={rc}")
            return
        client.subscribe(ack_topic)
        client.subscribe(status_topic)
        print(f"subscribed: {ack_topic}")
        print(f"subscribed: {status_topic}")

    def on_message(client, userdata, msg):
        try:
            payload = from_json_bytes(msg.payload)
        except Exception as e:
            print(f"invalid control message on {msg.topic}: {e}")
            return

        if msg.topic == ack_topic:
            tracker.handle_ack(payload)
        elif msg.topic == status_topic:
            tracker.handle_status(payload)

        print()
        print(tracker.summary_text())

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    start = time.time()
    try:
        while time.time() - start < args.duration_sec:
            tracker.update_timeouts()
            print()
            print(tracker.summary_text())

            if tracker.is_complete():
                break

            time.sleep(1.0)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
