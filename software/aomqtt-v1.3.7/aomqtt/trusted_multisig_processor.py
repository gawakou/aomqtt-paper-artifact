from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .controller_anomaly import AnomalyRuleConfig, ControllerAnomaly, detect_controller_anomalies, write_anomaly_reports
from .krl import KeyRevocationList
from .multisig_policy import (
    MultiSignaturePolicyResult,
    build_multisig_policy_ack,
    verify_multisig_policy_envelope,
)
from .policy_trust import extract_policy_metadata
from .transparency_log import TransparencyLog, TransparencyLogEntry
from .trusted_control_processor import _guard_result_to_rejection_reason

PolicyValidator = Callable[[Mapping[str, Any]], Any]
AckPublisher = Callable[[Mapping[str, Any]], None]
JsonPayload = bytes | bytearray | str | Mapping[str, Any]


@dataclass(frozen=True)
class TrustedMultiSigProcessingResult:
    """Final result for v1.2.0 multi-signature policy processing."""

    accepted: bool
    stage: str
    reason_code: str
    ack: Dict[str, Any]
    policy: Optional[Mapping[str, Any]]
    multisig_result: MultiSignaturePolicyResult
    transparency_entry: Optional[TransparencyLogEntry] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _payload_to_mapping(payload: JsonPayload) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8")
    if isinstance(payload, str):
        value = json.loads(payload)
        if not isinstance(value, Mapping):
            raise ValueError("JSON payload must be an object")
        return value
    raise TypeError(f"unsupported payload type: {type(payload).__name__}")


