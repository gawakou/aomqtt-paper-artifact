from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from .policy_trust import extract_policy_metadata
from .signing import canonical_json_bytes
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

GENESIS_HASH = "0" * 64


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def policy_digest(policy: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes({"policy": dict(policy)}))


@dataclass(frozen=True)
class TransparencyLogEntry:
    index: int
    policy_id: str
    sequence_no: int
    policy_digest: str
    previous_hash: str
    entry_hash: str
    signer_key_ids: List[str]
    threshold: int
    decision: str = "issued"
    reason_code: str = "OK"

    def unsigned_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("entry_hash", None)
        return data

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransparencyLogEntry":
        return cls(
            index=int(value.get("index", 0)),
            policy_id=str(value.get("policy_id", "unknown")),
            sequence_no=int(value.get("sequence_no", 0)),
            policy_digest=str(value.get("policy_digest", "")),
            previous_hash=str(value.get("previous_hash", GENESIS_HASH)),
            entry_hash=str(value.get("entry_hash", "")),
            signer_key_ids=[str(x) for x in value.get("signer_key_ids", [])],
            threshold=int(value.get("threshold", 1)),
            decision=str(value.get("decision", "issued")),
            reason_code=str(value.get("reason_code", "OK")),
        )


def compute_entry_hash(entry_without_hash: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(entry_without_hash))


def build_transparency_entry(
    policy: Mapping[str, Any],
    *,
    index: int,
    previous_hash: str,
    signer_key_ids: Sequence[str],
    threshold: int,
    decision: str = "issued",
    reason_code: str = "OK",
) -> TransparencyLogEntry:
    policy_id, sequence_no = extract_policy_metadata(policy)
    unsigned = {
        "index": int(index),
        "policy_id": policy_id,
        "sequence_no": sequence_no,
        "policy_digest": policy_digest(policy),
        "previous_hash": previous_hash,
        "signer_key_ids": list(signer_key_ids),
        "threshold": int(threshold),
        "decision": decision,
        "reason_code": reason_code,
    }
    return TransparencyLogEntry(entry_hash=compute_entry_hash(unsigned), **unsigned)


@dataclass(frozen=True)
class TransparencyLogVerificationResult:
    accepted: bool
    reason_code: str
    verified_entries: int
    failed_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TransparencyLog:
    """Small append-only hash-chain transparency log for policy issuance.

    This module is intentionally storage-agnostic. It can be used for local JSONL
    audit files first, then replaced or backed by a remote log service later.
    """

    def __init__(self, entries: Optional[Iterable[TransparencyLogEntry]] = None) -> None:
        self._entries: List[TransparencyLogEntry] = list(entries or [])

    @property
    def entries(self) -> List[TransparencyLogEntry]:
        return list(self._entries)

    def last_hash(self) -> str:
        if not self._entries:
            return GENESIS_HASH
        return self._entries[-1].entry_hash

    def append_policy(
        self,
        policy: Mapping[str, Any],
        *,
        signer_key_ids: Sequence[str],
        threshold: int,
        decision: str = "issued",
        reason_code: str = "OK",
    ) -> TransparencyLogEntry:
        entry = build_transparency_entry(
            policy,
            index=len(self._entries),
            previous_hash=self.last_hash(),
            signer_key_ids=signer_key_ids,
            threshold=threshold,
            decision=decision,
            reason_code=reason_code,
        )
        self._entries.append(entry)
        return entry

    def verify(self) -> TransparencyLogVerificationResult:
        previous = GENESIS_HASH
        for expected_index, entry in enumerate(self._entries):
            if entry.index != expected_index:
                return TransparencyLogVerificationResult(False, "TRANSPARENCY_LOG_INDEX_MISMATCH", expected_index, entry.index)
            if entry.previous_hash != previous:
                return TransparencyLogVerificationResult(False, "TRANSPARENCY_LOG_PREVIOUS_HASH_MISMATCH", expected_index, entry.index)
            if compute_entry_hash(entry.unsigned_dict()) != entry.entry_hash:
                return TransparencyLogVerificationResult(False, "TRANSPARENCY_LOG_ENTRY_HASH_MISMATCH", expected_index, entry.index)
            previous = entry.entry_hash
        return TransparencyLogVerificationResult(True, "OK", len(self._entries), None)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.to_dict(), sort_keys=True, ensure_ascii=False) for e in self._entries) + ("\n" if self._entries else "")

    @classmethod
    def from_jsonl(cls, text: str) -> "TransparencyLog":
        entries = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            entries.append(TransparencyLogEntry.from_dict(json.loads(line)))
        return cls(entries)

    def write_jsonl(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.to_jsonl(), encoding="utf-8")
        return out

    @classmethod
    def read_jsonl(cls, path: str | Path) -> "TransparencyLog":
        return cls.from_jsonl(Path(path).read_text(encoding="utf-8"))


