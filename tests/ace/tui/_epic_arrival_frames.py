"""Frame-level harness for a node joining the ``@epic`` tribe panel.

Boots the real ``AceApp`` under the host's shape (``BY_STATUS`` grouping, split
tribe panels, committed query ``NOT machine:apollo``, an ``@epic`` panel with a
clan container and a selection parked below its fold, a collapsed ``@job``
sibling) and drives each arrival through the real apply boundary
(``_apply_loaded_agents_prepared``), never by assigning ``app._agents``.

Every completed Agents-display refresh appends one paint frame to
``app._agents_paint_log`` (``actions/agents/_paint_log.py``); the invariant
checkers below assert over those frames rather than over aggregate counters.

The last two windows are not arrivals: they move ``@default`` rows to another
status bucket while ``@epic`` changes not at all, then while one ``@epic`` row
only picks up a badge. These are the sibling-panel cases the panel-scoped
rebuild gates exist for (sase-142.5). The removal window drops both
``@default`` rows, retiring the emptied panel, and the wide ``starting*`` pair
lands after it so the retirement still decides the column width: the width
must settle in the same frame as the rows.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.actions.agents._loading_compute import PreparedApplyData
from sase.ace.tui.actions.agents._paint_log import record_agents_paint_frame
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.util import trace
from sase.ace.tui.widgets import AgentList
from tests._agents_tab_query_helpers import _make_agent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
)

DEFAULT_WIDGET_ID = "agent-list-panel"
EPIC_WIDGET_ID = "agent-list-panel-epic"
JOB_WIDGET_ID = "agent-list-panel-job"
HOST_QUERY = "NOT machine:apollo"
TERMINAL_SIZE = (120, 30)

#: Arrival windows in the order they are applied.
#:
#: The wide ``starting*`` pair lands after the removal on purpose: the
#: removal window must still decide the column width when it retires
#: ``@default``, which a wider ``@epic`` row would otherwise pin.
ARRIVALS = (
    "noop",
    "plain_member",
    "clan_member",
    "second_clan",
    "starting_narrow",
    "starting_narrow_rendered",
    "sibling_status_move",
    "sibling_move_beside_epic_patch",
    "default_removed",
    "starting",
    "starting_rendered_wide",
)

#: Arrivals that add one ordinary non-clan row no wider than the existing ones.
PLAIN_ARRIVALS = ("plain_member", "starting_narrow_rendered")


@dataclass(frozen=True)
class PaintCall:
    """One ``AgentList`` content repaint observed while the run was recording."""

    marker: int  # index the next paint frame will take when the call happened
    widget_id: str | None
    method: str


@dataclass
class ArrivalWindow:
    """Frame index range ``[start, end)`` produced by one apply plus its settle."""

    label: str
    start: int
    end: int


@dataclass
class ArrivalRun:
    """Everything one recorded scenario run observed."""

    frames: list[Any] = field(default_factory=list)
    windows: dict[str, ArrivalWindow] = field(default_factory=dict)
    paint_calls: list[PaintCall] = field(default_factory=list)
    trace_frames: list[dict[str, Any]] = field(default_factory=list)
    # The refresh trace records each window produced, in the order recorded.
    records: dict[str, list[Any]] = field(default_factory=dict)

    def window_frames(self, label: str, *, with_previous: bool = False) -> list[Any]:
        window = self.windows[label]
        start = max(0, window.start - 1) if with_previous else window.start
        return self.frames[start : window.end]

    def calls_in(self, label: str) -> list[PaintCall]:
        window = self.windows[label]
        return [
            call
            for call in self.paint_calls
            if window.start <= call.marker < window.end
        ]


def _node(name: str, tribe: str | None, minute: int, **fields: Any) -> Agent:
    started = datetime(2026, 9, 18, 9, minute, 0)
    return _make_agent(
        cl_name=name,
        agent_name=name,
        raw_suffix=f"202609180{minute // 60}{minute % 60:02d}00",
        status=fields.pop("status", "RUNNING"),
        tribe=tribe,
        start_time=started,
        run_start_time=started,
        **fields,
    )


def _clan_member(name: str, clan: str, minute: int, provider: str) -> Agent:
    return _node(
        name,
        "epic",
        minute,
        llm_provider=provider,
        agent_clan=clan,
        agent_clan_generation="g1",
    )


def initial_roster() -> list[Agent]:
    """Loader rows: ``@default`` (2), ``@epic`` (14 nodes + one clan), ``@job`` (2).

    The ``@default`` rows carry long names on purpose: they hold the column
    width until the wide arrival, so the removal window retires the panel
    that decides the width.
    """
    return [
        _node("home-a-with-a-long-name-holding-the-column-wide-01", None, 1),
        _node("home-b-with-a-long-name-holding-the-column-wide-02", None, 2),
        *(_node(f"epic-node-{i:02d}", "epic", 10 + i) for i in range(14)),
        _clan_member("epic-claude", "epic-clan", 30, "claude"),
        _clan_member("epic-codex", "epic-clan", 31, "codex"),
        _node("job-a", "job", 40),
        _node("job-b", "job", 41),
    ]


def arrival_rosters(base: list[Agent]) -> list[tuple[str, list[Agent]]]:
    """The successive full rosters each arrival window applies.

    Each roster builds on the previous one. A plain node lands among the
    existing ``@epic`` rows (not at the end) so the arrival also shifts every
    later global index, the way a newest-first loader list does.
    """
    rosters: list[tuple[str, list[Agent]]] = []
    current = list(base)

    def arrive(label: str, rows: list[Agent]) -> None:
        current[:] = rows
        rosters.append((label, list(rows)))

    arrive("noop", current)
    plain = _node("epic-node-14", "epic", 45)  # as wide as its siblings
    arrive("plain_member", [*current[:2], plain, *current[2:]])
    arrive(
        "clan_member",
        [*current, _clan_member("epic-gemini", "epic-clan", 32, "gemini")],
    )
    arrive(
        "second_clan",
        [*current, _clan_member("epic-second-claude", "epic-clan-2", 33, "claude")],
    )
    narrow = _node("epic-node-15", "epic", 46, status="STARTING")
    arrive("starting_narrow", [*current, narrow])
    arrive(
        "starting_narrow_rendered",
        [*current[:-1], dataclasses.replace(narrow, status="RUNNING")],
    )
    # ``home-a`` finishes: a status-bucket move confined to ``@default``.
    arrive(
        "sibling_status_move",
        [dataclasses.replace(current[0], status="DONE"), *current[1:]],
    )
    # ``home-b`` finishes too while one ``@epic`` row picks up a badge: the
    # sibling's cosmetic change must be patched, not repainted with its panel.
    arrive(
        "sibling_move_beside_epic_patch",
        [
            current[0],
            dataclasses.replace(current[1], status="DONE"),
            *(
                dataclasses.replace(agent, activity="reviewing")
                if agent.cl_name == "epic-node-05"
                else agent
                for agent in current[2:]
            ),
        ],
    )
    # Both ``@default`` rows leave the roster: the authoritative apply retires
    # the emptied session-sticky panel in the same frame. ``@default`` holds
    # the column here (``home-a``/``home-b`` are the widest rows until the
    # wide arrival below), so the retirement must settle the column in the
    # same frame as the rows (sase-142.5 quiet-applies).
    arrive("default_removed", [agent for agent in current if agent.tribe])
    # The wide arrival lands after the removal, so the removal window above
    # still decides the column width when it retires ``@default``.
    wide = _node(
        "epic-a-very-long-arriving-node-name-wider-than-every-existing-row",
        "epic",
        50,
        status="STARTING",
    )
    arrive("starting", [*current, wide])
    arrive(
        "starting_rendered_wide",
        [*current[:-1], dataclasses.replace(wide, status="RUNNING")],
    )
    return rosters


async def _settle(page: AcePage, log: list[Any], *, timeout: float = 30.0) -> None:
    """Pump until no frame, fleet refresh, or task is still landing.

    Bounded by wall time, not iterations: the fleet follow-up of every apply
    does thread-backed work that a bare Textual settle does not wait for.
    """
    app = page.app
    deadline = time.monotonic() + timeout
    quiet = 0
    seen = -1
    while time.monotonic() < deadline:
        await page.pause()
        await page.pause(0.02)
        busy = bool(getattr(app, "_agents_fleet_loading", False)) or any(
            not task.done() for task in getattr(app, "_agents_fleet_async_tasks", ())
        )
        if len(log) == seen and not busy:
            quiet += 1
            if quiet >= 2:
                return
        else:
            quiet = 0
        seen = len(log)
    raise TimeoutError(
        f"Agents tab never settled: frames={len(log)} "
        f"fleet_loading={getattr(app, '_agents_fleet_loading', None)}"
    )


async def _record(run: ArrivalRun, monkeypatch: pytest.MonkeyPatch) -> None:
    roster = initial_roster()
    patch_startup_loaders(monkeypatch, agents=roster)
    # The host runs with federation configured, so the fleet header row is
    # always present; without this the header toggles with every fleet refresh
    # and resizes the column for reasons unrelated to arrivals.
    monkeypatch.setattr(AceApp, "_fleet_mode_available", lambda _app: True)
    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
        size=TERMINAL_SIZE,
    ) as page:
        await wait_for_startup(page)
        app = page.app
        log: list[Any] = []
        app._agents_paint_log = log
        app._grouping_mode = GroupingMode.BY_STATUS
        app._collapsed_panel_keys = {"job"}
        app._agent_search_query = HOST_QUERY
        app._agent_display_last_search_query = HOST_QUERY
        app._refresh_agents_display(list_changed=True)
        await _settle(page, log)

        # Park the selection inside @epic, below its fold.
        await page.press("J")
        for _ in range(12):
            await page.press("j")
        await _settle(page, log)
        assert app._panel_group.focused_key == "epic"

        state = AgentLoadState(
            tier="tier2",
            complete_history=True,
            artifact_source="source_scan",
            used_artifact_index=False,
        )

        def apply(rows: list[Agent]) -> None:
            selected = app._get_selected_agent()
            app._agents_refresh_active_source = "watcher"
            app._apply_loaded_agents_prepared(
                PreparedApplyData(
                    filtered_agents=list(rows),
                    has_always_visible=True,
                    hidden_count=0,
                    hideable_agents=[],
                    dismissed_agent_objects=[],
                ),
                on_agents_tab=True,
                selected_identity=selected.identity if selected else None,
                load_state=state,
                persist_dismissed_changes=False,
                incomplete_merge_already_applied=True,
            )

        # One warm-up apply of the unchanged roster lets per-apply stamps (runner
        # capacity on every row) settle, so the recorded no-op really is one.
        apply(roster)
        await _settle(page, log)
        # The host's committed query must really be in force, not silently dropped.
        assert app._agent_query_parse_error is None
        assert app._agent_search_query == HOST_QUERY

        records: list[Any] = []
        app._agents_refresh_trace_records = records
        origin = len(log)
        with _spy_on_agent_list_paints(run, log, origin):
            record_agents_paint_frame(app, kind="settled")  # the baseline frame
            for label, rows in arrival_rosters(roster):
                start = len(log) - origin
                first_record = len(records)
                apply(rows)
                await _settle(page, log)
                record_agents_paint_frame(app, kind="settled")
                run.windows[label] = ArrivalWindow(label, start, len(log) - origin)
                run.records[label] = records[first_record:]
        run.frames = log[origin:]


@contextmanager
def _spy_on_agent_list_paints(
    run: ArrivalRun, log: list[Any], origin: int
) -> Generator[None]:
    """Record every ``update_list`` / ``render_collapsed`` on any ``AgentList``."""
    originals = {
        name: getattr(AgentList, name) for name in ("update_list", "render_collapsed")
    }

    def wrap(name: str) -> Callable[..., Any]:
        original = originals[name]

        def spy(widget: AgentList, *args: Any, **kwargs: Any) -> Any:
            run.paint_calls.append(PaintCall(len(log) - origin, widget.id, name))
            return original(widget, *args, **kwargs)

        return spy

    for name in originals:
        setattr(AgentList, name, wrap(name))
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(AgentList, name, original)


def record_arrival_run(monkeypatch: pytest.MonkeyPatch, trace_path: Path) -> ArrivalRun:
    """Run the scenario once, with ``SASE_TUI_TRACE=1`` emitting to *trace_path*.

    Must run inside a test's own function-scoped fixtures: the suite's autouse
    isolation (``SASE_HOME``, the settle-barrier ``Pilot.pause``) lives there.
    """
    run = ArrivalRun()
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(trace_path))
    asyncio.run(_record(run, monkeypatch))
    trace._flush_trace_writes()
    if trace_path.exists():
        run.trace_frames = [
            record
            for line in trace_path.read_text().splitlines()
            if (record := json.loads(line)).get("event") == "agents.paint_frame"
        ]
    return run


def panel_rebuild_attributions(run: ArrivalRun, label: str) -> list[tuple[Any, Any]]:
    """The ``(panel widget id, reason)`` of each partial rebuild a window recorded."""
    return [
        (record.panel, record.fallback_reason)
        for record in run.records[label]
        if record.stage == "display_fallback" and record.panel is not None
    ]


# --- invariants over the paint log -------------------------------------------
# Each checker returns human-readable violations (empty means the invariant
# holds) naming the offending frame ``seq`` so a failure points at an observation.


def _panels_by_id(frame: Any) -> dict[str | None, Any]:
    return {panel.widget_id: panel for panel in frame.panels}


def visible_signature(frame: Any) -> tuple[Any, ...]:
    """What a user can see move: the column width and each panel's rows/size."""
    return (
        frame.container_width,
        tuple(
            (
                panel.widget_id,
                panel.option_count,
                panel.collapsed,
                panel.height,
                panel.requested_width,
            )
            for panel in frame.panels
        ),
    )


