"""Failed-clan cause chip, width drop, and failed-rollup time column."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_time import runtime_suffix_ticks
from textual.app import App, ComposeResult
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.failure_focus import (
    FailureFocus,
    _FailureRowFocus,
    _NotAdoptedHandoffFocus,
)
from sase.ace.tui.widgets._agent_list_build_rows import widget_viewport_width
from sase.ace.tui.widgets._agent_list_render_agent import (
    cached_format_agent_option,
    format_agent_option,
)
from sase.ace.tui.widgets._agent_list_render_agent_status import (
    row_has_droppable_cause_chip,
)
from sase.ace.tui.widgets._agent_list_render_cache import AgentRenderCache
from sase.ace.tui.widgets._agent_list_styling import BANNER_ROW
from sase.ace.tui.widgets.agent_list import AgentList
from sase.monitor_state import NOT_ADOPTED_COLOR, NOT_ADOPTED_GLYPH

from ._agent_list_monitor_rows_helpers import style_at

BY_STATUS = GroupingMode.BY_STATUS


class _CauseChipListApp(App[None]):
    """Minimal app hosting one agent list for resize tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield AgentList(id="agent-list")


def _agent_prompt(widget: AgentList) -> str:
    """Return the first painted agent row's plain text."""
    for row, (local_idx, _attempt) in enumerate(widget._row_entries):
        if local_idx == BANNER_ROW:
            continue
        return widget.get_option_at_index(row).prompt.plain
    raise AssertionError("no agent row painted")


_NOW = datetime(2026, 11, 22, 13, 0, 0)
_STOP = datetime(2026, 11, 22, 12, 8, 32)


def _focus(
    *,
    chip: str | None = None,
    chip_style: str | None = None,
    not_adopted: bool = False,
    extra_failed: int = 0,
) -> FailureFocus:
    return FailureFocus(
        member_label=".8",
        failed_row=_FailureRowFocus(
            name="research.8--1",
            stop_time=_STOP,
            duration_seconds=512.0,
        ),
        finalizer_chip=chip,
        not_adopted=(
            _NotAdoptedHandoffFocus(
                name="research.8--mon-0",
                kind="monitor",
                starter_name="research.8--1",
            )
            if not_adopted
            else None
        ),
        extra_failed=extra_failed,
        finalizer_chip_style=chip_style,
    )


def _clan(focus: FailureFocus | None) -> Agent:
    waiting = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="waiter",
        project_file="/tmp/clan.sase",
        status="WAITING",
        status_bucket="Waiting",
        start_time=_NOW - timedelta(minutes=10),
        run_start_time=_NOW - timedelta(minutes=10),
        agent_name="research.waiter",
        agent_clan="research",
        agent_clan_generation="gen-1",
    )
    row = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="clan-research",
        project_file="/tmp/clan.sase",
        status="FAILED",
        status_bucket="Failed",
        start_time=_NOW - timedelta(hours=1),
        run_start_time=_NOW - timedelta(hours=1),
        agent_name="research",
        agent_clan="research",
        agent_clan_generation="gen-1",
        is_clan_container=True,
        runtime_children=[waiting],
    )
    row.failure_focus = focus
    return row


def _healthy_clan() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="clan-healthy",
        project_file="/tmp/clan.sase",
        status="RUNNING",
        status_bucket="Running",
        start_time=_NOW - timedelta(minutes=5),
        run_start_time=_NOW - timedelta(minutes=5),
        agent_name="healthy",
        agent_clan="healthy",
        agent_clan_generation="gen-1",
        is_clan_container=True,
    )


def test_clan_cause_chip_no_finalizer_uses_failed_glyph() -> None:
    left, _suffix, _option_id = format_agent_option(
        _clan(_focus()),
        0,
        is_selected=False,
        now=_NOW,
    )
    assert "· .8 ✗" in left.plain
    assert style_at(left, left.plain.index(".8")) == "dim #FF5F5F"
    assert style_at(left, left.plain.index("✗")) == "bold #FF5F5F"


def test_clan_cause_chip_not_adopted_only() -> None:
    left, _suffix, _option_id = format_agent_option(
        _clan(_focus(not_adopted=True)),
        0,
        is_selected=False,
        now=_NOW,
    )
    expected = f"· .8 {NOT_ADOPTED_GLYPH}"
    assert expected in left.plain
    assert style_at(left, left.plain.index(NOT_ADOPTED_GLYPH)) == (
        f"bold {NOT_ADOPTED_COLOR}"
    )


def test_clan_cause_chip_finalizer_and_extra_failures() -> None:
    left, _suffix, _option_id = format_agent_option(
        _clan(_focus(chip="⊛✗ commit", chip_style="bold #FF5F5F", extra_failed=1)),
        0,
        is_selected=False,
        now=_NOW,
    )
    assert "· .8 ⊛✗ commit +1" in left.plain
    assert style_at(left, left.plain.index("⊛✗ commit")) == "bold #FF5F5F"


def test_clan_cause_chip_drops_before_name_under_width_budget() -> None:
    row = _clan(_focus(chip="⊛✗ commit", chip_style="bold #FF5F5F"))
    wide, _suffix, _ = format_agent_option(
        row, 0, is_selected=False, now=_NOW, width=200
    )
    narrow, _suffix, _ = format_agent_option(
        row, 0, is_selected=False, now=_NOW, width=40
    )
    assert "· .8 ⊛✗ commit" in wide.plain
    assert "research" in wide.plain
    assert "· .8 ⊛✗ commit" not in narrow.plain
    assert "research" in narrow.plain


