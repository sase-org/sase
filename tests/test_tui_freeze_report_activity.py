"""Sequence witnesses and prompt-state GC/hitch comparisons."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "tools" / "_tui_freeze_report_activity.py"
spec = importlib.util.spec_from_file_location("activity_report", path)
assert spec is not None and spec.loader is not None
activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activity)


def _state(wall: float, sequence: int, state: str, transition: str = "changed") -> dict:
    return {
        "t_wall": wall,
        "t_mono": wall,
        "sequence": sequence,
        "state": state,
        "transition": transition,
    }


def test_unknown_prefix_tail_and_missing_transition_are_not_idle() -> None:
    rows = [
        _state(10, 0, "prompt_idle", "initial"),
        _state(20, 2, "prompt_active"),
        _state(40, 2, "prompt_active", "checkpoint"),
    ]
    result = activity.analyze_prompt_states(rows, 0, 60, [])
    assert result["detail"]["unknown_s"] == 40
    assert result["detail"]["active_s"] == 20
    assert result["detail"]["idle_s"] == 0
    assert result["issues"]


def test_missing_transition_at_end_is_detected_by_checkpoint() -> None:
    rows = [
        _state(0, 0, "prompt_idle", "initial"),
        _state(60, 2, "prompt_idle", "checkpoint"),
    ]
    result = activity.analyze_prompt_states(rows, 0, 60, [])
    assert result["detail"]["unknown_s"] == 60


@pytest.mark.parametrize(
    "field,value", [("sequence", None), ("t_mono", -10), ("state", "invalid")]
)
def test_malformed_witness_does_not_prove_an_interval(
    field: str, value: object
) -> None:
    first = _state(0, 0, "prompt_idle", "initial")
    first[field] = value
    result = activity.analyze_prompt_states(
        [first, _state(60, 0, "prompt_idle", "checkpoint")], 0, 60, []
    )
    assert result["detail"]["unknown_s"] == 60


def test_mixed_heartbeat_totals_are_unassigned_and_episode_totals_stay_separate() -> (
    None
):
    rows = [
        _state(0, 0, "prompt_idle", "initial"),
        _state(450, 1, "prompt_active"),
        _state(700, 2, "modal_active"),
        _state(800, 3, "modal_open"),
        _state(900, 3, "modal_open", "checkpoint"),
    ]
    beats = [
        {
            "event": "tui_memory_heartbeat",
            "ts": wall,
            "window_s": 300,
            "gc_generations": {"2": {"total_s": 10}},
            "loop_hitch_seconds": 2,
            "loop_suppressed_seconds": 1,
        }
        for wall in (0, 300, 600, 900)
    ]
    episodes = [
        {"event": "tui_gc_pause", "start_ts": 500, "duration_s": 3},
        {"event": "tui_hitch_recovered", "ts": 505, "duration_seconds": 4},
    ]
    result = activity.analyze_prompt_states(rows, 0, 900, beats + episodes)["detail"]
    assert result["active_s"] == 250
    assert result["idle_s"] == 450
    assert result["modal_text_entry_s"] == 100
    observations = result["observations"]["by_state"]
    assert observations["prompt_idle"]["gc_total_s"] == 10
    assert observations["prompt_active"]["gc_total_s"] == 0
    assert observations["mixed"]["gc_total_s"] == 20
    assert observations["mixed"]["loop_hitch_seconds"] == 4
    assert observations["mixed"]["loop_suppressed_seconds"] == 2
    assert observations["prompt_active"]["gc_pause_s"] == 3
    assert observations["prompt_active"]["hitch_episode_s"] == 4


def test_rotation_checkpoint_seeds_state_without_original_initial_row() -> None:
    rows = [
        _state(0, 15, "prompt_idle", "checkpoint"),
        _state(600, 15, "prompt_idle", "checkpoint"),
    ]
    result = activity.analyze_prompt_states(rows, 100, 500, [])
    assert result["detail"]["idle_s"] == 400
    assert result["detail"]["unknown_s"] == 0
