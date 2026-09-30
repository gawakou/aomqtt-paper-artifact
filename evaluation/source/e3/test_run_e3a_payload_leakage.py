from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "e3"
    / "run_e3a_payload_leakage.py"
)
GENERATOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "e3"
    / "generate_e3_event_plan.py"
)

# Load generator first under the sibling module name expected by the runner.
gen_spec = importlib.util.spec_from_file_location(
    "generate_e3_event_plan", GENERATOR_PATH
)
assert gen_spec is not None and gen_spec.loader is not None
gen = importlib.util.module_from_spec(gen_spec)
sys.modules[gen_spec.name] = gen
gen_spec.loader.exec_module(gen)

spec = importlib.util.spec_from_file_location(
    "run_e3a_payload_leakage", MODULE_PATH
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def make_small_plan(path: Path) -> None:
    events = gen.generate_e3a_events(
        run_index=1,
        seed=20261002,
        messages_per_class=2,
    )
    gen.write_e3a_csv(events, path)


def test_condition_prefixes_are_isolated():
    assert mod.condition_prefix("e3a-r01", "A0") == "e3/a/e3a-r01/A0"
    assert mod.observer_filter("e3a-r01", "A1") == "e3/a/e3a-r01/A1/#"
    assert mod.plain_topic("e3a-r01") == "e3/a/e3a-r01/A0/plain"


def test_load_plan_revalidates_schema_and_exact_payloads(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    make_small_plan(plan)
    events = mod.load_plan(plan)
    assert len(events) == 16
    assert events[0].event_index == 0
    assert events[-1].event_index == 15
    assert {e.class_id for e in events} == {f"C{i}" for i in range(1, 9)}


def test_load_plan_limit_is_deterministic_prefix(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    make_small_plan(plan)
    full = mod.load_plan(plan)
    limited = mod.load_plan(plan, limit_events=5)
    assert limited == full[:5]


def test_load_plan_rejects_wrong_schema(tmp_path: Path):
    plan = tmp_path / "bad.csv"
    plan.write_text("x,y\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected E3-A plan schema"):
        mod.load_plan(plan)


def test_observer_command_contains_condition_scoped_filter(tmp_path: Path):
    cmd = mod.build_observer_command(
        observer_script=Path("/repo/experiments/e3/e3_broker_observer.py"),
        broker="localhost",
        port=1883,
        run_id="e3a-r01",
        condition="A2",
        condition_dir=tmp_path / "A2",
    )
    assert "--filter" in cmd
    assert "e3/a/e3a-r01/A2/#" in cmd
    assert str(tmp_path / "A2" / "observer.csv") in cmd


def test_gate_passes_valid_full_A2_result():
    class_counts = {f"C{i}": 500 for i in range(1, 9)}
    gate = mod.evaluate_gate(
        condition="A2",
        expected_events=4000,
        full_formal_plan=True,
        class_counts=class_counts,
        publisher_success=4000,
        publisher_physical=4000,
        observer_summary={
            "row_count": 4000,
            "sequence_contiguous": True,
            "unique_payload_sizes": [802],
            "unique_payload_size_count": 1,
        },
        subscriber_total=4000,
        subscriber_unique=4000,
        decrypt_failed=0,
        duplicates=0,
    )
    assert gate["overall_pass"] is True
    assert gate["checks"]["fixed_padding_single_observed_size"] is True
    assert gate["checks"]["class_balance_500_each"] is True


def test_gate_fails_A2_if_payload_size_varies():
    gate = mod.evaluate_gate(
        condition="A2",
        expected_events=8,
        full_formal_plan=False,
        class_counts={f"C{i}": 1 for i in range(1, 9)},
        publisher_success=8,
        publisher_physical=8,
        observer_summary={
            "row_count": 8,
            "sequence_contiguous": True,
            "unique_payload_sizes": [802, 806],
            "unique_payload_size_count": 2,
        },
        subscriber_total=8,
        subscriber_unique=8,
        decrypt_failed=0,
        duplicates=0,
    )
    assert gate["overall_pass"] is False
    assert gate["checks"]["fixed_padding_single_observed_size"] is False


def test_gate_fails_on_decryption_failure():
    gate = mod.evaluate_gate(
        condition="A1",
        expected_events=10,
        full_formal_plan=False,
        class_counts={"C1": 10},
        publisher_success=10,
        publisher_physical=10,
        observer_summary={
            "row_count": 10,
            "sequence_contiguous": True,
            "unique_payload_sizes": [100, 120],
            "unique_payload_size_count": 2,
        },
        subscriber_total=10,
        subscriber_unique=9,
        decrypt_failed=1,
        duplicates=0,
    )
    assert gate["overall_pass"] is False
    assert gate["checks"]["decrypt_failures_zero"] is False
    assert gate["checks"]["subscriber_unique_equals_plan"] is False


def test_nonlocal_broker_requires_explicit_opt_in(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    make_small_plan(plan)
    with pytest.raises(SystemExit):
        mod.parse_args(
            [
                "--plan",
                str(plan),
                "--run-id",
                "e3a-r01",
                "--out-root",
                str(tmp_path / "out"),
                "--broker",
                "192.0.2.1",
                "--dry-run",
            ]
        )


def test_dry_run_writes_execution_plan_without_network(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    make_small_plan(plan)
    out = tmp_path / "out"
    rc = mod.main(
        [
            "--plan",
            str(plan),
            "--run-id",
            "e3a-r01",
            "--out-root",
            str(out),
            "--broker",
            "localhost",
            "--limit-events",
            "5",
            "--dry-run",
        ]
    )
    assert rc == 0
    payload = json.loads((out / "e3a_execution_plan.json").read_text())
    assert payload["mode"] == "dry-run"
    assert payload["event_count"] == 5
    assert payload["conditions"] == ["A0", "A1", "A2"]
    assert payload["aomqtt_base_commit"] == mod.AOMQTT_BASE_COMMIT


def test_pacing_summary_distinguishes_scheduler_lateness_from_slot_miss():
    events = [
        mod.PlanEvent(i, i * 10_000_000, f"m{i}", "C1", "e3/payload", 80)
        for i in range(4)
    ]
    summary = mod.summarize_pacing(
        [100_000, 200_000, 0, 9_999_999],
        events,
    )
    assert summary["late_event_count"] == 3
    assert summary["slot_miss_count"] == 0
    assert summary["nominal_interval_ms"] == 10.0


def test_pacing_summary_counts_one_full_interval_as_slot_miss():
    events = [
        mod.PlanEvent(i, i * 10_000_000, f"m{i}", "C1", "e3/payload", 80)
        for i in range(3)
    ]
    summary = mod.summarize_pacing(
        [100_000, 10_000_000, 11_000_000],
        events,
    )
    assert summary["slot_miss_count"] == 2
