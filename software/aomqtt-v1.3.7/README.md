# AOMQTT Client SDK

AOMQTT Client SDK is a research prototype for client-side topic obfuscation, payload encryption, payload padding, token rotation, controller-driven policy delivery, policy ACK/status reporting, controller-side analysis, observation-driven policy control, trusted policy delivery hardening, multi-signature policy authorization, transparency-log-based policy auditability, reproducible paper-ready evaluation, and large-scale evaluation planning, and local broker measurement comparison, and repeated-trial statistical evaluation, and real repeated local trial automation over MQTT.

AOMQTT does not require modification of the MQTT broker. It is designed as a client-side security and control layer that can be used with existing MQTT brokers such as Eclipse Mosquitto.

<!-- V1.3.4_SECURITY_HARDENING_START -->
## v1.3.4 Security Hardening

v1.3.4 strengthens the trusted control plane based on source-code review of
the v1.3.x series. The release focuses on three security fixes:

1. **Multi-signature role binding**
   - Signer roles are now bound through `signature_policy["signer_roles"]`.
   - The role map is included in the signed multi-signature payload.
   - Unsigned `role` labels inside individual signature blocks are no longer
     trusted for `required_roles` decisions.

2. **Authenticated KRL loading and anti-rollback protection**
   - `verify_and_load_krl()` verifies KRL signatures before use.
   - `TrustedControlPolicyProcessor` supports `krl_public_key` and
     `krl_min_version`.
   - `update_krl()` accepts only authenticated KRLs with a strictly newer
     `krl_version`, preventing rollback to an older revocation list.

3. **Transparency log Signed Tree Head support**
   - `SignedTreeHead`, `sign_tree_head()`, `verify_tree_head()`, and
     `verify_consistency()` were added.
   - A signed tree head commits to the current log size and root/head hash.
   - Append-only consistency can be checked against a previously trusted STH.

The v1.3.4 regression tests are:

```bash
python -m pytest -q tests/test_multisig_role_binding_v134.py
python -m pytest -q tests/test_trusted_processor_krl_authentication_v134.py
python -m pytest -q tests/test_transparency_sth_v134.py
python -m pytest -q
```

Expected result after the v1.3.4 security hardening changes:

```text
195 passed
```

<!-- V1.3.4_SECURITY_HARDENING_END -->

## Overview

AOMQTT provides a client-side mechanism for protecting MQTT communication metadata and payloads while preserving compatibility with existing MQTT broker infrastructure.

The main goals of this project are:

- to obfuscate MQTT topic names using HMAC-based topic tokens;
- to encrypt MQTT payloads using authenticated encryption;
- to reduce payload-size leakage using padding policies;
- to support token rotation and overlap windows;
- to deliver control policies from an external controller;
- to verify signed control policies using trusted signing keys;
- to reject policies signed by unknown or revoked signing keys;
- to authorize policies using multi-signature threshold and role validation;
- to record policy decisions in a hash-chain-based transparency log;
- to report policy ACK and application status from clients;
- to aggregate controller-side ACK/status/reason_code results;
- to provide reproducible evaluation workflows for research papers;
- to generate paper-ready security evolution, policy decision, and summary tables;
- to generate paper-ready tables and figures;
- to plan large-scale, DoS-safe, public broker, mdx, and Starlink evaluations;
- to collect local broker measurements into a unified CSV schema;
- to aggregate repeated local comparison trials into statistical summaries;
- to automate real local broker trials and connect them to repeated-trial statistics.

This repository is organized as a reproducible research prototype for v1.3.3.


## v1.0.1 hardening update

v1.0.1 addresses issues identified by an external strict review of v1.0.0.  The primary goal is to keep the implementation suitable for research experiments while reducing accidental insecure operation and fixing behavior-affecting bugs.

Implemented fixes:

- Data-plane subscribers now re-subscribe remembered token filters after MQTT reconnects.  This is important because the default Paho MQTT v3.1.1 clean session can remove broker-side subscriptions after a disconnect.
- `AOMQTTConfig.__repr__()` and `AOMQTTConfig.to_dict()` redact `topic_key` and `payload_key` by default.  Internal reconstruction uses `to_dict(redact=False)` explicitly.
- Random payload padding now uses `secrets.randbelow(span)` and respects the full configured `padding_random_min_bytes` to `padding_random_max_bytes` range without modulo bias.
- Subscriber duplicate detection now uses a bounded LRU-style message-id window instead of an unbounded set.
- Control-topic receivers now require signed policies by default.  For isolated local experiments only, pass `require_signature=False` in code or use `--allow-unsigned-control-policy` in the examples.
- The bundled Mosquitto native example is explicitly documented as local-only and binds to `127.0.0.1`.  Docker uses a separate container config while the host port is bound to localhost.
- Release packaging should use a clean archive that excludes `.git/`, `__pycache__/`, `.pytest_cache/`, `.DS_Store`, and `__MACOSX/`.

Known research-prototype limitations that remain intentionally documented rather than fully solved in v1.0.1:

- `PayloadCrypto` still derives the AES-GCM key as `SHA-256(payload_key)` for prototype compatibility.  Human-memorable passphrases are not appropriate; use high-entropy keys for experiments.
- Token rotation rotates topic tokens, not the AEAD payload key.  Production-like long-running deployments need a key-distribution and payload-key rotation mechanism.
- The default MQTT QoS remains `0` for simple baseline evaluation.  Use `--qos 1` or a policy with QoS 1 when delivery acknowledgement is part of the experiment.

## Research Motivation

MQTT is widely used in IoT, monitoring systems, disaster-response systems, and infrastructure management. However, MQTT topic names often contain semantic information such as site names, device types, metrics, or operational states.

Even when payload encryption is applied, topic names and payload sizes may still leak sensitive operational information.

AOMQTT addresses this issue by introducing a client-side protection and control layer that supports:

- topic obfuscation;
- payload encryption;
- payload padding;
- token rotation;
- controller-driven policy delivery;
- policy ACK/status reporting;
- controller-side deployment analysis;
- observation-driven policy adaptation;
- trusted policy delivery and key lifecycle hardening;
- multi-signature policy authorization;
- transparency-log-based policy auditability;
- evaluation reproducibility and paper-ready security summary generation;
- large-scale, DoS-safe, public broker, mdx, and Starlink evaluation planning;
- local broker measurement collection and comparison;
- repeated-trial statistics and paper-ready confidence interval summaries;
- real repeated local trial automation with subscriber/publisher client-id isolation.

The design assumption is that the MQTT broker remains unmodified. This makes the approach applicable to existing broker deployments.

## Key Features

### Topic Obfuscation

AOMQTT supports HMAC-SHA256-based topic tokenization.

Supported tokenization modes are:

- `whole`: the entire topic is converted into a single token;
- `hierarchical`: each topic level is converted into a token while preserving the topic hierarchy length.

Example:

```text
Original topic:
  shelter/siteA/starlink/rtt

Whole token mode:
  aomqtt/v1/t/<token>

Hierarchical token mode:
  aomqtt/v1/h/<token1>/<token2>/<token3>/<token4>
```

### Payload Encryption

AOMQTT encrypts MQTT payloads using authenticated encryption.

The encrypted payload can be bound to the protected topic using additional authenticated data, depending on the configuration.

### Payload Padding

AOMQTT supports payload padding to reduce payload-size leakage.

Supported padding modes include:

- no padding;
- fixed-size padding;
- bucket-based padding;
- random padding.

### Token Rotation

AOMQTT supports token rotation with an overlap window.

This allows publishers and subscribers to transition between token epochs while reducing message loss during rotation.

### Policy Control

AOMQTT supports external policy control.

A controller can distribute policies to clients through MQTT control topics.

Policy examples include:

- tokenization mode;
- padding mode;
- padding size;
- rotation interval;
- rotation overlap;
- policy validity period.

### Policy ACK and Status Reporting

Clients can report whether a policy was accepted, rejected, expired, invalid, applied, or failed.

Typical ACK/status values include:

- `accepted`
- `rejected`
- `expired`
- `invalid_signature`
- `replay_detected`
- `applied`
- `failed`
- `timeout`

### Trusted Policy Delivery and Key Lifecycle Hardening

AOMQTT v1.1.0 introduces a trust validation layer for control policies.

The v1.1.0 trust layer supports:

- signed policy trust validation;
- `signer_key_id` based trusted key checking;
- rejection of policies signed by unknown signing keys;
- rejection of policies signed by revoked signing keys;
- invalid policy signature detection;
- Key Revocation List based policy rejection;
- explicit ACK reason codes for trust-related rejections;
- runtime trust scenario evaluation.

Typical trust-related reason codes include:

- `OK`
- `UNKNOWN_SIGNING_KEY`
- `REVOKED_SIGNING_KEY`
- `POLICY_SIGNATURE_INVALID`
- `PADDING_TOO_LARGE`