def option_count_violations(frames: list[Any]) -> list[str]:
    """Invariant 1: a gain-only roster never shrinks or blanks a panel."""
    violations: list[str] = []
    for prev, cur in zip(frames, frames[1:], strict=False):
        before = _panels_by_id(prev)
        for widget_id, panel in _panels_by_id(cur).items():
            old = before.get(widget_id)
            if old is None or old.collapsed or panel.collapsed:
                continue
            if panel.option_count < old.option_count:
                violations.append(
                    f"frame {cur.seq}: {widget_id} option_count "
                    f"{old.option_count} -> {panel.option_count}"
                )
            if old.option_count and not panel.option_count:
                violations.append(f"frame {cur.seq}: {widget_id} blanked")
    return violations


def widget_identity_violations(frames: list[Any]) -> list[str]:
    """Invariant 2: every panel keeps its widget object; ``@epic`` never leaves."""
    violations: list[str] = []
    first_seen: dict[str | None, int] = {}
    for frame in frames:
        panels = _panels_by_id(frame)
        if EPIC_WIDGET_ID not in panels:
            violations.append(f"frame {frame.seq}: {EPIC_WIDGET_ID} not mounted")
        for widget_id, panel in panels.items():
            expected = first_seen.setdefault(widget_id, panel.object_id)
            if panel.object_id != expected:
                violations.append(f"frame {frame.seq}: {widget_id} was remounted")
    return violations