def _extract_policy(envelope: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    policy = envelope.get("policy")
    return policy if isinstance(policy, Mapping) else None


def _convert_ack_to_rejected(ack: Mapping[str, Any], reason_code: str) -> Dict[str, Any]:
    out = dict(ack)
    out["status"] = "rejected"
    out["reason_code"] = reason_code
    return out


def _invalid_payload_result(*, client_id: str, reason_code: str, detail: str = "") -> TrustedMultiSigProcessingResult:
    # Build a compact synthetic result so callers always receive a final ACK.
    synthetic = MultiSignaturePolicyResult(
        accepted=False,
        reason_code=reason_code,
        policy_id="unknown",
        sequence_no=0,
        threshold=0,
        valid_signature_count=0,
        signer_key_ids=[],
        roles=[],
    )
    ack = build_multisig_policy_ack(synthetic, client_id=client_id)
    if detail:
        ack["detail"] = detail
    return TrustedMultiSigProcessingResult(
        accepted=False,
        stage="payload",
        reason_code=reason_code,
        ack=ack,
        policy=None,
        multisig_result=synthetic,
        transparency_entry=None,
    )


class TrustedMultiSignaturePolicyProcessor:
    """Runtime processor for v1.2.0 multi-signature policy handling.

    Existing MQTT control receivers can call `process_payload(msg.payload)`,
    publish `result.ack`, and apply `result.policy` only when
    `result.accepted` is true.

    The processor is transport-agnostic and intentionally keeps v1.1.0 single
    signature handling separate. It focuses on v1.2.0 envelopes with
    `signature_policy` and `signatures`.
    """

    def __init__(
        self,
        *,
        trusted_public_keys: Mapping[str, Ed25519PublicKey],
        krl: Optional[KeyRevocationList] = None,
        client_id: str = "unknown",
        min_threshold: Optional[int] = None,
        required_roles: Optional[Iterable[str]] = None,
        policy_validator: Optional[PolicyValidator] = None,
        ack_publisher: Optional[AckPublisher] = None,
        transparency_log: Optional[TransparencyLog] = None,
    ) -> None:
        self.trusted_public_keys = dict(trusted_public_keys)
        self.krl = krl
        self.client_id = client_id
        self.min_threshold = min_threshold
        self.required_roles = list(required_roles or [])
        self.policy_validator = policy_validator
        self.ack_publisher = ack_publisher
        self.transparency_log = transparency_log if transparency_log is not None else TransparencyLog()
        self._records: List[Dict[str, Any]] = []

    @property
    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def process_payload(self, payload: JsonPayload) -> TrustedMultiSigProcessingResult:
        try:
            envelope = _payload_to_mapping(payload)
        except Exception as exc:
            return self._finish(_invalid_payload_result(client_id=self.client_id, reason_code="INVALID_POLICY_JSON", detail=exc.__class__.__name__))
        return self.process_envelope(envelope)

    def process_envelope(self, envelope: Mapping[str, Any]) -> TrustedMultiSigProcessingResult:
        policy = _extract_policy(envelope)
        ms = verify_multisig_policy_envelope(
            envelope,
            trusted_public_keys=self.trusted_public_keys,
            krl=self.krl,
            min_threshold=self.min_threshold,
            required_roles=self.required_roles,
        )
        ack = build_multisig_policy_ack(ms, client_id=self.client_id)

        if not ms.accepted:
            return self._finish(
                TrustedMultiSigProcessingResult(
                    accepted=False,
                    stage="multisig",
                    reason_code=ms.reason_code,
                    ack=ack,
                    policy=policy,
                    multisig_result=ms,
                    transparency_entry=self._append_transparency(policy, ms, ack),
                )
            )

        if self.policy_validator is not None:
            try:
                guard_return = self.policy_validator(policy or {})
                guard_reason = _guard_result_to_rejection_reason(guard_return)
            except Exception as exc:  # pragma: no cover - exact exception text varies by caller
                guard_reason = f"POLICY_GUARD_EXCEPTION:{exc.__class__.__name__}"

            if guard_reason:
                rejected_ack = _convert_ack_to_rejected(ack, guard_reason)
                return self._finish(
                    TrustedMultiSigProcessingResult(
                        accepted=False,
                        stage="policy_guard",
                        reason_code=guard_reason,
                        ack=rejected_ack,
                        policy=policy,
                        multisig_result=ms,
                        transparency_entry=self._append_transparency(policy, ms, rejected_ack),
                    )
                )

        return self._finish(
            TrustedMultiSigProcessingResult(
                accepted=True,
                stage="accepted",
                reason_code="OK",
                ack=ack,
                policy=policy,
                multisig_result=ms,
                transparency_entry=self._append_transparency(policy, ms, ack),
            )
        )

    def _append_transparency(
        self,
        policy: Optional[Mapping[str, Any]],
        ms: MultiSignaturePolicyResult,
        ack: Mapping[str, Any],
    ) -> Optional[TransparencyLogEntry]:
        if policy is None:
            return None
        return self.transparency_log.append_policy(
            policy,
            signer_key_ids=ms.signer_key_ids,
            threshold=ms.threshold,
            decision=str(ack.get("status") or "unknown"),
            reason_code=str(ack.get("reason_code") or ms.reason_code),
        )

    def _finish(self, result: TrustedMultiSigProcessingResult) -> TrustedMultiSigProcessingResult:
        record = dict(result.ack)
        record["stage"] = result.stage
        if result.policy is not None:
            record["policy"] = dict(result.policy)
        if result.transparency_entry is not None:
            record["transparency_log_index"] = result.transparency_entry.index
            record["transparency_entry_hash"] = result.transparency_entry.entry_hash
        self._records.append(record)

        if self.ack_publisher is not None:
            self.ack_publisher(result.ack)

        return result

    def verify_transparency_log(self):
        return self.transparency_log.verify()

    def write_transparency_log(self, output_dir: str | Path) -> Path:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        return self.transparency_log.write_jsonl(out / "policy_transparency_log.jsonl")

    def detect_anomalies(self, config: Optional[AnomalyRuleConfig] = None) -> List[ControllerAnomaly]:
        return detect_controller_anomalies(self._records, config=config)

    def write_anomaly_reports(self, output_dir: str | Path, config: Optional[AnomalyRuleConfig] = None):
        return write_anomaly_reports(self.detect_anomalies(config=config), output_dir)
