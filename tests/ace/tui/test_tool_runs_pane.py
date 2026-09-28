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


def _pane_row(
    name: str,
    *,
    monitor: bool = False,
    monitor_id: str | None = None,
    proc: bool = False,
    proc_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        identity=("agent", name, ""),
        display_name=name,
        agent_name=name,
        is_monitor=monitor,
        monitor_id=monitor_id,
        is_named_proc=proc,
        proc_id=proc_id,
        fleet_origin_alias=None,
        is_clan_container=False,
    )


def _reveal_app(rows: list[object], selected: object | None = None) -> SimpleNamespace:
    app = SimpleNamespace()
    app._agents = list(rows)
    app._agents_with_children = list(rows)
    app._hideable_agents = []
    app.current_tab = "agents"
    app.current_idx = 0
    app.notifies: list[tuple[str, object]] = []
    app.notify = lambda msg, severity=None: app.notifies.append((msg, severity))  # type: ignore[attr-defined]
    app._panels: list[object] = []
    app._test_tool_run_panels = app._panels
    app.action_show_tool_runs_card = lambda: None  # type: ignore[attr-defined]
    if selected is not None:
        app._get_selected_agent = lambda: selected  # type: ignore[attr-defined]
    else:
        app._get_selected_agent = lambda: rows[0] if rows else None  # type: ignore[attr-defined]
    return app


def _reveal_panel(selected_run: str | None = None) -> SimpleNamespace:
    panel = SimpleNamespace()
    panel.selected: list[str] = []
    panel.cards_shown: list[str] = []
    panel.select_block = lambda block_id: panel.selected.append(block_id) or True  # type: ignore[attr-defined]
    panel._show_tools_card = lambda card_id: (
        panel.cards_shown.append(card_id) or card_id
    )  # type: ignore[attr-defined]
    panel._tool_runs_document = SimpleNamespace(cards=[SimpleNamespace(blocks=[1, 2])])
    panel._availability = {}
    return panel


def test_reveal_inline_agent_run_uses_real_jump_path() -> None:
    from sase.ace.tui.tool_runs.reveal import reveal_tool_run_block

    row = _pane_row("0t9--code")
    app = _reveal_app(
        [row], selected=SimpleNamespace(identity=("x",), agent_name="other")
    )
    panel = _reveal_panel()
    app._panels.append(panel)
    ok = reveal_tool_run_block(app, "a" * 32, agent="0t9--code")
    assert ok is True
    assert app.current_idx == 0
    assert panel.selected == ["a" * 32]
    assert panel.cards_shown == ["runs"]


def test_reveal_monitor_owned_run_selects_monitor_row() -> None:
    from sase.ace.tui.tool_runs.reveal import reveal_tool_run_block

    starter = _pane_row("starter")
    monitor = _pane_row("mon-agent", monitor=True, monitor_id="mon-1")
    app = _reveal_app([starter, monitor], selected=starter)
    panel = _reveal_panel()
    app._panels.append(panel)
    ok = reveal_tool_run_block(
        app, "b" * 32, agent="starter", owner_kind="monitor", owner_id="mon-1"
    )
    assert ok is True
    assert app.current_idx == 1
    assert panel.selected == ["b" * 32]


def test_reveal_miss_toasts_no_agent_row() -> None:
    from sase.ace.tui.tool_runs.reveal import reveal_tool_run_block

    row = _pane_row("someone")
    app = _reveal_app([row], selected=row)
    ok = reveal_tool_run_block(app, "c" * 32, agent="ghost")
    assert ok is False
    assert any("No agent row for ghost" in str(msg) for msg, _ in app.notifies)


def test_failures_detail_lists_affected_runs_and_fallback() -> None:
    from sase.ace.tui.modals.tool_runs_pane_render import ToolRunsPaneRenderMixin

    mixin = ToolRunsPaneRenderMixin.__new__(ToolRunsPaneRenderMixin)
    mixin._failure_groups = [
        {
            "class": "new",
            "tool": "check",
            "stage_key": "lint",
            "display": "bad",
            "runs": 2,
            "agents": 2,
            "signature": "sig",
            "affected_runs": [
                {
                    "run_id": "b" * 32,
                    "agent": "bob",
                    "created_ts": 200,
                    "class": "new",
                    "owner_kind": "monitor",
                    "owner_id": "m-1",
                },
                {"run_id": "a" * 32, "agent": "ann", "created_ts": 100, "class": "new"},
            ],
        }
    ]
    mixin._selected_identity = lambda: "failure-0"  # type: ignore[attr-defined]
    mixin._loaded_once = True
    text = mixin._failures_detail_text()
    assert "affected runs (newest first)" in text
    assert ("b" * 8) in text and ("a" * 8) in text
    assert text.index("b" * 8) < text.index("a" * 8)
    assert "bob" in text and "ann" in text
    # Without affected_runs the pane falls back to last_run_id.
    mixin._failure_groups = [
        {
            "class": "new",
            "tool": "check",
            "stage_key": "lint",
            "display": "bad",
            "runs": 1,
            "agents": 1,
            "signature": "sig",
            "last_run_id": "d" * 32,
        }
    ]
    fallback = mixin._failures_detail_text()
    assert ("d" * 8) in fallback


def test_failures_a_resolves_newest_run() -> None:
    from sase.ace.tui.modals.tool_runs_pane_tool_actions import (
        ToolRunsPaneToolActionsMixin,
    )

    mixin = ToolRunsPaneToolActionsMixin.__new__(ToolRunsPaneToolActionsMixin)
    mixin._failure_groups = [
        {
            "last_run_id": "z" * 32,
            "affected_runs": [
                {
                    "run_id": "b" * 32,
                    "agent": "bob",
                    "owner_kind": "monitor",
                    "owner_id": "m-1",
                },
            ],
        }
    ]
    mixin._selected_identity = lambda: "failure-0"  # type: ignore[attr-defined]
    found = mixin._newest_resolvable_failure_run()
    assert found is not None
    assert found[0] == "b" * 32
    assert found[2] == "monitor"


def test_focus_target_switches_to_runs_and_selects() -> None:
    from sase.ace.tui.modals.tool_runs_pane_shell import ToolRunsPaneShellMixin

    pane = ToolRunsPaneShellMixin.__new__(ToolRunsPaneShellMixin)
    pane._view = "failures"
    pane._loaded_once = True
    pane._pending_run_id = None
    pane._selected_run_id = None
    pane._session_state = SimpleNamespace(pending_run_id=None, active_view="failures")
    seen: dict[str, object] = {}
    pane._set_view = lambda view: (
        seen.__setitem__("view", view) or setattr(pane, "_view", view)
    )  # type: ignore[attr-defined]
    pane._select_run = lambda run_id: True  # type: ignore[attr-defined]
    assert pane.focus_tool_run("e" * 32) is True
    assert seen.get("view") == "runs"
    assert pane._pending_run_id == "e" * 32
