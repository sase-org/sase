"""Unit tests for the suite cost attribution pytest plugin."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from tests import _test_cost_plugin
from tests._test_cost import build_cost_record


class _FakePilotApp:
    is_running = True

    async def wait_for_refresh(self) -> bool:
        return True


class _FakePilot:
    app = _FakePilotApp()


async def _fake_pilot_pause(_pilot: _FakePilot, _delay: float | None) -> None:
    return None


def test_cost_recorder_attributes_causes_to_current_file(tmp_path: Path) -> None:
    recorder = _test_cost_plugin.CostRecorder(tmp_path, mode="cost", worker_count=1)
    token = _test_cost_plugin._CURRENT_FILE.set("tests/test_a.py")
    try:
        with recorder.measure("parser_create"):
            pass
        recorder._record_item("tests/test_a.py", wall_seconds=1.0, cpu_seconds=0.25)
        payload = recorder._worker_payload()
    finally:
        _test_cost_plugin._CURRENT_FILE.reset(token)
        recorder._restore_patches()

    assert payload["files"]["tests/test_a.py"]["node_count"] == 1
    assert payload["files"]["tests/test_a.py"]["causes"]["parser_create"]["count"] == 1
    assert payload["causes"]["parser_create"]["count"] == 1
    assert payload["rss_curve_kib"]["sample_count"] >= 2
    assert payload["rss_curve_kib"]["peak"] >= payload["rss_curve_kib"]["start"]


async def test_cost_recorder_attributes_ace_settle_helpers(tmp_path: Path) -> None:
    recorder = _test_cost_plugin.CostRecorder(tmp_path, mode="cost", worker_count=1)
    token = _test_cost_plugin._CURRENT_FILE.set("tests/test_a.py")
    try:
        from sase.ace.testing import settle as settle_helpers

        pilot = _FakePilot()
        await settle_helpers.settle_pilot(pilot, _pilot_pause=_fake_pilot_pause)
        await settle_helpers.pause_until_cpu_idle(pilot, _pilot_pause=_fake_pilot_pause)
        recorder._record_item("tests/test_a.py", wall_seconds=1.0, cpu_seconds=0.5)
        payload = recorder._worker_payload()
    finally:
        _test_cost_plugin._CURRENT_FILE.reset(token)
        recorder._restore_patches()

    causes = payload["files"]["tests/test_a.py"]["causes"]
    assert causes["ace_settle_pilot"]["count"] == 1
    assert causes["ace_pause_until_cpu_idle"]["count"] == 1


def test_cost_recorder_attributes_cpu_seconds_by_cause(tmp_path: Path) -> None:
    recorder = _test_cost_plugin.CostRecorder(tmp_path, mode="cost", worker_count=1)
    token = _test_cost_plugin._CURRENT_FILE.set("tests/test_a.py")
    try:
        with recorder.measure("cpu_bound_cause"):
            total = 0
            for i in range(2_000_000):
                total += i * i
        with recorder.measure("sleep_bound_cause"):
            time.sleep(0.05)  # sase-test-wait: need measurable wall time with ~0 CPU
        payload = recorder._worker_payload()
    finally:
        _test_cost_plugin._CURRENT_FILE.reset(token)
        recorder._restore_patches()

    cpu_cause = payload["causes"]["cpu_bound_cause"]
    sleep_cause = payload["causes"]["sleep_bound_cause"]
    assert cpu_cause["cpu_seconds"] > 0.0
    assert sleep_cause["cpu_seconds"] < sleep_cause["seconds"] / 2

    record = build_cost_record(
        [payload],
        mode="cost",
        worker_count=1,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert record["summary"]["causes"]["cpu_bound_cause"]["cpu_seconds"] > 0.0
    assert (
        record["files"]["tests/test_a.py"]["causes"]["cpu_bound_cause"]["cpu_seconds"]
        > 0.0
    )
