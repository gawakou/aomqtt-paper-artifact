# Repository finalization record

This record documents repository-layout cleanup after the E3/E4/E5 evaluation
artifacts were frozen.

- Retired obsolete E3 B3 ablation scratch output:
  `results/analysis/e3-privacy-b3-ablation/`
- Retired obsolete pre-freeze E4 scratch output:
  `results/analysis/policy-guard-micro/`
- Removed untracked Python `__pycache__` and `.pyc` debris.
- Added `results/e5/README.md` to distinguish the five formal E5 runs from
  the three pilot/validity-aborted runs.
- Added the final E3 B3 feature-ablation v2 analyzer source:
  `evaluation/source/e3/analyze_e3b_b3_feature_ablation_v2.py`
- No formal E1/E2/E3/E4/E5 measurement data were modified by this cleanup.

Latest detected retired scratch directory:

`/home/ogawa/aomqtt-paper-artifact-retired-20260930T080101Z`

Repository-wide checksums must be regenerated only after the remaining
publication metadata and provenance are finalized.

## Release-candidate integrity finalization

Generated: 2026-09-30T08:14:15Z

- Pre-final-commit repository HEAD: `d6efc44ac2916e544b3f9dc3631eb1c6937ebd08`
- Added reviewer-facing `ARTIFACT_INDEX.md`.
- Root `.gitignore` excludes Python caches while explicitly allowing frozen
  E5 `policy_signing_public.key` files to be versioned.
- E2 Full/Plain, E3-B3-ablation-v2, E4, and E5 local integrity manifests were
  verified before repository-wide hashing.
- Repository-wide checksums are generated non-cyclically: both
  `checksums/SHA256SUMS.txt` and
  `checksums/SHA256SUMS.txt.sha256` are excluded from the main manifest, and
  the sidecar hashes only the main manifest.