### Multi-Signature Policy and Transparency Log

AOMQTT v1.2.0 extends the v1.1.0 trusted policy delivery model by adding
multi-signature policy authorization and transparency-log-based policy
auditability.

The v1.2.0 multi-signature layer supports:

- multi-signature policy envelopes;
- threshold-based policy authorization;
- required signer role validation;
- KRL-aware multi-signature verification;
- rejection of policies with insufficient valid signatures;
- rejection of policies missing required signer roles;
- rejection of policies signed by revoked keys;
- rejection of policies with invalid signatures;
- integration with the existing client-side Policy Guard.

The v1.2.0 transparency log records policy decisions in a hash-chain-based
append-only log. The log can be verified to detect tampering, deletion, or
reordering of policy decision entries.

Typical v1.2.0 reason codes include:

- `OK`
- `MULTISIG_THRESHOLD_NOT_MET`
- `MULTISIG_REQUIRED_ROLE_MISSING`
- `REVOKED_SIGNING_KEY`
- `POLICY_SIGNATURE_INVALID`
- `PADDING_TOO_LARGE`

### Evaluation Reproducibility and Paper-Ready Summary

AOMQTT v1.2.1 adds evaluation reproducibility assets for paper writing.

The v1.2.1 evaluation layer supports:

- one-command security evolution evaluation;
- security evolution table generation;
- policy decision matrix generation;
- paper summary table generation;
- reproducible comparison of v1.0.2, v1.1.0, and v1.2.0 behavior;
- documentation for paper-oriented evaluation.

Generated v1.2.1 artifacts include:

- `security_evolution_table.csv`
- `policy_decision_matrix.csv`
- `paper_summary_table.csv`
- `v121_evaluation_manifest.json`

### Large-Scale, DoS-Safe, Public Broker, mdx, and Starlink Evaluation

AOMQTT v1.3.0 adds a safe evaluation planning framework for large-scale,
adversarial, public broker, mdx, and Starlink experiments.

The v1.3.0 evaluation layer supports:

- large-scale scenario plan generation;
- environment safety matrix generation;
- public broker safety policy documentation;
- mdx and Starlink evaluation planning;
- release table generation for v1.3.0 evaluation assets;
- one-command v1.3.0 evaluation workflow;
- explicit separation between local/authorized stress evaluation and public-broker compatibility probing.

Safety rule:

```text
DoS-like and high-rate workloads must be limited to local or explicitly
authorized environments. Public broker evaluation is limited to low-rate
compatibility probing.
```

Generated v1.3.0 artifacts include:

- `large_scale_scenario_plan.csv`
- `environment_safety_matrix.csv`
- `v130_large_scale_summary.json`
- `v130_release_table.csv`
- `v130_evaluation_manifest.json`

### Local Broker Measurement Runner and Comparison Table

AOMQTT v1.3.1 adds a local broker measurement runner and unified measurement
CSV schema.

The v1.3.1 measurement layer supports:

- plain MQTT baseline measurement;
- AOMQTT basic measurement collection;
- AOMQTT fixed padding measurement collection;
- AOMQTT fixed padding with token rotation and overlap measurement collection;
- v1.2.0 multi-signature control-plane normalization;
- unified measurement CSV generation;
- local comparison table generation;
- paper-ready local broker comparison summaries.

Generated v1.3.1 artifacts include:

- `unified_measurements.csv`
- `v131_measurement_summary.json`
- `v131_release_table.csv`
- `v131_paper_measurement_table.csv`
- `v131_local_comparison_table.csv`
- `v131_local_comparison_summary.json`

### Repeated Trials and Statistical Summaries

AOMQTT v1.3.2 adds repeated-trial statistics for local broker measurement
results.

The v1.3.2 statistics layer supports:

- repeated-trial measurement aggregation;
- per-scenario mean, standard deviation, and standard error;
- approximate 95% confidence intervals;
- paper-ready repeated-trial statistics tables;
- MQTT expansion ratio aggregation;
- duplicate ratio aggregation;
- success ratio aggregation;
- deterministic sample trial generation for validating the statistics pipeline.

Generated v1.3.2 artifacts include:

- `repeated_trial_measurements.csv`
- `repeated_trial_statistics.csv`
- `v132_paper_statistics_table.csv`
- `v132_repeated_trial_summary.json`
- `v132_repeated_trials_manifest.json`

### Real Repeated Local Trial Automation

AOMQTT v1.3.3 connects the v1.3.1 local measurement workflow and the v1.3.2
statistics workflow by automating real local broker trials.

The v1.3.3 automation layer supports:

- one-trial local measurement automation;
- repeated local trial execution;
- dry-run plan generation;
- local-broker safety guard;
- plain MQTT baseline execution;
- AOMQTT basic execution;
- AOMQTT fixed padding execution;
- AOMQTT fixed padding with token rotation and overlap execution;
- automatic local comparison table generation;
- automatic repeated-trial statistics collection;
- explicit Publisher/Subscriber MQTT `client_id` separation to avoid connection replacement.

Generated v1.3.3 artifacts include:

- `v133_trial_plan.json`
- `v133_trial_plan.sh`
- `v133_trial_manifest.json`
- `v133_repeated_trials_manifest.json`
- trial-level `v131_local_comparison_table.csv`
- aggregate `statistics/v132_paper_statistics_table.csv`

### Controller-Side Analysis

AOMQTT v0.9.2 and later include controller-side analysis support.

The controller can aggregate:

- ACK status;
- application status;
- reason codes;
- policy deployment summaries;
- accepted/rejected/applied/failed/timeout rates.

### Observation-Driven Policy Control

AOMQTT supports observation-driven policy control.

Observed metrics such as delivery behavior, ACK status, status reports, reason codes, and policy results can be used to analyze and adapt control policies.

## Architecture

The high-level architecture consists of the following components:

```text
+-------------------+          +-------------------+
| AOMQTT Publisher  |          | AOMQTT Subscriber |
+-------------------+          +-------------------+
          |                              |
          | protected MQTT topics        |
          v                              v
+--------------------------------------------------+
|              Existing MQTT Broker                |
|        e.g., Eclipse Mosquitto                   |
+--------------------------------------------------+
          ^                              ^
          | control policy / ACK / status|
          |                              |
+--------------------------------------------------+
|              AOMQTT Controller                   |
+--------------------------------------------------+
```

AOMQTT is implemented as a client-side layer. The MQTT broker only forwards MQTT messages and does not need to understand the original topic names, encryption keys, or control policy semantics.

## Repository Structure

```text
aomqtt-client-sdk/
├── aomqtt/
│   ├── client.py
│   ├── config.py
│   ├── crypto.py
│   ├── topic_token.py
│   ├── control/
│   ├── evaluation/
│   ├── observation/
│   ├── signing/
│   ├── krl.py
│   ├── policy_trust.py
│   ├── multisig_policy.py
│   ├── transparency_log.py
│   ├── trusted_multisig_processor.py
│   └── controller_anomaly.py
├── docs/
│   ├── release-checklist-v1.0.0.md
│   ├── experiment-workflow.md
│   ├── result-format.md
│   ├── v1.1.0-trusted-policy-delivery.md
│   ├── v1.1.0-runtime-scenarios.md
│   ├── v1.2.0-multisig-transparency.md
│   ├── v1.2.0-runtime-scenarios.md
│   ├── v1.2.0-release-notes-draft.md
│   ├── v1.2.1-evaluation-workflow.md
│   ├── v1.2.1-paper-evaluation-plan.md
│   ├── v1.2.1-release-notes-draft.md
│   ├── v1.3.0-large-scale-evaluation.md
│   ├── v1.3.0-public-broker-safety.md
│   ├── v1.3.0-mdx-starlink-evaluation-plan.md
│   ├── v1.3.0-release-notes-draft.md
│   ├── v1.3.1-local-broker-measurement-runner.md
│   ├── v1.3.1-measurement-schema.md
│   ├── v1.3.1-aomqtt-measurement-collector.md
│   ├── v1.3.1-local-comparison-table.md
│   ├── v1.3.1-release-notes-draft.md
│   ├── v1.3.2-repeated-trials-statistics.md
│   ├── v1.3.2-release-notes-draft.md
│   ├── v1.3.3-real-repeated-local-trials.md
│   └── v1.3.3-release-notes-draft.md
├── examples/
│   ├── publisher_example.py
│   ├── subscriber_example.py
│   ├── policy_auto_controller.py
│   ├── show_effective_policy.py
│   ├── multisig_transparency_demo.py
│   └── trusted_multisig_processor_demo.py
├── experiments/
│   ├── common.sh
│   ├── run_static_policy.sh
│   ├── run_observation_policy.sh
│   ├── run_rejected_policy_feedback.sh
│   ├── run_all_v091_scenarios.sh
│   ├── collect_v091_evaluation_table.sh
│   ├── run_all_v100_scenarios.sh
│   ├── collect_v100_evaluation_table.sh
│   ├── run_v110_trust_scenarios.sh
│   ├── run_v120_multisig_transparency_scenarios.sh
│   ├── collect_v120_release_table.sh
│   ├── run_v121_security_evolution.sh
│   ├── collect_v121_security_evolution_table.py
│   ├── collect_v121_policy_decision_matrix.py
│   ├── collect_v121_paper_summary_table.py
│   ├── run_v130_large_scale_scenarios.py
│   ├── collect_v130_evaluation_table.py
│   ├── run_v130_evaluation.sh
│   ├── v131_measurement_schema.py
│   ├── run_v131_plain_mqtt_measurement.py
│   ├── run_v131_local_measurements.py
│   ├── collect_v131_measurement_table.py
│   ├── collect_v131_aomqtt_measurement.py
│   ├── collect_v131_local_comparison_table.py
│   ├── run_v131_local_measurements.sh
│   ├── collect_v132_repeated_trial_statistics.py
│   ├── generate_v132_sample_trials.py
│   ├── run_v132_repeated_trials.sh
│   ├── run_v133_real_local_trial.py
│   ├── run_v133_real_repeated_trials.py
│   └── run_v133_real_repeated_trials.sh
├── scripts/
│   ├── generate_paper_tables.py
│   ├── generate_paper_figures.py
│   └── generate_paper_assets.py
├── results/
├── tests/
├── README.md
├── pyproject.toml
├── requirements.txt
└── docker-compose.yml
```

