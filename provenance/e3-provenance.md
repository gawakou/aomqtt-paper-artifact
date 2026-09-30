# E3 privacy-evaluation provenance

## Evaluated software baseline

- AOMQTT v1.3.7
- Core commit: `6dc0b2c497098aca569a636d1f8f8bb2adc4253a`

## Frozen E3 harness revisions

- E3-A harness: `9f6e64bbb891508f793cc9ea883f9449cffb074a`
- E3-A tag: `e3a-harness-freeze-v1`
- E3-B harness: `0b38486ca60c1a7afcf398d96eb39e0388c333ab`
- E3-B tag: `e3b-harness-freeze-v1`
- Privacy-analysis harness: `c4123a92cce8d43f70a1f955d6db9303ae853671`
- Analysis tag: `e3-analysis-freeze-v1`

## Formal runs

- E3-A: five accepted formal runs (r01-r05) for A0-A2.
- E3-B: five accepted formal runs (r01-r05) for B0-B3.
- Formal run gates and SHA-256 freeze records are included in the E3 archive.
- The committed privacy-analysis outputs were reproduced after the analysis
  harness was committed, with identical principal output digests.

## Analysis environment

The frozen analysis manifest records:

- Python 3.12.3
- NumPy 2.5.3
- SciPy 1.18.1
- scikit-learn 1.9.1
