"""Durable coverage for the Admin Center Tools pane (epic sase-1bt.10)."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.config_center_catalog import (
    _TAB_BY_NUMBER,
    _TAB_SPECS,
    validated_center_tab,
)
from sase.ace.tui.modals.tool_runs_pane_data import (
    ToolRunFocusTarget,
    _brief_matches,
    _parse_tool_runs_filter,
    filter_briefs,
    format_run_row,
    order_runs,
)


def _brief(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "run_id": "6c3d5107" + "0" * 24,
        "label": "check",
        "state": "failed",
        "created_ts": 100,
        "tool_name": "check",
        "agent": "0t9--code",
        "project": "sase",
        "owner_kind": None,
        "owner_id": None,
        "verdict": SimpleNamespace(bucket="new_failures"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_tools_tab_is_seven_and_updates_is_eight() -> None:
    assert validated_center_tab("tools") == "tools"
    assert _TAB_BY_NUMBER[7].id == "tools"
    assert _TAB_BY_NUMBER[8].id == "updates"
    assert [spec.id for spec in _TAB_SPECS].index("tools") < [
        spec.id for spec in _TAB_SPECS
    ].index("updates")


def test_tool_runs_keymaps_load_with_tools_scope() -> None:
    keymaps = load_keymap_registry({}).tool_runs
    assert keymaps.toggle_scope == "A"
    assert keymaps.jump_to_agent == "a"
    assert keymaps.open_log == "v"
    assert keymaps.copy_run_id == "y"


def test_filter_parses_scoped_tokens() -> None:
    filt = _parse_tool_runs_filter(
        "tool:check state:failed agent:0t9 verdict:new_failures text"
    )
    assert filt.tool == "check"
    assert filt.state == "failed"
    assert filt.agent == "0t9"
    assert filt.verdict == "new_failures"
    assert filt.text == "text"
    assert _parse_tool_runs_filter("").tool is None


def test_filter_matches_and_rejects() -> None:
    brief = _brief()
    assert _brief_matches(brief, _parse_tool_runs_filter("tool:check"))
    assert _brief_matches(brief, _parse_tool_runs_filter("verdict:new_failures"))
    assert not _brief_matches(brief, _parse_tool_runs_filter("tool:test"))
    assert not _brief_matches(brief, _parse_tool_runs_filter("state:running"))
    assert not _brief_matches(brief, _parse_tool_runs_filter("agent:nobody"))
    assert not _brief_matches(brief, _parse_tool_runs_filter("zzz-no-match"))


def test_project_scope_filters_runs() -> None:
    briefs = [_brief(), _brief(project="other", run_id="a" * 32)]
    assert len(filter_briefs(briefs, "", project="sase")) == 1
    assert len(filter_briefs(briefs, "", project=None)) == 2


def test_order_pins_silent_then_live_then_settled() -> None:
    silent = _brief(run_id="s" * 32, state="running", created_ts=30)
    live = _brief(run_id="l" * 32, state="running", created_ts=20)
    settled = _brief(run_id="x" * 32, state="failed", created_ts=10)
    live_by_id = {
        "s" * 32: SimpleNamespace(last_activity_ts=0),
        "l" * 32: SimpleNamespace(last_activity_ts=1_000_000),
    }
    ordered = order_runs(
        [settled, live, silent],
        live_by_id,  # type: ignore[arg-type]
        now_ts=1_000_010,
        silent_after_s=60,
    )
    assert [kind for kind, _ in ordered] == ["silent", "live", "settled"]
    assert [brief.run_id for _, brief in ordered] == ["s" * 32, "l" * 32, "x" * 32]


def test_run_row_marks_silent_and_includes_id() -> None:
    brief = _brief()
    row = format_run_row("silent", brief)
    assert row.startswith("⚒⚠")
    assert "6c3d5107" in row
    assert format_run_row("settled", brief).startswith("✗")


def test_focus_target_carries_run_id() -> None:
    assert ToolRunFocusTarget(run_id="abc").run_id == "abc"
