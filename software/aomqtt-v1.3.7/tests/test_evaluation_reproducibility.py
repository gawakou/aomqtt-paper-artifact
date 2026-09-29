import csv
import json
from pathlib import Path

from aomqtt.evaluation import (
    DEFAULT_EXPERIMENT_ID,
    DEFAULT_RUN_ID,
    ExperimentContext,
    METRICS_SCHEMA_VERSION,
    generate_run_id,
    save_experiment_config,
)
from aomqtt.observation.csv_logger import PublishCSVLogger
from aomqtt.observation.delivery import DeliveryCSVLogger


class FakeMetric:
    def __init__(self, row):
        self._row = row

    def to_row(self):
        return dict(self._row)


def test_generate_run_id_has_run_prefix():
    run_id = generate_run_id()
    assert run_id.startswith("run-")


def test_experiment_context_defaults():
    context = ExperimentContext()

    assert context.experiment_id == DEFAULT_EXPERIMENT_ID
    assert context.run_id == DEFAULT_RUN_ID
    assert context.metrics_schema_version == METRICS_SCHEMA_VERSION


def test_experiment_context_as_dict():
    context = ExperimentContext(
        experiment_id="exp-test",
        run_id="run-test",
    )

    data = context.as_dict()

    assert data["experiment_id"] == "exp-test"
    assert data["run_id"] == "run-test"
    assert data["metrics_schema_version"] == METRICS_SCHEMA_VERSION


def test_save_experiment_config_json(tmp_path: Path):
    context = ExperimentContext(
        experiment_id="exp-test",
        run_id="run-test",
    )

    output = tmp_path / "experiment_config.json"

    save_experiment_config(
        output_path=output,
        context=context,
        config={
            "broker": "localhost",
            "topic": "shelter/siteA/starlink/rtt",
        },
    )

    assert output.exists()

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["experiment"]["experiment_id"] == "exp-test"
    assert data["experiment"]["run_id"] == "run-test"
    assert data["experiment"]["metrics_schema_version"] == METRICS_SCHEMA_VERSION
    assert data["config"]["broker"] == "localhost"


def test_publish_csv_logger_has_reproducibility_fields(tmp_path: Path):
    csv_path = tmp_path / "publisher_metrics.csv"

    with PublishCSVLogger(
        csv_path,
        experiment_id="exp-pub",
        run_id="run-pub",
    ) as logger:
        logger.write(
            FakeMetric(
                {
                    "timestamp": 1.0,
                    "client_id": "c_pub_001",
                    "policy_id": "p1",
                    "success": True,
                }
            )
        )

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["metrics_schema_version"] == str(METRICS_SCHEMA_VERSION)
    assert rows[0]["experiment_id"] == "exp-pub"
    assert rows[0]["run_id"] == "run-pub"


def test_delivery_csv_logger_has_reproducibility_fields(tmp_path: Path):
    csv_path = tmp_path / "subscriber_metrics.csv"

    with DeliveryCSVLogger(
        csv_path,
        experiment_id="exp-sub",
        run_id="run-sub",
    ) as logger:
        logger.write(
            FakeMetric(
                {
                    "timestamp": 1.0,
                    "client_id": "c_sub_001",
                    "policy_id": "p1",
                    "decrypt_success": True,
                }
            )
        )

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["metrics_schema_version"] == str(METRICS_SCHEMA_VERSION)
    assert rows[0]["experiment_id"] == "exp-sub"
    assert rows[0]["run_id"] == "run-sub"


def test_csv_schema_starts_with_reproducibility_fields():
    assert PublishCSVLogger.FIELDNAMES[:3] == [
        "metrics_schema_version",
        "experiment_id",
        "run_id",
    ]
    assert DeliveryCSVLogger.FIELDNAMES[:3] == [
        "metrics_schema_version",
        "experiment_id",
        "run_id",
    ]