def container_width_violations(frames: list[Any]) -> list[str]:
    """Invariant 3a: the column width moves once, monotonically, per arrival."""
    widths = [frame.container_width for frame in frames]
    changes = [
        (frames[idx].seq, widths[idx - 1], widths[idx])
        for idx in range(1, len(widths))
        if widths[idx] != widths[idx - 1]
    ]
    violations: list[str] = []
    if len(changes) > 1:
        violations.append(f"container width changed {len(changes)} times: {changes}")
    directions = {new > old for _, old, new in changes}
    if len(directions) > 1:
        violations.append(f"container width was not monotonic: {changes}")
    return violations


def visual_transition_violations(frames: list[Any]) -> list[str]:
    """Invariant 3b: an arrival is one visual transition, not a rows-then-width pair."""
    transitions = [
        frame.seq
        for prev, frame in zip(frames, frames[1:], strict=False)
        if visible_signature(frame) != visible_signature(prev)
    ]
    if len(transitions) <= 1:
        return []
    return [f"visible state changed in {len(transitions)} frames: {transitions}"]


def selection_violations(frames: list[Any]) -> list[str]:
    """Invariant 4: the selected identity stays highlighted and inside the viewport."""
    violations: list[str] = []
    for frame in frames:
        panel = _panels_by_id(frame).get(frame.focused_widget_id)
        if panel is None or frame.selected_identity is None:
            violations.append(f"frame {frame.seq}: no focused panel or selection")
            continue
        if panel.highlighted_identity != frame.selected_identity:
            violations.append(
                f"frame {frame.seq}: highlighted {panel.highlighted_identity} "
                f"is not selected {frame.selected_identity}"
            )
        row = panel.highlighted
        if row is None or not (
            panel.scroll_y <= row < panel.scroll_y + panel.viewport_height
        ):
            violations.append(
                f"frame {frame.seq}: row {row} outside scroll "
                f"{panel.scroll_y}+{panel.viewport_height}"
            )
    return violations


