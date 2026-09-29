from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple, Union

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .control_policy_trust import ControlPolicyTrustEvaluation, JsonPayload, verify_control_policy_payload, load_ed25519_public_key_b64
from .controller_anomaly import AnomalyRuleConfig, ControllerAnomaly, detect_controller_anomalies, write_anomaly_reports
from .krl import KeyRevocationList, KRLValidationError, verify_and_load_krl

PolicyValidator = Callable[[Mapping[str, Any]], Any]
AckPublisher = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class TrustedControlProcessingResult:
    """Final processing result after v1.1.0 trust validation and optional Policy Guard.

    `trust_evaluation` contains the raw trust-layer decision. `ack` is the final
    ACK that should be published by a Control Receiver. If a Policy Guard rejects
    a policy after trust validation succeeds, the final ACK is converted to a
    rejected ACK while keeping policy_id, sequence_no, and signer_key_id.
    """

    accepted: bool
    stage: str
    reason_code: str
    ack: Dict[str, Any]
    policy: Optional[Mapping[str, Any]]
    trust_evaluation: ControlPolicyTrustEvaluation

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # trust_evaluation is already converted by asdict, but make the intent explicit.
        return data


def _guard_result_to_rejection_reason(value: Any) -> Optional[str]:
    """Normalize common validator return styles.

    Supported accepted return values:
      - None
      - True
      - "OK"
      - {"accepted": True}
      - (True, "OK")

    Supported rejected return values:
      - False
      - "REASON_CODE"
      - {"accepted": False, "reason_code": "REASON_CODE"}
      - (False, "REASON_CODE")
    """

    if value is None or value is True:
        return None
    if value is False:
        return "POLICY_GUARD_REJECTED"
    if isinstance(value, str):
        return None if value == "OK" else value
    if isinstance(value, Mapping):
        accepted = value.get("accepted", value.get("ok"))
        if accepted is True:
            return None
        if accepted is False:
            return str(value.get("reason_code") or value.get("reason") or "POLICY_GUARD_REJECTED")
        # A mapping without an explicit accepted flag is treated as accepted so
        # callers can return details without changing the control flow.
        return None
    if isinstance(value, Tuple) or isinstance(value, tuple):
        if not value:
            return None
        accepted = bool(value[0])
        if accepted:
            return None
        if len(value) >= 2 and value[1]:
            return str(value[1])
        return "POLICY_GUARD_REJECTED"
    return None


def _convert_ack_to_rejected(ack: Mapping[str, Any], reason_code: str) -> Dict[str, Any]:
    out = dict(ack)
    out["status"] = "rejected"
    out["reason_code"] = reason_code
    return out


def load_trusted_public_keys_b64(values: Mapping[str, str]) -> Dict[str, Ed25519PublicKey]:
    """Load a config-style mapping of key_id -> Base64 Ed25519 public key."""

    return {key_id: load_ed25519_public_key_b64(public_key_b64) for key_id, public_key_b64 in values.items()}


