"""Tests for the UpdatesAvailableIndicator widget rendering."""

import subprocess
from pathlib import Path

import pytest

from sase.ace.tui.widgets.update_accents import (
    AGENT_CLI_ACCENT,
    UPDATES_ACCENT,
    UPDATES_SURFACE,
    build_core_tag,
)
from sase.ace.tui.widgets.updates_indicator import UpdatesAvailableIndicator

_IDENTITY_STYLE = f"bold {UPDATES_ACCENT} on {UPDATES_SURFACE}"
_CLI_STYLE = f"bold {AGENT_CLI_ACCENT} on {UPDATES_SURFACE}"


def _styles(text: object) -> str:
    return repr(getattr(text, "spans", ()))


def test_zero_updates_renders_hidden_badge() -> None:
    text = UpdatesAvailableIndicator._build_content(0)

    assert text.plain == ""


def test_positive_updates_render_updates_badge() -> None:
    text = UpdatesAvailableIndicator._build_content(3)

    assert text.plain == " ⬆ 3 "
    assert _IDENTITY_STYLE in _styles(text)


def test_core_update_renders_rebuild_badge() -> None:
    text = UpdatesAvailableIndicator._build_content(3, core=True)

    assert text.plain == " ⬆ 3  core "
    assert _IDENTITY_STYLE in _styles(text)
    assert str(build_core_tag().style) in _styles(text)
    assert "core" in text.plain


def test_core_tag_requires_a_sase_count() -> None:
    without_core = UpdatesAvailableIndicator._build_content(3)
    cli_only = UpdatesAvailableIndicator._build_content(0, core=True, agent_cli_count=2)

    assert "core" not in without_core.plain
    assert cli_only.plain == " CLI ⬆ 2 "
    assert "core" not in cli_only.plain
    assert _CLI_STYLE in _styles(cli_only)


def test_agent_cli_only_renders_labeled_sage_segment() -> None:
    text = UpdatesAvailableIndicator._build_content(0, agent_cli_count=2)

    assert text.plain == " CLI ⬆ 2 "
    assert _CLI_STYLE in _styles(text)


def test_mixed_updates_render_joined_domain_segments() -> None:
    text = UpdatesAvailableIndicator._build_content(3, agent_cli_count=2)

    assert text.plain == " ⬆ 3  CLI ⬆ 2 "
    assert _IDENTITY_STYLE in _styles(text)
    assert _CLI_STYLE in _styles(text)


def test_mixed_core_updates_preserve_rebuild_signal() -> None:
    text = UpdatesAvailableIndicator._build_content(
        3,
        core=True,
        agent_cli_count=2,
    )

    assert text.plain == " ⬆ 3  core  CLI ⬆ 2 "
    assert _IDENTITY_STYLE in _styles(text)
    assert _CLI_STYLE in _styles(text)
    assert str(build_core_tag().style) in _styles(text)


def test_tooltip_separates_domains_and_manual_only_updates() -> None:
    assert UpdatesAvailableIndicator._build_tooltip(
        2,
        agent_cli_count=1,
        manual_agent_cli_count=1,
    ) == (
        "2 SASE/core/plugin updates and 1 agent CLI update available. "
        "Click to open Updates, or press ,U to update the eligible set from "
        "the latest completed background check. 1 agent CLI update requires "
        "manual action."
    )


def test_core_tooltip_explains_rebuild_cost() -> None:
    assert UpdatesAvailableIndicator._build_tooltip(3, core=True) == (
        "3 SASE/core/plugin updates available. Includes sase-core "
        "(Rust rebuild, expect a slower update). Click to open Updates, "
        "or press ,U to update the eligible set from the latest completed "
        "background check."
    )


def test_set_available_updates_domain_counts_and_tooltip() -> None:
    indicator = UpdatesAvailableIndicator()

    indicator.set_available(
        2,
        agent_cli_count=1,
        manual_agent_cli_count=1,
    )

    assert indicator.count == 3
    assert indicator.sase_count == 2
    assert indicator.agent_cli_count == 1
    assert indicator.manual_agent_cli_count == 1
    assert indicator.core is False
    assert "1 agent CLI update requires manual action" in str(indicator.tooltip)


def test_set_available_reacts_when_core_changes_at_same_count() -> None:
    indicator = UpdatesAvailableIndicator()
    indicator.set_available(2)

    indicator.set_available(2, core=True)

    assert indicator.count == 2
    assert indicator.core is True
    rendered = UpdatesAvailableIndicator._build_content(
        indicator.sase_count,
        core=indicator.core,
        agent_cli_count=indicator.agent_cli_count,
    )
    assert "core" in rendered.plain
    assert "Includes sase-core" in str(indicator.tooltip)


