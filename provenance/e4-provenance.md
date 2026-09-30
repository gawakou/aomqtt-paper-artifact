# E4 guarded control-policy enforcement provenance

## Evaluated software baseline

- AOMQTT v1.3.7
- Core commit: `6dc0b2c497098aca569a636d1f8f8bb2adc4253a`
- Paper-artifact repository state immediately before the E4 freeze:
  `d6efc44ac2916e544b3f9dc3631eb1c6937ebd08`

## Formal E4 design

E4 evaluates the runtime guarded policy-application path in-process.

- PG0: valid signed policy -> accepted and applied
- PG1: signed message modified after signing -> `invalid_signature`
- PG2: expired signed policy -> `expired_policy`
- PG3: replayed/stale sequence -> `stale_sequence_no`
- PG4: untrusted signing key identifier -> `unknown_key_id`
- PG5: validly signed request disabling payload encryption ->
  `payload_encryption_disable_forbidden`

Each condition was repeated five times after installing a valid sequence-1
last-known-good baseline, for 30 candidate-policy trials in total.

## Formal result

- 30/30 candidate trials passed the predefined gate.
- PG0: 5/5 accepted and applied.
- PG1-PG5: 25/25 rejected with the expected reason code.
- All rejected candidates preserved the last-known-good policy, accepted
  sequence state, and effective publisher configuration.

## Timing scope

The recorded E4 elapsed time is an in-process implementation measurement. It
includes the receiver validation path and, for PG0, the zero-delay application
timer. It excludes MQTT broker forwarding, network round-trip time, and
controller-decision time.

## Frozen files

- Harness: `evaluation/source/e4/run_policy_guard_micro_eval.py`
- Per-trial results:
  `results/analysis/e4-policy-guard/policy_guard_trials.csv`
- Aggregate results:
  `results/analysis/e4-policy-guard/policy_guard_summary.csv`
- Machine-readable summary:
  `results/analysis/e4-policy-guard/policy_guard_summary.json`
- Freeze note:
  `results/analysis/e4-policy-guard/E4_POLICY_GUARD_FREEZE.txt`

## Environment

- Python 3.12.3
- Freeze time: 2026-09-30T05:54:53Z
