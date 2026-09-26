"""Human output and exit codes for ``sase plan approve`` under ``NO_COLOR``."""

from __future__ import annotations

import argparse
import shlex
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.core.time import get_timezone
from sase.main.plan_approve_handler import handle_plan_approve_command
from sase.main.plan_approve_render import (
    render_approval_error,
    render_coder_recovery,
    render_coder_recovery_dry_run,
    render_direct_approval,
    render_direct_approval_dry_run,
    render_direct_approval_refusal,
    render_gate_approval,
    render_gate_approval_dry_run,
)
from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalPlan,
    DirectApprovalRefusal,
    DirectApprovalRefused,
    DirectApprovalRequest,
    RetiredGate,
)
from sase.main.plan_direct_approval_recovery import CoderRecovery, PriorCoder
from sase.main.plan_direct_approval_run import DirectApprovalOutcome
from sase.main.plan_pending import PendingPlan
from sase.notifications.models import Notification
from sase.plan_approval_actions import (
    PlanApprovalActionError,
    PlanApprovalActionResult,
)

_PLAN_REF = "plan:202609/updates_tab.md"
_PROMPT = f"+sase %model:@medium #coder({_PLAN_REF})"


@pytest.fixture(autouse=True)
def _no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)


def _placement(mode: str = "standalone") -> CoderPlacement:
    if mode == "session":
        return CoderPlacement(
            mode="session", parent="bob", member_name="bob--code", agent_session="bob"
        )
    return CoderPlacement(mode="standalone", reason="this plan records no planner")


def _direct_plan(
    *,
    kind: str = "tale",
    mode: str = "standalone",
    gate: RetiredGate | None = None,
    prompt: str = _PROMPT,
) -> DirectApprovalPlan:
    return DirectApprovalPlan(
        request=DirectApprovalRequest(selector="updates_tab"),
        kind=kind,  # type: ignore[arg-type]
        source_path=Path("/plans/updates_tab.md"),
        location="proposal",
        name="updates_tab",
        title="Cache the Updates tab's first open",
        size="medium",
        project="sase",
        project_tag="+sase",
        planner=None,
        gate=gate,
        placement=_placement(mode),
        model_directive="@medium",
        predicted_plan_ref=_PLAN_REF,
        coder_prompt_preview=prompt,
    )


def _outcome(
    plan: DirectApprovalPlan,
    *,
    coder: AgentLaunchResult | None = None,
    coder_error: str | None = None,
    warnings: tuple[str, ...] = (),
    gate_answered_concurrently: bool = False,
    prompt: str = _PROMPT,
) -> DirectApprovalOutcome:
    return DirectApprovalOutcome(
        plan=plan,
        local_plan_path=Path("/home/u/.sase/plans/202609/updates_tab.md"),
        plan_ref=_PLAN_REF,
        saved_plan_path=None if plan.kind == "approve" else "/sdd/updates_tab.md",
        coder_prompt=prompt,
        coder=coder,
        coder_error=coder_error,
        warnings=warnings,
        gate_answered_concurrently=gate_answered_concurrently,
    )


def _launched(name: str | None = "bob--code", pid: int = 4242) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=pid,
        workspace_num=1,
        workspace_dir="/work",
        output_path="/work/out.log",
        agent_name=name,
    )


def _gate(state: str = "expired") -> RetiredGate:
    return RetiredGate(
        notification_id="a1b2c3d4e5f6",
        state=state,  # type: ignore[arg-type]
    )


def _pending_plan() -> PendingPlan:
    notification = Notification(
        id="a1b2c3d4e5f6",
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="plan",
        files=["/plans/updates_tab.md"],
        action="PlanApproval",
        action_data={},
    )
    return PendingPlan(
        notification=notification,
        name="updates_tab",
        display_name="updates_tab",
        archive_path=None,
        bundle_plan_path=None,
        title="Cache the Updates tab's first open",
        tier="tale",
        agent="planner",
        age="1m",
    )


def _gate_result(**overrides: object) -> PlanApprovalActionResult:
    fields: dict[str, object] = {
        "notification_id": "a1b2c3d4e5f6",
        "response_file": "plan_response.json",
        "response_path": Path("/r/plan_response.json"),
        "response_json": {},
        "message": "Tale approved",
    }
    fields.update(overrides)
    return PlanApprovalActionResult(**fields)  # type: ignore[arg-type]


