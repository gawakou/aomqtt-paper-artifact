# AOMQTT Paper Artifact

Research artifact for:

**AOMQTT: An Observation-Driven Secure MQTT Client Framework without Broker Modification—Design, Implementation, and Multi-Client Evaluation**

This repository contains the frozen experimental definitions, evaluation and
analysis scripts, sanitized run-level results, aggregate outputs, integrity
records, and environment provenance associated with the paper.

This is **not** the active AOMQTT development repository.

## Software baseline

The software evaluated in the paper is:

- **AOMQTT v1.3.7**
- Commit: `6dc0b2c497098aca569a636d1f8f8bb2adc4253a`

The exact evaluated AOMQTT v1.3.7 source snapshot is included under `software/aomqtt-v1.3.7/`.

Development repository reference:

https://github.com/gawakou/aomqtt-client-sdk

## Repository contents

- `software/`: evaluated software revision information and the frozen AOMQTT v1.3.7 source snapshot
- `evaluation/source/e1/`: E1 replication runner, baseline helpers, and analyzer
- `evaluation/source/e2/`: frozen E2 analysis programs
- `evaluation/source/e3/`: frozen E3 event-plan, observer, runner, analysis, and test programs
- `evaluation/source/e4/`: frozen E4 guarded control-policy micro-evaluation harness
- `results/e1/`: one-publisher / one-subscriber E1 replication archive
- `results/e1/summary/`: directly viewable E1 per-run and per-condition summary tables
- `results/e2/full/`: ten accepted Full AOMQTT E2 run archives
- `results/e2/plain/`: ten accepted Plain MQTT E2 run archives
- `results/e3/`: frozen E3 formal-data archive and integrity sidecar
- `results/analysis/e3-privacy/`: directly inspectable E3 privacy-analysis outputs
- `results/analysis/e4-policy-guard/`: frozen E4 guarded control-policy results and integrity manifest
- `results/analysis/e2-full/`: frozen Full AOMQTT aggregate analysis
- `results/analysis/e2-plain/`: frozen Plain MQTT aggregate analysis
- `provenance/`: software and experimental provenance
- `checksums/`: repository-wide SHA-256 integrity manifest

## E1 feature-level evaluation

E1 uses one publisher and one subscriber, with five accepted runs per condition:

- A1: Plain MQTT
- A2: topic protection and payload encryption
- A3: A2 + fixed 512-byte padding
- A4: A3 + 30-s token rotation with 5-s overlap

Each run contains 6,000 logical messages at QoS 1.

## E2 multi-client evaluation

E2 uses five publishers and five subscribers and compares:

- Plain MQTT
- Full AOMQTT

There are ten accepted runs per condition.

## E3 broker-visible privacy evaluation

E3 uses five accepted formal runs per condition.

- E3-A: payload-length inference under Plain MQTT, encrypted/unpadded AOMQTT,
  and fixed 512-byte padding.
- E3-B: cross-epoch topic-token linkability under rotation without padding,
  rotation with fixed padding, and fixed padding with a 5-s overlap.
- The final analysis uses five-fold Leave-One-Run-Out validation and preserves
  the frozen harness and analysis provenance.

See `provenance/e3-provenance.md` and `results/analysis/e3-privacy/`.

## E4 guarded control-policy enforcement

E4 evaluates the guarded runtime policy-application path in-process.

- Six conditions (PG0-PG5), five trials per condition.
- PG0 is a valid signed update and must be accepted and applied.
- PG1-PG5 cover invalid signature, expiration, replay/stale sequence,
  untrusted signing key identifier, and a validly signed request that disables
  required payload encryption.
- The formal gate requires rejected candidates to preserve the last-known-good
  policy and effective publisher configuration.
- All 30 candidate-policy trials passed the predefined gate.

E4 timing is local control-path execution time only; it excludes broker,
network, and controller-decision latency.

See `provenance/e4-provenance.md` and
`results/analysis/e4-policy-guard/`.

## Artifact integrity

Verify repository files with:

```bash
sha256sum -c checksums/SHA256SUMS.txt
```

Individual E1/E2/E3 archive checksum sidecars are also retained beside the
corresponding archives.

## Sanitization

The public E1 archive was sanitized only to remove an e-mail address contained
in environment metadata. The experiment measurement data were not modified.

Private RFC1918 addresses, laboratory VM hostnames, and local filesystem paths
may remain where they are relevant provenance.

## Source provenance

See [SOURCE_PROVENANCE.md](SOURCE_PROVENANCE.md).

## Rights

See [RIGHTS.md](RIGHTS.md).

<!-- E5-CLOSED-LOOP-START -->
## E5 — Single-step closed-loop observation-driven control

E5 exercises the implemented AOMQTT v1.3.7 closed-loop path against a live
MQTT broker. Five formal runs start with 30-s token rotation and a 5-s overlap.
When the observed subscriber duplicate rate exceeds 10%, the existing
rule-based controller selects `decrease_overlap`, generates a signed runtime
policy reducing overlap to 3 s, and waits for both Publisher and Subscriber
ACK/Status confirmation.

Across the five formal runs, duplicate rate decreased from 12.773% ± 1.381% to
7.386% ± 1.556% while delivery loss remained 0% and decryption success remained
100% in every run. All formal validity and application gates passed.

Artifacts:
- `evaluation/source/e5/`
- `results/e5/`
- `results/analysis/e5-closed-loop/`
- `provenance/e5-provenance.md`

E5 is a single-step functional closed-loop demonstration; it does not claim
controller stability, convergence, or optimality.
<!-- E5-CLOSED-LOOP-END -->

<!-- ARTIFACT-INDEX-START -->
## Artifact index

For a reviewer-oriented map from E1 through E5, including the final E3-B3
feature ablation, E4 Policy Guard evaluation, E5 formal/pilot classification,
and integrity commands, see [ARTIFACT_INDEX.md](ARTIFACT_INDEX.md).
<!-- ARTIFACT-INDEX-END -->
