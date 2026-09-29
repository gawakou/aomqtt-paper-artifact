from __future__ import annotations

import json
import urllib.error
import urllib.request

from .signer import PolicySigner, SignatureEnvelope, b64encode_bytes


class RemoteSignerError(RuntimeError):
    pass


class RemoteHTTPSigner(PolicySigner):
    """HTTP remote signer.

    Request JSON:
        {"key_id": "...", "algorithm": "Ed25519", "payload_b64": "..."}

    Expected response JSON:
        {"key_id": "...", "algorithm": "Ed25519", "signature": "..."}
    """

    algorithm = "Ed25519"
    signing_method = "remote-http"

    def __init__(self, key_id: str, endpoint_url: str, timeout: float = 5.0):
        if not key_id:
            raise ValueError("key_id must not be empty")
        if not endpoint_url:
            raise ValueError("endpoint_url must not be empty")
        self.key_id = key_id
        self.endpoint_url = endpoint_url
        self.timeout = timeout

    def sign(self, canonical_policy: bytes) -> SignatureEnvelope:
        payload = {
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "payload_b64": b64encode_bytes(canonical_policy),
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                response = json.loads(res.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RemoteSignerError(f"remote signer failed: {exc}") from exc

        if response.get("key_id") != self.key_id:
            raise RemoteSignerError("remote signer returned mismatched key_id")
        if response.get("algorithm") != self.algorithm:
            raise RemoteSignerError("remote signer returned unsupported algorithm")
        signature = response.get("signature")
        if not isinstance(signature, str) or not signature:
            raise RemoteSignerError("remote signer returned empty signature")

        return SignatureEnvelope(
            key_id=self.key_id,
            algorithm=self.algorithm,
            signature=signature,
            signing_method=self.signing_method,
        )