def unchanged_apply_violations(run: ArrivalRun, label: str) -> list[str]:
    """Invariant 5: an apply that changes no rendered row repaints nothing."""
    frames = run.window_frames(label, with_previous=True)
    baseline = frames[0]
    violations = [
        f"{call.method} on {call.widget_id} (before frame index {call.marker})"
        for call in run.calls_in(label)
    ]
    for frame in frames[1:]:
        if visible_signature(frame) != visible_signature(baseline):
            violations.append(f"frame {frame.seq}: geometry differs from baseline")
    return violations


def collapse_intent_violations(frames: list[Any]) -> list[str]:
    """Invariant 6a: a panel paints collapsed only when the app says it is."""
    return [
        f"frame {frame.seq}: {panel.widget_id} collapsed={panel.collapsed} "
        f"but the app's decision is {panel.collapse_intent}"
        for frame in frames
        for panel in frame.panels
        if panel.collapsed != panel.collapse_intent
    ]


def grouping_mode_violations(frames: list[Any]) -> list[str]:
    """Invariant 6b: no panel reports a grouping mode other than the app's."""
    return [
        f"frame {frame.seq}: {panel.widget_id} is {panel.grouping_mode}, "
        f"app is {frame.app_grouping_mode}"
        for frame in frames
        for panel in frame.panels
        if panel.grouping_mode != frame.app_grouping_mode
    ]
