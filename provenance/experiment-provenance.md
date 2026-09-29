# Experiment Provenance

## E1

The `results/e1/` directory contains the sanitized public archive for the
journal-level AOMQTT v1.3.7 E1 replication.

The archive contains run-level publisher/subscriber observations, experiment
configuration, Chrony diagnostics, the replication runner, the E1 analysis
program, and integrity information.

## E2

The `results/e2/full/` and `results/e2/plain/` directories contain the ten
accepted Full AOMQTT and ten accepted Plain MQTT run archives respectively.

Frozen aggregate analysis outputs are under:

- `results/analysis/e2-full/`
- `results/analysis/e2-plain/`

The associated analysis programs are also surfaced under
`evaluation/source/e2/` for convenient inspection.

## Integrity

Repository-wide SHA-256 values are recorded under `checksums/`.
Original E2 archive sidecars and the public E1 archive sidecar are retained
beside their corresponding run archives.
