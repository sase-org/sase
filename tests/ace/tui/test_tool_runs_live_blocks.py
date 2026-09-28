"""Tests for the runs-card-live phase (epic sase-1bt, sase-1bt.8).

A live run's block progresses in place: a pure 1 Hz elapsed repaint
from the cached detail plus ``now`` (no I/O), a detail refetch only on
glance drift, pending stages from the reference run, silent state from
``now`` alone, follow-versus-hold on new arrivals, and an in-place
settle transition that keeps the cursor and the block id.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.tool_runs.blocks import render_tool_run_block
from sase.ace.tui.tool_runs.deck import (
    ToolRunsDetailLevel,
    tool_run_is_silent,
    tool_run_outcome_line,
)
from sase.ace.tui.tool_runs import detail as _detail_module
from sase.ace.tui.widgets.decks.tool_runs import view as _view_module
from sase.ace.tui.widgets.decks.tool_runs import widget as _widget_module
from sase.ace.tui.widgets.decks.tool_runs import widget_live as _widget_live_module
from sase.ace.tui.widgets.decks.tool_runs.document import build_tool_runs_document
from sase.ace.tui.widgets.decks.tool_runs.live import (
    live_detail_drifted,
    tool_runs_rows_have_live,
    want_live_tick,
)
from sase.core.tool_run import (
    ToolRunBrief,
    ToolRunDetail,
    ToolRunDetailStage,
    ToolRunDetailStageCounts,
    ToolRunExpectedStage,
    ToolRunGlance,
    ToolRunGlanceStage,
    ToolRunVerdictSummary,
)

NOW = 1_758_600_000.0


def _glance(
    run_id: str = "6c3d5107" + "0" * 24,
    *,
    state: str = "running",
    stage: str | None = "test (scoped)",
    done: int = 6,
    expected: int = 11,
    last_activity_ago_s: float = 5.0,
    elapsed_s: float = 133.0,
    typical_ms: int | None = 253_000,
    stop_requested: bool = False,
) -> ToolRunGlance:
    created = int(NOW - elapsed_s - 60)
    return ToolRunGlance(
        run_id=run_id,
        label="check",
        state=state,
        created_ts=created,
        last_activity_ts=int(NOW - last_activity_ago_s),
        stages_done=done,
        stop_requested=stop_requested,
        tool_name="check",
        agent="0t9--code",
        running_ts=int(NOW - elapsed_s),
        current_stage=(
            ToolRunGlanceStage(description=stage, started_ms=int((NOW - 20) * 1000))
            if stage is not None
            else None
        ),
        stages_expected=expected,
        typical_ms=typical_ms,
    )


def _brief(
    run_id: str,
    bucket: str = "running",
    **counts: Any,
) -> ToolRunBrief:
    return ToolRunBrief(
        run_id=run_id,
        label="check",
        state="running" if bucket == "running" else "succeeded",
        created_ts=int(NOW - 200),
        verdict=ToolRunVerdictSummary(bucket=bucket, **counts),
        running_ts=int(NOW - 133),
    )


def _stage(
    description: str,
    started_ms: int | None,
    elapsed_ms: int | None,
    exit_code: int | None = 0,
) -> ToolRunDetailStage:
    finished = (
        None if started_ms is None or elapsed_ms is None else started_ms + elapsed_ms
    )
    return ToolRunDetailStage(
        description=description,
        started_ms=started_ms,
        finished_ms=finished,
        elapsed_ms=elapsed_ms,
        exit_code=exit_code,
        counts=ToolRunDetailStageCounts(),
    )


def _live_stages() -> tuple[Any, ...]:
    """Stages stamped near NOW so live bars and durations stay sane."""

    base = int(NOW * 1000) - 133_000
    return (
        _stage("fmt (python)", base, 300),
        _stage("lint (mypy)", base + 300, 63_000),
        _stage("test (scoped)", base + 63_300, None, exit_code=None),
    )


def _detail(**overrides: Any) -> ToolRunDetail:
    kwargs: dict[str, Any] = {
        "store_exists": True,
        "found": True,
        "display_argv": ("just", "check"),
        "stages": _live_stages(),
        "expected_stages": (ToolRunExpectedStage("test (scoped)", 91_000),),
        "triage_items": (),
    }
    kwargs.update(overrides)
    return ToolRunDetail(**kwargs)


def _live_row_no_progress(run_id: str) -> SimpleNamespace:
    """A live row without glance progress fields (detail must supply them)."""

    return SimpleNamespace(
        run_id=run_id,
        label="check",
        state="running",
        verdict=None,
        created_ts=int(NOW - 200),
        running_ts=int(NOW - 70),
        last_activity_ts=int(NOW - 5),
        typical_ms=None,
        stop_requested=False,
        agent="0t9--code",
        bead=None,
        workspace=None,
        owner_kind=None,
        owner_id=None,
    )


def _tail() -> SimpleNamespace:
    return SimpleNamespace(
        availability="available",
        source="run",
        lines=("line 0",),
        total_bytes=64,
        truncated=False,
    )


def _loaded(run_id: str, detail: ToolRunDetail) -> SimpleNamespace:
    return SimpleNamespace(run_id=run_id, detail=detail, tail=_tail(), live=True)


def test_live_outcome_line_progress_and_typical() -> None:
    line = tool_run_outcome_line(_glance(), now_s=NOW)
    assert line is not None
    text = line.plain
    assert "⚒ check" in text
    assert "▶ running" in text
    assert "test (scoped)" in text
    assert "7/11" in text
    assert "2m13s / typ 4m13s" in text


def test_live_outcome_line_from_detail_stages() -> None:
    row = _live_row_no_progress("d" * 32)
    detail = _detail(
        expected_stages=(
            ToolRunExpectedStage("test (scoped)", 91_000),
            ToolRunExpectedStage("deploy (prod)", 12_000),
        )
    )
    line = tool_run_outcome_line(row, detail, now_s=NOW)
    assert line is not None
    text = line.plain
    assert "test (scoped)" in text
    assert "3/4" in text


def test_live_outcome_overflow_falls_back_to_elapsed() -> None:
    row = _glance(done=11, expected=11)
    line = tool_run_outcome_line(row, now_s=NOW)
    assert line is not None
    assert "12/11" not in line.plain
    assert "2m13s" in line.plain


def test_live_starting_and_stopping() -> None:
    starting = tool_run_outcome_line(_glance(state="created", stage=None), now_s=NOW)
    assert starting is not None and "starting" in starting.plain
    stopping = tool_run_outcome_line(_glance(stop_requested=True), now_s=NOW)
    assert stopping is not None and "stopping" in stopping.plain


def test_silent_block_renders_from_now_alone() -> None:
    row = _glance(last_activity_ago_s=4 * 24 * 3600)
    assert tool_run_is_silent(row, NOW)
    line = tool_run_outcome_line(row, now_s=NOW)
    assert line is not None
    assert "⚒⚠" in line.plain
    assert "silent 4d" in line.plain
    assert "last activity" in line.plain
    assert "test (scoped)" in line.plain
    text = render_tool_run_block(
        row, _detail(), tail=_tail(), now_s=NOW, include_outcome=True
    ).plain
    assert "The TUI never settles runs" in text
    # Fresh activity is not silent and carries no hint.
    fresh = render_tool_run_block(_glance(), _detail(), tail=_tail(), now_s=NOW).plain
    assert "silent" not in fresh
    assert "The TUI never settles runs" not in fresh


def test_settled_outcome_ignores_clock() -> None:
    row = ToolRunBrief(
        run_id="a" * 32,
        label="check",
        state="succeeded",
        created_ts=int(NOW - 300),
        verdict=ToolRunVerdictSummary(bucket="pass"),
        duration_ms=241_000,
        settled_ts=NOW - 60,
    )
    clocked = tool_run_outcome_line(row, now_s=NOW).plain
    unclocked = tool_run_outcome_line(row).plain
    assert clocked == unclocked
    text = render_tool_run_block(row, _detail(), tail=_tail(), now_s=NOW).plain
    assert "▶ running" not in text
    assert "pass" in text


def test_inflight_bar_grows_with_now_and_no_io(monkeypatch: Any) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("render path must not touch the loader")

    monkeypatch.setattr(_detail_module, "tool_run_detail", _boom)
    row = _glance()
    first = render_tool_run_block(row, _detail(), tail=_tail(), now_s=NOW).plain
    second = render_tool_run_block(row, _detail(), tail=_tail(), now_s=NOW + 30).plain
    assert "▶" in first and "▶" in second
    assert "…" in first and "…" in second
    assert first != second
    assert "2m13s" in first
    assert "2m43s" in second


def test_want_live_tick_gate() -> None:
    assert want_live_tick(
        visible=True, has_live=True, navigating=False, typing=False, in_flight=False
    )
    assert not want_live_tick(
        visible=False, has_live=True, navigating=False, typing=False, in_flight=False
    )
    assert not want_live_tick(
        visible=True, has_live=False, navigating=False, typing=False, in_flight=False
    )
    assert not want_live_tick(
        visible=True, has_live=True, navigating=True, typing=False, in_flight=False
    )
    assert not want_live_tick(
        visible=True, has_live=True, navigating=False, typing=True, in_flight=False
    )
    assert not want_live_tick(
        visible=True, has_live=True, navigating=False, typing=False, in_flight=True
    )


def _token(value: int) -> SimpleNamespace:
    return SimpleNamespace(surface="tool_runs", indeterminate=False, value=value)


def test_live_detail_drifted() -> None:
    assert not live_detail_drifted(None, _token(1))
    assert live_detail_drifted(_token(2), None)
    assert not live_detail_drifted(_token(1), _token(1))
    assert live_detail_drifted(_token(2), _token(1))
    assert not tool_runs_rows_have_live(())
    assert tool_runs_rows_have_live((_glance(),))
    assert not tool_runs_rows_have_live((_brief("c" * 32, bucket="pass", new=0),))


def _live_view(rows: tuple[Any, ...], details: dict[str, Any]) -> Any:
    view = _view_module.ToolRunsDeckView.__new__(_view_module.ToolRunsDeckView)
    view._detail_level = ToolRunsDetailLevel.STANDARD
    view._active_card = "runs"
    view._block_cursors = {}
    view._block_cursor_subject = None
    view._block_modes = {}
    view._block_projected = None
    view._live_rows = rows
    view._live_details = dict(details)
    view._live_total_runs = len(rows)
    view._live_truncated = False
    view._live_subject = object()
    view._live_signature = "sig"
    view._painted_store_token = _token(1)
    view._current_agent = SimpleNamespace(identity="agent-1")
    view._current_generation = 3
    view._current_preferred = None
    view._current_worker = None
    view._live_timer = None
    return view


def test_pure_repaint_advances_without_io(monkeypatch: Any) -> None:
    from sase.ace.tui.tool_runs import detail as detail_module
    from sase.ace.tui.tool_runs.deck import tool_runs_card_search_text

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("pure repaint must not load details")

    monkeypatch.setattr(detail_module, "load_tool_run_detail_blocking", _boom)
    monkeypatch.setattr(detail_module, "cached_tool_run_detail", _boom)
    monkeypatch.setattr(_widget_live_module, "tool_runs_render_width", lambda view: 100)
    monkeypatch.setattr(
        _widget_live_module, "tool_runs_hint_numbers", lambda view: None
    )
    monkeypatch.setattr(_widget_module, "tool_runs_render_width", lambda view: 100)
    monkeypatch.setattr(_widget_module, "tool_runs_hint_numbers", lambda view: None)
    live = _glance(run_id="d" * 32)
    settled = ToolRunBrief(
        run_id="e" * 32,
        label="test",
        state="succeeded",
        created_ts=int(NOW - 400),
        verdict=ToolRunVerdictSummary(bucket="pass"),
        duration_ms=62_000,
    )
    rows = (settled, live)
    detail = _detail()
    view = _live_view(rows, {"d" * 32: _loaded("d" * 32, detail)})
    shown: list[Any] = []
    monkeypatch.setattr(
        _view_module.ToolRunsDeckView,
        "show_tool_runs_document",
        lambda self, document, card: shown.append(document) or card,
    )
    frozen = {"now": NOW}
    monkeypatch.setattr(_widget_live_module.time, "time", lambda: frozen["now"])
    view._live_pure_repaint()
    assert len(shown) == 1
    first_ids = [block.block_id for block in shown[0].cards[0].blocks]
    assert first_ids == ["e" * 32, "d" * 32]
    first_text = tool_runs_card_search_text(shown[0].cards[0].renderables)
    frozen["now"] = NOW + 30
    view._live_pure_repaint()
    assert len(shown) == 2
    second_ids = [block.block_id for block in shown[1].cards[0].blocks]
    assert second_ids == first_ids
    second_text = tool_runs_card_search_text(shown[1].cards[0].renderables)
    assert second_text != first_text
    assert "2m43s" in second_text


def test_tick_reloads_only_on_drift(monkeypatch: Any) -> None:
    row = _brief("e" * 32)
    view = _live_view((row,), {})
    monkeypatch.setattr(_widget_live_module, "live_host_visible", lambda view: True)
    monkeypatch.setattr(_widget_live_module, "live_navigating", lambda view: False)
    monkeypatch.setattr(_widget_live_module, "live_typing", lambda view: False)
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        _view_module.ToolRunsDeckView,
        "_live_pure_repaint",
        lambda self: calls.setdefault("pure", 0) or calls.update(pure=1),
    )
    seen: dict[str, Any] = {}

    def _fake_update(self: Any, agent: Any, **kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(_view_module.ToolRunsDeckView, "update_display", _fake_update)
    import sase.ace.tui.tool_runs.snapshot as snapshot_module

    monkeypatch.setattr(
        snapshot_module, "get_snapshot", lambda: SimpleNamespace(store_token=_token(1))
    )
    view._on_live_timer()
    assert "force" not in seen
    assert calls.get("pure") == 1
    monkeypatch.setattr(
        snapshot_module, "get_snapshot", lambda: SimpleNamespace(store_token=_token(2))
    )
    view._on_live_timer()
    assert seen.get("force") is True


def test_follow_hold_and_settle_cursors() -> None:
    view = _live_view((), {})
    subject = object()
    first = build_tool_runs_document(
        (_brief("a" * 32), _brief("b" * 32)), subject=subject, digest="d1"
    )
    view._reconcile_block_cursors(first, new_subject=True, enabled=True)
    cursor = view._block_cursors.get("runs")
    assert cursor is not None and cursor.block_id == "b" * 32
    assert cursor.following
    # A parked reader holds while the arrival dot marks the new block.
    from sase.ace.tui.widgets.decks.block_model import arrived_ids, step_cursor

    parked = step_cursor(("a" * 32, "b" * 32), cursor, -1)
    assert parked is not None and parked.block_id == "a" * 32
    view._block_cursors["runs"] = parked
    second = build_tool_runs_document(
        (_brief("a" * 32), _brief("b" * 32), _brief("c" * 32)),
        subject=subject,
        digest="d2",
    )
    view._reconcile_block_cursors(second, new_subject=False, enabled=True)
    held = view._block_cursors.get("runs")
    assert held is not None and held.block_id == "a" * 32
    assert arrived_ids(("a" * 32, "b" * 32, "c" * 32), held) == ("c" * 32,)
    # A follower lands on the arrival; a settle keeps the block id.
    view._block_cursors["runs"] = cursor
    view._reconcile_block_cursors(second, new_subject=False, enabled=True)
    assert view._block_cursors["runs"].block_id == "c" * 32
    settled = build_tool_runs_document(
        (_brief("a" * 32), _brief("b" * 32), _brief("c" * 32)),
        subject=subject,
        digest="d3",
    )
    view._reconcile_block_cursors(settled, new_subject=False, enabled=True)
    assert view._block_cursors["runs"].block_id == "c" * 32
