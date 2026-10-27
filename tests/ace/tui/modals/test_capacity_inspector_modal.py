"""Tests for the keyboard-first machine-capacity inspector."""

from __future__ import annotations

import argparse
import io
import re
from contextlib import redirect_stdout
from unittest.mock import MagicMock

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.tui.modals.capacity_inspector_modal import (
    CapacityInspectorModal,
    CapacityInspectorSelection,
)
from sase.agents.cli_load import handle_agents_load
from tests._runner_slots_helpers import _record
from tests.test_machine_capacity_report import (
    _report_from_records,
    _screenshot_records,
)


def _report():
    return _report_from_records(_screenshot_records())


def _option_text(option: object) -> str:
    prompt = option.prompt
    return prompt.plain if isinstance(prompt, Text) else str(prompt)


def _select(options: OptionList, option_id: str) -> None:
    options.highlighted = next(
        index for index, option in enumerate(options.options) if option.id == option_id
    )


class _InspectorApp(App[None]):
    def __init__(self, modal: CapacityInspectorModal) -> None:
        super().__init__()
        self.modal = modal
        self.selection: CapacityInspectorSelection | None = None

    def compose(self) -> ComposeResult:
        yield Static("test host")

    def on_mount(self) -> None:
        self.push_screen(self.modal, self._on_dismiss)

    def _on_dismiss(self, selection: CapacityInspectorSelection | None) -> None:
        self.selection = selection


async def test_capacity_inspector_shows_report_and_jumps_from_agent_rows() -> None:
    app = _InspectorApp(CapacityInspectorModal(_report(), running_nodes=6))

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        headline = modal.query_one("#capacity-inspector-headline", Static)
        facts = modal.query_one("#capacity-inspector-facts", Static)
        assert "5 / 8 units in use" in headline.render().plain
        assert "6 running · 5 charged · 1 at 0" in facts.render().plain

        options = modal.query_one("#capacity-inspector-options", OptionList)
        _select(options, "agent:/worker-a")
        await pilot.press("enter")
        await pilot.pause()

    assert app.selection == CapacityInspectorSelection("worker-a", "/worker-a")


async def test_capacity_inspector_folds_groups_with_enter_h_l_and_member_return() -> (
    None
):
    report = _report_from_records(
        [
            _record(f"/idle-{index:02d}", requested_at=None, run_started=False)
            for index in range(12)
        ]
    )
    app = _InspectorApp(CapacityInspectorModal(report, running_nodes=0))

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        options = modal.query_one("#capacity-inspector-options", OptionList)
        group_id = "group:not_started"
        assert any(option.id == group_id for option in options.options)
        assert (
            sum(
                bool(option.id and option.id.startswith("member:"))
                for option in options.options
            )
            == 0
        )

        _select(options, group_id)
        await pilot.press("enter")
        await pilot.pause()
        options = modal.query_one("#capacity-inspector-options", OptionList)
        assert (
            sum(
                bool(option.id and option.id.startswith("member:"))
                for option in options.options
            )
            == 12
        )

        _select(options, "member:not_started:/idle-00")
        await pilot.press("h")
        await pilot.pause()
        options = modal.query_one("#capacity-inspector-options", OptionList)
        assert options.options[options.highlighted].id == group_id
        assert not any(
            option.id and option.id.startswith("member:") for option in options.options
        )

        await pilot.press("l")
        await pilot.pause()
        options = modal.query_one("#capacity-inspector-options", OptionList)
        assert any(
            option.id == "member:not_started:/idle-11" for option in options.options
        )


def test_capacity_inspector_copy_matches_cli_json(monkeypatch: object) -> None:
    report = _report()
    expected = io.StringIO()
    with redirect_stdout(expected):
        handle_agents_load(
            argparse.Namespace(json=True, rescan=False),
            report_fn=lambda force_rescan=False: report,
        )

    schedule = MagicMock()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "sase.ace.tui.modals.capacity_inspector_modal.schedule_copy_delivery",
        schedule,
    )
    CapacityInspectorModal(report, running_nodes=6).action_copy_snapshot()

    assert schedule.call_args.args[1] == expected.getvalue()