def test_viewport_width_caps_to_narrower_parent() -> None:
    parent = type("P", (), {"size": type("S", (), {"width": 50})(), "parent": None})()
    widget = type("W", (), {"size": type("S", (), {"width": 90})(), "parent": parent})()
    assert widget_viewport_width(widget) == 50


def test_viewport_width_zero_when_unmounted() -> None:
    widget = type("W", (), {"size": None, "parent": None})()
    assert widget_viewport_width(widget) == 0


def test_healthy_clan_row_has_no_cause_chip() -> None:
    left, _suffix, _option_id = format_agent_option(
        _healthy_clan(),
        0,
        is_selected=False,
        now=_NOW,
    )
    assert "· .8" not in left.plain
    assert "✗" not in left.plain or "FAILED" not in left.plain


def test_row_has_droppable_cause_chip_predicate() -> None:
    assert row_has_droppable_cause_chip(_clan(_focus())) is True
    assert (
        row_has_droppable_cause_chip(
            _clan(_focus(chip="⊛✗ commit", chip_style="bold #FF5F5F"))
        )
        is True
    )
    assert row_has_droppable_cause_chip(_clan(None)) is False
    assert row_has_droppable_cause_chip(_healthy_clan()) is False


def test_render_key_width_only_keys_chip_capable_rows() -> None:
    cache = AgentRenderCache()
    healthy = _healthy_clan()
    first = cached_format_agent_option(
        cache, healthy, 0, is_selected=False, now=_NOW, width=40
    )
    second = cached_format_agent_option(
        cache, healthy, 0, is_selected=False, now=_NOW, width=200
    )
    assert second[0] is first[0]

    clan = _clan(_focus(chip="⊛✗ commit", chip_style="bold #FF5F5F"))
    wide = cached_format_agent_option(
        cache, clan, 0, is_selected=False, now=_NOW, width=200
    )
    narrow = cached_format_agent_option(
        cache, clan, 0, is_selected=False, now=_NOW, width=40
    )
    assert "· .8 ⊛✗ commit" in wide[0].plain
    assert "· .8 ⊛✗ commit" not in narrow[0].plain


async def test_cause_chip_drops_and_returns_on_resize_without_rebuild(
    monkeypatch,
) -> None:
    import sase.ace.tui.widgets._agent_list_base as _base

    builds = 0
    original = _base.build_list

    def _counting(widget, agents, *args, **kwargs):
        nonlocal builds
        builds += 1
        return original(widget, agents, *args, **kwargs)

    monkeypatch.setattr(_base, "build_list", _counting)
    app = _CauseChipListApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        widget.update_list(
            [_clan(_focus(chip="⊛✗ commit", chip_style="bold #FF5F5F"))],
            0,
            grouping_mode=BY_STATUS,
            now=_NOW,
        )
        await pilot.pause()
        assert builds == 1
        assert "· .8 ⊛✗ commit" in _agent_prompt(widget)

        await pilot.resize_terminal(60, 40)
        await pilot.pause()
        await pilot.pause()
        assert builds == 1
        assert "· .8 ⊛✗ commit" not in _agent_prompt(widget)
        assert "research" in _agent_prompt(widget)
        assert widget._cause_chip_resize_scheduled is False

        await pilot.resize_terminal(140, 40)
        await pilot.pause()
        await pilot.pause()
        assert builds == 1
        assert "· .8 ⊛✗ commit" in _agent_prompt(widget)


async def test_zero_width_build_corrects_chip_on_first_sizing(monkeypatch) -> None:
    import sase.ace.tui.widgets._agent_list_base as _base

    builds = 0
    original = _base.build_list

    def _counting(widget, agents, *args, **kwargs):
        nonlocal builds
        builds += 1
        return original(widget, agents, *args, **kwargs)

    monkeypatch.setattr(_base, "build_list", _counting)
    widget = AgentList()
    widget.update_list(
        [_clan(_focus(chip="⊛✗ commit", chip_style="bold #FF5F5F"))],
        0,
        grouping_mode=BY_STATUS,
        now=_NOW,
    )
    assert builds == 1
    assert "· .8 ⊛✗ commit" in _agent_prompt(widget)

    class _PrebuiltApp(App[None]):
        def compose(self) -> ComposeResult:
            yield widget

    app = _PrebuiltApp()
    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert builds == 1
        assert "· .8 ⊛✗ commit" not in _agent_prompt(widget)
        assert "research" in _agent_prompt(widget)


async def test_resize_without_chip_rows_schedules_no_patch(monkeypatch) -> None:
    import sase.ace.tui.widgets._agent_list_build_patch_single as _patch

    calls = 0
    original = _patch.patch_row

    def _counting(widget, agent_idx, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(widget, agent_idx, *args, **kwargs)

    monkeypatch.setattr(_patch, "patch_row", _counting)
    app = _CauseChipListApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        widget = app.query_one(AgentList)
        widget.update_list([_healthy_clan()], 0, grouping_mode=BY_STATUS, now=_NOW)
        await pilot.pause()
        before = _agent_prompt(widget)

        await pilot.resize_terminal(60, 40)
        await pilot.pause()
        await pilot.pause()
        assert calls == 0
        assert widget._cause_chip_resize_scheduled is False
        assert _agent_prompt(widget) == before


def test_failed_clan_rollup_uses_failed_turn_stop_time() -> None:
    row = _clan(_focus(chip="⊛✗ commit", chip_style="bold #FF5F5F"))
    _left, suffix, _option_id = format_agent_option(
        row,
        0,
        is_selected=False,
        now=_NOW,
    )
    assert runtime_suffix_ticks(row) is False
    assert "🏃‍♂️" not in suffix.plain
    assert suffix.plain == "12:08:32 · 8m32s"
