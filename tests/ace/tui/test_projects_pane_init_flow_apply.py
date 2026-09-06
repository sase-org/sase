"""Pilot tests for post-apply refresh, selection preservation, and timeouts."""

from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from tests.ace.tui._projects_pane_init_flow_helpers import (
    _RecordingReporter,
    _TimeoutReporter,
    _completion,
    _drift_payload,
    _install_submit,
    _open_projects,
    _patch_panes,
)
from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)


async def test_apply_completion_refresh_preserves_selected_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        make_project_record("alpha", state="enabled"),
        make_project_record("beta", state="enabled"),
    ]
    _patch_panes(monkeypatch, records=records)
    async with AcePage() as page:
        submitted = _install_submit(page)
        _center, pane = await _open_projects(page)
        option_list = pane.query_one("#projects-list", OptionList)
        option_list.highlighted = 1
        await page.pause()
        assert pane._selected_project_name() == "beta"

        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        payload = _drift_payload("beta")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        await page.press("y")
        await page.wait_for(lambda _s: len(submitted) == 2)

        records[:] = [
            make_project_record("beta", state="enabled"),
            make_project_record("alpha", state="enabled"),
        ]
        apply_args, apply_kwargs, apply_handle = submitted[1]
        apply_reporter = _RecordingReporter(
            stdout="Initialization summary: 1 initialized\n",
            returncode=0,
        )
        apply_result = apply_args[1](apply_reporter)
        apply_kwargs["on_complete"](
            _completion(
                apply_handle.proc_id,
                apply_result.payload,
                proc_type="init-apply",
                message=apply_result.message,
            )
        )
        await page.pause()

        assert pane._selected_project_name() == "beta"
        assert option_list.highlighted == 0
        assert "Initialized 1" in pane._status_message


async def test_apply_timeout_surfaces_failure_and_refreshes(
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

        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        payload = _drift_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        await page.press("y")
        await page.wait_for(lambda _s: len(submitted) == 2)

        apply_args, apply_kwargs, apply_handle = submitted[1]
        timeout_reporter = _TimeoutReporter()
        apply_result = apply_args[1](timeout_reporter)
        apply_kwargs["on_complete"](
            _completion(
                apply_handle.proc_id,
                apply_result.payload,
                success=False,
                proc_type="init-apply",
                message=apply_result.message,
                error=apply_result.error,
            )
        )
        await page.pause()

        assert apply_result.payload is not None
        assert apply_result.payload.kind == "failure"
        assert any(
            "timed out" in message and severity == "error"
            for message, severity in notices
        )
        assert "timed out" in pane._status_message
        assert pane._selected_project_name() == "alpha"