def _out(capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    captured = capsys.readouterr()
    assert "\x1b" not in captured.out + captured.err
    return captured.out, captured.err


# -- gate route ------------------------------------------------------------


def test_gate_success_card_names_coder_and_gate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(
        _pending_plan(),
        _gate_result(coder_agent="bob--code", gate_turn_member="bob--gate"),
    )

    out, err = _out(capsys)
    assert err == ""
    assert "✓ Tale approved · updates_tab" in out
    assert "Cache the Updates tab's first open" in out
    assert "coder   bob--code · launched by bob--gate" in out
    assert "gate    a1b2c3d4 → /r/plan_response.json" in out
    assert "follow  sase agent show bob--code" in out


def test_gate_success_without_result_fields_says_shell_launches_next(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(_pending_plan(), _gate_result())

    out, _ = _out(capsys)
    assert "coder   the gate shell launches it next" in out
    assert "follow" not in out


def test_gate_success_reports_coder_launch_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(_pending_plan(), _gate_result(coder_error="no capacity"))

    out, _ = _out(capsys)
    assert "! coder launch failed: no capacity" in out
    assert "follow" not in out


def test_gate_epic_approval_shows_monitor_launch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(
        _pending_plan(),
        _gate_result(message="Epic approved", epic_launch_monitor_id="42"),
    )

    out, _ = _out(capsys)
    assert "launch  monitor 42 · sase monitor show 42 --follow" in out
    assert "coder" not in out


def test_gate_epic_approval_shows_proc_launch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(
        _pending_plan(),
        _gate_result(message="Epic approved", epic_launch_task_id="7"),
    )

    out, _ = _out(capsys)
    assert "launch  proc 7 · sase proc show 7 --follow" in out


def test_gate_dry_run_card_changes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval_dry_run(_pending_plan(), "tale")

    out, err = _out(capsys)
    assert err == ""
    assert "◇ Dry run · updates_tab would be approved as a tale" in out
    assert "gate    a1b2c3d4 · the gate shell launches the coder" in out
    assert "Nothing was changed. Re-run without -n/--dry-run to approve." in out


# -- direct route ----------------------------------------------------------


def test_direct_agent_session_card(capsys: pytest.CaptureFixture[str]) -> None:
    plan = _direct_plan(mode="session", gate=_gate("expired"))

    render_direct_approval(_outcome(plan, coder=_launched()))

    out, err = _out(capsys)
    assert err == ""
    assert "✓ Tale approved · updates_tab" in out
    assert f"plan    {_PLAN_REF} · committed to sase" in out
    assert "coder   bob--code · agent session bob · %model:@medium" in out
    assert "no agent session" not in out
    assert "gate    a1b2c3d4 · expired approval gate closed" in out
    assert "follow  sase agent show bob--code" in out


def test_direct_standalone_card_gives_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(_outcome(_direct_plan(), coder=_launched("kx7")))

    out, _ = _out(capsys)
    assert "coder   kx7 · standalone · %model:@medium" in out
    assert "no agent session: this plan records no planner" in out
    assert "gate    none · never proposed" in out
    assert "follow  sase agent show kx7" in out


def test_direct_standalone_card_falls_back_to_pid_without_agent_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(_outcome(_direct_plan(), coder=_launched(None, pid=9001)))

    out, _ = _out(capsys)
    assert "coder   PID 9001 · standalone" in out
    assert "None" not in out
    assert "follow  sase agent list" in out
    assert "sase agent show" not in out


def test_direct_approve_kind_is_not_labelled_committed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(
        _outcome(_direct_plan(kind="approve"), coder=_launched("kx7"))
    )

    out, _ = _out(capsys)
    assert "✓ Approve approved · updates_tab" in out
    assert "committed to sase" not in out


def test_direct_commit_only_card_launches_no_coder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(_outcome(_direct_plan(kind="commit")))

    out, _ = _out(capsys)
    assert "coder   none · commit only" in out
    assert "follow" not in out
    assert "Launch it yourself" not in out


def test_direct_card_prints_best_effort_warnings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(
        _outcome(
            _direct_plan(),
            coder=_launched("kx7"),
            warnings=("planner metadata could not be recorded: boom",),
        )
    )

    out, _ = _out(capsys)
    assert "! planner metadata could not be recorded: boom" in out


def test_direct_partial_failure_card_gives_recovery_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _direct_plan(mode="session", gate=_gate("orphaned"))

    render_direct_approval(_outcome(plan, coder_error="launch exploded"))

    out, err = _out(capsys)
    assert err == ""
    assert f"✓ Plan committed · updates_tab · {_PLAN_REF}" in out
    assert "✗ Coder launch failed: launch exploded" in out
    assert "Launch it yourself:" in out
    assert f"sase run {shlex.quote(_PROMPT)}" in out
    assert "follow" not in out


def test_direct_partial_failure_recovery_command_survives_multiline_prompt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompt = f"{_PROMPT}\n\nAdditional instructions:\nkeep [it] it's small"

    render_direct_approval(
        _outcome(_direct_plan(prompt=prompt), coder_error="boom", prompt=prompt)
    )

    out, _ = _out(capsys)
    command = out[out.index("sase run ") + len("sase run ") :].rstrip("\n")
    assert shlex.split(command) == [prompt]


def test_direct_gate_answered_concurrently_card_for_tale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    note = "gate a1b2c3d4e5f6 was answered concurrently; no coder was launched by this command"
    plan = _direct_plan(mode="session", gate=_gate("orphaned"))

    render_direct_approval(
        _outcome(plan, warnings=(note,), gate_answered_concurrently=True)
    )

    out, err = _out(capsys)
    assert err == ""
    assert f"✓ Plan committed · updates_tab · {_PLAN_REF}" in out
    assert "coder   none launched · left to the gate's responder" in out
    assert "no agent session" not in out
    assert "gate    a1b2c3d4 · answered concurrently, not closed here" in out
    assert f"! {note}" in " ".join(out.split())
    assert "Check whether the gate's responder launched a coder:" in out
    assert "sase agent list" in out
    assert f"sase run {shlex.quote(_PROMPT)}" in out
    assert "follow" not in out


def test_direct_gate_answered_concurrently_card_for_commit_needs_no_recovery(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _direct_plan(kind="commit", gate=_gate("orphaned"))

    render_direct_approval(_outcome(plan, gate_answered_concurrently=True))

    out, _ = _out(capsys)
    assert "✓ Plan committed · updates_tab" in out
    assert "coder   none · commit only" in out
    assert "sase run" not in out


def test_direct_dry_run_card_standalone(capsys: pytest.CaptureFixture[str]) -> None:
    render_direct_approval_dry_run(_direct_plan())

    out, err = _out(capsys)
    assert err == ""
    assert "◇ Dry run · updates_tab would be approved as a tale" in out
    assert "plan    /plans/updates_tab.md" in out
    assert f"→ {_PLAN_REF} in sase" in out
    assert "coder   standalone · %model:@medium" in out
    assert "no agent session: this plan records no planner" in out
    assert "gate    none · never proposed" in out
    assert f"prompt  {_PROMPT}" in out
    assert "Nothing was changed. Re-run without -n/--dry-run to approve." in out


def test_direct_dry_run_card_agent_session_with_gate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval_dry_run(_direct_plan(mode="session", gate=_gate("orphaned")))

    out, _ = _out(capsys)
    assert "coder   agent session bob · %model:@medium" in out
    assert "no agent session" not in out
    assert "gate    a1b2c3d4 · orphaned" in out


def test_refusal_prints_header_details_and_hints_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval_refusal(
        DirectApprovalRefusal(
            code="already_committed",
            header="foo is already committed as plan:202609/foo.md",
            detail_lines=("A committed tale is already approved.",),
            hints=("sase plan show foo", "sase plan list"),
        )
    )

    out, err = _out(capsys)
    assert out == ""
    assert err.splitlines() == [
        "✗ foo is already committed as plan:202609/foo.md",
        "  A committed tale is already approved.",
        "  sase plan show foo",
        "  sase plan list",
    ]


def test_refusal_does_not_double_prefix_or_repeat_hints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval_refusal(
        DirectApprovalRefusal(
            code="epic_guard",
            header="✗ big_epic is an epic plan",
            detail_lines=("sase plan approve big_epic -k epic",),
            hints=("sase plan approve big_epic -k epic",),
        )
    )

    _, err = _out(capsys)
    assert err.splitlines() == [
        "✗ big_epic is an epic plan",
        "  sase plan approve big_epic -k epic",
    ]


@pytest.mark.parametrize(
    ("code", "hint"),
    [
        ("git_credential_denied", "Check git credentials"),
        ("plan_archive_failed", "Nothing was approved"),
        ("conflict_already_handled", "Run `sase plan list`"),
        ("not_found", "Run `sase plan list`"),
        ("already_committed", "Run `sase plan list`"),
        ("already_approved", "Run `sase plan list`"),
    ],
)
def test_approval_error_renders_code_specific_hint(
    capsys: pytest.CaptureFixture[str], code: str, hint: str
) -> None:
    render_approval_error(PlanApprovalActionError(code, "target", "it broke"))

    out, err = _out(capsys)
    assert out == ""
    assert err.splitlines()[0] == "✗ it broke"
    assert hint in err


def test_approval_error_without_recovery_hint_is_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_approval_error(PlanApprovalActionError("invalid_request", "wait", "bad"))

    _, err = _out(capsys)
    assert err.splitlines() == ["✗ bad"]


# -- handler seam: exit codes ------------------------------------------------


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
    plan = _direct_plan()

    code, _ = _run_direct_route(plan, outcome=_outcome(plan, coder=_launched("kx7")))

    assert code == 0
    assert "✓ Tale approved · updates_tab" in _out(capsys)[0]


def test_handler_exits_one_when_coder_launch_failed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _direct_plan()

    code, _ = _run_direct_route(plan, outcome=_outcome(plan, coder_error="boom"))

    out, _ = _out(capsys)
    assert code == 1
    assert "✗ Coder launch failed: boom" in out


def test_handler_exits_one_when_tale_gate_was_answered_concurrently(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _direct_plan(gate=_gate("orphaned"))

    code, _ = _run_direct_route(
        plan, outcome=_outcome(plan, gate_answered_concurrently=True)
    )

    assert code == 1
    assert "Check whether the gate's responder launched a coder:" in _out(capsys)[0]


def test_handler_exits_zero_when_commit_gate_was_answered_concurrently() -> None:
    plan = _direct_plan(kind="commit", gate=_gate("orphaned"))

    code, _ = _run_direct_route(
        plan, outcome=_outcome(plan, gate_answered_concurrently=True)
    )

    assert code == 0


def test_handler_dry_run_exits_zero_without_executing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, execute = _run_direct_route(_direct_plan(), dry_run=True)

    assert code == 0
    execute.assert_not_called()  # type: ignore[attr-defined]
    assert "◇ Dry run" in _out(capsys)[0]


def test_handler_exits_two_for_upfront_refusal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    refusal = DirectApprovalRefusal(
        code="planner_running",
        header="updates_tab's planner bob is still running",
        hints=("sase plan list",),
    )

    code, execute = _run_direct_route(refusal)

    out, err = _out(capsys)
    assert code == 2
    assert out == ""
    assert err.startswith("✗ updates_tab's planner bob is still running")
    execute.assert_not_called()  # type: ignore[attr-defined]


def test_handler_exits_two_for_refusal_raised_during_execution(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _direct_plan(kind="approve", gate=_gate("orphaned"))
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

    _, err = _out(capsys)
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
            return_value=_direct_plan(),
        ),
        patch("sase.main.plan_direct_approval_run._adopt_plan") as adopt,
        patch("sase.main.plan_direct_approval_run._launch_coder") as launch,
    ):
        code = _exit_code(_args())

    _, err = _out(capsys)
    assert code == 2
    assert "must be run by the user" in err
    adopt.assert_not_called()
    launch.assert_not_called()


def test_handler_allows_dry_run_from_inside_an_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_AGENT", "bob")

    code, _ = _run_direct_route(_direct_plan(), dry_run=True)

    assert code == 0
    assert "◇ Dry run" in _out(capsys)[0]


# -- coder recovery -------------------------------------------------------


def _failed_prior(name: str = "0sk--code"):  # type: ignore[no-untyped-def]
    from sase.main.plan_direct_approval_recovery import PriorCoder

    return PriorCoder(name=name, state="ended", outcome="failed", age="14m ago")


def _recovery_plan_for_render(**overrides: object) -> DirectApprovalPlan:
    base = {
        "request": DirectApprovalRequest(selector="work"),
        "kind": "tale",
        "source_path": Path("/home/u/.sase/plans/202609/work.md"),
        "location": "proposal",
        "name": "work",
        "title": "Work title",
        "size": "small",
        "project": "demo",
        "project_tag": "+demo",
        "planner": "0sk",
        "gate": None,
        "placement": CoderPlacement(
            mode="session",
            parent="0sk",
            member_name="0sk--2",
            agent_session="0sk",
        ),
        "model_directive": "@small",
        "bead": None,
        "predicted_plan_ref": "plan:202609/work.md",
        "coder_prompt_preview": "+demo %model:@small #coder(plan:202609/work.md)",
        "recovery": CoderRecovery(
            verdict="recover",
            prior_coders=(_failed_prior(),),
            approved_action="tale",
            approved_age="18m ago",
            gate_id="7ff58c91",
            plan_argument="plan:202609/work.md",
        ),
    }
    base.update(overrides)
    return DirectApprovalPlan(**base)  # type: ignore[arg-type]


def _recovery_outcome(plan: DirectApprovalPlan, **overrides: object):
    from sase.main.plan_direct_approval_run import DirectApprovalOutcome

    fields: dict[str, object] = {
        "plan": plan,
        "local_plan_path": plan.source_path,
        "plan_ref": plan.predicted_plan_ref,
        "saved_plan_path": None,
        "coder_prompt": plan.coder_prompt_preview,
        "coder": None,
        "coder_error": None,
        "warnings": (),
    }
    fields.update(overrides)
    return DirectApprovalOutcome(**fields)  # type: ignore[arg-type]


def test_recovery_card(capsys: pytest.CaptureFixture[str]) -> None:
    plan = _recovery_plan_for_render()
    render_coder_recovery(_recovery_outcome(plan, coder=_launched("0sk--2")))

    out = capsys.readouterr().out
    assert "Coder relaunched · work" in out
    assert "Work title" in out
    assert (
        "plan    plan:202609/work.md · approved as a tale 18m ago · gate 7ff58c91"
        in out
    )
    assert "before  0sk--code · failed 14m ago" in out
    assert "coder   0sk--2 · agent session 0sk · %model:@small" in out
    assert "follow  sase agent show 0sk--2" in out


def test_recovery_card_without_prior_coder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    recovery = CoderRecovery(
        verdict="recover",
        prior_coders=(),
        approved_action="approve",
        approved_age="",
        gate_id=None,
        plan_argument="/home/u/.sase/plans/202609/work.md",
    )
    render_coder_recovery(
        _recovery_outcome(_recovery_plan_for_render(recovery=recovery))
    )

    out = capsys.readouterr().out
    assert "none found · the approval's coder never launched" in out


def test_recovery_launch_failure_card(capsys: pytest.CaptureFixture[str]) -> None:
    plan = _recovery_plan_for_render()
    render_coder_recovery(_recovery_outcome(plan, coder_error="boom"))

    out = capsys.readouterr().out
    assert "before  0sk--code · failed 14m ago" in out
    assert "Coder launch failed: boom" in out
    assert "Launch it yourself:" in out
    assert "sase run" in out


def test_recovery_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    render_coder_recovery_dry_run(_recovery_plan_for_render())

    out = capsys.readouterr().out
    assert "would get a replacement coder" in out
    assert "plan:202609/work.md · approved as a tale 18m ago" in out
    assert "before  0sk--code · failed 14m ago" in out
    assert "Nothing was changed." in out


def test_coder_running_refusal_renders_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.plan_approve_render import render_direct_approval_refusal
    from sase.main.plan_direct_approval import coder_running_refusal

    recovery = CoderRecovery(
        verdict="live",
        prior_coders=(PriorCoder(name="0sk--code", state="live", outcome="running"),),
        approved_action="tale",
        approved_age="18m ago",
        gate_id="7ff58c91",
        plan_argument="plan:202609/work.md",
        refusal_code="coder_running",
    )
    render_direct_approval_refusal(
        coder_running_refusal("work", "Work title", recovery)
    )

    err = capsys.readouterr().err
    assert "is already approved and its coder is running" in err
    assert "coder   0sk--code · running" in err
    assert err.count("sase agent show 0sk--code") == 1


def test_already_implemented_refusal_offers_run_anyway(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.plan_approve_render import render_direct_approval_refusal
    from sase.main.plan_direct_approval import already_implemented_refusal

    recovery = CoderRecovery(
        verdict="succeeded",
        prior_coders=(
            PriorCoder(
                name="0sk--code",
                state="succeeded",
                outcome="completed",
                age="2h ago",
            ),
        ),
        approved_action="tale",
        approved_age="18m ago",
        gate_id="7ff58c91",
        plan_argument="plan:202609/work.md",
        refusal_code="already_implemented",
    )
    render_direct_approval_refusal(
        already_implemented_refusal("work", "Work title", recovery, "PROMPT")
    )

    err = capsys.readouterr().err
    assert "is already approved and implemented" in err
    assert "coder   0sk--code · completed 2h ago" in err
    assert "To run another coder anyway:" in err
    assert "sase run" in err
