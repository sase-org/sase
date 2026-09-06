"""Pilot tests for the single-project ``i`` init check and apply flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.actions.proc_actions import TrackedProcResult
from sase.ace.tui.modals.init_plan_modal import InitPlanModal
from tests.ace.tui._projects_pane_init_flow_helpers import (
    _RecordingReporter,
    _completion,
    _current_json,
    _drift_payload,
    _install_submit,
    _open_projects,
    _patch_panes,
)
from tests.ace.tui.modals.projects_pane_init_test_helpers import (
    check_payload,
    planner_row,
    project_plan,
)


async def test_entering_projects_tab_submits_no_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        await _open_projects(page)
        await page.pause()
        assert submitted == []


async def test_i_on_drifted_project_submits_check_and_sets_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        notices: list[tuple[str, str]] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append((message, str(kwargs.get("severity", "information"))))
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]
        _center, pane = await _open_projects(page)
        option_list = pane.query_one("#projects-list", OptionList)
        assert page.app.focused is option_list

        await page.press("i")
        await page.pause()

        assert "Checking initialization for alpha" in pane._status_message
        assert len(submitted) == 1
        args, kwargs, handle = submitted[0]
        assert args[0] == "init-check"
        assert kwargs["dedup_key"] == "sase-init-check:alpha"
        assert kwargs["exclusive_scopes"] == ("sase-init",)
        assert kwargs["cl_name"] == "alpha"
        assert kwargs["duplicate_message"] == (
            "A project initialization is already running."
        )
        reporter = _RecordingReporter(stdout=_current_json(), returncode=0)
        result = args[1](reporter)
        assert reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "alpha",
            "--check",
            "--json",
        ]
        assert reporter.runs[0][1]["log_lines"] is False
        assert reporter.runs[0][1]["cwd"] == Path.home()
        assert isinstance(result, TrackedProcResult)

        payload = _drift_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        modal = page.app.screen
        assert isinstance(modal, InitPlanModal)
        await page.wait_for(lambda _s: len(modal.query("#init-plan-confirm")) > 0)

        await page.press("y")
        await page.wait_for(lambda _s: len(submitted) == 2)
        apply_args, apply_kwargs, _apply_handle = submitted[1]
        assert apply_args[0] == "init-apply"
        assert apply_kwargs["dedup_key"] == "sase-init:alpha"
        assert apply_kwargs["exclusive_scopes"] == ("sase-init",)
        apply_reporter = _RecordingReporter(stdout="", returncode=0)
        apply_args[1](apply_reporter)
        assert apply_reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "alpha",
            "--yes",
        ]


async def test_current_payload_opens_no_modal_and_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        notices: list[str] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append(message)
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]
        _center, pane = await _open_projects(page)
        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        current = check_payload(
            project_plan(
                "alpha",
                planners=(planner_row("memory", label="Memory", summary="Current"),),
            ),
            status="current",
        )
        kwargs["on_complete"](_completion(handle.proc_id, current))
        await page.pause()
        assert not isinstance(page.app.screen, InitPlanModal)
        assert any("is initialized" in message for message in notices)
        assert "Memory" in notices[-1] or "Memory" in pane._status_message
