"""Attributable perf samples and prompt-state transitions (sase-1nf.14.1.2).

Phase interaction-evidence: perf samples carry instance/time attribution
with one-time provenance, overwritten in-flight samples are counted, the
log rotates, and prompt/modal activity transitions reconstruct durations
with explicit unknown spans.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.util import perf as perf_module
from sase.ace.tui.util.perf import (
    JKPerfTimer,
    PromptActivityTracker,
    _provenance_snapshot,
    _rotated_perf_path,
)


def _read_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_sample_carries_instance_time_and_provenance(tmp_path: Path) -> None:
    timer = JKPerfTimer(
        log_path=tmp_path / "tui_jk.jsonl",
        app_instance_id="aaa",
        pid=4242,
        provenance={
            "sase_version": "v1",
            "source_revision": "deadbee",
            "python_version": "3.14.0",
        },
    )
    timer.begin("next", "agents")
    timer.mark_model_updated()
    timer.mark_painted()

    rows = _read_rows(tmp_path / "tui_jk.jsonl")
    assert len(rows) == 1
    row = rows[0]
    # Legacy fields are preserved.
    assert row["action"] == "next"
    assert row["tab"] == "agents"
    assert row["model_ms"] >= 0
    assert row["paint_ms"] >= row["model_ms"]
    # New attribution fields pair monotonic action time with wall time.
    assert row["dropped_total"] == 0
    assert row["app_instance_id"] == "aaa"
    assert row["pid"] == 4242
    assert isinstance(row["t_wall"], float)
    assert isinstance(row["t_keypress"], float)
    assert row["sase_version"] == "v1"
    assert row["source_revision"] == "deadbee"
    assert row["python_version"] == "3.14.0"


def test_overwritten_inflight_counts_dropped_in_sample(tmp_path: Path) -> None:
    timer = JKPerfTimer(log_path=tmp_path / "tui_jk.jsonl", app_instance_id="aaa")
    timer.begin("next", "agents")
    assert timer.dropped_samples == 0
    timer.begin("prev", "agents")
    assert timer.dropped_samples == 1
    timer.mark_painted()

    rows = _read_rows(tmp_path / "tui_jk.jsonl")
    # The sample log keeps one row kind only: overwritten input travels in
    # the surviving sample's cumulative counter, never as a marker row.
    assert len(rows) == 1
    assert rows[0]["action"] == "prev"
    assert rows[0]["dropped_total"] == 1


def test_rotation_keeps_one_generation(tmp_path: Path) -> None:
    path = tmp_path / "tui_jk.jsonl"
    timer = JKPerfTimer(log_path=path, app_instance_id="aaa", max_bytes=200)
    for _ in range(40):
        timer.begin("next", "agents")
        timer.mark_painted()
    assert _rotated_perf_path(path).exists()
    assert not list(tmp_path.glob("*.2"))
    assert path.stat().st_size <= 200 + 4096


def test_two_instances_share_one_log_without_mixing(tmp_path: Path) -> None:
    path = tmp_path / "tui_jk.jsonl"
    first = JKPerfTimer(log_path=path, app_instance_id="aaa", pid=100)
    second = JKPerfTimer(log_path=path, app_instance_id="bbb", pid=100)
    first.begin("next", "agents")
    first.mark_painted()
    second.begin("prev", "agents")
    second.mark_painted()

    rows = _read_rows(path)
    by_instance = {row["app_instance_id"] for row in rows if "action" in row}
    assert by_instance == {"aaa", "bbb"}


def test_provenance_snapshot_is_cached_not_rediscovered(
    tmp_path: Path, monkeypatch
) -> None:
    calls = {"count": 0}

    def _fake_snapshot() -> dict:
        calls["count"] += 1
        return {"sase_version": "v1"}

    monkeypatch.setattr(perf_module, "_provenance_snapshot", _fake_snapshot)
    timer = JKPerfTimer(log_path=tmp_path / "tui_jk.jsonl")
    for _ in range(5):
        timer.begin("next", "agents")
        timer.mark_painted()
    # One snapshot at construction; never rediscovered per key.
    assert calls["count"] == 1
    timer.bind("aaa")
    assert calls["count"] == 2


def test_provenance_snapshot_never_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        perf_module.platform, "python_version", lambda: (_ for _ in ()).throw(OSError())
    )
    snapshot = _provenance_snapshot()
    assert snapshot["python_version"] is None


def test_activity_initial_state_and_transitions() -> None:
    emitted: list[dict] = []
    tracker = PromptActivityTracker(app_instance_id="aaa", pid=7, emit=emitted.append)
    tracker.start()
    tracker.note_prompt_opened()
    tracker.note_prompt_opened()  # Duplicate opens do not double-record.
    tracker.note_prompt_closed()
    tracker.note_modal_opened("FilterModal", text_entry=True)
    tracker.note_modal_closed("FilterModal", text_entry=True)

    rows = emitted
    assert [row["transition"] for row in rows] == [
        "initial",
        "prompt_opened",
        "prompt_closed",
        "modal_opened",
        "modal_closed",
    ]
    assert rows[0]["state"] == "unknown"
    assert rows[1]["state"] == "prompt_active"
    assert rows[-1]["state"] == "prompt_idle"
    assert rows[-2]["text_entry"] is True
    for row in rows:
        assert row["app_instance_id"] == "aaa"
        assert row["pid"] == 7
        assert isinstance(row["t_wall"], float)
        assert isinstance(row["t_mono"], float)
        # Prompt contents are never logged: only state/screen/timing keys.
        assert set(row) <= {
            "event",
            "transition",
            "state",
            "screen",
            "text_entry",
            "app_instance_id",
            "pid",
            "t_mono",
            "t_wall",
        }


def test_default_emit_resolves_module_sender_for_harness_patch(
    monkeypatch,
) -> None:
    """The durable sink resolves at call time so the harness can no-op it."""
    emitted: list[dict] = []
    monkeypatch.setattr(perf_module, "_emit_prompt_activity", emitted.append)
    tracker = PromptActivityTracker(app_instance_id="aaa")
    tracker.start()
    assert len(emitted) == 1
    assert emitted[0]["event"] == "prompt_activity"
    assert emitted[0]["app_instance_id"] == "aaa"


def test_modal_text_entry_detection_prefers_post_mount_truth() -> None:
    from textual.widgets import Input, TextArea

    from sase.ace.tui.app import AceApp

    class _Query:
        def __init__(self, items: list) -> None:
            self._items = items

        def results(self):  # type: ignore[no-untyped-def]
            return iter(self._items)

    class _Screen:
        def __init__(self, items: list) -> None:
            self._items = items

        def query(self, widget_type: type):  # type: ignore[no-untyped-def]
            return _Query(
                [item for item in self._items if isinstance(item, widget_type)]
            )

    assert AceApp._modal_text_entry(_Screen([Input()])) is True
    assert AceApp._modal_text_entry(_Screen([TextArea()])) is True
    assert AceApp._modal_text_entry(_Screen([])) is False
    assert AceApp._modal_text_entry("screen-name") is None
    assert AceApp._modal_text_entry(None) is None


def test_activity_tracker_is_bounded() -> None:
    tracker = PromptActivityTracker(emit=lambda row: None)
    tracker.start(prompt_open=False)
    assert tracker.transitions[0]["state"] == "prompt_idle"
    for _ in range(perf_module.ACTIVITY_WINDOW + 50):
        tracker.note_prompt_opened()
        tracker.note_prompt_closed()
    assert len(tracker.transitions) == perf_module.ACTIVITY_WINDOW
