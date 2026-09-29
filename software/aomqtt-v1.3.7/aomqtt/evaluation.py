from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import json


METRICS_SCHEMA_VERSION = 2
DEFAULT_EXPERIMENT_ID = "exp-default"
DEFAULT_RUN_ID = "run-default"


def generate_run_id() -> str:
    return datetime.now().strftime("run-%Y%m%d-%H%M%S")


@dataclass(frozen=True)
class ExperimentContext:
    experiment_id: str = DEFAULT_EXPERIMENT_ID
    run_id: str = DEFAULT_RUN_ID
    metrics_schema_version: int = METRICS_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def save_experiment_config(
    *,
    output_path: str | Path,
    context: ExperimentContext,
    config: dict[str, Any],
) -> None:
    payload = {
        "experiment": context.as_dict(),
        "config": config,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.suffix in {".yaml", ".yml"}:
        try:
            import yaml

            output_path.write_text(
                yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            return
        except ModuleNotFoundError:
            pass

    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


REPRODUCIBILITY_FIELDS_V1 = [
    "metrics_schema_version",
    "experiment_id",
    "run_id",
]