class TreeHeadValidationError(Exception):
    """Raised when a signed tree head fails verification or consistency."""


@dataclass(frozen=True)
class SignedTreeHead:
    """A signed commitment to a log size and head hash at a point in time."""

    log_size: int
    root_hash: str
    key_id: str
    signature: str

    def unsigned_body(self) -> Dict[str, Any]:
        return {
            "log_size": int(self.log_size),
            "root_hash": self.root_hash,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_size": int(self.log_size),
            "root_hash": self.root_hash,
            "key_id": self.key_id,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignedTreeHead":
        return cls(
            log_size=int(value.get("log_size", 0)),
            root_hash=str(value.get("root_hash", GENESIS_HASH)),
            key_id=str(value.get("key_id", "")),
            signature=str(value.get("signature", "")),
        )


def _coerce_sth(sth: Union[SignedTreeHead, Mapping[str, Any]]) -> SignedTreeHead:
    return sth if isinstance(sth, SignedTreeHead) else SignedTreeHead.from_dict(sth)


def _b64encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode_text(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def sign_tree_head(
    log: "TransparencyLog",
    private_key: Ed25519PrivateKey,
    key_id: str,
) -> SignedTreeHead:
    """Produce a signed commitment to the log's current size and head hash."""
    body = {
        "log_size": len(log.entries),
        "root_hash": log.last_hash(),
    }
    signature = _b64encode_bytes(private_key.sign(canonical_json_bytes(body)))
    return SignedTreeHead(
        log_size=body["log_size"],
        root_hash=body["root_hash"],
        key_id=str(key_id),
        signature=signature,
    )


def _sth_signature_ok(sth: SignedTreeHead, public_key: Ed25519PublicKey) -> bool:
    if not sth.signature:
        return False
    try:
        public_key.verify(
            _b64decode_text(sth.signature),
            canonical_json_bytes(sth.unsigned_body()),
        )
        return True
    except Exception:
        return False


def verify_tree_head(
    log: "TransparencyLog",
    sth: Union[SignedTreeHead, Mapping[str, Any]],
    public_key: Ed25519PublicKey,
) -> bool:
    """Return True if the STH is signed correctly and matches the current log."""
    head = _coerce_sth(sth)
    if not _sth_signature_ok(head, public_key):
        return False
    if not log.verify().accepted:
        return False
    return len(log.entries) == head.log_size and log.last_hash() == head.root_hash


def verify_consistency(
    log: "TransparencyLog",
    old_sth: Union[SignedTreeHead, Mapping[str, Any]],
    public_key: Ed25519PublicKey,
) -> bool:
    """Return True if log is an append-only extension of old_sth."""
    old = _coerce_sth(old_sth)
    if not _sth_signature_ok(old, public_key):
        return False
    if not log.verify().accepted:
        return False
    if old.log_size == 0:
        return old.root_hash == GENESIS_HASH
    if old.log_size > len(log.entries):
        return False
    return log.entries[old.log_size - 1].entry_hash == old.root_hash

