# AOMQTT v1.0.0 Experiment Workflow

This document defines the recommended execution order of examples and experiments for AOMQTT Client SDK v1.0.0.

The goal is to make the evaluation workflow reproducible for research papers, technical reports, and release validation.

## 1. Purpose

AOMQTT v1.0.0 is organized as a reproducible research prototype.

The workflow is divided into two levels:

1. examples: small commands for confirming basic behavior;
2. experiments: reproducible evaluation scenarios that save results under `results/<run_id>/`.

The recommended order is:

```text
1. Prepare environment
2. Start MQTT broker
3. Run basic examples
4. Run policy-related examples
5. Run individual experiment scenarios
6. Run all experiment scenarios
7. Aggregate evaluation results
8. Generate paper-ready assets
```

## 2. Prerequisites

Create and activate a Python virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies.

```bash
pip install -r requirements.txt
pip install -e .
```

Run tests before starting experiments.

```bash
python -m pytest
```

## 3. Start MQTT Broker

Start the local MQTT broker.

```bash
docker compose up -d
```

Confirm that the broker is running.

```bash
docker compose ps
```

If needed, stop the broker with:

```bash
docker compose down
```

## 4. Example Execution Order

Examples are intended to verify that basic AOMQTT functions work before running the full evaluation workflow.

Recommended order:

```text
1. subscriber_example.py
2. publisher_example.py
3. show_effective_policy.py
4. policy_auto_controller.py
```

### 4.1 Basic Subscriber

Start the subscriber first.

```bash
python examples/subscriber_example.py \
  --broker localhost \
  --topic shelter/siteA/starlink/rtt \
  --qos 1
```

Keep this process running in one terminal.

### 4.2 Basic Publisher

In another terminal, run the publisher.

```bash
python examples/publisher_example.py \
  --broker localhost \
  --topic shelter/siteA/starlink/rtt \
  --count 20 \
  --interval 1 \
  --qos 1 \
  --metrics-csv results/basic_publisher_metrics.csv
```

Expected behavior:

- the subscriber receives messages;
- the publisher completes without error;
- the metrics CSV file is created.

### 4.3 Show Effective Policy

Use this command to confirm the effective policy configuration.

```bash
python examples/show_effective_policy.py
```

Expected behavior:

- the current effective policy is displayed;
- sensitive key values are not exposed directly.

### 4.4 Policy Auto Controller

Run the policy controller example after confirming publisher/subscriber behavior.

```bash
python examples/policy_auto_controller.py
```

Expected behavior:

- the controller publishes control policies;
- clients can accept, reject, or apply policies depending on policy content and validation results;
- ACK/status behavior can be observed through the control-plane topics.

## 5. Experiment Scenario Order

Experiments are intended to produce reproducible outputs under `results/<run_id>/`.

The recommended v1.0.0 scenario order is:

```text
1. Static policy scenario
2. Observation-driven policy scenario
3. Rejected policy feedback scenario
4. All scenarios
5. Evaluation table collection
```

## 6. Run Individual Scenarios

### 6.1 Static Policy Scenario

This scenario evaluates AOMQTT behavior under a fixed policy.

```bash
RUN_ID=run-v100-static ./experiments/run_static_policy.sh
```

Expected output:

```text
results/run-v100-static/
```

### 6.2 Observation-Driven Policy Scenario

This scenario evaluates policy control based on observed behavior.

```bash
RUN_ID=run-v100-observation ./experiments/run_observation_policy.sh
```

Expected output:

```text
results/run-v100-observation/
```

### 6.3 Rejected Policy Feedback Scenario

This scenario evaluates how rejected policies are reported to the controller.

```bash
RUN_ID=run-v100-rejected ./experiments/run_rejected_policy_feedback.sh
```

Expected output:

```text
results/run-v100-rejected/
```

The rejected policy feedback scenario should confirm that rejected ACKs contain traceable information such as:

- policy ID;
- sequence number;
- reason code;
- client ID;
- timestamp.

## 7. Run All Scenarios

After confirming the individual scenarios, run the full v1.0.0 workflow.

```bash
RUN_ID=run-v100-final ./experiments/run_all_v100_scenarios.sh
```

Expected output:

```text
results/run-v100-final/
```

The all-scenario script should run the following scenarios in order:

```text
1. static_policy
2. observation_policy
3. rejected_policy_feedback
```

## 8. Collect Evaluation Tables

After running the scenarios, collect derived evaluation tables.

```bash
RUN_ID=run-v100-final ./experiments/collect_v100_evaluation_table.sh
```

Expected output examples:

```text
results/run-v100-final/derived/deployment_summary.csv
results/run-v100-final/derived/deployment_summary.json
results/run-v100-final/derived/ack_status_summary.csv
results/run-v100-final/derived/reason_code_summary.csv
results/run-v100-final/derived/policy_comparison_summary.csv
```

## 9. Generate Paper-Ready Assets

After result collection, generate paper-ready tables and figures.

```bash
python scripts/generate_paper_assets.py \
  --results-dir results/run-v100-final
```

Expected output:

```text
results/run-v100-final/paper/
├── tables/
│   ├── table_policy_comparison.csv
│   ├── table_ack_status_summary.csv
│   └── table_reason_code_summary.csv
└── figures/
    ├── fig_ack_status_breakdown.png
    ├── fig_policy_result_comparison.png
    └── fig_reason_code_breakdown.png
```

## 10. Recommended Full Command Sequence

The following command sequence is recommended for a clean v1.0.0 validation run.

```bash
python -m pytest

docker compose up -d

RUN_ID=run-v100-static ./experiments/run_static_policy.sh

RUN_ID=run-v100-observation ./experiments/run_observation_policy.sh

RUN_ID=run-v100-rejected ./experiments/run_rejected_policy_feedback.sh

RUN_ID=run-v100-final ./experiments/run_all_v100_scenarios.sh

RUN_ID=run-v100-final ./experiments/collect_v100_evaluation_table.sh

python scripts/generate_paper_assets.py \
  --results-dir results/run-v100-final
```

## 11. Result Validation

After running the workflow, check the result directory.

```bash
find results/run-v100-final -maxdepth 3 -type f | sort
```

Recommended checks:

```bash
test -f results/run-v100-final/manifest.json
test -d results/run-v100-final/raw
test -d results/run-v100-final/derived
test -d results/run-v100-final/paper
test -d results/run-v100-final/paper/tables
test -d results/run-v100-final/paper/figures
```

## 12. Git Management

Generated result files should not be committed by default.

Before committing documentation or scripts, check:

```bash
git status
```

If generated result files appear unexpectedly, update `.gitignore`.

Recommended policy:

```text
results/*
!results/.gitkeep
```

## 13. v1.0.0 Workflow Completion Criteria

The workflow is complete when:

- basic examples run successfully;
- each experiment scenario runs successfully;
- the all-scenario script runs successfully;
- results are saved under `results/<run_id>/`;
- derived CSV/JSON summaries are generated;
- paper-ready tables and figures are generated;
- generated result files are not accidentally committed.