## Installation

Create and activate a Python virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies.

```bash
pip install -r requirements.txt
```

Install the package in editable mode if needed.

```bash
pip install -e .
```

Run tests.

```bash
python -m pytest
```

## MQTT Broker

A local MQTT broker can be started using Docker Compose.

```bash
docker compose up -d
```

Confirm that the broker is running.

```bash
docker compose ps
```

Stop the broker if needed.

```bash
docker compose down
```

## Quick Start

### Subscriber

Start a subscriber.

```bash
python examples/subscriber_example.py \
  --broker localhost \
  --topic shelter/siteA/starlink/rtt \
  --qos 1
```

### Publisher

Start a publisher in another terminal.

```bash
python examples/publisher_example.py \
  --broker localhost \
  --topic shelter/siteA/starlink/rtt \
  --count 20 \
  --interval 1 \
  --qos 1 \
  --metrics-csv results/basic_publisher_metrics.csv
```

## Policy Control

AOMQTT supports controller-driven policy delivery.

The controller publishes policy messages to a control topic.

```text
aomqtt/control/<group_id>/policy
```

Clients report ACK and status information to the following topics.

```text
aomqtt/control/<group_id>/ack
aomqtt/control/<group_id>/status
```

Typical policy result states include:

- `accepted`
- `rejected`
- `expired`
- `invalid_signature`
- `replay_detected`
- `applied`
- `failed`
- `timeout`

## Documentation

The repository includes documentation for reproducible evaluation and release validation.

```text
docs/release-checklist-v1.0.0.md
docs/experiment-workflow.md
docs/result-format.md
docs/v1.1.0-trusted-policy-delivery.md
docs/v1.1.0-runtime-scenarios.md
docs/v1.1.0-release-notes-draft.md
docs/v1.2.0-multisig-transparency.md
docs/v1.2.0-runtime-scenarios.md
docs/v1.2.0-release-notes-draft.md
docs/v1.2.1-evaluation-workflow.md
docs/v1.2.1-paper-evaluation-plan.md
docs/v1.2.1-release-notes-draft.md
docs/v1.3.0-large-scale-evaluation.md
docs/v1.3.0-public-broker-safety.md
docs/v1.3.0-mdx-starlink-evaluation-plan.md
docs/v1.3.0-release-notes-draft.md
docs/v1.3.1-local-broker-measurement-runner.md
docs/v1.3.1-measurement-schema.md
docs/v1.3.1-aomqtt-measurement-collector.md
docs/v1.3.1-local-comparison-table.md
docs/v1.3.1-release-notes-draft.md
docs/v1.3.2-repeated-trials-statistics.md
docs/v1.3.2-release-notes-draft.md
docs/v1.3.3-real-repeated-local-trials.md
docs/v1.3.3-release-notes-draft.md
```

### Release Checklist

```text
docs/release-checklist-v1.0.0.md
```

This file defines the release criteria for v1.0.0.

### Version-Specific Documentation

```text
docs/v1.1.0-trusted-policy-delivery.md
docs/v1.1.0-runtime-scenarios.md
docs/v1.1.0-release-notes-draft.md
docs/v1.2.0-multisig-transparency.md
docs/v1.2.0-runtime-scenarios.md
docs/v1.2.0-release-notes-draft.md
docs/v1.2.1-evaluation-workflow.md
docs/v1.2.1-paper-evaluation-plan.md
docs/v1.2.1-release-notes-draft.md
docs/v1.3.0-large-scale-evaluation.md
docs/v1.3.0-public-broker-safety.md
docs/v1.3.0-mdx-starlink-evaluation-plan.md
docs/v1.3.0-release-notes-draft.md
docs/v1.3.1-local-broker-measurement-runner.md
docs/v1.3.1-measurement-schema.md
docs/v1.3.1-aomqtt-measurement-collector.md
docs/v1.3.1-local-comparison-table.md
docs/v1.3.1-release-notes-draft.md
docs/v1.3.2-repeated-trials-statistics.md
docs/v1.3.2-release-notes-draft.md
docs/v1.3.3-real-repeated-local-trials.md
docs/v1.3.3-release-notes-draft.md
```

These files document version-specific trusted policy delivery, multi-signature policy authorization, transparency-log auditability, and evaluation reproducibility assets.

### v1.2.0 Multi-Signature Policy and Transparency Log

```text
docs/v1.2.0-multisig-transparency.md
docs/v1.2.0-runtime-scenarios.md
docs/v1.2.0-release-notes-draft.md
```

These files document the v1.2.0 multi-signature policy authorization,
transparency-log audit mechanism, runtime scenarios, and release notes draft.

### v1.2.1 Evaluation Reproducibility

```text
docs/v1.2.1-evaluation-workflow.md
docs/v1.2.1-paper-evaluation-plan.md
docs/v1.2.1-release-notes-draft.md
docs/v1.3.0-large-scale-evaluation.md
docs/v1.3.0-public-broker-safety.md
docs/v1.3.0-mdx-starlink-evaluation-plan.md
docs/v1.3.0-release-notes-draft.md
docs/v1.3.1-local-broker-measurement-runner.md
docs/v1.3.1-measurement-schema.md
docs/v1.3.1-aomqtt-measurement-collector.md
docs/v1.3.1-local-comparison-table.md
docs/v1.3.1-release-notes-draft.md
docs/v1.3.2-repeated-trials-statistics.md
docs/v1.3.2-release-notes-draft.md
docs/v1.3.3-real-repeated-local-trials.md
docs/v1.3.3-release-notes-draft.md
```

These files document the v1.2.1 evaluation workflow, paper-oriented evaluation
plan, and release notes draft.

### Experiment Workflow

```text
docs/experiment-workflow.md
```

This file defines the recommended execution order of examples and experiments.

### Result Format

```text
docs/result-format.md
```

This file defines the standard result directory structure and CSV/JSON schemas.

## Evaluation Workflow

The recommended v1.0.0 evaluation workflow is:

```text
1. Start MQTT broker
2. Run basic publisher/subscriber examples
3. Run static policy scenario
4. Run observation-driven policy scenario
5. Run rejected policy feedback scenario
6. Run all v1.0.0 scenarios
7. Aggregate controller-side analysis results
8. Export evaluation summaries to CSV and JSON
9. Generate paper-ready tables and figures
```

### Static Policy Scenario

```bash
RUN_ID=run-v100-static ./experiments/run_static_policy.sh
```

### Observation-Driven Policy Scenario

```bash
RUN_ID=run-v100-observation ./experiments/run_observation_policy.sh
```

### Rejected Policy Feedback Scenario

```bash
RUN_ID=run-v100-rejected ./experiments/run_rejected_policy_feedback.sh
```

### All v1.0.0 Scenarios

```bash
RUN_ID=run-v100-final ./experiments/run_all_v100_scenarios.sh
```

### Collect v1.0.0 Evaluation Tables

```bash
RUN_ID=run-v100-final ./experiments/collect_v100_evaluation_table.sh
```

### v1.1.0 Runtime Trust Scenarios

v1.1.0 includes a broker-independent runtime trust scenario runner.

```bash
RUN_ID=run-v110-trust-scenarios-001 ./experiments/run_v110_trust_scenarios.sh
```

Expected summary:

```text
accepted: 1
rejected: 4
total: 5
reason_code:
  OK: 1
  PADDING_TOO_LARGE: 1
  POLICY_SIGNATURE_INVALID: 1
  REVOKED_SIGNING_KEY: 1
  UNKNOWN_SIGNING_KEY: 1
```