def test_capacity_inspector_renders_invalid_and_unavailable_verdicts() -> None:
    invalid = _report()
    object.__setattr__(invalid, "accounting_valid", False)
    invalid_modal = CapacityInspectorModal(invalid, running_nodes=6)
    assert "blocked" in invalid_modal._verdict_text().plain.lower()
    assert "? free" in invalid_modal._headline_text().plain

    unavailable = _report()
    object.__setattr__(unavailable, "accounting_available", False)
    unavailable_modal = CapacityInspectorModal(unavailable, running_nodes=6)
    options = unavailable_modal._build_options()
    assert any("reports totals only" in _option_text(option) for option in options)


def test_capacity_inspector_loading_state_has_no_numbers() -> None:
    modal = CapacityInspectorModal(None, running_nodes=None)
    assert not re.search(r"\d", modal._headline_text().plain)
    assert not re.search(r"\d", modal._verdict_text().plain)


async def test_capacity_inspector_refresh_keeps_identity_then_falls_back_in_section() -> (
    None
):
    modal = CapacityInspectorModal(_report(), running_nodes=6)
    app = _InspectorApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        options = modal.query_one("#capacity-inspector-options", OptionList)
        _select(options, "agent:/worker-b")
        await pilot.pause()
        modal.update_capacity_report(_report(), running_nodes=7)
        options = modal.query_one("#capacity-inspector-options", OptionList)
        assert options.options[options.highlighted].id == "agent:/worker-b"

        reduced = _report_from_records(
            [
                _record("/worker-a", run_started=True),
                _record("/worker-c", run_started=True),
                _record(
                    "/verify-a",
                    agent_session="verify-a",
                    agent_session_role="monitor",
                    monitor_id="verify-a-turn",
                    queue_weight=1.0,
                ),
            ]
        )
        modal.update_capacity_report(reduced, running_nodes=3)
        options = modal.query_one("#capacity-inspector-options", OptionList)
        assert options.options[options.highlighted].id == "agent:/worker-c"
        assert modal.running_nodes == 3


async def test_capacity_inspector_detail_tracks_highlight_and_group_expansion_survives_refresh() -> (
    None
):
    records = [
        _record(f"/idle-{index:02d}", requested_at=None, run_started=False)
        for index in range(4)
    ]
    report = _report_from_records(records)
    modal = CapacityInspectorModal(report, running_nodes=0)
    app = _InspectorApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        options = modal.query_one("#capacity-inspector-options", OptionList)
        _select(options, "group:not_started")
        await pilot.press("l")
        await pilot.pause()
        options = modal.query_one("#capacity-inspector-options", OptionList)
        _select(options, "member:not_started:/idle-00")
        await pilot.pause()
        detail = modal.query_one("#capacity-inspector-detail", Static).render().plain
        assert "waiting to start" in detail
        assert "idle-00" in detail

        modal.update_capacity_report(report, running_nodes=0)
        options = modal.query_one("#capacity-inspector-options", OptionList)
        assert any(
            option.id == "member:not_started:/idle-03" for option in options.options
        )


async def test_capacity_inspector_freshness_uses_injected_clock() -> None:
    report = _report()
    moment = [report.computed_at + 3]
    modal = CapacityInspectorModal(report, running_nodes=6, clock=lambda: moment[0])
    app = _InspectorApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        headline = modal.query_one("#capacity-inspector-headline", Static)
        assert "updated 3s ago" in headline.render().plain
        moment[0] = report.computed_at + 26
        modal._tick_freshness()
        assert "⟳ updated 26s ago" in headline.render().plain

        stale_report = _report_from_records(_screenshot_records(), scan_current=False)
        modal.update_capacity_report(stale_report, running_nodes=6)
        assert "records changed · rescanning" in headline.render().plain
