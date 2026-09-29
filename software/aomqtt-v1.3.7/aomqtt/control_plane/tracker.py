"""Controller-side Policy deployment tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class ClientPolicyState:
    client_id: str
    role: str = "-"
    policy_id: str = "-"
    sequence_no: int = -1
    ack_status: str = "pending"
    apply_status: str = "pending"
    received_at: Optional[float] = None
    will_apply_at: Optional[float] = None
    applied_at: Optional[float] = None
    failed_at: Optional[float] = None
    reason: Optional[str] = None
    reason_code: Optional[str] = None

    def as_row(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "role": self.role,
            "policy_id": self.policy_id,
            "sequence_no": self.sequence_no,
            "ack_status": self.ack_status,
            "apply_status": self.apply_status,
            "received_at": self.received_at,
            "will_apply_at": self.will_apply_at,
            "applied_at": self.applied_at,
            "failed_at": self.failed_at,
            "reason_code": self.reason_code or "-",
            "reason": self.reason or "-",
        }


class PolicyDeploymentTracker:
    """Track ACK and application status for one Policy deployment."""

    def __init__(
        self,
        *,
        policy_id: str,
        sequence_no: int,
        expected_clients: Optional[Iterable[str]] = None,
        ack_timeout_sec: float = 5.0,
        apply_timeout_sec: float = 20.0,
        started_at: Optional[float] = None,
    ) -> None:
        if not policy_id:
            raise ValueError("policy_id must not be empty")
        if sequence_no < 0:
            raise ValueError("sequence_no must be non-negative")

        self.policy_id = policy_id
        self.sequence_no = sequence_no
        self.ack_timeout_sec = ack_timeout_sec
        self.apply_timeout_sec = apply_timeout_sec
        self.started_at = time.time() if started_at is None else started_at

        self._states: Dict[str, ClientPolicyState] = {}
        for client_id in expected_clients or []:
            self._states[client_id] = ClientPolicyState(
                client_id=client_id,
                policy_id=policy_id,
                sequence_no=sequence_no,
            )

    def handle_ack(self, msg: Dict[str, Any]) -> None:
        if msg.get("policy_id") != self.policy_id:
            return
        if int(msg.get("sequence_no", -1)) != self.sequence_no:
            return

        client_id = str(msg.get("client_id", ""))
        if not client_id:
            return

        state = self._states.setdefault(
            client_id,
            ClientPolicyState(
                client_id=client_id,
                policy_id=self.policy_id,
                sequence_no=self.sequence_no,
            ),
        )

        state.role = str(msg.get("role", state.role))
        state.policy_id = self.policy_id
        state.sequence_no = self.sequence_no
        state.ack_status = str(msg.get("status", "unknown"))
        state.received_at = msg.get("received_at")
        state.will_apply_at = msg.get("will_apply_at")
        state.reason = msg.get("reason", state.reason)
        state.reason_code = msg.get("reason_code", state.reason_code)

        if state.ack_status == "rejected":
            state.apply_status = "-"

    def handle_status(self, msg: Dict[str, Any]) -> None:
        if msg.get("policy_id") != self.policy_id:
            return
        if int(msg.get("sequence_no", -1)) != self.sequence_no:
            return

        client_id = str(msg.get("client_id", ""))
        if not client_id:
            return

        state = self._states.setdefault(
            client_id,
            ClientPolicyState(
                client_id=client_id,
                policy_id=self.policy_id,
                sequence_no=self.sequence_no,
            ),
        )

        state.role = str(msg.get("role", state.role))
        state.policy_id = self.policy_id
        state.sequence_no = self.sequence_no
        state.apply_status = str(msg.get("status", "unknown"))
        state.applied_at = msg.get("applied_at")
        state.failed_at = msg.get("failed_at")
        state.reason = msg.get("reason", state.reason)
        state.reason_code = msg.get("reason_code", state.reason_code)

    def update_timeouts(self, *, now: Optional[float] = None) -> None:
        current = time.time() if now is None else now

        for state in self._states.values():
            if state.ack_status == "pending":
                if current - self.started_at >= self.ack_timeout_sec:
                    state.ack_status = "timeout"
                    state.apply_status = "-"
                    state.reason = "no ACK"
                    state.reason_code = "timeout"

            elif state.ack_status == "accepted" and state.apply_status == "pending":
                base = state.will_apply_at or state.received_at or self.started_at
                if current - float(base) >= self.apply_timeout_sec:
                    state.apply_status = "timeout"
                    state.reason = "no applied/failed status"
                    state.reason_code = "timeout"

    def rows(self) -> List[Dict[str, Any]]:
        return [self._states[k].as_row() for k in sorted(self._states.keys())]

    def is_complete(self) -> bool:
        if not self._states:
            return False

        for state in self._states.values():
            if state.ack_status == "pending":
                return False
            if state.ack_status == "accepted" and state.apply_status == "pending":
                return False
        return True

    def summary_text(self) -> str:
        lines = []
        lines.append("Policy deployment status")
        lines.append(f"policy_id: {self.policy_id}")
        lines.append(f"sequence_no: {self.sequence_no}")
        lines.append("")
        lines.append(
            f"{'client_id':<20} {'role':<12} {'ACK':<10} {'STATUS':<10} {'reason_code':<18} reason"
        )
        lines.append("-" * 96)

        for row in self.rows():
            lines.append(
                f"{row['client_id']:<20} "
                f"{row['role']:<12} "
                f"{row['ack_status']:<10} "
                f"{row['apply_status']:<10} "
                f"{row['reason_code']:<18} "
                f"{row['reason']}"
            )

        return "\n".join(lines)