def test_set_available_without_sase_count_shows_no_core_tag() -> None:
    indicator = UpdatesAvailableIndicator()

    indicator.set_available(0, core=True, agent_cli_count=2)

    assert indicator.core is False
    rendered = UpdatesAvailableIndicator._build_content(
        indicator.sase_count,
        core=True,
        agent_cli_count=indicator.agent_cli_count,
    )
    assert "core" not in rendered.plain


def test_render_helpers_perform_no_disk_or_subprocess_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("indicator render paths must stay in-memory")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(subprocess, "run", fail)

    text = UpdatesAvailableIndicator._build_content(
        2,
        core=True,
        agent_cli_count=1,
    )
    tooltip = UpdatesAvailableIndicator._build_tooltip(
        2,
        core=True,
        agent_cli_count=1,
        manual_agent_cli_count=1,
    )

    assert text.plain == " ⬆ 2  core  CLI ⬆ 1 "
    assert "manual action" in tooltip


async def test_click_dispatches_open_updates_panel_action() -> None:
    from textual.app import App, ComposeResult

    calls: list[str] = []

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield UpdatesAvailableIndicator(id="updates-indicator")

        def action_open_updates_panel(self) -> None:
            calls.append("opened")

    app = _TestApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(1)
        await pilot.click("#updates-indicator")
        await pilot.pause()
        assert calls == ["opened"]


def test_running_only_renders_gear_and_visible_group() -> None:
    indicator = UpdatesAvailableIndicator()
    indicator.set_running(("comprehensive update",))

    assert indicator.running_count == 1
    assert UpdatesAvailableIndicator._build_content(0, gear="updating").plain == " ⚙ "
    assert indicator.group_visible is True


def test_running_with_counts_renders_gear_first() -> None:
    text = UpdatesAvailableIndicator._build_content(3, gear="updating")

    assert text.plain == " ⚙  ⬆ 3 "


def test_running_full_combination_renders_gear_core_and_cli() -> None:
    text = UpdatesAvailableIndicator._build_content(
        3, core=True, agent_cli_count=2, gear="updating"
    )

    assert text.plain == " ⚙  ⬆ 3  core  CLI ⬆ 2 "


def test_not_running_output_is_unchanged() -> None:
    assert UpdatesAvailableIndicator._build_content(3).plain == " ⬆ 3 "
    assert UpdatesAvailableIndicator._build_content(0).plain == ""


def test_set_running_noops_on_unchanged_tuple() -> None:
    indicator = UpdatesAvailableIndicator()
    indicator.set_running(("a",))
    body_before = indicator._body.plain
    tooltip_before = indicator.tooltip

    indicator.set_running(("a",))

    assert indicator._body.plain == body_before
    assert indicator.tooltip == tooltip_before


def test_set_available_and_set_running_do_not_overwrite_each_other() -> None:
    indicator = UpdatesAvailableIndicator()
    indicator.set_available(3)
    indicator.set_running(("comprehensive update",))

    assert "⬆ 3" in indicator._body.plain
    assert "⚙" in indicator._body.plain

    indicator.set_available(5)

    assert "⬆ 5" in indicator._body.plain
    assert "⚙" in indicator._body.plain
    assert "comprehensive update" in str(indicator.tooltip)


def test_updating_tooltip_single_label() -> None:
    tooltip = UpdatesAvailableIndicator._build_tooltip(
        3, running_labels=("comprehensive update",)
    )

    assert "Update in progress: comprehensive update" in tooltip
    assert "Click to watch it in the Procs tab." in tooltip
    assert "3 SASE/core/plugin updates available." in tooltip
    assert ",U" not in tooltip
    assert "Click to open Updates" not in tooltip


def test_updating_tooltip_multiple_labels() -> None:
    tooltip = UpdatesAvailableIndicator._build_tooltip(
        0, running_labels=("alpha", "beta")
    )

    assert "2 updates in progress: alpha, beta" in tooltip
    assert "Click to watch it in the Procs tab." in tooltip


def test_not_updating_tooltip_is_unchanged() -> None:
    assert UpdatesAvailableIndicator._build_tooltip(0) == "No updates available"
    assert "Click to open Updates" in UpdatesAvailableIndicator._build_tooltip(3)


