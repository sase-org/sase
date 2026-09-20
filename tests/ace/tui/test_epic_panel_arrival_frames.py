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

The two ``sibling_*`` windows (sase-142.5) are not arrivals: they move
``@default`` rows to another status bucket and assert that only ``@default`` is
rebuilt, that the rebuild names its panel and reason, and that ``@epic`` records
no ``update_list`` or ``render_collapsed``. The ``default_removed`` window drops
both ``@default`` rows and asserts the collapse settles the column width in the
same frame as the rows. The wide ``starting*`` pair lands after the removal so
the collapse still decides the column width.
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
    # A bucket move in @default names only @default: a panel rebuild, not a
    # rebuild of the whole tab.
    "sibling_status_move": ("display_panel_rebuild", "status_membership_change"),
    "sibling_move_beside_epic_patch": (
        "display_panel_rebuild",
        "status_membership_change",
    ),
    # Emptying @default rebuilds only @default: its banner keys are gone.
    "default_removed": ("display_panel_rebuild", "status_membership_change"),
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
        "sibling_status_move": 19,  # @default moved a row; @epic did not change
        "sibling_move_beside_epic_patch": 19,
        "default_removed": 19,  # the removal only empties @default
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


# --- a structural change in a sibling panel ------------------------------------

#: ``@default`` moves a row to another status bucket. In the second window one
#: ``@epic`` row also changes cosmetically, which the tree used to repaint with
#: the whole panel because the change rebuilt every panel together.
_SIBLING_WINDOWS = ("sibling_status_move", "sibling_move_beside_epic_patch")


def _panel(frame: Any, widget_id: str) -> Any:
    return next(p for p in frame.panels if p.widget_id == widget_id)


@pytest.mark.parametrize("label", _SIBLING_WINDOWS)
def test_a_bucket_move_in_default_repaints_no_other_panel(
    run: frames.ArrivalRun, label: str
) -> None:
    calls = [(call.method, call.widget_id) for call in run.calls_in(label)]

    # ``@default`` is rebuilt for its new bucket; ``@epic`` and the collapsed
    # ``@job`` record neither an ``update_list`` nor a ``render_collapsed``.
    assert calls == [("update_list", frames.DEFAULT_WIDGET_ID)]


def test_a_cosmetic_epic_change_beside_the_bucket_move_is_patched_in_place(
    run: frames.ArrivalRun,
) -> None:
    label = "sibling_move_beside_epic_patch"
    window = run.windows[label]
    before = _panel(run.frames[window.start - 1], frames.EPIC_WIDGET_ID)
    after = _panel(run.frames[window.end - 1], frames.EPIC_WIDGET_ID)

    patches = [
        record
        for record in run.records[label]
        if record.display_cost == "row_patch" and record.source == "watcher"
    ]

    assert len(patches) == 1
    assert (after.object_id, after.option_count) == (
        before.object_id,
        before.option_count,
    )


@pytest.mark.parametrize("label", _SIBLING_WINDOWS)
def test_a_bucket_move_in_default_leaves_the_epic_panel_exactly_as_it_was(
    run: frames.ArrivalRun, label: str
) -> None:
    window = run.windows[label]
    before = _panel(run.frames[window.start - 1], frames.EPIC_WIDGET_ID)

    for frame in run.window_frames(label):
        epic = _panel(frame, frames.EPIC_WIDGET_ID)
        # Its rows, highlight, and width are untouched. Its scroll offset may
        # move: ``@default`` changed height, so the column re-divides and the
        # selection is scrolled to stay inside the resized viewport
        # (invariant 4 holds that it does).
        assert epic.object_id == before.object_id
        assert (epic.option_count, epic.highlighted) == (
            before.option_count,
            before.highlighted,
        )
        assert epic.requested_width == before.requested_width
        assert epic.highlighted_identity == frame.selected_identity


@pytest.mark.parametrize("label", _SIBLING_WINDOWS)
def test_a_partial_rebuild_names_its_panel_and_its_reason(
    run: frames.ArrivalRun, label: str
) -> None:
    refresh_costs = [
        record.display_cost
        for record in run.records[label]
        if record.display_cost is not None
    ]

    assert frames.panel_rebuild_attributions(run, label) == [
        (frames.DEFAULT_WIDGET_ID, "status_membership_change")
    ]
    assert "display_full_rebuild" not in refresh_costs
    assert "display_panel_rebuild" in refresh_costs
    # The refresh completed on the incremental path, not the full-rebuild one.
    kinds = {frame.kind for frame in run.window_frames(label)}
    assert "incremental" in kinds
    assert "full_rebuild" not in kinds


# --- a removal that collapses a panel ----------------------------------------


def test_a_removal_that_collapses_a_panel_settles_the_column_in_frame(
    run: frames.ArrivalRun,
) -> None:
    label = "default_removed"
    window = run.windows[label]
    before = run.frames[window.start - 1]
    refresh = next(
        frame for frame in run.window_frames(label) if frame.kind == "incremental"
    )
    after = run.frames[window.end - 1]
    default_before = _panel(before, frames.DEFAULT_WIDGET_ID)
    default_after = _panel(after, frames.DEFAULT_WIDGET_ID)

    # The collapse is the only paint call in the window: no panel was rebuilt
    # with update_list, including the collapsed one.
    assert [(call.method, call.widget_id) for call in run.calls_in(label)] == [
        ("render_collapsed", frames.DEFAULT_WIDGET_ID)
    ]
    # The widget stays mounted as a title strip: roster absence never retires
    # a session-sticky key.
    assert default_before.option_count > 0 and not default_before.collapsed
    assert (default_after.option_count, default_after.collapsed) == (0, True)
    assert default_after.object_id == default_before.object_id
    # The column moves in the refresh frame itself: no width-only frame
    # follows it a pump cycle later.
    assert refresh.container_width < before.container_width
    assert after.container_width == refresh.container_width
    assert not [
        frame for frame in run.window_frames(label) if frame.kind == "container_width"
    ]
    assert (
        frames.visual_transition_violations(
            run.window_frames(label, with_previous=True)
        )
        == []
    )


def test_a_removal_that_collapses_a_panel_leaves_the_other_panels_alone(
    run: frames.ArrivalRun,
) -> None:
    label = "default_removed"
    window = run.windows[label]
    before = run.frames[window.start - 1]
    after = run.frames[window.end - 1]

    for widget_id in (frames.EPIC_WIDGET_ID, frames.JOB_WIDGET_ID):
        panel_before = _panel(before, widget_id)
        panel_after = _panel(after, widget_id)
        assert panel_after.object_id == panel_before.object_id
        assert (
            panel_after.option_count,
            panel_after.collapsed,
            panel_after.requested_width,
        ) == (
            panel_before.option_count,
            panel_before.collapsed,
            panel_before.requested_width,
        )


def test_only_a_partial_rebuild_is_attributed_to_a_panel_across_every_arrival(
    run: frames.ArrivalRun,
) -> None:
    attributed = {
        label: frames.panel_rebuild_attributions(run, label)
        for label in frames.ARRIVALS
    }

    assert {label: pairs for label, pairs in attributed.items() if pairs} == {
        **{
            label: [(frames.DEFAULT_WIDGET_ID, "status_membership_change")]
            for label in _SIBLING_WINDOWS
        },
        # Emptying @default changes its own banner keys, so it names @default
        # for the same reason as the bucket moves.
        "default_removed": [(frames.DEFAULT_WIDGET_ID, "status_membership_change")],
    }
