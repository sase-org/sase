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
    seen: list[object] = []

    monkeypatch.setattr(
        SessionProcReporter,
        "dev_command_runner",
        lambda self: sentinel,
    )

    def execute(_plan: DevUpdatePlan, **kwargs: Any) -> DevUpdateResult:
        seen.append(kwargs.get("run"))
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


def test_individual_and_combined_update_procs_use_dev_command_runner() -> None:
    source = Path(update_procs.__file__).read_text(encoding="utf-8")
    assert source.count("run=reporter.dev_command_runner()") == 2
