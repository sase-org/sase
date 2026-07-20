"""Tests for the UpdatesAvailableIndicator widget rendering."""

import subprocess
from pathlib import Path

import pytest

from sase.ace.tui.widgets.updates_indicator import UpdatesAvailableIndicator


def _styles(text: object) -> str:
    return repr(getattr(text, "spans", ()))


def test_zero_updates_renders_hidden_badge() -> None:
    text = UpdatesAvailableIndicator._build_content(0)

    assert text.plain == ""


def test_positive_updates_render_updates_badge() -> None:
    text = UpdatesAvailableIndicator._build_content(3)

    assert text.plain == " ↑ 3 "
    assert "#AF87FF" in _styles(text)


def test_core_update_renders_rebuild_badge() -> None:
    text = UpdatesAvailableIndicator._build_content(3, core=True)

    assert text.plain == " ↑ 3 * "
    assert "#FFAF5F" in _styles(text)


def test_agent_cli_only_renders_labeled_cyan_segment() -> None:
    text = UpdatesAvailableIndicator._build_content(0, agent_cli_count=2)

    assert text.plain == " CLI ↑ 2 "
    assert "#00D7FF" in _styles(text)


def test_mixed_updates_render_joined_domain_segments() -> None:
    text = UpdatesAvailableIndicator._build_content(3, agent_cli_count=2)

    assert text.plain == " ↑ 3 CLI ↑ 2 "
    assert "#AF87FF" in _styles(text)
    assert "#00D7FF" in _styles(text)


def test_mixed_core_updates_preserve_rebuild_signal() -> None:
    text = UpdatesAvailableIndicator._build_content(
        3,
        core=True,
        agent_cli_count=2,
    )

    assert text.plain == " ↑ 3 * CLI ↑ 2 "
    assert "#FFAF5F" in _styles(text)
    assert "#00D7FF" in _styles(text)


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
    assert "Includes sase-core" in str(indicator.tooltip)


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

    assert text.plain == " ↑ 2 * CLI ↑ 1 "
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
