"""Auto Policy Controller for AOMQTT v0.8.3."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import paho.mqtt.client as mqtt

from aomqtt.control_plane.messages import from_json_bytes
from aomqtt.control_plane.topics import control_ack_topic, control_status_topic
from aomqtt.control_plane.tracker import PolicyDeploymentTracker

from .generator import generate_next_policy_dict, load_policy_yaml, save_policy_yaml
from .metrics import ObservationMetrics, aggregate_observation_metrics
from .rules import PolicyDecision, RuleThresholds, decide_policy_action


@dataclass
class AutoPolicyControllerResult:
    metrics: ObservationMetrics
    decision: PolicyDecision
    generated_policy: dict
    generated_policy_id: str
    output_policy_path: str
    tracker_summary: Optional[str] = None


def _extract_generated_policy_id(policy_data: dict) -> str:
    policy = policy_data.get("policy", policy_data)
    if not isinstance(policy, dict):
        return "unknown"
    return str(policy.get("id") or policy.get("policy_id") or "unknown")


def _parse_expected_clients(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


class AutoPolicyController:
    """Run one observation-driven Policy control cycle."""

    def __init__(
        self,
        *,
        broker: str,
        group_id: str,
        base_policy: str | Path,
        publisher_metrics: str | Path | None,
        subscriber_metrics: str | Path | None,
        sequence_no: int,
        output_policy: str | Path,
        valid_after: float = 10.0,
        expires_after: float = 3600.0,
        signing_private_key_file: str | Path | None = None,
        expected_clients: str | None = None,
        ack_timeout_sec: float = 10.0,
        apply_timeout_sec: float = 30.0,
        wait_ack_status: bool = True,
        dry_run: bool = False,
        thresholds: RuleThresholds | None = None,
    ) -> None:
        self.broker = broker
        self.group_id = group_id
        self.base_policy = Path(base_policy)
        self.publisher_metrics = publisher_metrics
        self.subscriber_metrics = subscriber_metrics
        self.sequence_no = sequence_no
        self.output_policy = Path(output_policy)
        self.valid_after = valid_after
        self.expires_after = expires_after
        self.signing_private_key_file = signing_private_key_file
        self.expected_clients = _parse_expected_clients(expected_clients)
        self.ack_timeout_sec = ack_timeout_sec
        self.apply_timeout_sec = apply_timeout_sec
        self.wait_ack_status = wait_ack_status
        self.dry_run = dry_run
        self.thresholds = thresholds or RuleThresholds()

    def run(self) -> AutoPolicyControllerResult:
        metrics = aggregate_observation_metrics(
            publisher_metrics_csv=self.publisher_metrics,
            subscriber_metrics_csv=self.subscriber_metrics,
        )
        decision = decide_policy_action(metrics, self.thresholds)

        base = load_policy_yaml(self.base_policy)
        generated = generate_next_policy_dict(
            base,
            decision,
            sequence_no=self.sequence_no,
            thresholds=self.thresholds,
        )
        save_policy_yaml(generated, self.output_policy)

        policy_id = _extract_generated_policy_id(generated)

        tracker_summary = None

        if not self.dry_run:
            if self.wait_ack_status:
                tracker_summary = self._publish_and_wait(policy_id)
            else:
                self._publish_policy()

        return AutoPolicyControllerResult(
            metrics=metrics,
            decision=decision,
            generated_policy=generated,
            generated_policy_id=policy_id,
            output_policy_path=str(self.output_policy),
            tracker_summary=tracker_summary,
        )

    def _publish_policy(self) -> None:
        script = Path("examples/policy_controller_publish.py")
        if not script.exists():
            raise FileNotFoundError("examples/policy_controller_publish.py not found")

        cmd = [
            sys.executable,
            str(script),
            "--broker",
            self.broker,
            "--group-id",
            self.group_id,
            "--policy",
            str(self.output_policy),
            "--valid-after",
            str(self.valid_after),
            "--sequence-no",
            str(self.sequence_no),
            "--expires-after",
            str(self.expires_after),
        ]

        if self.signing_private_key_file:
            cmd += [
                "--signing-private-key-file",
                str(self.signing_private_key_file),
            ]

        subprocess.run(cmd, check=True)

    def _publish_and_wait(self, policy_id: str) -> str:
        tracker = PolicyDeploymentTracker(
            policy_id=policy_id,
            sequence_no=self.sequence_no,
            expected_clients=self.expected_clients,
            ack_timeout_sec=self.ack_timeout_sec,
            apply_timeout_sec=self.apply_timeout_sec,
        )

        ack_topic = control_ack_topic(self.group_id)
        status_topic = control_status_topic(self.group_id)

        def on_connect(client, userdata, flags, rc):
            client.subscribe(ack_topic)
            client.subscribe(status_topic)

        def on_message(client, userdata, msg):
            try:
                payload = from_json_bytes(msg.payload)
            except Exception:
                return

            if msg.topic == ack_topic:
                tracker.handle_ack(payload)
            elif msg.topic == status_topic:
                tracker.handle_status(payload)

        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(self.broker, 1883, keepalive=60)
        client.loop_start()

        try:
            time.sleep(0.5)
            self._publish_policy()

            start = time.time()
            max_wait = self.ack_timeout_sec + self.apply_timeout_sec + self.valid_after + 5.0

            while time.time() - start < max_wait:
                tracker.update_timeouts()
                if tracker.is_complete():
                    break
                time.sleep(1.0)

            tracker.update_timeouts()
            return tracker.summary_text()

        finally:
            client.loop_stop()
            client.disconnect()


def result_to_json(result: AutoPolicyControllerResult) -> str:
    return json.dumps(
        {
            "metrics": result.metrics.to_dict(),
            "decision": {
                "action": result.decision.action,
                "reason": result.decision.reason,
                "changes": result.decision.changes,
            },
            "generated_policy_id": result.generated_policy_id,
            "output_policy_path": result.output_policy_path,
            "tracker_summary": result.tracker_summary,
        },
        ensure_ascii=False,
        indent=2,
    )
