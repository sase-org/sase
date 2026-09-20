"""Frame-level invariants for a node joining the ``@epic`` tribe panel (sase-142).

Aggregate counters (panel counts, roster sizes, fallback tallies) all pass on an
idle tab, which is how two soaks called the ``@epic`` flicker fixed while no row
ever moved. These tests instead replay real arrivals through the apply boundary
and assert over the paint frames of ``actions/agents/_paint_log.py``.

Every invariant is a plain assertion. They first landed as
``xfail(strict=True)`` markers on the invariants the tree then violated (the
collapsed panel's grouping mode, the repaint of an unchanged apply, the column
resize one pump cycle after the rows); the fixes removed the markers rather than
relaxing any invariant. See ``_epic_arrival_frames.py`` for the scenario and the
invariant checkers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.ace.tui import _epic_arrival_frames as frames

_GAIN_ARRIVALS = (
    "plain_member",
    "clan_member",
    "second_clan",
    "starting_narrow_rendered",
    "starting_rendered_wide",
)

#: The costliest display cost each arrival's refreshes record, and the
#: fallback reason that sent it there (``None`` when nothing fell back).
#: ``None`` cost: nothing rendered changed, so no display work is recorded.
_ARRIVAL_COSTS: dict[str, tuple[str | None, str | None]] = {
    "noop": (None, None),
    "plain_member": ("display_row_insert", None),
    "clan_member": ("row_patch", None),  # the container row absorbs the member
    "second_clan": ("display_panel_rebuild", "workflow_tree_change"),
    "starting_narrow": (None, None),  # STARTING has no row yet
    "starting_narrow_rendered": ("display_row_insert", None),
    "starting": (None, None),
    "starting_rendered_wide": ("display_panel_rebuild", "width_growth"),
}


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
        "plain_member": 17,
        "clan_member": 17,  # the clan container row absorbs its new member
        "second_clan": 18,  # a second container row
        "starting_narrow": 18,  # STARTING is not rendered
        "starting_narrow_rendered": 19,
        "starting": 19,
        "starting_rendered_wide": 20,
    }
    for label in frames.ARRIVALS:
        refreshes = [
            frame
            for frame in run.window_frames(label)
            if frame.kind in ("full_rebuild", "incremental")
        ]
        assert refreshes, f"{label}: no completed refresh was observed"
    # Only a completed refresh owns display costs; width and settle frames do not.
    assert all(
        frame.display_cost is None and frame.fallback_reason is None
        for frame in run.frames
        if frame.kind in ("container_width", "settled")
    )


@pytest.mark.parametrize("label", frames.ARRIVALS)
def test_each_arrival_records_the_display_path_it_took(
    run: frames.ArrivalRun, label: str
) -> None:
    refreshes = [
        frame
        for frame in run.window_frames(label)
        if frame.kind in ("full_rebuild", "incremental")
    ]
    costs = [frame.display_cost for frame in refreshes if frame.display_cost]
    fallbacks = [frame.fallback_reason for frame in refreshes if frame.fallback_reason]

    expected_cost, expected_fallback = _ARRIVAL_COSTS[label]
    assert (costs[0] if costs else None) == expected_cost
    assert (fallbacks[0] if fallbacks else None) == expected_fallback


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


# --- invariants the tree used to violate --------------------------------------


@pytest.mark.parametrize("label", _GAIN_ARRIVALS)
def test_an_arrival_is_one_visual_transition(
    run: frames.ArrivalRun, label: str
) -> None:
    assert frames.visual_transition_violations(_gain_frames(run, label)) == []


@pytest.mark.parametrize("label", ["noop", "starting_narrow", "starting"])
def test_an_apply_that_changes_no_rendered_row_repaints_nothing(
    run: frames.ArrivalRun, label: str
) -> None:
    assert frames.unchanged_apply_violations(run, label) == []


def test_no_panel_reports_a_grouping_mode_other_than_the_apps(
    run: frames.ArrivalRun,
) -> None:
    assert frames.grouping_mode_violations(run.frames) == []


# --- an ordinary node joins in place ------------------------------------------


@pytest.mark.parametrize("label", frames.PLAIN_ARRIVALS)
def test_an_ordinary_arrival_inserts_its_row_without_repainting_any_panel(
    run: frames.ArrivalRun, label: str
) -> None:
    before = run.frames[run.windows[label].start - 1]
    after = run.frames[run.windows[label].end - 1]
    epic_before = next(p for p in before.panels if p.widget_id == frames.EPIC_WIDGET_ID)
    epic_after = next(p for p in after.panels if p.widget_id == frames.EPIC_WIDGET_ID)

    assert run.calls_in(label) == []  # no update_list / render_collapsed anywhere
    assert epic_after.option_count == epic_before.option_count + 1
    assert epic_after.object_id == epic_before.object_id
    # The selection was parked below the fold and stays on its own row.
    assert epic_after.highlighted_identity == after.selected_identity
    assert epic_after.highlighted == epic_before.highlighted + 1
    # The narrow row does not move the column or any other panel's rows.
    assert after.container_width == before.container_width
    assert epic_after.requested_width == epic_before.requested_width
    other_rows = {
        p.widget_id: p.option_count
        for p in after.panels
        if p.widget_id != frames.EPIC_WIDGET_ID
    }
    assert other_rows == {
        p.widget_id: p.option_count
        for p in before.panels
        if p.widget_id != frames.EPIC_WIDGET_ID
    }


def test_the_wide_arrival_resizes_the_column_in_the_frame_that_paints_its_row(
    run: frames.ArrivalRun,
) -> None:
    window = run.windows["starting_rendered_wide"]
    before = run.frames[window.start - 1]
    refresh = next(
        frame
        for frame in run.window_frames("starting_rendered_wide")
        if frame.display_cost == "display_panel_rebuild"
    )
    epic = next(p for p in refresh.panels if p.widget_id == frames.EPIC_WIDGET_ID)

    assert epic.requested_width > max(p.requested_width for p in before.panels)
    assert refresh.container_width > before.container_width
    # No later width-only frame: the negotiated width was already final.
    assert not [
        frame
        for frame in run.window_frames("starting_rendered_wide")
        if frame.kind == "container_width"
    ]
