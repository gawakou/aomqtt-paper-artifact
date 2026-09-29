# AOMQTT v1.0.0 Release Checklist

This checklist defines the release criteria for AOMQTT Client SDK v1.0.0.

The goal of v1.0.0 is to stabilize AOMQTT as a reproducible research prototype for MQTT topic obfuscation, payload encryption, payload padding, token rotation, controller-driven policy delivery, observation-driven policy control, and paper-ready evaluation.

## 1. Branch and Version Management

- [ ] The development branch is `release/v1.0.0-research-prototype`.
- [ ] The branch is based on the latest `main`.
- [ ] v0.9.2 changes are already merged into `main`.
- [ ] The working tree is clean before starting each release step.
- [ ] The final release tag will be `v1.0.0`.

Recommended checks:

```bash
git branch --show-current
git status
git log --oneline --decorate -8
```

## 2. Code Quality

- [ ] All tests pass with `python -m pytest`.
- [ ] No temporary debug code remains.
- [ ] No temporary local files are tracked.
- [ ] Generated result files are not accidentally committed.
- [ ] Public interfaces required for v1.0.0 are stable.
- [ ] Existing v0.9.2 functionality remains compatible.

Recommended command:

```bash
python -m pytest
```

## 3. README

- [ ] `README.md` describes AOMQTT as a research prototype.
- [ ] `README.md` explains the research motivation.
- [ ] `README.md` explains key features.
- [ ] `README.md` explains the high-level architecture.
- [ ] `README.md` explains installation.
- [ ] `README.md` explains quick-start examples.
- [ ] `README.md` explains policy control.
- [ ] `README.md` explains observation-driven policy control.
- [ ] `README.md` explains the evaluation workflow.
- [ ] `README.md` explains the result directory format.
- [ ] `README.md` explains paper-ready table and figure generation.

## 4. Documentation

- [ ] `docs/release-checklist-v1.0.0.md` exists.
- [ ] `docs/experiment-workflow.md` exists.
- [ ] `docs/result-format.md` exists.
- [ ] Documentation clearly separates examples, experiments, results, and paper assets.
- [ ] Documentation uses the same terminology as the README.

Recommended documentation files:

```text
docs/
├── release-checklist-v1.0.0.md
├── experiment-workflow.md
└── result-format.md
```

## 5. Examples

- [ ] Basic subscriber example can be executed.
- [ ] Basic publisher example can be executed.
- [ ] Policy controller example can be executed.
- [ ] Effective policy display example can be executed.
- [ ] Example commands are documented in README.
- [ ] Example commands are documented in `docs/experiment-workflow.md`.

Recommended example order:

```text
1. subscriber_example.py
2. publisher_example.py
3. show_effective_policy.py
4. policy_auto_controller.py
```

## 6. Experiments

- [ ] Static policy scenario can be executed.
- [ ] Observation-driven policy scenario can be executed.
- [ ] Rejected policy feedback scenario can be executed.
- [ ] All scenarios can be executed by one script.
- [ ] Each experiment accepts `RUN_ID`.
- [ ] Each experiment saves outputs under `results/<run_id>/`.

Required experiment scripts:

```text
experiments/
├── common.sh
├── run_static_policy.sh
├── run_observation_policy.sh
├── run_rejected_policy_feedback.sh
├── run_all_v100_scenarios.sh
└── collect_v100_evaluation_table.sh
```

Recommended commands:

```bash
RUN_ID=run-v100-static ./experiments/run_static_policy.sh

RUN_ID=run-v100-observation ./experiments/run_observation_policy.sh

RUN_ID=run-v100-rejected ./experiments/run_rejected_policy_feedback.sh

RUN_ID=run-v100-final ./experiments/run_all_v100_scenarios.sh
```

## 7. Result Directory Format

- [ ] Each run is saved under `results/<run_id>/`.
- [ ] Raw logs are saved under `raw/`.
- [ ] Aggregated outputs are saved under `derived/`.
- [ ] Paper-ready outputs are saved under `paper/`.
- [ ] Experiment configuration is saved under `config/`.
- [ ] A manifest file is generated as `manifest.json`.

Required structure:

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

## 8. Controller-Side Analysis

- [ ] ACK results are aggregated.
- [ ] Status results are aggregated.
- [ ] Reason codes are aggregated.
- [ ] Deployment summaries are exported to CSV.
- [ ] Deployment summaries are exported to JSON.
- [ ] Accepted, rejected, applied, failed, expired, invalid, and timeout cases are distinguishable.
- [ ] Rejected policies can be traced using `policy_id` and `sequence_no` where possible.

Expected derived files:

```text
derived/
├── deployment_summary.csv
├── deployment_summary.json
├── ack_status_summary.csv
├── reason_code_summary.csv
└── policy_comparison_summary.csv
```

## 9. Paper-Ready Tables and Figures

- [ ] `scripts/generate_paper_tables.py` exists.
- [ ] `scripts/generate_paper_figures.py` exists.
- [ ] `scripts/generate_paper_assets.py` exists.
- [ ] Paper-ready tables are generated under `results/<run_id>/paper/tables/`.
- [ ] Paper-ready figures are generated under `results/<run_id>/paper/figures/`.
- [ ] Tables are generated in CSV format.
- [ ] Figures are generated in PNG format.
- [ ] Scripts can be executed from the repository root.

Recommended command:

```bash
python scripts/generate_paper_assets.py \
  --results-dir results/run-v100-final
```

Expected output:

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

## 10. Git Ignore Policy

- [ ] Generated result files are ignored.
- [ ] Python cache files are ignored.
- [ ] Virtual environments are ignored.
- [ ] Temporary local files are ignored.
- [ ] `results/.gitkeep` may be tracked if needed.
- [ ] Paper-ready sample outputs are not committed unless intentionally selected.

Recommended `.gitignore` entries:

```text
.venv/
__pycache__/
.pytest_cache/
.DS_Store
results/*
!results/.gitkeep
```

## 11. Final Validation

Before creating the v1.0.0 tag, run:

```bash
python -m pytest

RUN_ID=run-v100-final ./experiments/run_all_v100_scenarios.sh

python scripts/generate_paper_assets.py \
  --results-dir results/run-v100-final

git status
```

The release is ready when:

- [ ] Tests pass.
- [ ] Evaluation scenarios complete.
- [ ] Result directories are generated correctly.
- [ ] Paper-ready assets are generated correctly.
- [ ] No unintended generated files are staged.
- [ ] Documentation is complete.

## 12. Release Tag

After final validation:

```bash
git checkout main
git merge release/v1.0.0-research-prototype
git tag -a v1.0.0 -m "Release AOMQTT Client SDK v1.0.0"
git push origin main
git push origin v1.0.0
```

## 13. v1.0.0 Completion Criteria

AOMQTT v1.0.0 is complete when:

- README is reorganized for v1.0.0.
- Release checklist is available.
- Example and experiment execution order is documented.
- Evaluation result format is standardized.
- Paper-ready table and figure generation workflow is available.
- Tests pass.
- Results can be reproduced under `results/<run_id>/`.
- A GitHub release tag `v1.0.0` can be created.
