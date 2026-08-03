"""Agent-CLI update-history rendering and scope-toggle tests."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from rich.console import Console
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.plugins_browser_agent_clis_history import (
    build_agent_cli_history_panel,
    _relative_time,
)
from sase.agent_clis.history import AgentCliUpdateRun, AgentCliUpdateRunEntry
from sase.agent_clis.models import UpdateResultStatus, UpdateTrigger

from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
)

_NOW = 1_800_000_000.0
_COLORS = {"claude": "#D97757", "codex": "#10A37F", "qwen": "#FF5FAF"}


def _entry(
    name: str,
    display_name: str,
    status: UpdateResultStatus,
    *,
    old: str | None = "1.0.0",
    new: str | None = "1.1.0",
    reason: str | None = None,
) -> AgentCliUpdateRunEntry:
    command = None
    if status in {UpdateResultStatus.UPDATED, UpdateResultStatus.FAILED}:
        command = (name, "update")
    return AgentCliUpdateRunEntry(
        name=name,
        display_name=display_name,
        status=status,
        old_version=old,
        new_version=new,
        command=command,
        reason=reason,
        elapsed_seconds=2.5,
        output_tail=None,
    )


def _run(
    run_id: str,
    *,
    epoch: float,
    trigger: UpdateTrigger,
    entries: tuple[AgentCliUpdateRunEntry, ...],
    elapsed: float = 9.0,
) -> AgentCliUpdateRun:
    counts = {
        result_status.value: sum(entry.status is result_status for entry in entries)
        for result_status in UpdateResultStatus
    }
    return AgentCliUpdateRun(
        schema_version=1,
        run_id=run_id,
        timestamp="2027-01-15T12:00:00+00:00",
        epoch=epoch,
        trigger=trigger,
        all_clis=len(entries) > 1,
        elapsed_seconds=elapsed,
        counts=counts,
        entries=entries,
    )


def _render_panel(
    runs: tuple[AgentCliUpdateRun, ...],
    *,
    selected: str | None = "claude",
    enabled: bool = True,
    error: str | None = None,
    all_clis: bool = False,
    now: float = _NOW,
    max_rows: int = 8,
) -> str:
    status = next(
        (item for item in _agent_cli_statuses() if item.name == selected),
        None,
    )
    renderable = build_agent_cli_history_panel(
        status,
        runs,
        enabled=enabled,
        error=error,
        all_clis=all_clis,
        now=now,
        max_rows=max_rows,
        colors=_COLORS,
    )
    return _render(renderable)


def _render(renderable: object) -> str:
    output = io.StringIO()
    Console(file=output, width=120, no_color=True).print(renderable)
    return output.getvalue()


def test_per_cli_history_lists_only_executed_selected_entries_newest_first() -> None:
    newest = _run(
        "newest",
        epoch=_NOW - 30,
        trigger=UpdateTrigger.COMPREHENSIVE,
        entries=(
            _entry("claude", "Claude Code", UpdateResultStatus.UPDATED, old="2.0"),
            _entry("codex", "Codex CLI", UpdateResultStatus.UPDATED, old="99.0"),
        ),
    )
    older = _run(
        "older",
        epoch=_NOW - 3_600,
        trigger=UpdateTrigger.ADMIN_CENTER,
        entries=(
            _entry(
                "claude",
                "Claude Code",
                UpdateResultStatus.FAILED,
                old="1.5",
                reason="permission denied",
            ),
        ),
    )
    nonexecuted = _run(
        "noop-context",
        epoch=_NOW - 7_200,
        trigger=UpdateTrigger.CLI,
        entries=(
            _entry(
                "claude",
                "Claude Code",
                UpdateResultStatus.ALREADY_CURRENT,
            ),
            _entry("qwen", "Qwen Code", UpdateResultStatus.SKIPPED),
        ),
    )

    rendered = _render_panel((newest, older, nonexecuted))

    assert rendered.index("2.0") < rendered.index("1.5")
    assert "99.0" not in rendered
    assert "already current" not in rendered
    assert "skipped" not in rendered
    assert "permission denied" in rendered


def test_all_clis_history_groups_runs_and_collapses_nonexecuted_entries() -> None:
    mixed = _run(
        "mixed",
        epoch=_NOW - 7_200,
        trigger=UpdateTrigger.COMPREHENSIVE,
        entries=(
            _entry("claude", "Claude Code", UpdateResultStatus.UPDATED),
            _entry("codex", "Codex CLI", UpdateResultStatus.ALREADY_CURRENT),
            _entry("qwen", "Qwen Code", UpdateResultStatus.SKIPPED),
        ),
    )
    executed_only = _run(
        "executed",
        epoch=_NOW - 10_800,
        trigger=UpdateTrigger.ADMIN_CENTER,
        entries=(_entry("codex", "Codex CLI", UpdateResultStatus.FAILED),),
    )

    rendered = _render_panel((mixed, executed_only), all_clis=True)

    assert rendered.index("2h ago") < rendered.index("3h ago")
    assert "2h ago · ,U · 9.0s" in rendered
    assert "3h ago · A · 9.0s" in rendered
    assert "· 1 already current · ○ 1 skipped" in rendered
    assert rendered.count("already current") == 1
    assert "Claude Code" in rendered
    assert "Codex CLI" in rendered


@pytest.mark.parametrize(
    ("trigger", "badge"),
    [
        (UpdateTrigger.COMPREHENSIVE, ",U"),
        (UpdateTrigger.ADMIN_CENTER, "A"),
        (UpdateTrigger.CLI, "CLI"),
        (UpdateTrigger.UNKNOWN, "—"),
    ],
)
def test_history_trigger_badges(trigger: UpdateTrigger, badge: str) -> None:
    run = _run(
        "badge",
        epoch=_NOW - 30,
        trigger=trigger,
        entries=(_entry("claude", "Claude Code", UpdateResultStatus.UPDATED),),
    )

    rendered = _render_panel((run,), all_clis=True)

    assert f"30s ago · {badge} · 9.0s" in rendered


def test_history_relative_time_boundaries_and_future_clock_skew(
    tz_divergence: None,
) -> None:
    ages = (30, 90, 2 * 3_600, 2 * 86_400, 8 * 86_400, -30)
    runs = tuple(
        _run(
            f"age-{age}",
            epoch=_NOW - age,
            trigger=UpdateTrigger.CLI,
            entries=(_entry("claude", "Claude Code", UpdateResultStatus.UPDATED),),
        )
        for age in ages
    )
    absolute = "Jan 07 03:00"

    rendered = _render_panel(runs, all_clis=True, max_rows=0)

    for expected in ("30s ago", "1m ago", "2h ago", "2d ago", absolute, "just now"):
        assert expected in rendered


def test_history_absolute_time_uses_configured_timezone(tz_divergence: None) -> None:
    epoch = datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp()

    assert _relative_time(epoch, now=epoch + 8 * 86_400) == "Jul 03 06:24"


def test_per_cli_history_row_limit_and_unlimited_subtitle() -> None:
    runs = tuple(
        _run(
            f"run-{index}",
            epoch=_NOW - index * 60 - 1,
            trigger=UpdateTrigger.CLI,
            entries=(
                _entry(
                    "claude",
                    "Claude Code",
                    UpdateResultStatus.UPDATED,
                    old=f"1.{index}.0",
                    new=f"1.{index}.1",
                ),
            ),
        )
        for index in range(5)
    )

    limited = _render_panel(runs, max_rows=2)
    unlimited = _render_panel(runs, max_rows=0)

    assert limited.count("▲") == 2
    assert "2 of 5 runs · H all CLIs" in limited
    assert unlimited.count("▲") == 5
    assert "of 5 runs" not in unlimited
    assert "H all CLIs" in unlimited


def test_history_hidden_without_selection_or_when_disabled() -> None:
    run = _run(
        "hidden",
        epoch=_NOW - 30,
        trigger=UpdateTrigger.CLI,
        entries=(_entry("claude", "Claude Code", UpdateResultStatus.UPDATED),),
    )

    assert not _render_panel((run,), selected=None).strip()
    assert not _render_panel((run,), enabled=False).strip()


def test_history_error_and_empty_states() -> None:
    error = _render_panel((), error="disk gone")
    empty_selected = _render_panel(())
    empty_all = _render_panel((), all_clis=True)

    assert "Could not read update history:" in error
    assert "disk gone" in error
    for rendered in (empty_selected, empty_all):
        assert "No sase-managed agent CLI updates recorded yet." in rendered
        assert "Press A to update agent CLIs, or ,U to update everything." in rendered


def test_history_selected_cli_empty_points_to_other_cli_runs() -> None:
    runs = tuple(
        _run(
            f"other-{index}",
            epoch=_NOW - index * 60 - 1,
            trigger=UpdateTrigger.CLI,
            entries=(_entry("codex", "Codex CLI", UpdateResultStatus.UPDATED),),
        )
        for index in range(3)
    )

    rendered = _render_panel(runs)

    assert "No recorded updates for Claude Code." in rendered
    assert "3 runs recorded for other CLIs — press H to see them." in rendered


async def test_history_scope_toggle_repaints_only_history_and_is_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    run = _run(
        "toggle",
        epoch=1_700_000_000.0 - 30,
        trigger=UpdateTrigger.COMPREHENSIVE,
        entries=(
            _entry("claude", "Claude Code", UpdateResultStatus.UPDATED),
            _entry("codex", "Codex CLI", UpdateResultStatus.UPDATED, old="9.9"),
        ),
    )
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        agent_cli_colors=_COLORS,
        agent_cli_history=(run,),
    )
    state = AdminCenterSessionState()

    async with AcePage() as page:
        pane = await _open_plugins_pane(page, session_state=state)
        assert pane.check_action("toggle_history_scope", ()) is False
        pane._switch_to_subtab("agent-clis")
        assert pane.check_action("toggle_history_scope", ()) is True
        detail_name = pane._agent_cli_detail_name
        history = pane.query_one("#agent-clis-history", Static)

        pane.action_toggle_history_scope()

        assert state.updates.agent_cli_history_all is True
        assert pane._agent_cli_detail_name == detail_name
        assert "Update history · all agent CLIs" in _render(history.content)
        pane._switch_to_subtab("core")
        assert pane.check_action("toggle_history_scope", ()) is False
