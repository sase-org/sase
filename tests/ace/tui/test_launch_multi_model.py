"""Multi-model launch fan-out tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._launch_multi_model import (
    _write_fanout_failure_report,
)
from sase.xprompt.models import XPrompt
from tests.ace.tui._launch_fan_out_helpers import (
    _ctx,
    _launch_result,
    _MultiModelApp,
)


def test_multi_model_launch_uses_canonical_multi_prompt_launcher() -> None:
    app = _MultiModelApp()
    ctx = _ctx()
    local_xprompts = {"_plan": XPrompt(name="_plan", content="Plan locally")}
    launched = [_launch_result(0), _launch_result(1)]

    with patch(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        return_value=launched,
    ) as launch_multi:
        outcome = app._run_multi_model_launch(
            ["%model:a p", "%model:b p"],
            ctx,
            ("git", "proj"),
            has_wait=False,
            fanout_kind="model",
            local_xprompts=local_xprompts,
        )

    launch_multi.assert_called_once()
    kwargs = launch_multi.call_args.kwargs
    assert kwargs["segments"] == ["%model:a p", "%model:b p"]
    assert kwargs["local_xprompts"] == local_xprompts
    assert kwargs["cl_name"] == "cl"
    assert kwargs["project_file"] == "/tmp/proj.sase"
    assert kwargs["project_name"] == "proj"
    assert kwargs["is_home_mode"] is False
    assert kwargs["vcs_ref"] == ("git", "proj")
    assert kwargs["default_bare_segments_to_home"] is False
    assert "on_agent_spawned" not in kwargs
    app._apply_launch_outcome(outcome)
    assert app.launch_delta_batches == [launched]


def test_multi_model_dispatch_snapshots_xprompts_without_broad_refresh() -> None:
    app = _MultiModelApp()
    ctx = _ctx()
    local_xprompts = {"_epic": XPrompt(name="_epic", content="Epic")}
    captured: dict[str, Any] = {}

    app._launch_multi_model_agents(
        ["#_epic"],
        ctx,
        None,
        has_wait=False,
        fanout_kind="alternatives",
        local_xprompts=local_xprompts,
    )
    local_xprompts["_late"] = XPrompt(name="_late", content="Late")

    assert app.refresh_requests == []
    assert len(app.launch_tasks) == 1

    def _capture_launch(**kwargs: Any) -> list[Any]:
        captured["local_xprompts"] = kwargs["local_xprompts"]
        return []

    with patch(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        side_effect=_capture_launch,
    ):
        app._run_submitted_launch_tasks()

    assert set(captured["local_xprompts"]) == {"_epic"}


def test_multi_model_xprompt_alternatives_are_passed_as_planned_segments() -> None:
    app = _MultiModelApp()
    ctx = _ctx()
    segments = ["%id:ag.1\n#plan\nDo", "%id:ag.2\n#epic\nDo"]

    with patch(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        return_value=[_launch_result(0), _launch_result(1)],
    ) as launch_multi:
        app._run_multi_model_launch(
            segments,
            ctx,
            None,
            has_wait=False,
            fanout_kind="alternatives",
        )

    assert launch_multi.call_args.kwargs["segments"] == segments


def test_multi_model_failure_records_toast_and_persistent_notification() -> None:
    app = _MultiModelApp()
    ctx = _ctx()
    submitted = "#swarm"

    with (
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=RuntimeError("workspace claim failed"),
        ),
        patch(
            "sase.ace.tui.actions.agent_workflow._launch_multi_model._write_fanout_failure_report",
            return_value=Path("/tmp/fanout_failure.txt"),
        ),
        patch("sase.notifications.append_notification") as append_notification,
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
    ):
        outcome = app._run_multi_model_launch(
            ["%id:ag.1\n#plan", "%id:ag.2\n#epic"],
            ctx,
            ("git", "proj"),
            has_wait=True,
            fanout_kind="alternatives",
            submitted_xprompt=submitted,
        )

    record_failed.assert_called_once_with(submitted)
    append_notification.assert_called_once()
    notification = append_notification.call_args.args[0]
    assert notification.sender == "user-agent"
    assert notification.action == "ViewErrorReport"
    assert notification.action_data["source"] == "tui_prompt_fanout"
    assert notification.action_data["fanout_kind"] == "alternatives"
    assert "workspace claim failed" in notification.notes[1]

    app._apply_launch_outcome(outcome)

    assert app.notification_refresh_count == 1
    assert (
        "Prompt fan-out launch failed - see Logs in SASE Admin Center (#)",
        "error",
    ) in app.notifications


def test_fanout_failure_report_includes_submitted_xprompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    submitted = "#swarm\n```text\nkeep fence safe\n```"

    report_path = _write_fanout_failure_report(
        "RuntimeError: workspace claim failed",
        ctx=_ctx(),
        vcs_ref=("git", "proj"),
        has_wait=True,
        fanout_kind="alternatives",
        slot_count=2,
        submitted_xprompt=submitted,
    )

    text = report_path.read_text(encoding="utf-8")
    assert "## Submitted XPrompt" in text
    assert "````markdown" in text
    assert submitted in text
