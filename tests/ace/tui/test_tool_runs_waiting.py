"""Waiting-queue rendering across the TUI tool-run surfaces."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.modals.tool_runs_pane_data import format_run_row, order_runs
from sase.ace.tui.tool_runs.deck import (
    tool_run_is_silent,
    tool_run_outcome_line,
)
from sase.ace.tui.tool_runs.header_chip import header_chip_for_node
from sase.ace.tui.tool_runs.row_chip import (
    chip_uses_elapsed_fallback,
    row_chip_for_runs,
    tool_run_chip_token,
)
from sase.core.tool_run import (
    ToolRunAdmissionView,
    ToolRunBrief,
    ToolRunGlance,
    ToolRunNodeSummary,
    ToolRunVerdictSummary,
)
from sase.tool.view_vocabulary import (
    header_chip_text,
    row_chip_text,
    run_waiting_ahead,
    style_for_bucket,
)

_NOW = 2000.0


def _waiting_view(ahead: int = 2) -> ToolRunAdmissionView:
    return ToolRunAdmissionView(
        state="waiting",
        key="check",
        limit=1,
        ahead=ahead,
        holders=1,
        requested_ts_ms=1000,
    )


def _glance(run_id: str = "w1", *, ahead: int = 2, **fields: object) -> ToolRunGlance:
    values: dict[str, object] = {
        "run_id": run_id,
        "label": "check",
        "state": "running",
        "created_ts": 1000,
        "last_activity_ts": 1000,
        "stages_done": 0,
    }
    values.update(fields)
    glance = ToolRunGlance(**values)  # type: ignore[arg-type]
    object.__setattr__(glance, "admission", _waiting_view(ahead))
    return glance


def _brief(run_id: str = "w1", *, ahead: int = 2) -> ToolRunBrief:
    brief = ToolRunBrief(
        run_id=run_id,
        label="check",
        state="running",
        created_ts=1000,
        verdict=ToolRunVerdictSummary(bucket="running"),
    )
    object.__setattr__(brief, "admission", _waiting_view(ahead))
    return brief


def test_waiting_bucket_style() -> None:
    style = style_for_bucket("waiting")
    assert style.word == "waiting"
    assert "◷" in style.glyph


def test_run_waiting_ahead_reads_the_view() -> None:
    assert run_waiting_ahead(_glance(ahead=3)) == 3
    assert run_waiting_ahead(SimpleNamespace()) is None
    assert run_waiting_ahead(SimpleNamespace(admission=None)) is None


def test_row_chip_names_the_wait() -> None:
    text, style = row_chip_for_runs((_glance(ahead=2),), _NOW)
    assert "waiting 2" in text
    assert "◷" in text
    assert style == style_for_bucket("waiting").color
    assert "silent" not in text


def test_row_chip_token_moves_with_ahead() -> None:
    first = tool_run_chip_token((_glance(ahead=2),), _NOW)
    second = tool_run_chip_token((_glance(ahead=1),), _NOW)
    assert first is not None and second is not None
    assert first != second


def test_row_chip_waiting_never_silent_or_elapsed() -> None:
    glance = _glance()
    assert chip_uses_elapsed_fallback((glance,), _NOW) is False
    assert "silent" not in row_chip_text("check", waiting_ahead=1)


def test_header_chip_names_the_wait() -> None:
    text = header_chip_text("check", "waiting", waiting_ahead=1, waiting_key="check")
    assert text == "⚒◷ check · waiting for check (1 ahead)"


def test_header_chip_for_node_prefers_waiting() -> None:
    summary = ToolRunNodeSummary(
        key="agent",
        live=(_glance(run_id="w1", last_activity_ts=1000),),
        latest_by_tool=(),
        runs=(),
    )
    agent = SimpleNamespace(
        fleet_origin_alias=None,
        is_clan_container=False,
        agent_name="ag",
        workspace_num=None,
    )
    rendered = header_chip_for_node(
        agent,
        summary,
        snapshot_runs=(_glance(run_id="w1", last_activity_ts=1000),),
        snapshot_silent_after_s=60,
        now_ts=_NOW + 900,
    )
    assert rendered is not None
    text, style, run_id = rendered
    assert "waiting for check (2 ahead)" in text
    assert style == style_for_bucket("waiting").color
    assert run_id == "w1"


def test_deck_outcome_line_names_the_wait() -> None:
    line = tool_run_outcome_line(_brief(ahead=1), None, now_s=_NOW)
    assert "waiting for check (1 ahead)" in line.plain
    assert tool_run_is_silent(_brief(), _NOW) is False


def test_pane_order_keeps_waiting_out_of_silent() -> None:
    brief = _brief()
    glance = _glance(last_activity_ts=100)
    ordered = order_runs([brief], {"w1": glance}, now_ts=int(_NOW), silent_after_s=60)
    assert [(kind, b.run_id) for kind, b in ordered] == [("live", "w1")]
    assert "waiting for check" in format_run_row("live", brief)
