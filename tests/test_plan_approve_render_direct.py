"""Direct-route render tests for ``sase plan approve``."""

from __future__ import annotations

import shlex

import pytest

from sase.main.plan_approve_render import (
    render_approval_error,
    render_direct_approval,
    render_direct_approval_dry_run,
    render_direct_approval_refusal,
)
from sase.main.plan_direct_approval import DirectApprovalRefusal
from sase.plan_approval_actions import PlanApprovalActionError
from tests._plan_approve_render_helpers import (
    PLAN_REF,
    PROMPT,
    make_direct_plan,
    make_launched,
    make_outcome,
    make_retired_gate,
    no_color,  # noqa: F401 (registers the autouse fixture)
    read_output,
)


def test_direct_agent_session_card(capsys: pytest.CaptureFixture[str]) -> None:
    plan = make_direct_plan(mode="session", gate=make_retired_gate("expired"))

    render_direct_approval(make_outcome(plan, coder=make_launched()))

    out, err = read_output(capsys)
    assert err == ""
    assert "✓ Tale approved · updates_tab" in out
    assert f"plan    {PLAN_REF} · committed to sase" in out
    assert "coder   bob--code · agent session bob · %model:@medium" in out
    assert "no agent session" not in out
    assert "gate    a1b2c3d4 · expired approval gate closed" in out
    assert "follow  sase agent show bob--code" in out


def test_direct_standalone_card_gives_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(make_outcome(make_direct_plan(), coder=make_launched("kx7")))

    out, _ = read_output(capsys)
    assert "coder   kx7 · standalone · %model:@medium" in out
    assert "no agent session: this plan records no planner" in out
    assert "gate    none · never proposed" in out
    assert "follow  sase agent show kx7" in out


def test_direct_standalone_card_falls_back_to_pid_without_agent_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(
        make_outcome(make_direct_plan(), coder=make_launched(None, pid=9001))
    )

    out, _ = read_output(capsys)
    assert "coder   PID 9001 · standalone" in out
    assert "None" not in out
    assert "follow  sase agent list" in out
    assert "sase agent show" not in out


def test_direct_approve_kind_is_not_labelled_committed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(
        make_outcome(make_direct_plan(kind="approve"), coder=make_launched("kx7"))
    )

    out, _ = read_output(capsys)
    assert "✓ Approve approved · updates_tab" in out
    assert "committed to sase" not in out


def test_direct_commit_only_card_launches_no_coder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(make_outcome(make_direct_plan(kind="commit")))

    out, _ = read_output(capsys)
    assert "coder   none · commit only" in out
    assert "follow" not in out
    assert "Launch it yourself" not in out


def test_direct_card_prints_best_effort_warnings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval(
        make_outcome(
            make_direct_plan(),
            coder=make_launched("kx7"),
            warnings=("planner metadata could not be recorded: boom",),
        )
    )

    out, _ = read_output(capsys)
    assert "! planner metadata could not be recorded: boom" in out


def test_direct_partial_failure_card_gives_recovery_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = make_direct_plan(mode="session", gate=make_retired_gate("orphaned"))

    render_direct_approval(make_outcome(plan, coder_error="launch exploded"))

    out, err = read_output(capsys)
    assert err == ""
    assert f"✓ Plan committed · updates_tab · {PLAN_REF}" in out
    assert "✗ Coder launch failed: launch exploded" in out
    assert "Retry (re-runs every fallback and records the receipt):" in out
    assert "sase plan approve" in out
    assert "Or launch it yourself:" in out
    assert f"sase run {shlex.quote(PROMPT)}" in out
    assert "follow" not in out


def test_direct_partial_failure_recovery_command_survives_multiline_prompt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompt = f"{PROMPT}\n\nAdditional instructions:\nkeep [it] it's small"

    render_direct_approval(
        make_outcome(make_direct_plan(prompt=prompt), coder_error="boom", prompt=prompt)
    )

    out, _ = read_output(capsys)
    command = out[out.index("sase run ") + len("sase run ") :].rstrip("\n")
    assert shlex.split(command) == [prompt]


def test_direct_gate_answered_concurrently_card_for_tale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    note = "gate a1b2c3d4e5f6 was answered concurrently; no coder was launched by this command"
    plan = make_direct_plan(mode="session", gate=make_retired_gate("orphaned"))

    render_direct_approval(
        make_outcome(plan, warnings=(note,), gate_answered_concurrently=True)
    )

    out, err = read_output(capsys)
    assert err == ""
    assert f"✓ Plan committed · updates_tab · {PLAN_REF}" in out
    assert "coder   none launched · left to the gate's responder" in out
    assert "no agent session" not in out
    assert "gate    a1b2c3d4 · answered concurrently, not closed here" in out
    assert f"! {note}" in " ".join(out.split())
    assert "Check whether the gate's responder launched a coder:" in out
    assert "sase agent list" in out
    assert f"sase run {shlex.quote(PROMPT)}" in out
    assert "follow" not in out


def test_direct_gate_answered_concurrently_card_for_commit_needs_no_recovery(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = make_direct_plan(kind="commit", gate=make_retired_gate("orphaned"))

    render_direct_approval(make_outcome(plan, gate_answered_concurrently=True))

    out, _ = read_output(capsys)
    assert "✓ Plan committed · updates_tab" in out
    assert "coder   none · commit only" in out
    assert "sase run" not in out


def test_direct_dry_run_card_standalone(capsys: pytest.CaptureFixture[str]) -> None:
    render_direct_approval_dry_run(make_direct_plan())

    out, err = read_output(capsys)
    assert err == ""
    assert "◇ Dry run · updates_tab would be approved as a tale" in out
    assert "plan    /plans/updates_tab.md" in out
    assert f"→ {PLAN_REF} in sase" in out
    assert "coder   standalone · %model:@medium" in out
    assert "no agent session: this plan records no planner" in out
    assert "gate    none · never proposed" in out
    assert f"prompt  {PROMPT}" in out
    assert "Nothing was changed. Re-run without -n/--dry-run to approve." in out


def test_direct_dry_run_card_agent_session_with_gate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_direct_approval_dry_run(
        make_direct_plan(mode="session", gate=make_retired_gate("orphaned"))
    )

    out, _ = read_output(capsys)
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

    out, err = read_output(capsys)
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

    _, err = read_output(capsys)
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

    out, err = read_output(capsys)
    assert out == ""
    assert err.splitlines()[0] == "✗ it broke"
    assert hint in err


def test_approval_error_without_recovery_hint_is_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_approval_error(PlanApprovalActionError("invalid_request", "wait", "bad"))

    _, err = read_output(capsys)
    assert err.splitlines() == ["✗ bad"]
