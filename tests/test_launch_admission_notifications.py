"""Launch-admission notification behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.agent_launch_wire import LaunchConditionWire
from tests._launch_admission_helpers import (
    agent_result as _agent_result,
    agent_unit as _agent_unit,
    code as _code,
    plan as _plan,
    proc_unit as _proc_unit,
    run_plan as _run_plan,
)


def test_proc_unit_dispatches_through_injected_hook(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    with patch("sase.procs.store.reserve_proc") as reserve_proc:
        progress, _ = _run_plan(
            tmp_path,
            _plan(_proc_unit("unit-1", tmp_path)),
            request_id="req-proc",
            proc_dispatcher=lambda unit, fingerprint: (
                True,
                "proc-hook",
                None,
                [],
            ),
        )
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.unit_results[0].outcome == "launched"
    reserve_proc.assert_not_called()


def test_clean_proc_only_admission_does_not_notify(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(_proc_unit("unit-1", tmp_path))
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            plan,
            request_id="req-clean-proc",
            proc_dispatcher=lambda unit, fingerprint: (
                True,
                "proc-hook",
                None,
                [],
            ),
        )
    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.unit_results[0].outcome == "launched"
    assert (response_dir / "launch_admission" / "receipt.json").is_file()
    notify.assert_not_called()


def test_agent_only_admission_still_notifies(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            _plan(_agent_unit("unit-1")),
            request_id="req-agent-notify",
            agent_dispatcher=lambda unit, fingerprint: (
                True,
                "reviewer",
                None,
                [_agent_result(tmp_path)],
            ),
        )
    assert progress.admission_complete
    notify.assert_called_once()
    assert notify.call_args.kwargs["success"] is True
    assert notify.call_args.kwargs["extra_files"] == [
        str(response_dir / "launch_admission" / "receipt.json")
    ]


def test_proc_only_launch_error_still_notifies(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            _plan(_proc_unit("unit-1", tmp_path)),
            request_id="req-proc-error",
            proc_dispatcher=lambda unit, fingerprint: (
                False,
                None,
                "spawn failed",
                [],
            ),
        )
    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launch_errors == 1
    notify.assert_called_once()
    assert notify.call_args.kwargs["success"] is False
    assert notify.call_args.kwargs["extra_files"] == [
        str(response_dir / "launch_admission" / "receipt.json")
    ]


@pytest.mark.parametrize(
    ("verdict", "expected_success"),
    [("skipped", True), ("condition_error", False)],
)
def test_proc_only_condition_terminal_outcomes_still_notify(
    tmp_path: Path,
    verdict: str,
    expected_success: bool,
) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(
        _proc_unit(
            "unit-1",
            tmp_path,
            condition=LaunchConditionWire(code=_code()),
        )
    )
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            plan,
            request_id=f"req-proc-{verdict}",
            condition_evaluator=lambda unit, waited, context: (verdict, verdict),
            proc_dispatcher=lambda unit, fingerprint: pytest.fail(
                "conditioned proc should not dispatch"
            ),
        )
    assert progress.admission_complete
    assert progress.unit_results[0].outcome == verdict
    notify.assert_called_once()
    assert notify.call_args.kwargs["success"] is expected_success
    assert notify.call_args.kwargs["extra_files"] == [
        str(response_dir / "launch_admission" / "receipt.json")
    ]
