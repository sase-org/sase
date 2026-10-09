"""Coder-recovery render tests for ``sase plan approve``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.plan_approve_render import (
    render_coder_recovery,
    render_coder_recovery_dry_run,
)
from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalPlan,
    DirectApprovalRequest,
)
from sase.main.plan_direct_approval_recovery import CoderRecovery, PriorCoder
from tests._plan_approve_render_helpers import (
    make_launched,
    no_color,  # noqa: F401 (registers the autouse fixture)
)


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
    render_coder_recovery(_recovery_outcome(plan, coder=make_launched("0sk--2")))

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
    assert "Coder relaunch failed" in out
    assert "before  0sk--code · failed 14m ago" in out
    assert "Coder launch failed: boom" in out
    assert "Retry (re-runs every fallback and records the receipt):" in out
    assert "sase plan approve" in out
    assert "Or launch it yourself:" in out
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