The scenario runner generates the following artifacts under `results/<run_id>/`.

```text
control_ack_summary.csv
control_ack_summary.json
controller_anomaly_report.csv
controller_anomaly_report.json
v110_trust_scenario_summary.json
```

### v1.2.0 Multi-Signature and Transparency Scenarios

v1.2.0 includes a broker-independent runtime scenario runner for
multi-signature policy authorization and transparency-log verification.

```bash
RUN_ID=run-v120-multisig-transparency-001 \
./experiments/run_v120_multisig_transparency_scenarios.sh

RUN_ID=run-v120-multisig-transparency-001 \
./experiments/collect_v120_release_table.sh
```

Expected summary:

```text
accepted: 1
rejected: 5
total: 6
reason_code:
  OK: 1
  MULTISIG_REQUIRED_ROLE_MISSING: 1
  MULTISIG_THRESHOLD_NOT_MET: 1
  PADDING_TOO_LARGE: 1
  POLICY_SIGNATURE_INVALID: 1
  REVOKED_SIGNING_KEY: 1
transparency_log:
  accepted: true
  verified_entries: 6
  reason_code: OK
```

The scenario runner generates the following artifacts under `results/<run_id>/`.

```text
control_ack_summary.csv
control_ack_summary.json
controller_anomaly_report.csv
controller_anomaly_report.json
policy_transparency_log.jsonl
transparency_log_verification.json
v120_multisig_transparency_summary.json
v120_release_table.csv
```

### v1.2.1 Evaluation Reproducibility Workflow

v1.2.1 includes a one-command evaluation workflow that reruns the v1.1.0 and
v1.2.0 security scenarios and generates paper-ready comparison tables.

```bash
RUN_ID=run-v121-evaluation-reproducibility-001 \
./experiments/run_v121_security_evolution.sh
```

Expected summary:

```text
159 passed

v1.1.0 scenario:
  accepted: 1
  rejected: 4
  total: 5

v1.2.0 scenario:
  accepted: 1
  rejected: 5
  total: 6
  transparency_log.accepted: true
  transparency_log.verified_entries: 6
```

The workflow generates the following paper-ready artifacts under `results/<run_id>/`.

```text
security_evolution_table.csv
security_evolution_table.json
policy_decision_matrix.csv
policy_decision_matrix.json
paper_summary_table.csv
paper_summary_table.json
v121_evaluation_manifest.json
```

### v1.3.0 Large-Scale Evaluation Planning Workflow

v1.3.0 includes a safe evaluation planning workflow for large-scale,
adversarial, public broker, mdx, and Starlink scenarios.

```bash
RUN_ID=run-v130-large-scale-evaluation-001 \
./experiments/run_v130_evaluation.sh
```

This workflow does not generate high-rate network traffic by default. It
generates scenario plans, safety matrices, and release tables.

Expected summary:

```text
162 passed
scenario_count: 10
environment_count: 4
planned_logical_messages: 90010
planned_expected_mqtt_messages: 91013
planned_control_messages: 7500
planned_transparency_entries: 7500
public_broker_allowed_scenarios: 1
public_broker_disallowed_scenarios: 9
```

The workflow generates the following artifacts under `results/<run_id>/`.

```text
large_scale_scenario_plan.csv
large_scale_scenario_plan.json
environment_safety_matrix.csv
environment_safety_matrix.json
v130_large_scale_summary.json
v130_release_table.csv
v130_release_table.json
v130_evaluation_manifest.json
```

### v1.3.1 Local Broker Measurement Workflow

v1.3.1 includes a local broker measurement runner and unified comparison table
workflow.

Sample-mode validation:

```bash
RUN_ID=run-v131-local-measurements-001 \
MODE=sample \
./experiments/run_v131_local_measurements.sh
```

Plain MQTT local measurement:

```bash
python experiments/run_v131_plain_mqtt_measurement.py \
  --run-id run-v131-plain-local-6000-001 \
  --broker localhost \
  --port 1883 \
  --count 6000 \
  --qos 1 \
  --raw-csv results/run-v131-plain-local-6000-001/raw/plain_mqtt_baseline.csv \
  --summary-json results/run-v131-plain-local-6000-001/summaries/plain_mqtt_baseline.json
```

AOMQTT measurement collection:

```bash
python experiments/collect_v131_aomqtt_measurement.py \
  --run-id run-v131-aomqtt-basic-6000-001 \
  --scenario-id aomqtt_basic \
  --publisher-csv results/run-v131-aomqtt-basic-6000-001/raw/publisher_metrics.csv \
  --subscriber-csv results/run-v131-aomqtt-basic-6000-001/raw/subscriber_metrics.csv \
  --summary-json results/run-v131-aomqtt-basic-6000-001/summaries/aomqtt_basic.json
```

Local comparison table generation:

```bash
python experiments/collect_v131_local_comparison_table.py
```

The current local comparison includes:

```text
plain_mqtt_baseline
aomqtt_basic
aomqtt_padding512
aomqtt_padding512_rotation30_overlap5
```

Current measured comparison summary:

```text
plain_mqtt_baseline:
  logical_messages: 6000
  mqtt_messages: 6000
  delivery_latency_ms_p95: 1.2118816375732422
  publish_complete_ms_p95: 1.3044169172644615

aomqtt_basic:
  logical_messages: 6000
  mqtt_messages: 6000
  delivery_latency_ms_p95: 1.3301372528076172
  publish_complete_ms_p95: 1.2691658921539783
  payload_encrypted_bytes_avg: 216.044

aomqtt_padding512:
  logical_messages: 6000
  mqtt_messages: 6000
  delivery_latency_ms_p95: 1.1518001556396484
  publish_complete_ms_p95: 1.11008295789361
  payload_encrypted_bytes_avg: 802.0

aomqtt_padding512_rotation30_overlap5:
  logical_messages: 6000
  mqtt_messages: 9880
  delivery_latency_ms_p95: 1.8122196197509766
  publish_complete_ms_p95: 1.2501669116318226
  payload_encrypted_bytes_avg: 802.0
  duplicate_ratio_vs_logical: 0.532
  mqtt_expansion_ratio: 1.6466666666666667
```

The workflow generates:

```text
results/run-v131-local-comparison-6000-001/unified_measurements.csv
results/run-v131-local-comparison-6000-001/v131_local_comparison_table.csv
results/run-v131-local-comparison-6000-001/v131_local_comparison_summary.json
results/run-v131-local-comparison-6000-001/v131_local_comparison_manifest.json
```

### v1.3.2 Repeated-Trial Statistics Workflow

v1.3.2 aggregates repeated v1.3.1 local comparison trials and generates
statistical summaries.

Sample-mode validation:

```bash
RUN_ID=run-v132-repeated-trials-001 \
TRIAL_COUNT=5 \
./experiments/run_v132_repeated_trials.sh
```

This sample workflow does not send network traffic. It generates deterministic
trial inputs and validates the statistics pipeline.

For real repeated trials, pass measured v1.3.1 comparison tables:

```bash
python experiments/collect_v132_repeated_trial_statistics.py \
  --inputs \
    results/run-v131-local-comparison-trial-01/v131_local_comparison_table.csv \
    results/run-v131-local-comparison-trial-02/v131_local_comparison_table.csv \
    results/run-v131-local-comparison-trial-03/v131_local_comparison_table.csv \
  --out-dir results/run-v132-repeated-trials-real-001
```

The workflow generates:

```text
results/run-v132-repeated-trials-001/repeated_trial_measurements.csv
results/run-v132-repeated-trials-001/repeated_trial_statistics.csv
results/run-v132-repeated-trials-001/v132_paper_statistics_table.csv
results/run-v132-repeated-trials-001/v132_repeated_trial_summary.json
results/run-v132-repeated-trials-001/v132_repeated_trials_manifest.json
```

Current sample-mode validation summary:

```text
trial_file_count: 5
measurement_row_count: 20
scenario_count: 4
scenarios:
  plain_mqtt_baseline
  aomqtt_basic
  aomqtt_padding512
  aomqtt_padding512_rotation30_overlap5
```

### v1.3.3 Real Repeated Local Trials Workflow

v1.3.3 automates real local broker trials and repeated-trial statistics.

Dry-run validation:

```bash
RUN_ID=run-v133-real-local-repeated-001 \
TRIAL_COUNT=3 \
COUNT=100 \
EXECUTE=0 \
./experiments/run_v133_real_repeated_trials.sh
```

Execute-mode smoke test:

```bash
RUN_ID=run-v133-real-local-repeated-smoke-clientid-001 \
TRIAL_COUNT=2 \
COUNT=100 \
EXECUTE=1 \
./experiments/run_v133_real_repeated_trials.sh
```

Recommended paper-scale local repeated trial:

