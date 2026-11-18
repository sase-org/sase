"""TUI update paths inject the reporter's recovering dev-command runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from sase.ace.tui.modals.plugins_browser_comprehensive_update_execution import (
    _execute_sase_leg,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    ComprehensiveUpdateRequest,
)
from sase.ace.tui.modals.plugins_browser_dev_update import DevUpdatePreview
from sase.ace.tui.modals import plugins_browser_sase_update_procs as update_procs
from sase.ace.tui.session_proc_reporter import SessionProcReporter
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from tests.ace.tui._session_reporter import session_reporter


def test_comprehensive_sase_leg_injects_reporter_dev_command_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reporter = session_reporter(proc_type="comprehensive-update")
    sentinel = object()
    wait_sentinel = object()
    seen: list[object] = []
    seen_wait: list[object] = []

    monkeypatch.setattr(
        SessionProcReporter,
        "dev_command_runner",
        lambda self: sentinel,
    )
    monkeypatch.setattr(
        SessionProcReporter,
        "code_swap_wait",
        lambda self: wait_sentinel,
    )

    def execute(_plan: DevUpdatePlan, **kwargs: Any) -> DevUpdateResult:
        seen.append(kwargs.get("run"))
        seen_wait.append(kwargs.get("wait"))
        return DevUpdateResult(changed=False, outcomes=())

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_pane._execute_tui_dev_update",
        execute,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "append_dev_update_journal",
        lambda *_args, **_kwargs: None,
    )
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(()),
        sase_preview=DevUpdatePreview(
            plan=cast(DevUpdatePlan, object()), subject="sase"
        ),
    )

    _execute_sase_leg(preview, uv_tool=None, reporter=reporter)

    assert seen == [sentinel]
    assert seen_wait == [wait_sentinel]


def test_individual_and_combined_update_procs_use_dev_command_runner() -> None:
    source = Path(update_procs.__file__).read_text(encoding="utf-8")
    assert source.count("run=reporter.dev_command_runner()") == 2
    assert source.count("wait=reporter.code_swap_wait()") == 2


def test_operations_execute_dev_update_forwards_wait_selectively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals import plugins_browser_operations as ops

    seen: dict[str, Any] = {}

    def accepts_both(plan: Any, *, run: Any = None, wait: Any = None) -> str:
        seen["run"] = run
        seen["wait"] = wait
        return "both"

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_pane._execute_tui_dev_update",
        accepts_both,
    )
    mixin = ops.PluginsBrowserOperationsMixin()
    assert mixin._execute_dev_update("plan", run="r", wait="w") == "both"
    assert seen == {"run": "r", "wait": "w"}

    def accepts_run_only(plan: Any, *, run: Any = None) -> str:
        seen.clear()
        seen["run"] = run
        return "run-only"

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_pane._execute_tui_dev_update",
        accepts_run_only,
    )
    assert mixin._execute_dev_update("plan", run="r", wait="w") == "run-only"
    assert seen == {"run": "r"}

    def accepts_neither(plan: Any) -> str:
        return "neither"

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_pane._execute_tui_dev_update",
        accepts_neither,
    )
    assert mixin._execute_dev_update("plan", run="r", wait="w") == "neither"