class TrustedControlPolicyProcessor:
    """Runtime processor for v1.1.0 trusted control-policy handling.

    The class is intentionally small and transport-agnostic. Existing MQTT code
    can call `process_payload(msg.payload)` from the control callback and then
    publish `result.ack` through its current ACK/status topic implementation.

    Optional `policy_validator` should point to the existing v1.0.2 Policy Guard
    or a thin adapter around it.
    """

    def __init__(
        self,
        *,
        trusted_public_keys: Mapping[str, Ed25519PublicKey],
        krl: Optional[Union[KeyRevocationList, Mapping[str, Any]]] = None,
        krl_public_key: Optional[Ed25519PublicKey] = None,
        krl_min_version: int = -1,
        client_id: str = "unknown",
        require_signature: bool = True,
        policy_validator: Optional[PolicyValidator] = None,
        ack_publisher: Optional[AckPublisher] = None,
    ) -> None:
        self.trusted_public_keys = dict(trusted_public_keys)

        # KRL handling. If a public key is configured, every initial or runtime
        # KRL must be authenticated and strictly newer than the last accepted
        # version. This prevents rollback to an older list that omits a revoked
        # signing key.
        self.krl_public_key = krl_public_key
        self._krl_min_version = int(krl_min_version)
        self.krl: Optional[KeyRevocationList] = None
        if krl is not None:
            if krl_public_key is not None:
                self.krl = verify_and_load_krl(
                    krl,
                    krl_public_key,
                    min_version=self._krl_min_version,
                )
                self._krl_min_version = self.krl.krl_version
            elif isinstance(krl, KeyRevocationList):
                # Backward-compatible local-trust path. The caller is asserting
                # that the object was loaded from a trusted local source.
                self.krl = krl
                self._krl_min_version = max(self._krl_min_version, krl.krl_version)
            else:
                raise KRLValidationError(
                    "krl_public_key is required to load a KRL from an unverified mapping"
                )

        self.client_id = client_id
        self.require_signature = require_signature
        self.policy_validator = policy_validator
        self.ack_publisher = ack_publisher
        self._records: List[Dict[str, Any]] = []

    @property
    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)


    @property
    def krl_version(self) -> int:
        """Highest KRL version accepted so far (-1 if no KRL is loaded)."""
        return self._krl_min_version

    def update_krl(self, krl: Union[KeyRevocationList, Mapping[str, Any]]) -> KeyRevocationList:
        """Replace the active KRL with a newer authenticated KRL."""
        if self.krl_public_key is None:
            raise KRLValidationError("cannot update KRL without a configured krl_public_key")
        verified = verify_and_load_krl(
            krl,
            self.krl_public_key,
            min_version=self._krl_min_version,
        )
        self.krl = verified
        self._krl_min_version = verified.krl_version
        return verified

    def process_payload(self, payload: JsonPayload) -> TrustedControlProcessingResult:
        trust = verify_control_policy_payload(
            payload,
            trusted_public_keys=self.trusted_public_keys,
            krl=self.krl,
            client_id=self.client_id,
            require_signature=self.require_signature,
        )

        if not trust.accepted:
            return self._finish(
                TrustedControlProcessingResult(
                    accepted=False,
                    stage="trust",
                    reason_code=trust.reason_code,
                    ack=dict(trust.ack),
                    policy=trust.policy,
                    trust_evaluation=trust,
                )
            )

        if self.policy_validator is not None:
            try:
                guard_return = self.policy_validator(trust.policy or {})
                guard_reason = _guard_result_to_rejection_reason(guard_return)
            except Exception as exc:  # pragma: no cover - exact exception text varies by caller
                guard_reason = f"POLICY_GUARD_EXCEPTION:{exc.__class__.__name__}"

            if guard_reason:
                return self._finish(
                    TrustedControlProcessingResult(
                        accepted=False,
                        stage="policy_guard",
                        reason_code=guard_reason,
                        ack=_convert_ack_to_rejected(trust.ack, guard_reason),
                        policy=trust.policy,
                        trust_evaluation=trust,
                    )
                )

        return self._finish(
            TrustedControlProcessingResult(
                accepted=True,
                stage="accepted",
                reason_code=trust.reason_code,
                ack=dict(trust.ack),
                policy=trust.policy,
                trust_evaluation=trust,
            )
        )

    def _finish(self, result: TrustedControlProcessingResult) -> TrustedControlProcessingResult:
        record = dict(result.ack)
        if result.policy is not None:
            record["policy"] = dict(result.policy)
        record["stage"] = result.stage
        self._records.append(record)

        if self.ack_publisher is not None:
            self.ack_publisher(result.ack)

        return result

    def detect_anomalies(self, config: Optional[AnomalyRuleConfig] = None) -> List[ControllerAnomaly]:
        return detect_controller_anomalies(self._records, config=config)

    def write_anomaly_reports(self, output_dir: str | Path, config: Optional[AnomalyRuleConfig] = None):
        return write_anomaly_reports(self.detect_anomalies(config=config), output_dir)
