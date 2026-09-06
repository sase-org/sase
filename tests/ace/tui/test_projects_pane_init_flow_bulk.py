"""Pilot tests for the bulk ``I`` and marked-set init check/apply flow."""

from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from tests.ace.tui._projects_pane_init_flow_helpers import (
    _RecordingReporter,
    _completion,
    _current_json,
    _install_submit,
    _open_projects,
    _patch_panes,
)
from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)
from tests.ace.tui.modals.projects_pane_init_test_helpers import (
    check_payload,
    planner_row,
    project_plan,
)


async def test_initialize_all_ignores_marks_and_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        _center, pane = await _open_projects(page)
        pane._marked_projects.add("alpha")
        pane._text_filter = "alpha"
        pane._apply_filters()
        pane.query_one("#projects-list", OptionList).focus()
        await page.pause()

        await page.press("I")
        await page.pause()

        assert len(submitted) == 1
        args, kwargs, _handle = submitted[0]
        assert args[0] == "init-check"
        assert kwargs["dedup_key"] == "sase-init-check:all"
        reporter = _RecordingReporter(stdout=_current_json(), returncode=0)
        args[1](reporter)
        assert reporter.runs[0][0] == [
            "sase",
            "init",
            "--all",
            "--check",
            "--json",
        ]


async def test_marked_set_init_submits_one_ordered_check_and_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        _center, pane = await _open_projects(page)
        pane._marked_projects = {"alpha", "beta"}
        pane.query_one("#projects-list", OptionList).focus()

        await page.press("i")
        await page.pause()

        assert len(submitted) == 1
        args, kwargs, handle = submitted[0]
        assert args[0] == "init-check"
        assert kwargs["dedup_key"] == "sase-init-check:alpha:beta"
        assert kwargs["exclusive_scopes"] == ("sase-init",)
        assert kwargs["cl_name"] == ""
        reporter = _RecordingReporter(stdout=_current_json(), returncode=0)
        args[1](reporter)
        assert reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "alpha",
            "-p",
            "beta",
            "--check",
            "--json",
        ]

        payload = check_payload(
            project_plan(
                "alpha",
                status="needs_attention",
                planners=(planner_row("memory", has_changes=True),),
            ),
            project_plan(
                "beta",
                status="needs_attention",
                planners=(planner_row("memory", has_changes=True),),
            ),
        )
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        await page.press("y")
        await page.wait_for(lambda _s: len(submitted) == 2)

        apply_args, _apply_kwargs, _apply_handle = submitted[1]
        apply_reporter = _RecordingReporter(
            stdout="Initialization summary: 2 initialized\n",
            returncode=0,
        )
        apply_args[1](apply_reporter)
        assert apply_reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "alpha",
            "-p",
            "beta",
            "--yes",
        ]


async def test_i_filters_disabled_marks_and_submits_nothing_when_only_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(
        monkeypatch,
        records=[
            make_project_record("alpha", state="disabled", launchable=False),
            make_project_record("beta", state="enabled"),
        ],
    )
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
        option_list.highlighted = 0
        pane._marked_projects = {"alpha"}
        pane.action_initialize_project()
        await page.pause()

        assert submitted == []
        assert "alpha" in pane._status_message
        assert any(severity == "warning" for _message, severity in notices)

        pane._marked_projects = {"alpha", "beta"}
        pane.action_initialize_project()
        await page.pause()
        assert len(submitted) == 1
        reporter = _RecordingReporter(stdout=_current_json("beta"), returncode=0)
        submitted[0][0][1](reporter)
        assert reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "beta",
            "--check",
            "--json",
        ]