```bash
RUN_ID=run-v133-real-local-repeated-6000-001 \
TRIAL_COUNT=5 \
COUNT=6000 \
EXECUTE=1 \
./experiments/run_v133_real_repeated_trials.sh
```

The v1.3.3 automation generates:

```text
results/<run_id>/trials/trial-01/v131_local_comparison_table.csv
results/<run_id>/trials/trial-02/v131_local_comparison_table.csv
results/<run_id>/statistics/v132_paper_statistics_table.csv
results/<run_id>/v133_repeated_trials_manifest.json
```

The v1.3.3 runner explicitly assigns different MQTT client IDs to Publisher and
Subscriber to avoid connection replacement by the broker.

```text
subscriber client_id: <run_id>-<scenario>-subscriber
publisher client_id:  <run_id>-<scenario>-publisher
```

Current execute-mode smoke result:

```text
aomqtt_basic:
  delivery_p95_mean_ms: 1.6754865646362305
  success_ratio_mean: 1.0

aomqtt_padding512:
  delivery_p95_mean_ms: 2.1430253982543945
  success_ratio_mean: 1.0

aomqtt_padding512_rotation30_overlap5:
  delivery_p95_mean_ms: 1.9794702529907227
  success_ratio_mean: 1.0

plain_mqtt_baseline:
  delivery_p95_mean_ms: 1.9165277481079102
  success_ratio_mean: 1.0
```

Short-interval rotation validation:

```text
logical_messages: 300
mqtt_messages: 412
success_messages: 300
failed_messages: 0
duplicates: 104
rotation_overlap_duplicates: 112
delivery_latency_ms_p95: 5.485057830810547
publish_complete_ms_p95: 3.778790822252631
payload_encrypted_bytes_avg: 802.0
```

## Result Directory Format

Evaluation results should be stored under `results/<run_id>/`.

The recommended v1.0.0 result directory format is:

```text
results/<run_id>/
├── config/
│   └── experiment_config.yaml
├── raw/
│   ├── publisher_metrics.csv
│   ├── subscriber_metrics.csv
│   ├── controller_ack_log.csv
│   ├── controller_status_log.csv
│   └── controller_deployment_events.csv
├── derived/
│   ├── deployment_summary.csv
│   ├── deployment_summary.json
│   ├── ack_status_summary.csv
│   ├── reason_code_summary.csv
│   └── policy_comparison_summary.csv
├── paper/
│   ├── tables/
│   └── figures/
└── manifest.json
```

The `raw/` directory stores raw measurement logs.

The `derived/` directory stores aggregated summaries.

The `paper/` directory stores paper-ready tables and figures.

## Paper-Ready Assets

v1.0.0 provides scripts for generating paper-ready tables and figures.

```text
scripts/generate_paper_tables.py
scripts/generate_paper_figures.py
scripts/generate_paper_assets.py
```

Generate all paper-ready assets.

```bash
python scripts/generate_paper_assets.py \
  --results-dir results/run-v100-final
```

Generated assets are stored under:

```text
results/<run_id>/paper/
├── tables/
│   ├── table_policy_comparison.csv
│   ├── table_ack_status_summary.csv
│   └── table_reason_code_summary.csv
└── figures/
    ├── fig_ack_status_breakdown.png
    ├── fig_policy_result_comparison.png
    └── fig_reason_code_breakdown.png
```

## v1.3.3 Validation Commands

The following commands are recommended before creating the v1.3.3 release tag.

```bash
python -m pytest -q

RUN_ID=run-v133-real-local-repeated-001 \
TRIAL_COUNT=3 \
COUNT=100 \
EXECUTE=0 \
./experiments/run_v133_real_repeated_trials.sh

RUN_ID=run-v133-real-local-repeated-smoke-clientid-001 \
TRIAL_COUNT=2 \
COUNT=100 \
EXECUTE=1 \
./experiments/run_v133_real_repeated_trials.sh
```

The expected dry-run result is:

```text
173 passed
mode: dry-run
trial_count: 3
trial plan generated for trial-01, trial-02, and trial-03
```

The expected execute-mode smoke result is:

```text
173 passed
AOMQTT subscriber metrics contain received rows
delivery_p95_mean_ms is present for AOMQTT scenarios
success_ratio_mean = 1.0 for all scenarios
```

## v1.3.2 Validation Commands

The following commands are recommended before creating the v1.3.2 release tag.

```bash
python -m pytest -q

RUN_ID=run-v132-repeated-trials-001 \
TRIAL_COUNT=5 \
./experiments/run_v132_repeated_trials.sh
```

The expected test and sample workflow results are:

```text
170 passed
trial_file_count: 5
measurement_row_count: 20
scenario_count: 4
```

Generated artifacts include:

```text
repeated_trial_measurements.csv
repeated_trial_statistics.csv
v132_paper_statistics_table.csv
v132_repeated_trial_summary.json
v132_repeated_trials_manifest.json
```

## v1.3.1 Validation Commands

The following commands are recommended before creating the v1.3.1 release tag.

```bash
python -m pytest -q

RUN_ID=run-v131-local-measurements-001 \
MODE=sample \
./experiments/run_v131_local_measurements.sh

python experiments/collect_v131_local_comparison_table.py
```

The expected test and sample workflow results are:

```text
168 passed
scenario_count: 5
total_logical_messages: 24006
total_mqtt_messages: 25003
total_duplicates: 1003
total_control_accepted: 1
total_control_rejected: 5
total_transparency_verified_entries: 6
```

The current measured local comparison contains four scenarios:

```text
plain_mqtt_baseline
aomqtt_basic
aomqtt_padding512
aomqtt_padding512_rotation30_overlap5
```

## v1.3.0 Validation Commands

The following commands are recommended before creating the v1.3.0 release tag.

```bash
python -m pytest -q

RUN_ID=run-v130-large-scale-evaluation-001 \
./experiments/run_v130_evaluation.sh
```

The expected test and scenario results are:

```text
162 passed
scenario_count: 10
environment_count: 4
planned_logical_messages: 90010
planned_expected_mqtt_messages: 91013
planned_control_messages: 7500
planned_transparency_entries: 7500
public_broker_allowed_scenarios: 1
public_broker_disallowed_scenarios: 9
```

Safety requirement:

```text
DoS-like and high-rate workloads are limited to local or explicitly authorized
environments. Public-broker evaluation is limited to low-rate compatibility
probing.
```

## v1.2.1 Validation Commands

The following commands are recommended before creating the v1.2.1 release tag.

```bash
python -m pytest -q

RUN_ID=run-v121-evaluation-reproducibility-001 \
./experiments/run_v121_security_evolution.sh
```

The expected test and scenario results are:

```text
159 passed
v1.1.0 scenario:
  accepted: 1
  rejected: 4
  total: 5

v1.2.0 scenario:
  accepted: 1
  rejected: 5
  total: 6
  transparency_log.accepted: true
  transparency_log.verified_entries: 6
```

The expected `paper_summary_table.csv` includes:

```text
unit_and_scenario_tests,159
v1.1.0_trust_scenario_total,5
v1.1.0_trust_scenario_rejected,4
v1.2.0_multisig_scenario_total,6
v1.2.0_multisig_scenario_rejected,5
v1.2.0_transparency_log_verified_entries,6
v1.2.0_transparency_log_result,True
```

## v1.2.0 Validation Commands

The following commands are recommended before creating the v1.2.0 release tag.

```bash
python -m pytest -q

RUN_ID=run-v120-multisig-transparency-001 \
./experiments/run_v120_multisig_transparency_scenarios.sh

RUN_ID=run-v120-multisig-transparency-001 \
./experiments/collect_v120_release_table.sh
```

The expected test and scenario results are:

```text
156 passed
accepted: 1
rejected: 5
total: 6
transparency_log:
  accepted: true
  verified_entries: 6
  reason_code: OK
```

## v1.1.0 Validation Commands

The following commands are recommended before creating the v1.1.0 release tag.

```bash
python -m pytest -q

RUN_ID=run-v110-trust-scenarios-001 ./experiments/run_v110_trust_scenarios.sh
```

The expected test and scenario results are:

```text
136 passed
accepted: 1
rejected: 4
total: 5
```

## v1.0.0 Validation Commands

The following commands are recommended before creating the v1.0.0 release tag.

```bash
python -m pytest

bash -n experiments/run_all_v100_scenarios.sh
bash -n experiments/collect_v100_evaluation_table.sh

python -m py_compile scripts/generate_paper_tables.py
python -m py_compile scripts/generate_paper_figures.py
python -m py_compile scripts/generate_paper_assets.py
```

Run the full v1.0.0 experiment workflow.

```bash
docker compose up -d

RUN_ID=run-v100-final ./experiments/run_all_v100_scenarios.sh

python scripts/generate_paper_assets.py \
  --results-dir results/run-v100-final
```

Check generated files.

```bash
find results/run-v100-final -maxdepth 4 -type f | sort
```

