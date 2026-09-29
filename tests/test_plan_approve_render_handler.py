"""Handler exit-code tests for ``sase plan approve``."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from sase.main.plan_approve_handler import handle_plan_approve_command
from sase.main.plan_direct_approval import (
    DirectApprovalPlan,
    DirectApprovalRefused,
    DirectApprovalRefusal,
)
from sase.main.plan_direct_approval_run import DirectApprovalOutcome
from tests._plan_approve_render_helpers import (
    make_direct_plan,
    make_launched,
    make_outcome,
    make_retired_gate,
    no_color,  # noqa: F401 (registers the autouse fixture)
    read_output,
)


def _args(**overrides: object) -> argparse.Namespace:
    fields: dict[str, object] = {
        "selector": "updates_tab",
        "kind": None,
        "prompt": None,
        "model": None,
        "wait": None,
        "dry_run": False,
        "project": "sase",
    }
    fields.update(overrides)
    return argparse.Namespace(**fields)


def _exit_code(args: argparse.Namespace) -> int:
    with pytest.raises(SystemExit) as exc_info:
        handle_plan_approve_command(args)
    code = exc_info.value.code
    assert isinstance(code, int)
    return code


def _run_direct_route(
    direct: DirectApprovalPlan | DirectApprovalRefusal,
    *,
    outcome: DirectApprovalOutcome | None = None,
    dry_run: bool = False,
) -> tuple[int, object]:
    """Run the handler with the engine mocked at the resolver/executor seams."""
    with (
        patch(
            "sase.main.plan_direct_approval.resolve_direct_approval",
            return_value=direct,
        ),
        patch(
            "sase.main.plan_direct_approval_run.execute_direct_approval",
            return_value=outcome,
        ) as execute,
    ):
        return _exit_code(_args(dry_run=dry_run)), execute


def test_handler_exits_zero_for_complete_direct_approval(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = make_direct_plan()

    code, _ = _run_direct_route(
        plan, outcome=make_outcome(plan, coder=make_launched("kx7"))
    )

    assert code == 0
    assert "✓ Tale approved · updates_tab" in read_output(capsys)[0]


def test_handler_exits_one_when_coder_launch_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = make_direct_plan()

    code, _ = _run_direct_route(plan, outcome=make_outcome(plan, coder_error="boom"))

    out, _ = read_output(capsys)
    assert code == 1
    assert "✗ Coder launch failed: boom" in out


def test_handler_exits_one_when_tale_gate_was_answered_concurrently(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = make_direct_plan(gate=make_retired_gate("orphaned"))

    code, _ = _run_direct_route(
        plan, outcome=make_outcome(plan, gate_answered_concurrently=True)
    )

    assert code == 1
    assert (
        "Check whether the gate's responder launched a coder:" in read_output(capsys)[0]
    )


def test_handler_exits_zero_when_commit_gate_was_answered_concurrently() -> None:
    plan = make_direct_plan(kind="commit", gate=make_retired_gate("orphaned"))

    code, _ = _run_direct_route(
        plan, outcome=make_outcome(plan, gate_answered_concurrently=True)
    )

    assert code == 0


def test_handler_dry_run_exits_zero_without_executing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, execute = _run_direct_route(make_direct_plan(), dry_run=True)

    assert code == 0
    execute.assert_not_called()  # type: ignore[attr-defined]
    assert "◇ Dry run" in read_output(capsys)[0]


def test_handler_exits_two_for_upfront_refusal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    refusal = DirectApprovalRefusal(
        code="planner_running",
        header="updates_tab's planner bob is still running",
        hints=("sase plan list",),
    )

    code, execute = _run_direct_route(refusal)

    out, err = read_output(capsys)
    assert code == 2
    assert out == ""
    assert err.startswith("✗ updates_tab's planner bob is still running")
    execute.assert_not_called()  # type: ignore[attr-defined]


def test_handler_exits_two_for_refusal_raised_during_execution(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = make_direct_plan(kind="approve", gate=make_retired_gate("orphaned"))
    refusal = DirectApprovalRefusal(
        code="conflict_already_handled",
        header="updates_tab was already handled",
        hints=("sase plan list",),
    )
    with (
        patch(
            "sase.main.plan_direct_approval.resolve_direct_approval",
            return_value=plan,
        ),
        patch(
            "sase.main.plan_direct_approval_run.execute_direct_approval",
            side_effect=DirectApprovalRefused(refusal),
        ),
    ):
        code = _exit_code(_args())

    _, err = read_output(capsys)
    assert code == 2
    assert "✗ updates_tab was already handled" in err


def test_handler_refuses_direct_execution_from_inside_an_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_AGENT", "bob")

    with (
        patch(
            "sase.main.plan_direct_approval.resolve_direct_approval",
            return_value=make_direct_plan(),
        ),
        patch("sase.main.plan_direct_approval_run._adopt_plan") as adopt,
        patch("sase.main.plan_direct_approval_run._launch_coder") as launch,
    ):
        code = _exit_code(_args())

    _, err = read_output(capsys)
    assert code == 2
    assert "must be run by the user" in err
    adopt.assert_not_called()
    launch.assert_not_called()


def test_handler_allows_dry_run_from_inside_an_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_AGENT", "bob")

    code, _ = _run_direct_route(make_direct_plan(), dry_run=True)

    assert code == 0
    assert "◇ Dry run" in read_output(capsys)[0]
