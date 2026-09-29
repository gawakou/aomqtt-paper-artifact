# AOMQTT Roadmap after v0.6

| Version | Main purpose | Key implementation |
|---|---|---|
| v0.1 | Minimal SDK | Paho wrapper, HMAC topic tokenization, AES-GCM |
| v0.2 | Token-mode comparison | hierarchical / whole switching |
| v0.3 | Long-term linkability mitigation | token rotation, overlap window |
| v0.4 | Implementation architecture | transport adapter, core separation, client observation foundation |
| v0.5 | Evaluation framework | publisher/subscriber CSV, loss/duplicate/decryption/delivery evaluation |
| v0.6 | Payload-size leakage mitigation | fixed/bucket/random padding and overhead evaluation |
| v0.7 | External control | policy controller for token mode, rotation, padding, overlap |
| v0.8 | Observation-driven control | automatic policy adjustment based on client observations |
| v0.9 | High-performance implementation | Rust core or Rust client SDK |
| v1.0 | Paper reproducibility package | Docker, scripts, plots, threat model, replication guide |

## v0.6 contribution

v0.6 adds payload padding as a configurable metadata-leakage mitigation and makes
its overhead measurable. The primary research claim is not that padding fully
prevents traffic analysis, but that AOMQTT can expose and quantify the trade-off
between privacy level, MQTT compatibility, delivery reliability, and operational
overhead.