## Development Roadmap

### v0.9.2

Controller-side analysis enhancement.

- aggregate ACK/status/reason_code across clients and runs;
- export deployment summaries to CSV and JSON;
- compare accepted/rejected/applied/failed/timeout rates.

### v1.0.0

Research prototype stabilization.

- reorganize README for research use;
- add release checklist;
- clarify example and experiment execution order;
- standardize evaluation result format;
- organize v1.0.0 experiment orchestration scripts;
- organize paper-ready table and figure generation scripts;
- stabilize the repository for paper submission and reproducible evaluation.

### v1.1.0

Trusted policy delivery and key lifecycle hardening.

- add signed policy trust validation;
- add `signer_key_id` based trusted key checking;
- reject policies signed by unknown signing keys;
- reject policies signed by revoked signing keys;
- detect invalid policy signatures;
- preserve client-side Policy Guard rejection for unsafe policies;
- generate runtime trust scenario summaries and anomaly reports.

### v1.2.0

Multi-signature policy authorization and transparency-log-based policy auditability.

- add multi-signature policy envelopes;
- add threshold-based policy authorization;
- add role-based signer validation;
- integrate KRL-aware multi-signature verification;
- reject policies with insufficient valid signatures;
- reject policies missing required signer roles;
- reject policies signed by revoked keys;
- record policy decisions in a hash-chain-based transparency log;
- verify transparency log integrity and export audit artifacts.

### v1.2.1

Evaluation reproducibility and paper-ready summaries.

- add a one-command security evolution evaluation workflow;
- generate a security evolution table for v1.0.2, v1.1.0, and v1.2.0;
- generate a policy decision matrix with expected decisions and reason codes;
- generate a compact paper summary table;
- document the paper evaluation plan and reproducibility workflow;
- stabilize tests for deterministic evaluation output.

### v1.3.0

Large-scale, DoS-safe, public broker, mdx, and Starlink evaluation planning.

- add a large-scale scenario plan generator;
- add an environment safety matrix;
- define public-broker compatibility probing limits;
- document mdx and Starlink evaluation plans;
- generate v1.3.0 release tables and evaluation manifests;
- separate high-rate local/authorized evaluation from public-broker compatibility probing.

### v1.3.1

Local broker measurement runner and comparison table.

- add a unified measurement CSV schema;
- add a plain MQTT local broker measurement helper;
- add AOMQTT measurement collection from publisher/subscriber metrics;
- add sample and collect modes for local measurement workflows;
- add a local comparison table collector;
- generate paper-ready local broker comparison tables.

### v1.3.2

Repeated trials and statistical summaries.

- add repeated-trial statistics collector;
- add deterministic sample trial generator;
- generate per-scenario mean, standard deviation, standard error, and 95% confidence intervals;
- generate paper-ready repeated-trial statistics table;
- aggregate MQTT expansion ratio, duplicate ratio, and success ratio;
- support real repeated-trial inputs from v1.3.1 comparison tables.

### v1.3.3

Real repeated local trial automation.

- add one-trial local measurement automation;
- add repeated local trial runner;
- add dry-run plan generation;
- add execute-mode repeated local trial workflow;
- integrate v1.3.1 local comparison table generation;
- integrate v1.3.2 repeated-trial statistics collection;
- enforce local broker safety by default;
- assign distinct MQTT client IDs to Publisher and Subscriber.

## Release Target

The v1.3.3 release is considered complete when:

- all tests pass;
- dry-run repeated local trial plan generation succeeds;
- execute-mode smoke test succeeds against a local broker;
- AOMQTT subscriber metrics contain received rows;
- AOMQTT delivery p95 is captured in repeated-trial statistics;
- success ratio remains 1.0 for successful local smoke scenarios;
- rotation/overlap behavior can be validated with short rotation interval settings;
- Publisher and Subscriber use distinct MQTT client IDs;
- README documents v1.3.3 real repeated local trial workflow and validation commands;
- release branch can be merged into `main`;
- Git tag `v1.3.3` can be created.

The v1.3.2 release is considered complete when:

- all tests pass;
- sample repeated-trial workflow succeeds;
- repeated-trial measurements can be aggregated;
- `repeated_trial_statistics.csv` can be generated;
- `v132_paper_statistics_table.csv` can be generated;
- mean, standard deviation, standard error, and 95% confidence interval fields are present;
- MQTT expansion ratio, duplicate ratio, and success ratio are aggregated;
- README documents v1.3.2 statistics workflow and validation commands;
- release branch can be merged into `main`;
- Git tag `v1.3.2` can be created.

The v1.3.1 release is considered complete when:

- all tests pass;
- sample-mode local measurement workflow succeeds;
- plain MQTT local measurement can be collected into the unified schema;
- AOMQTT basic, padding, and rotation measurements can be collected from publisher/subscriber CSVs;
- local comparison table can be generated;
- `v131_local_comparison_summary.json` reports measured comparison metrics;
- README documents v1.3.1 measurement workflow and validation commands;
- release branch can be merged into `main`;
- Git tag `v1.3.1` can be created.

The v1.3.0 release is considered complete when:

- all tests pass;
- v1.3.0 evaluation workflow succeeds;
- `large_scale_scenario_plan.csv` can be generated;
- `environment_safety_matrix.csv` can be generated;
- `v130_release_table.csv` can be generated;
- public-broker scenarios are limited to low-rate compatibility probing;
- local/adversarial scenarios are marked as local or explicitly authorized only;
- mdx and Starlink evaluation plans are documented;
- README documents v1.3.0 evaluation workflow and validation commands;
- release branch can be merged into `main`;
- Git tag `v1.3.0` can be created.

The v1.2.1 release is considered complete when:

- all tests pass;
- v1.2.1 security evolution workflow succeeds;
- v1.1.0 and v1.2.0 scenarios are rerun from the v1.2.1 workflow;
- `security_evolution_table.csv` can be generated;
- `policy_decision_matrix.csv` can be generated;
- `paper_summary_table.csv` can be generated with the expected test count;
- `v121_evaluation_manifest.json` records generated artifacts;
- README documents the v1.2.1 evaluation workflow and validation commands;
- release branch can be merged into `main`;
- Git tag `v1.2.1` can be created.

The v1.2.0 release is considered complete when:

- all tests pass;
- v1.2.0 multi-signature runtime scenario passes;
- v1.2.0 release table can be generated;
- multi-signature threshold and required-role validation are verified;
- revoked signer, invalid signature, and unsafe policy cases are rejected;
- transparency log verification succeeds;
- ACK summary, anomaly report, transparency log, and release table are exported;
- README documents v1.2.0 features and validation commands;
- release branch can be merged into `main`;
- Git tag `v1.2.0` can be created.

The v1.0.0 release is considered complete when:

- all tests pass;
- README explains the research prototype clearly;
- examples can be executed in documented order;
- experiments can be executed in documented order;
- results are saved under a consistent `results/<run_id>/` structure;
- controller-side summaries are exported as CSV and JSON;
- paper-ready tables and figures can be generated reproducibly;
- release branch can be merged into `main`;
- Git tag `v1.0.0` can be created.

## v1.2.0 Multi-Signature Policy and Transparency Log

AOMQTT v1.2.0 extends the v1.1.0 trusted policy delivery model by adding
multi-signature policy authorization and transparency-log-based policy
auditability.

The purpose of v1.2.0 is to reduce reliance on a single Policy Controller
signing key. A control policy can require multiple valid signatures and
specific signer roles before it is accepted by a client-side processor.

### Main Features

v1.2.0 adds the following features:

- multi-signature policy envelope;
- threshold-based policy authorization;
- required signer role validation;
- KRL-aware multi-signature verification;
- rejection of policies with insufficient valid signatures;
- rejection of policies missing required signer roles;
- rejection of policies signed by revoked keys;
- rejection of policies with invalid signatures;
- integration with the existing client-side Policy Guard;
- hash-chain-based transparency log for policy decisions;
- transparency log verification for detecting tampering, deletion, or reordering;
- runtime scenario evaluation for multi-signature and transparency-log behavior.

### Runtime Multi-Signature and Transparency Scenarios

The v1.2.0 scenario runner verifies the following cases.

| Scenario | Expected result | Reason code |
|---|---|---|
| Valid multi-signature policy | accepted | `OK` |
| Insufficient valid signatures | rejected | `MULTISIG_THRESHOLD_NOT_MET` |
| Missing required signer role | rejected | `MULTISIG_REQUIRED_ROLE_MISSING` |
| Revoked signing key | rejected | `REVOKED_SIGNING_KEY` |
| Invalid signature | rejected | `POLICY_SIGNATURE_INVALID` |
| Unsafe padding policy | rejected | `PADDING_TOO_LARGE` |

Run:

