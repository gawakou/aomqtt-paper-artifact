from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "e3"
    / "generate_e3_event_plan.py"
)
SPEC = importlib.util.spec_from_file_location("generate_e3_event_plan", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_payload_constructor_hits_requested_length():
    for seq, target in [(0, 64), (1, 80), (17, 170), (3999, 440)]:
        payload = mod.build_exact_payload(
            message_id=f"e3a-r01-{seq:06d}",
            seq=seq,
            target_plain_bytes=target,
        )
        assert len(mod.compact_json_bytes(payload)) == target
        assert set(payload) == {"message_id", "seq", "blob"}
        assert "class_id" not in payload
        assert "logical_topic" not in payload


def test_exact_payload_constructor_rejects_too_small_target():
    with pytest.raises(ValueError):
        mod.build_exact_payload(
            message_id="e3a-r01-000000",
            seq=0,
            target_plain_bytes=1,
        )


def test_e3a_default_count_balance_pacing_and_exact_sizes():
    events = mod.generate_e3a_events(run_index=1, seed=20261002)

    assert len(events) == 8 * 500
    assert Counter(e.class_id for e in events) == {
        f"C{i}": 500 for i in range(1, 9)
    }
    assert {e.logical_topic for e in events} == {"e3/payload"}
    assert [e.event_index for e in events] == list(range(4000))
    assert events[0].relative_time_ns == 0
    assert events[-1].relative_time_ns == 3999 * 10_000_000

    for i, e in enumerate(events):
        assert e.relative_time_ns == i * 10_000_000
        assert 64 <= e.target_plain_bytes <= 440
        payload = mod.build_exact_payload(
            message_id=e.message_id,
            seq=e.event_index,
            target_plain_bytes=e.target_plain_bytes,
        )
        assert len(mod.compact_json_bytes(payload)) == e.target_plain_bytes


def test_e3a_same_seed_is_byte_reproducible(tmp_path: Path):
    events1 = mod.generate_e3a_events(run_index=3, seed=20261004)
    events2 = mod.generate_e3a_events(run_index=3, seed=20261004)
    p1 = tmp_path / "one.csv"
    p2 = tmp_path / "two.csv"
    mod.write_e3a_csv(events1, p1)
    mod.write_e3a_csv(events2, p2)

    assert p1.read_bytes() == p2.read_bytes()
    assert sha256(p1) == sha256(p2)


def test_e3a_different_seed_changes_plan():
    events1 = mod.generate_e3a_events(run_index=1, seed=100)
    events2 = mod.generate_e3a_events(run_index=1, seed=101)
    assert events1 != events2


def test_e3b_same_seed_is_byte_reproducible_and_sorted(tmp_path: Path):
    events1 = mod.generate_e3b_events(run_index=2, seed=20261103)
    events2 = mod.generate_e3b_events(run_index=2, seed=20261103)
    p1 = tmp_path / "one.csv"
    p2 = tmp_path / "two.csv"
    mod.write_e3b_csv(events1, p1)
    mod.write_e3b_csv(events2, p2)

    assert p1.read_bytes() == p2.read_bytes()
    assert sha256(p1) == sha256(p2)
    assert len(events1) > 0

    times = [e.relative_time_ns for e in events1]
    assert times == sorted(times)
    assert all(0 <= t < int(360 * 1e9) for t in times)
    assert {e.logical_topic_id for e in events1} == {
        f"T{i}" for i in range(1, 9)
    }

    interval_ns = 30 * 1_000_000_000
    for e in events1:
        assert e.epoch_slot == e.relative_time_ns // interval_ns
        assert 64 <= e.target_plain_bytes <= 440
        payload = mod.build_exact_payload(
            message_id=e.message_id,
            seq=e.event_index,
            target_plain_bytes=e.target_plain_bytes,
        )
        assert len(mod.compact_json_bytes(payload)) == e.target_plain_bytes


def test_e3b_different_seed_changes_plan():
    events1 = mod.generate_e3b_events(run_index=1, seed=200)
    events2 = mod.generate_e3b_events(run_index=1, seed=201)
    assert events1 != events2


def test_cli_writes_csv_and_manifest_with_matching_sha256(tmp_path: Path):
    out = tmp_path / "e3a-r01.csv"
    rc = mod.main(
        [
            "e3a",
            "--run-index",
            "1",
            "--seed",
            "20261002",
            "--messages-per-class",
            "3",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    manifest_path = out.with_suffix(out.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text())

    assert manifest["schema_version"] == "e3-event-plan-v1"
    assert manifest["mode"] == "e3a"
    assert manifest["event_count"] == 24
    assert manifest["output_csv_sha256"] == sha256(out)

    with out.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 24
