"""Grouping-mode refresh paths for finalized Agents-tab display diffs."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode

from ._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _display_costs,
)


def _by_status_app(agents: list[Agent], monkeypatch: Any) -> _DisplayDiffApp:
    """Build a single-panel app rendered under the BY_STATUS bucket tree."""
    app = _DisplayDiffApp(agents, monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    # Re-render so the widgets carry the BY_STATUS status-bucket tree (and the
    # per-row patch context the row-patch path reads).
    app._refresh_panel_widgets(jump_hints=None)
    return app


def _by_machine_app(agents: list[Agent], monkeypatch: Any) -> _DisplayDiffApp:
    """Build a single-panel app rendered under the BY_MACHINE bucket tree."""
    app = _DisplayDiffApp(agents, monkeypatch)
    app._grouping_mode = GroupingMode.BY_MACHINE
    app._refresh_panel_widgets(jump_hints=None)
    return app


def _clan_projection(status: str) -> list[Agent]:
    member = _agent("research.member", tribe=None, suffix="member", status=status)
    member.agent_clan = "research"
    member.agent_clan_generation = "20260718120000"
    return project_clan_tree([member])


def test_standard_clan_status_bucket_change_rebuilds_instead_of_patching(
    monkeypatch: Any,
) -> None:
    previous_agents = _clan_projection("RUNNING")
    next_agents = _clan_projection("DONE")
    app = _DisplayDiffApp(previous_agents, monkeypatch)
    app._agents_refresh_trace_records.clear()

    app._agents = next_agents
    app._refresh_agents_display_after_finalize(
        previous_agents=previous_agents,
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert any(
        record.fallback_reason == "clan_member_order_change"
        for record in app._agents_refresh_trace_records
    )
    assert "display_full_rebuild" in _display_costs(app)


def test_standard_clan_badge_only_change_patches_in_place(monkeypatch: Any) -> None:
    projected = _clan_projection("RUNNING")
    app = _DisplayDiffApp(projected, monkeypatch)
    app._agents_refresh_trace_records.clear()
    member = projected[1]

    member.live_file_change_hint = True

    assert app._try_patch_agent_row(member) is True
    assert app.full_rebuilds == 0
    assert app._agents_refresh_trace_records[-1].fallback_reason is None
    assert "row_patch" in _display_costs(app)


def test_by_status_badge_only_change_patches_in_place(monkeypatch: Any) -> None:
    # Regression: a deferred live-hint pencil on a redirected Plan row used to
    # wait for the next full rebuild because BY_STATUS vetoed every row patch.
    agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _by_status_app([agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    # Badge-only live-hint flip on the same row keeps it in the Running bucket.
    agent.live_file_change_hint = True
    assert app._try_patch_agent_row(agent) is True

    assert app.full_rebuilds == 0
    costs = _display_costs(app)
    assert "row_patch" in costs
    assert "display_full_rebuild" not in costs
    assert app._agents_refresh_trace_records[-1].fallback_reason is None


def test_by_status_status_bucket_move_refuses_row_patch(monkeypatch: Any) -> None:
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _by_status_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    new_agent = replace(old_agent, status="DONE")
    app._agents = [new_agent]

    # Running -> Done crosses status buckets, so the in-place patch must refuse
    # and leave the caller to rebuild the affected panel.
    assert app._try_patch_agent_row(new_agent) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "unsupported_grouping"
    )


def test_by_status_launch_anchor_change_refuses_row_patch(monkeypatch: Any) -> None:
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _by_status_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    new_agent = replace(
        old_agent,
        start_time=datetime(2026, 6, 8, 12, 1, 0),
    )
    app._agents = [new_agent]

    assert app._try_patch_agent_row(new_agent) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "unsupported_grouping"
    )


def test_by_machine_status_bucket_move_refuses_row_patch(monkeypatch: Any) -> None:
    # A status-bucket crossing change (Running -> Done) moves the row to a
    # different status subgroup, so the strengthened machine_grouping_signature
    # must force a rebuild rather than patch the stale-positioned row in place.
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    old_agent.fleet_origin_alias = "apollo"
    new_agent = replace(old_agent, status="DONE")
    app = _by_machine_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    app._agents = [new_agent]

    assert app._try_patch_agent_row(new_agent) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "unsupported_grouping"
    )


def test_by_machine_badge_only_change_patches_in_place(monkeypatch: Any) -> None:
    # A same-bucket, badge-only change (e.g. a deferred live-hint pencil)
    # leaves every machine_grouping_signature field unchanged, so it still
    # patches in place.
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    old_agent.fleet_origin_alias = "apollo"
    app = _by_machine_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    old_agent.live_file_change_hint = True
    assert app._try_patch_agent_row(old_agent) is True

    assert app.full_rebuilds == 0
    assert "row_patch" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)
    assert app._agents_refresh_trace_records[-1].fallback_reason is None


def test_by_machine_origin_move_refuses_row_patch(monkeypatch: Any) -> None:
    old_agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    old_agent.fleet_origin_alias = "apollo"
    app = _by_machine_app([old_agent], monkeypatch)
    app._agents_refresh_trace_records.clear()

    new_agent = replace(old_agent)
    new_agent.fleet_origin_alias = "zeus"
    app._agents = [new_agent]

    assert app._try_patch_agent_row(new_agent) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "unsupported_grouping"
    )


def test_stale_widget_grouping_mode_falls_back_to_full_rebuild(
    monkeypatch: Any,
) -> None:
    # Reproduces the BY_STATUS -> STANDARD ("by project") cycle: app state
    # advances to STANDARD while the rendered widgets still hold the previous
    # mode's status-bucket tree. Patching those rows in place would leave the
    # stale banners on screen, so the incremental path must defer to a full
    # rebuild instead.
    agent = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _DisplayDiffApp([agent], monkeypatch)
    for widget in app._container.children:
        widget._grouping_mode = GroupingMode.BY_STATUS

    assert app._grouping_mode is GroupingMode.STANDARD

    app._agents = [agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[agent],
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert app._agents_refresh_trace_records[0].fallback_reason == (
        "stale_grouping_mode"
    )
    assert "display_full_rebuild" in _display_costs(app)