```bash
RUN_ID=run-v120-multisig-transparency-001 \
./experiments/run_v120_multisig_transparency_scenarios.sh

RUN_ID=run-v120-multisig-transparency-001 \
./experiments/collect_v120_release_table.sh
```

Expected summary:

```text
accepted: 1
rejected: 5
total: 6
reason_code:
  OK: 1
  MULTISIG_REQUIRED_ROLE_MISSING: 1
  MULTISIG_THRESHOLD_NOT_MET: 1
  PADDING_TOO_LARGE: 1
  POLICY_SIGNATURE_INVALID: 1
  REVOKED_SIGNING_KEY: 1
transparency_log:
  accepted: true
  verified_entries: 6
  reason_code: OK
```

Generated artifacts:

```text
results/run-v120-multisig-transparency-001/control_ack_summary.csv
results/run-v120-multisig-transparency-001/control_ack_summary.json
results/run-v120-multisig-transparency-001/controller_anomaly_report.csv
results/run-v120-multisig-transparency-001/controller_anomaly_report.json
results/run-v120-multisig-transparency-001/policy_transparency_log.jsonl
results/run-v120-multisig-transparency-001/transparency_log_verification.json
results/run-v120-multisig-transparency-001/v120_multisig_transparency_summary.json
results/run-v120-multisig-transparency-001/v120_release_table.csv
```

### Release Validation

Before creating the v1.2.0 release tag, run:

```bash
python -m pytest -q

RUN_ID=run-v120-multisig-transparency-001 \
./experiments/run_v120_multisig_transparency_scenarios.sh

RUN_ID=run-v120-multisig-transparency-001 \
./experiments/collect_v120_release_table.sh
```

The current v1.2.0 validation result is:

```text
156 passed
accepted: 1
rejected: 5
total: 6
transparency_log:
  accepted: true
  verified_entries: 6
  reason_code: OK
```


## v1.2.1 Evaluation Reproducibility and Paper-Ready Summary

AOMQTT v1.2.1 adds evaluation reproducibility assets for paper writing.

This release does not add new security primitives. Instead, it organizes the
security evolution from v1.0.2 to v1.2.0 into reproducible, paper-ready tables.

### Main Features

v1.2.1 adds the following features:

- security evolution table generator;
- policy decision matrix generator;
- paper summary table generator;
- one-command security evolution evaluation runner;
- evaluation workflow documentation;
- paper evaluation plan documentation;
- automated tests for evaluation asset generation;
- stabilization of a padding-related test to avoid random ciphertext false positives.

### Evaluation Workflow

Run:

```bash
RUN_ID=run-v121-evaluation-reproducibility-001 \
./experiments/run_v121_security_evolution.sh
```

This workflow runs:

1. automated tests;
2. v1.1.0 trusted policy delivery scenario;
3. v1.2.0 multi-signature and transparency-log scenario;
4. security evolution table generation;
5. policy decision matrix generation;
6. paper summary table generation;
7. evaluation manifest generation.

### Generated Artifacts

```text
results/run-v121-evaluation-reproducibility-001/security_evolution_table.csv
results/run-v121-evaluation-reproducibility-001/security_evolution_table.json
results/run-v121-evaluation-reproducibility-001/policy_decision_matrix.csv
results/run-v121-evaluation-reproducibility-001/policy_decision_matrix.json
results/run-v121-evaluation-reproducibility-001/paper_summary_table.csv
results/run-v121-evaluation-reproducibility-001/paper_summary_table.json
results/run-v121-evaluation-reproducibility-001/v121_evaluation_manifest.json
```

### Current Validation Result

```text
159 passed

v1.1.0 scenario:
  accepted: 1
  rejected: 4
  total: 5

v1.2.0 scenario:
  accepted: 1
  rejected: 5
  total: 6
  transparency_log.accepted: true
  transparency_log.verified_entries: 6

paper_summary_table.csv:
  unit_and_scenario_tests: 159
  v1.1.0_trust_scenario_total: 5
  v1.1.0_trust_scenario_rejected: 4
  v1.2.0_multisig_scenario_total: 6
  v1.2.0_multisig_scenario_rejected: 5
  v1.2.0_transparency_log_verified_entries: 6
  v1.2.0_transparency_log_result: True
```


## v1.3.0 Large-Scale, DoS-Safe, Public Broker, mdx, and Starlink Evaluation

AOMQTT v1.3.0 adds a safe evaluation planning framework for large-scale,
adversarial, public broker, mdx, and Starlink experiments.

This release does not execute high-rate network traffic by default. Instead, it
generates reproducible scenario plans, safety matrices, and paper-ready release
tables for later execution in local or explicitly authorized environments.

### Safety Policy

DoS-like and high-rate workloads must be limited to local or explicitly
authorized environments.

Public broker evaluation is limited to low-rate compatibility probing. Public
brokers must not be used for DoS-like workloads, policy storms, ACK storms,
high-rate throughput experiments, or large-scale fan-out tests.

### Main Features

v1.3.0 adds the following features:

- large-scale scenario plan generator;
- environment safety matrix;
- public broker safety policy documentation;
- mdx and Starlink evaluation plan;
- v1.3.0 release table collector;
- one-command v1.3.0 evaluation runner;
- tests for v1.3.0 evaluation assets.

### Evaluation Workflow

Run:

```bash
RUN_ID=run-v130-large-scale-evaluation-001 \
./experiments/run_v130_evaluation.sh
```

This workflow runs:

1. automated tests;
2. large-scale scenario plan generation;
3. environment safety matrix generation;
4. v1.3.0 release table generation;
5. evaluation manifest generation.

### Generated Artifacts

```text
results/run-v130-large-scale-evaluation-001/large_scale_scenario_plan.csv
results/run-v130-large-scale-evaluation-001/large_scale_scenario_plan.json
results/run-v130-large-scale-evaluation-001/environment_safety_matrix.csv
results/run-v130-large-scale-evaluation-001/environment_safety_matrix.json
results/run-v130-large-scale-evaluation-001/v130_large_scale_summary.json
results/run-v130-large-scale-evaluation-001/v130_release_table.csv
results/run-v130-large-scale-evaluation-001/v130_release_table.json
results/run-v130-large-scale-evaluation-001/v130_evaluation_manifest.json
```

### Current Validation Result

```text
162 passed
scenario_count: 10
environment_count: 4
planned_logical_messages: 90010
planned_expected_mqtt_messages: 91013
planned_control_messages: 7500
planned_transparency_entries: 7500
public_broker_allowed_scenarios: 1
public_broker_disallowed_scenarios: 9
```


## v1.3.1 Local Broker Measurement Runner and Comparison Table

AOMQTT v1.3.1 adds a local broker measurement runner and a unified measurement
CSV schema.

The purpose of v1.3.1 is to connect the v1.3.0 evaluation plan to actual local
broker measurements and paper-ready local comparison tables.

### Main Features

v1.3.1 adds the following features:

- unified measurement schema;
- plain MQTT local broker measurement helper;
- deterministic sample measurement workflow;
- AOMQTT measurement collector for publisher/subscriber metrics;
- measurement table collector;
- local comparison table generator;
- paper-ready local broker comparison summary.

### Measured Local Broker Comparison

The current local broker comparison uses 6000 logical messages per data-plane
scenario.

| Scenario | Logical messages | MQTT messages | Success | Duplicates | Delivery p95 ms | Publish p95 ms | Encrypted payload avg |
|---|---:|---:|---:|---:|---:|---:|---:|
| plain_mqtt_baseline | 6000 | 6000 | 6000 | 0 | 1.2118816375732422 | 1.3044169172644615 | |
| aomqtt_basic | 6000 | 6000 | 6000 | 0 | 1.3301372528076172 | 1.2691658921539783 | 216.044 |
| aomqtt_padding512 | 6000 | 6000 | 6000 | 0 | 1.1518001556396484 | 1.11008295789361 | 802.0 |
| aomqtt_padding512_rotation30_overlap5 | 6000 | 9880 | 6000 | 3192 | 1.8122196197509766 | 1.2501669116318226 | 802.0 |

For the rotation scenario:

```text
mqtt_expansion_ratio = 9880 / 6000 = 1.6466666666666667
duplicate_ratio_vs_logical = 3192 / 6000 = 0.532
```

### Validation

```bash
python -m pytest -q

RUN_ID=run-v131-local-measurements-001 \
MODE=sample \
./experiments/run_v131_local_measurements.sh

python experiments/collect_v131_local_comparison_table.py
```

The current validation result is:

```text
168 passed
```

Generated local comparison artifacts:

```text
results/run-v131-local-comparison-6000-001/unified_measurements.csv
results/run-v131-local-comparison-6000-001/v131_local_comparison_table.csv
results/run-v131-local-comparison-6000-001/v131_local_comparison_summary.json
results/run-v131-local-comparison-6000-001/v131_local_comparison_manifest.json
```


## v1.3.2 Repeated Trials and Statistical Summaries

