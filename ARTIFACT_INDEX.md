# AOMQTT Paper Artifact Index

This repository is the frozen research artifact for:

**AOMQTT: An Observation-Driven Secure MQTT Client Framework without Broker
Modification—Design, Implementation, and Multi-Client Evaluation**

The evaluated software baseline is **AOMQTT v1.3.7**, commit
`6dc0b2c497098aca569a636d1f8f8bb2adc4253a`. The exact source snapshot is
included under `software/aomqtt-v1.3.7/`.

## Evaluation map

| Evaluation | Purpose | Canonical source | Canonical results / analysis |
|---|---|---|---|
| E1 | Feature-level one-publisher/one-subscriber evaluation | `evaluation/source/e1/` | `results/e1/` |
| E2 | Five-publisher/five-subscriber multi-client evaluation | `evaluation/source/e2/` | `results/e2/`, `results/analysis/e2-full/`, `results/analysis/e2-plain/` |
| E3 | Broker-visible payload-length and topic-linkability privacy evaluation | `evaluation/source/e3/` | `results/e3/`, `results/analysis/e3-privacy/` |
| E3-B3 ablation v2 | Isolates the broker-visible temporal co-occurrence cue in B3 | `evaluation/source/e3/analyze_e3b_b3_feature_ablation_v2.py` | `results/analysis/e3-privacy-b3-ablation-v2/` |
| E4 | Guarded control-policy enforcement micro-evaluation | `evaluation/source/e4/` | `results/analysis/e4-policy-guard/` |
| E5 | Single-step observation-driven closed-loop evaluation | `evaluation/source/e5/` | `results/e5/`, `results/analysis/e5-closed-loop/` |

## E3-B3 feature ablation v2

The final ablation uses the frozen B3 pair-score input and five-fold
Leave-One-Run-Out evaluation.

- FULL: Top-1 `0.9955`, MRR `0.9919`
- BASE (co-occurrence disabled): Top-1 `0.3477`, MRR `0.5712`
- CO-OCCURRENCE ONLY: Top-1 `0.9818`, MRR `0.9802`

The interpretation is intentionally scoped to the frozen E3 synthetic workload
and observer/features. See
`results/analysis/e3-privacy-b3-ablation-v2/E3_B3_ABLATION_V2_FREEZE.txt`.

## E4 Policy Guard

E4 exercises the actual v1.3.7 guarded control-policy path in-process. All
30/30 trials passed across the valid-policy and rejection conditions. Timing is
local control-path execution time and excludes broker/network transport.

See `provenance/e4-provenance.md` and
`results/analysis/e4-policy-guard/`.

## E5 closed-loop evaluation

Five formal runs passed all predefined validity and application gates. The
implemented rule-based controller reduced rotation overlap from 5 s to 3 s
after observing a subscriber duplicate rate above the 10% threshold.

Across the five formal runs:

- duplicate rate: `12.773% ± 1.381%` → `7.386% ± 1.556%`;
- mean relative reduction: `42.670% ± 5.757%`;
- delivery loss: `0%` in every pre/post formal phase; and
- decryption success: `100%` in every pre/post formal phase.

E5 is a single-step functional closed-loop demonstration. It does not establish
controller stability, convergence, or optimal overlap.

The three pre-formal pilot/validity-aborted runs are retained and classified in
`results/e5/README.md` and `provenance/e5-provenance.md`.

## Integrity verification

Repository-wide integrity:

```bash
sha256sum -c checksums/SHA256SUMS.txt
sha256sum -c checksums/SHA256SUMS.txt.sha256
```

The repository-wide manifest intentionally excludes the manifest itself and
its sidecar to avoid cyclic checksumming. The sidecar authenticates
`checksums/SHA256SUMS.txt`.

Local E2, E3-B3-v2, E4, and E5 freeze manifests are retained alongside their
corresponding analysis outputs.

## Provenance

See:

- `provenance/experiment-provenance.md`
- `provenance/e3-provenance.md`
- `provenance/e4-provenance.md`
- `provenance/e5-provenance.md`
- `provenance/repository-finalization.md`
- `SOURCE_PROVENANCE.md`