async def test_click_while_running_dispatches_open_update_procs() -> None:
    from textual.app import App, ComposeResult

    calls: list[str] = []

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield UpdatesAvailableIndicator(id="updates-indicator")

        def action_open_updates_panel(self) -> None:
            calls.append("updates")

        def action_open_update_procs(self) -> None:
            calls.append("procs")

    app = _TestApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3)
        indicator.set_running(("comprehensive update",))
        await pilot.click("#updates-indicator")
        await pilot.pause()
        assert calls == ["procs"]

        calls.clear()
        indicator.set_running(())
        await pilot.click("#updates-indicator")
        await pilot.pause()
        assert calls == ["updates"]


def _pending(
    labels: tuple[str, ...] = ("sync", "mail"),
    identities: tuple[str, ...] = ("sync-1", "mail-1"),
) -> object:
    from sase.ace.tui.update_gear import PendingUpdateRestart

    return PendingUpdateRestart(
        blocker_labels=labels,
        blocker_identities=identities,
        queued_at=1700000000.0,
        restart_by=1700000060.0,
    )


def test_gear_precedence_green_over_yellow() -> None:
    from sase.ace.tui.update_gear import resolve_update_gear

    assert (
        resolve_update_gear(updating=True, restart_pending=True, failed=False)
        == "updating"
    )
    assert (
        resolve_update_gear(updating=False, restart_pending=True, failed=False)
        == "restart_pending"
    )
    assert resolve_update_gear(updating=False, restart_pending=False, failed=True) == (
        "failed"
    )
    assert (
        resolve_update_gear(updating=False, restart_pending=False, failed=False) is None
    )


def test_pending_only_badge_renders_gear_with_zero_counts() -> None:
    indicator = UpdatesAvailableIndicator()
    indicator.set_restart_pending(_pending())  # type: ignore[arg-type]

    assert indicator.gear_state == "restart_pending"
    assert indicator._body.plain == " ⚙ "
    assert indicator.group_visible is True
    assert UpdatesAvailableIndicator._build_content(
        0, gear="restart_pending"
    ).plain == (" ⚙ ")


def test_pending_badge_holds_single_gear_under_precedence() -> None:
    indicator = UpdatesAvailableIndicator()
    indicator.set_available(2)
    indicator.set_running(("comprehensive update",))
    indicator.set_restart_pending(_pending())  # type: ignore[arg-type]

    assert indicator.gear_state == "updating"
    assert indicator._body.plain.count("⚙") == 1

    indicator.set_running(())

    assert indicator.gear_state == "restart_pending"
    assert indicator._body.plain.count("⚙") == 1


def test_yellow_tooltip_lists_blockers_with_more_and_time() -> None:
    from sase.ace.tui.update_gear import PendingUpdateRestart

    pending = PendingUpdateRestart(
        blocker_labels=("sync", "mail", "a", "b"),
        blocker_identities=("1", "2", "3", "4"),
        queued_at=1700000000.0,
        restart_by=1700000060.0,
    )
    tooltip = UpdatesAvailableIndicator._build_tooltip(0, pending_restart=pending)

    assert "New SASE code installed" in tooltip
    assert "sync, mail, a +1 more" in tooltip
    assert "Click to see what it is waiting on." in tooltip
    assert ":" in tooltip


def test_set_restart_pending_noops_on_equal_value() -> None:
    indicator = UpdatesAvailableIndicator()
    indicator.set_restart_pending(_pending())  # type: ignore[arg-type]
    body_before = indicator._body.plain
    tooltip_before = indicator.tooltip

    indicator.set_restart_pending(_pending())  # type: ignore[arg-type]

    assert indicator._body.plain == body_before
    assert indicator.tooltip == tooltip_before


async def test_click_while_pending_dispatches_open_restart_blockers() -> None:
    from textual.app import App, ComposeResult

    calls: list[str] = []

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield UpdatesAvailableIndicator(id="updates-indicator")

        def action_open_updates_panel(self) -> None:
            calls.append("updates")

        def action_open_update_procs(self) -> None:
            calls.append("procs")

        def action_open_restart_blockers(self) -> None:
            calls.append("blockers")

    app = _TestApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_restart_pending(_pending())  # type: ignore[arg-type]
        await pilot.click("#updates-indicator")
        await pilot.pause()
        assert calls == ["blockers"]

        calls.clear()
        indicator.set_restart_pending(None)
        await pilot.click("#updates-indicator")
        await pilot.pause()
        assert calls == ["updates"]
