# AOMQTT Revised Roadmap after v0.5

| Version | Main goal | Main implementation | Research role |
|---|---|---|---|
| v0.1 | Minimal SDK | Paho wrapper, HMAC topic tokenization, AES-GCM | minimum client-only privacy layer |
| v0.2 | Token mode comparison | hierarchical / whole switching | privacy-functionality trade-off |
| v0.3 | Long-term tracking mitigation | token rotation, overlap window | linkability reduction prototype |
| v0.4 | Implementation foundation | Transport Adapter separation, Core independence, client observation | broker/client implementation independence |
| v0.5 | Evaluation framework | baseline comparison, publisher/subscriber CSV, loss/duplicate evaluation, whole/hierarchical/rotation comparison | evidence for paper evaluation |
| v0.6 | Payload-size leakage mitigation | fixed/bucket/random padding and overhead evaluation | payload-size metadata leakage reduction |
| v0.7 | External policy control | policy controller for token_mode, rotation, padding, overlap | operator-driven privacy policy |
| v0.8 | Observation-driven control | automatic policy adjustment from client metrics | observation-driven MQTT privacy control |
| v0.9 | High-performance implementation | Rust core or Rust client SDK | performance and deployability |
| v1.0 | Reproducible research package | Docker, scripts, plots, threat model, paper artifacts | publishable stable prototype |

v0.5 is intentionally not a new cryptographic primitive release. It is the
release that makes AOMQTT measurable: latency, success rate, delivery loss,
duplicate delivery, decryption failure, and rotation overhead can be evaluated
under multiple baselines.