AOMQTT v1.3.2 adds repeated-trial statistics for v1.3.1 local broker measurement
results.

The purpose of v1.3.2 is to make local broker evaluation more suitable for
paper submission by aggregating multiple measurement trials into statistical
summaries.

### Main Features

v1.3.2 adds the following features:

- repeated-trial statistics collector;
- deterministic sample trial generator;
- one-command sample repeated-trial workflow;
- paper-ready repeated-trial statistics table;
- per-scenario mean, standard deviation, and standard error;
- approximate 95% confidence intervals;
- MQTT expansion ratio aggregation;
- duplicate ratio aggregation;
- success ratio aggregation.

### Sample-Mode Validation

```bash
RUN_ID=run-v132-repeated-trials-001 \
TRIAL_COUNT=5 \
./experiments/run_v132_repeated_trials.sh
```

Current validation result:

```text
170 passed
trial_file_count: 5
measurement_row_count: 20
scenario_count: 4
```

### Generated Artifacts

```text
results/run-v132-repeated-trials-001/repeated_trial_measurements.csv
results/run-v132-repeated-trials-001/repeated_trial_statistics.csv
results/run-v132-repeated-trials-001/v132_paper_statistics_table.csv
results/run-v132-repeated-trials-001/v132_repeated_trial_summary.json
results/run-v132-repeated-trials-001/v132_repeated_trials_manifest.json
```

### Real Repeated Trials

For real paper measurements, run the v1.3.1 local comparison workflow multiple
times and then aggregate the measured comparison tables:

```bash
python experiments/collect_v132_repeated_trial_statistics.py \
  --inputs \
    results/run-v131-local-comparison-trial-01/v131_local_comparison_table.csv \
    results/run-v131-local-comparison-trial-02/v131_local_comparison_table.csv \
    results/run-v131-local-comparison-trial-03/v131_local_comparison_table.csv \
  --out-dir results/run-v132-repeated-trials-real-001
```


## v1.3.3 Real Repeated Local Trial Automation

AOMQTT v1.3.3 automates real repeated local broker trials.

The release connects the v1.3.1 local measurement workflow and the v1.3.2
repeated-trial statistics workflow.

### Main Features

v1.3.3 adds the following features:

- one-trial local measurement automation;
- repeated local trial runner;
- dry-run plan generation;
- execute-mode local broker measurements;
- local-broker safety guard;
- automatic v1.3.1 local comparison table generation;
- automatic v1.3.2 repeated-trial statistics aggregation;
- explicit Publisher/Subscriber MQTT `client_id` separation.

### MQTT Client ID Isolation

A critical fix in v1.3.3 is that Publisher and Subscriber use distinct MQTT
client IDs.

Without this fix, a Publisher and Subscriber using the same default client ID
can replace each other at the broker, leaving subscriber metrics with only a CSV
header and no received messages.

v1.3.3 uses:

```text
subscriber client_id: <run_id>-<scenario>-subscriber
publisher client_id:  <run_id>-<scenario>-publisher
```

### Dry-Run Validation

```bash
RUN_ID=run-v133-real-local-repeated-001 \
TRIAL_COUNT=3 \
COUNT=100 \
EXECUTE=0 \
./experiments/run_v133_real_repeated_trials.sh
```

### Execute-Mode Smoke Test

```bash
RUN_ID=run-v133-real-local-repeated-smoke-clientid-001 \
TRIAL_COUNT=2 \
COUNT=100 \
EXECUTE=1 \
./experiments/run_v133_real_repeated_trials.sh
```

Current smoke result:

| Scenario | n | Delivery p95 mean ms | Publish p95 mean ms | Success ratio |
|---|---:|---:|---:|---:|
| plain_mqtt_baseline | 2 | 1.9165277481079102 | 1.9436669535934925 | 1.0 |
| aomqtt_basic | 2 | 1.6754865646362305 | 1.4811874134466052 | 1.0 |
| aomqtt_padding512 | 2 | 2.1430253982543945 | 1.8490625079721212 | 1.0 |
| aomqtt_padding512_rotation30_overlap5 | 2 | 1.9794702529907227 | 1.943395473062992 | 1.0 |

### Rotation/Overlap Validation

A short-interval rotation validation confirmed that overlap produces extra MQTT
messages and subscriber-side duplicates:

```text
logical_messages: 300
mqtt_messages: 412
success_messages: 300
failed_messages: 0
duplicates: 104
rotation_overlap_duplicates: 112
delivery_latency_ms_p95: 5.485057830810547
publish_complete_ms_p95: 3.778790822252631
payload_encrypted_bytes_avg: 802.0
```

### Recommended Paper-Scale Trial

```bash
RUN_ID=run-v133-real-local-repeated-6000-001 \
TRIAL_COUNT=5 \
COUNT=6000 \
EXECUTE=1 \
./experiments/run_v133_real_repeated_trials.sh
```


## License

This repository is intended for research and experimental development.

## v1.0.2 Security Hardening: Compromised Policy Controller

AOMQTT v1.0.2 strengthens client-side policy validation against compromised,
misconfigured, or malicious Policy Controllers.

AOMQTT does not fully trust the Policy Controller. The controller can propose
signed control policies, but each client independently verifies signatures,
sequence numbers, validity periods, key identifiers, and local safety
constraints before applying them.

Security-critical properties, such as payload encryption and topic
obfuscation, cannot be disabled by controller policies. If a policy violates
client-side security invariants or resource limits, the client rejects it,
reports a rejected ACK with a reason code, and continues using the
last-known-good safe policy. The client does not fall back to plain MQTT.

The Policy Controller must not hold payload encryption keys or topic HMAC keys.
It should only distribute signed control policies. This limits the impact of
Policy Controller compromise: even if the controller is compromised, it cannot
directly decrypt payloads or recover original MQTT topic names.

### Client-side Policy Guard

The v1.0.2 Policy Guard enforces local safety constraints, including:

- payload encryption must not be disabled
- topic obfuscation must not be disabled
- padding fixed size must not exceed the client-side maximum
- rotation interval must not be shorter than the client-side minimum
- rotation overlap must not exceed the client-side maximum
- policy lifetime must not exceed the client-side maximum
- token mode must be included in the client-side allowlist
- key identifiers must be trusted when a trust store is configured
- replayed or old sequence numbers are rejected

Rejected policies preserve traceability by reporting policy_id, sequence_no,
key_id, and reason_code whenever these fields can be extracted from the raw
policy payload.


## v1.1.0 Trusted Policy Delivery and Key Lifecycle Hardening

AOMQTT v1.1.0 extends the control-plane security model by adding trusted
policy delivery and key lifecycle hardening.

The main objective is to reduce trust in the Policy Controller and its signing
environment. A policy is accepted only when it is signed by a trusted signing
key, is not signed by a revoked key, has a valid signature, and also satisfies
the existing client-side safety constraints.

### Main Features

v1.1.0 adds the following features:

- signed policy trust validation;
- `signer_key_id` based trusted key checking;
- Key Revocation List based rejected policy handling;
- rejection of policies signed by unknown signing keys;
- rejection of policies signed by revoked signing keys;
- invalid policy signature detection;
- runtime trust scenario evaluation;
- controller-side ACK summary generation;
- controller anomaly report generation.

### Runtime Trust Scenarios

The v1.1.0 scenario runner verifies the following cases.

| Scenario | Expected result | Reason code |
|---|---|---|
| Trusted signed policy | accepted | `OK` |
| Unknown signing key | rejected | `UNKNOWN_SIGNING_KEY` |
| Revoked signing key | rejected | `REVOKED_SIGNING_KEY` |
| Invalid signature | rejected | `POLICY_SIGNATURE_INVALID` |
| Unsafe padding policy | rejected | `PADDING_TOO_LARGE` |

Run:

```bash
RUN_ID=run-v110-trust-scenarios-001 ./experiments/run_v110_trust_scenarios.sh
```

Expected summary:

```text
accepted: 1
rejected: 4
total: 5
reason_code:
  OK: 1
  PADDING_TOO_LARGE: 1
  POLICY_SIGNATURE_INVALID: 1
  REVOKED_SIGNING_KEY: 1
  UNKNOWN_SIGNING_KEY: 1
```

Generated artifacts:

```text
results/run-v110-trust-scenarios-001/control_ack_summary.csv
results/run-v110-trust-scenarios-001/control_ack_summary.json
results/run-v110-trust-scenarios-001/controller_anomaly_report.csv
results/run-v110-trust-scenarios-001/controller_anomaly_report.json
results/run-v110-trust-scenarios-001/v110_trust_scenario_summary.json
```

### Release Validation

Before creating the v1.1.0 release tag, run:

```bash
python -m pytest -q
RUN_ID=run-v110-trust-scenarios-001 ./experiments/run_v110_trust_scenarios.sh
```

The current v1.1.0 validation result is:

```text
136 passed
accepted: 1
rejected: 4
total: 5
```

