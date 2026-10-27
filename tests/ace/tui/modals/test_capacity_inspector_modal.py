"""Tests for the keyboard-first machine-capacity inspector."""

from __future__ import annotations

import argparse
import io
import json
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
    report = _report()
    app = _InspectorApp(CapacityInspectorModal(report, running_nodes=6))

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        summary = modal.query_one("#capacity-inspector-summary", Static)
        assert "5 of 8 units in use" in summary.render().plain
        assert "6 running nodes · 5 holding capacity · 1 holding 0" in (
            summary.render().plain
        )

        options = modal.query_one("#capacity-inspector-options", OptionList)
        target_index = next(
            index
            for index, option in enumerate(options.options)
            if "worker-a" in _option_text(option)
        )
        options.highlighted = target_index
        await pilot.press("enter")
        await pilot.pause()

    assert app.selection is not None
    assert app.selection.name == "worker-a"


async def test_capacity_inspector_expands_a_truncated_idle_group() -> None:
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
        expand_index = next(
            index
            for index, option in enumerate(options.options)
            if "Show 2 more" in _option_text(option)
        )
        options.highlighted = expand_index
        await pilot.press("enter")
        await pilot.pause()

        options = modal.query_one("#capacity-inspector-options", OptionList)
        option_texts = [_option_text(option) for option in options.options]
        assert any("Show first 10 · Enter to collapse" in text for text in option_texts)
        assert sum("idle-" in label for label in option_texts) == 12


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

    copied = schedule.call_args.args[1]
    assert copied == expected.getvalue()


def test_capacity_inspector_marks_invalid_and_unavailable_accounting() -> None:
    invalid = _report()
    object.__setattr__(invalid, "accounting_valid", False)
    invalid_summary = (
        CapacityInspectorModal(
            invalid,
            running_nodes=6,
        )
        ._summary_text()
        .plain
    )
    assert "Admission blocked" in invalid_summary
    assert "known subtotal" in invalid_summary

    unavailable = _report()
    object.__setattr__(unavailable, "accounting_available", False)
    unavailable_summary = (
        CapacityInspectorModal(
            unavailable,
            running_nodes=6,
        )
        ._summary_text()
        .plain
    )
    assert "Capacity accounting unavailable" in unavailable_summary


async def test_capacity_inspector_refreshes_from_a_new_report() -> None:
    app = _InspectorApp(CapacityInspectorModal(_report(), running_nodes=6))

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        modal.update_capacity_report(_report(), running_nodes=7)

        summary = modal.query_one("#capacity-inspector-summary", Static)
        assert "7 running nodes" in summary.render().plain
        assert modal.running_nodes == 7
