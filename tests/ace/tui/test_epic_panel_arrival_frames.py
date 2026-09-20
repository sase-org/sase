"""Frame-level invariants for a node joining the ``@epic`` tribe panel (sase-142).

Aggregate counters (panel counts, roster sizes, fallback tallies) all pass on an
idle tab, which is how two soaks called the ``@epic`` flicker fixed while no row
ever moved. These tests instead replay real arrivals through the apply boundary
and assert over the paint frames of ``actions/agents/_paint_log.py``.

Invariants the current tree violates land as
``xfail(strict=True, reason="sase-13i @epic panel flicker: ...")``: the suite
stays green, and the moment a fix lands the strict xfail turns red and forces
the marker's removal. A marker still standing when the epic ends is a finding
for the land agent to triage, not a marker to delete. See
``_epic_arrival_frames.py`` for the scenario and the invariant checkers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.ace.tui import _epic_arrival_frames as frames

_GAIN_ARRIVALS = ("clan_member", "second_clan", "starting_rendered_wide")

_FLICKER = "sase-13i @epic panel flicker: "


def _strict_xfail(reason: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        strict=True, raises=AssertionError, reason=_FLICKER + reason
    )


_RECORDED: frames.ArrivalRun | None = None


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> frames.ArrivalRun:
    """Return the arrival scenario's frames, recording it on first use.

    Recording boots the real app (seconds), so every invariant shares one run.
    It happens inside the first requesting test rather than a module-scoped
    fixture, because the suite's per-test autouse isolation must be active.
    """
    global _RECORDED
    if _RECORDED is None:
        _RECORDED = frames.record_arrival_run(monkeypatch, tmp_path / "trace.jsonl")
    return _RECORDED


def _gain_frames(run: frames.ArrivalRun, label: str) -> list[Any]:
    return run.window_frames(label, with_previous=True)


# --- the harness observes what it claims to -----------------------------------


def test_scenario_starts_with_the_selection_below_the_epic_fold(
    run: frames.ArrivalRun,
) -> None:
    baseline = run.frames[0]
    epic = next(p for p in baseline.panels if p.widget_id == frames.EPIC_WIDGET_ID)
    job = next(p for p in baseline.panels if p.widget_id == frames.JOB_WIDGET_ID)

    assert baseline.app_grouping_mode == "BY_STATUS"
    assert baseline.focused_widget_id == frames.EPIC_WIDGET_ID
    assert epic.highlighted_identity == baseline.selected_identity
    assert epic.highlighted is not None
    assert epic.highlighted >= epic.viewport_height  # parked below the fold
    assert epic.scroll_y > 0
    assert job.collapsed and job.option_count == 0  # the collapsed sibling


def test_each_arrival_reaches_the_epic_panel_through_a_refresh(
    run: frames.ArrivalRun,
) -> None:
    epic_rows = {
        label: next(
            p
            for p in run.window_frames(label)[-1].panels
            if p.widget_id == frames.EPIC_WIDGET_ID
        ).option_count
        for label in frames.ARRIVALS
    }

    assert epic_rows == {
        "noop": 16,
        "clan_member": 16,  # the clan container row absorbs its new member
        "second_clan": 17,  # a second container row
        "starting": 17,  # STARTING is not rendered
        "starting_rendered_wide": 18,
    }
    for label in frames.ARRIVALS:
        refreshes = [
            frame
            for frame in run.window_frames(label)
            if frame.kind in ("full_rebuild", "incremental")
        ]
        assert refreshes, f"{label}: no completed refresh was observed"
        assert all(frame.display_cost for frame in refreshes)
    # Only a completed refresh owns display costs; width and settle frames do not.
    assert all(
        frame.display_cost is None and frame.fallback_reason is None
        for frame in run.frames
        if frame.kind in ("container_width", "settled")
    )


def test_wide_arrival_is_the_width_negotiation_trigger(
    run: frames.ArrivalRun,
) -> None:
    before = run.frames[run.windows["starting_rendered_wide"].start - 1]
    after = run.frames[run.windows["starting_rendered_wide"].end - 1]
    requested = {
        frame.seq: max(p.requested_width for p in frame.panels)
        for frame in (before, after)
    }

    assert requested[after.seq] > requested[before.seq]
    assert after.container_width > before.container_width


def test_trace_channel_emits_the_same_frames_as_the_collector(
    run: frames.ArrivalRun,
) -> None:
    emitted = {record["seq"]: record for record in run.trace_frames}

    assert {frame.seq for frame in run.frames} <= emitted.keys()
    for frame in run.frames:
        record = emitted[frame.seq]
        assert record["kind"] == frame.kind
        assert record["container_width"] == frame.container_width
        assert [p["widget_id"] for p in record["panels"]] == [
            p.widget_id for p in frame.panels
        ]


# --- invariants 1, 2, 4 and 6a hold on the current tree -----------------------


@pytest.mark.parametrize("label", _GAIN_ARRIVALS)
def test_a_gain_only_arrival_never_shrinks_or_blanks_a_panel(
    run: frames.ArrivalRun, label: str
) -> None:
    assert frames.option_count_violations(_gain_frames(run, label)) == []


def test_panel_widgets_are_never_remounted_across_arrivals(
    run: frames.ArrivalRun,
) -> None:
    assert frames.widget_identity_violations(run.frames) == []


@pytest.mark.parametrize("label", frames.ARRIVALS)
def test_container_width_moves_at_most_once_and_monotonically(
    run: frames.ArrivalRun, label: str
) -> None:
    assert frames.container_width_violations(_gain_frames(run, label)) == []


def test_selection_stays_highlighted_and_scrolled_into_view(
    run: frames.ArrivalRun,
) -> None:
    assert frames.selection_violations(run.frames) == []


def test_no_panel_paints_collapsed_against_the_apps_decision(
    run: frames.ArrivalRun,
) -> None:
    assert frames.collapse_intent_violations(run.frames) == []


# --- invariants the current tree violates -------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "clan_member",
        "second_clan",
        pytest.param(
            "starting_rendered_wide",
            marks=_strict_xfail(
                "the wide row paints in the refresh frame and the column resizes "
                "a pump cycle later (AgentList.WidthChanged)"
            ),
        ),
    ],
)
def test_an_arrival_is_one_visual_transition(
    run: frames.ArrivalRun, label: str
) -> None:
    assert frames.visual_transition_violations(_gain_frames(run, label)) == []


@pytest.mark.parametrize(
    "label",
    [
        pytest.param(
            "noop",
            marks=_strict_xfail(
                "an apply that changes nothing still repaints the collapsed panel"
            ),
        ),
        pytest.param(
            "starting",
            marks=_strict_xfail(
                "an unrendered STARTING arrival still repaints the collapsed panel"
            ),
        ),
    ],
)
def test_an_apply_that_changes_no_rendered_row_repaints_nothing(
    run: frames.ArrivalRun, label: str
) -> None:
    assert frames.unchanged_apply_violations(run, label) == []


@_strict_xfail("the collapsed panel keeps the default grouping mode")
def test_no_panel_reports_a_grouping_mode_other_than_the_apps(
    run: frames.ArrivalRun,
) -> None:
    assert frames.grouping_mode_violations(run.frames) == []
