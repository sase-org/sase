"""Resolver and decision model for gateless plan approvals."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalRefusal,
    DirectApprovalRequest,
    compose_coder_prompt,
    resolve_direct_approval,
)
from sase.main.plan_pending_diagnosis import PlanGateHistory
from sase.plan_approval_actions import PlanApprovalValidationError
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _write_plan(tmp_path: Path, name: str, content: str) -> Path:
    plan = tmp_path / name
    plan.write_text(content, encoding="utf-8")
    return plan


def _request(selector: str, **overrides: object) -> DirectApprovalRequest:
    fields: dict[str, object] = {"selector": selector, "project": "demo"}
    fields.update(overrides)
    return DirectApprovalRequest(**fields)  # type: ignore[arg-type]


def test_unknown_selector_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_direct_approval(_request("no-such-plan-xyz")) is None


def test_ambiguous_selector_refuses(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    for shard in ("202609", "202610"):
        plan = home / "plans" / shard / "dup.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    outcome = resolve_direct_approval(_request("dup"))
    assert isinstance(outcome, DirectApprovalRefusal)
    assert outcome.code == "ambiguous"


def test_invalid_plan_raises_validation(tmp_path: Path, monkeypatch) -> None:
    plan = _write_plan(tmp_path, "bad.md", "---\ntier: tale\n---\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(PlanApprovalValidationError):
        resolve_direct_approval(_request(str(plan)))


def test_standalone_when_no_planner(tmp_path: Path, monkeypatch) -> None:
    plan = _write_plan(tmp_path, "solo.md", VALID_TALE_PLAN)
    monkeypatch.chdir(tmp_path)
    outcome = resolve_direct_approval(_request(str(plan)))
    assert not isinstance(outcome, (DirectApprovalRefusal, type(None)))
    assert outcome.placement.mode == "standalone"
    assert outcome.placement.reason == "this plan records no planner"
    assert outcome.kind == "tale"
    assert outcome.project == "demo"
    assert outcome.project_tag == "+demo" or outcome.project_tag
    assert outcome.model_directive.startswith("@")
    assert "#coder(" in outcome.coder_prompt_preview


def test_epic_guard_without_explicit_kind(tmp_path: Path, monkeypatch) -> None:
    plan = _write_plan(tmp_path, "big.md", VALID_EPIC_PLAN)
    monkeypatch.chdir(tmp_path)
    outcome = resolve_direct_approval(_request(str(plan)))
    assert isinstance(outcome, DirectApprovalRefusal)
    assert outcome.code == "epic_guard"
    assert "-k epic" in outcome.detail_lines[0]


def test_epic_kind_refuses_with_bead_work_hint(tmp_path: Path, monkeypatch) -> None:
    plan = _write_plan(tmp_path, "small.md", VALID_TALE_PLAN)
    monkeypatch.chdir(tmp_path)
    outcome = resolve_direct_approval(
        _request(str(plan), kind="epic", kind_explicit=True)
    )
    assert isinstance(outcome, DirectApprovalRefusal)
    assert outcome.code == "epic_without_gate"
    assert any("sase bead work" in hint for hint in outcome.hints)


def test_agent_session_placement_via_attach(tmp_path: Path, monkeypatch) -> None:
    from sase.agent.agent_session_attach import AgentSessionAttachLaunchPlan

    content = VALID_TALE_PLAN.replace(
        "title: Approved implementation",
        "title: Approved implementation\nproposed_by: bob",
    )
    plan = _write_plan(tmp_path, "fam.md", content)
    monkeypatch.chdir(tmp_path)
    attach = AgentSessionAttachLaunchPlan(
        parent_arg="bob",
        suffix_arg="code",
        parent_name="bob",
        parent_base="bob",
        parent_timestamp="20260924000000",
        parent_artifacts_dir=str(tmp_path),
        role_suffix="--code",
        agent_name="bob--code",
        agent_session_role="code",
        parent_agent_session_member_name="bob",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="demo",
        parent_is_running=False,
    )
    with patch(
        "sase.agent.agent_session_attach.resolve_agent_session_attach_plan",
        return_value=attach,
    ):
        outcome = resolve_direct_approval(_request(str(plan)))
    assert not isinstance(outcome, (DirectApprovalRefusal, type(None)))
    assert outcome.placement.mode == "session"
    assert outcome.placement.member_name == "bob--code"
    assert "%id(code, session=bob)" in outcome.coder_prompt_preview


def test_planner_running_refuses(tmp_path: Path, monkeypatch) -> None:
    from sase.agent.agent_session_attach import AgentSessionAttachLaunchPlan

    content = VALID_TALE_PLAN.replace(
        "title: Approved implementation",
        "title: Approved implementation\nproposed_by: bob",
    )
    plan = _write_plan(tmp_path, "run.md", content)
    monkeypatch.chdir(tmp_path)
    attach = AgentSessionAttachLaunchPlan(
        parent_arg="bob",
        suffix_arg="code",
        parent_name="bob",
        parent_base="bob",
        parent_timestamp="20260924000000",
        parent_artifacts_dir=str(tmp_path),
        role_suffix="--code",
        agent_name="bob--code",
        agent_session_role="code",
        parent_agent_session_member_name="bob",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="demo",
        parent_is_running=True,
    )
    with patch(
        "sase.agent.agent_session_attach.resolve_agent_session_attach_plan",
        return_value=attach,
    ):
        outcome = resolve_direct_approval(_request(str(plan)))
    assert isinstance(outcome, DirectApprovalRefusal)
    assert outcome.code == "planner_running"


def test_attach_error_falls_back_standalone(tmp_path: Path, monkeypatch) -> None:
    from sase.agent.agent_session_attach import AgentSessionAttachError

    content = VALID_TALE_PLAN.replace(
        "title: Approved implementation",
        "title: Approved implementation\nproposed_by: bob",
    )
    plan = _write_plan(tmp_path, "alone.md", content)
    monkeypatch.chdir(tmp_path)
    with patch(
        "sase.agent.agent_session_attach.resolve_agent_session_attach_plan",
        side_effect=AgentSessionAttachError(
            "Cannot attach session member to 'bob': no such agent session"
        ),
    ):
        outcome = resolve_direct_approval(_request(str(plan)))
    assert not isinstance(outcome, (DirectApprovalRefusal, type(None)))
    assert outcome.placement.mode == "standalone"
    assert "Cannot attach" not in (outcome.placement.reason or "")


def test_custom_prompt_model_wins(tmp_path: Path, monkeypatch) -> None:
    plan = _write_plan(tmp_path, "model.md", VALID_TALE_PLAN)
    monkeypatch.chdir(tmp_path)
    outcome = resolve_direct_approval(
        _request(str(plan), coder_prompt="%model:@large do the thing")
    )
    assert not isinstance(outcome, (DirectApprovalRefusal, type(None)))
    # The -p text carries the directive; no %model prefix is added.
    assert outcome.model_directive == ""
    assert "%model:" not in outcome.coder_prompt_preview.split("#coder(")[0]


def test_compose_coder_prompt_quoting_and_bead() -> None:
    placement = CoderPlacement(mode="standalone", reason="no planner")
    prompt = compose_coder_prompt(
        project_tag="+sase",
        model_directive="@medium",
        plan_argument="plan:202609/my plan.md",
        extra_prompt="be quick",
        wait=None,
        bead="sase-1",
        placement=placement,
    )
    assert prompt.startswith("+sase %model:@medium %id(bead=sase-1) #coder(")
    assert '"plan:202609/my plan.md"' in prompt
    assert "Additional instructions:\nbe quick" in prompt


def test_compose_coder_prompt_agent_session() -> None:
    placement = CoderPlacement(mode="session", parent="bob", agent_session="bob")
    prompt = compose_coder_prompt(
        project_tag="+sase",
        model_directive="@small",
        plan_argument="plan:202609/foo.md",
        extra_prompt=None,
        wait=None,
        bead=None,
        placement=placement,
    )
    assert "%id(code, session=bob)" in prompt
    assert "family=" not in prompt
    assert "#coder(plan:202609/foo.md)" in prompt


def test_compose_coder_prompt_session_directive_parses_without_legacy_syntax() -> None:
    from sase.feature_flags import override_flags
    from sase.xprompt.directives import extract_prompt_directives

    placement = CoderPlacement(mode="session", parent="bob", agent_session="bob")
    prompt = compose_coder_prompt(
        project_tag="+sase",
        model_directive="@small",
        plan_argument="plan:202609/foo.md",
        extra_prompt=None,
        wait=None,
        bead=None,
        placement=placement,
    )
    with override_flags(legacy_agent_family_syntax=False):
        _, directives = extract_prompt_directives(prompt)
    assert directives.agent_session_attach_parent == "bob"
    assert directives.agent_session_attach_suffix == "code"


# --- coder recovery placement --------------------------------------------------


def _attach_plan_for_placement(*, running: bool = False):
    from sase.agent.agent_session_attach import AgentSessionAttachLaunchPlan

    return AgentSessionAttachLaunchPlan(
        parent_arg="0sk",
        suffix_arg="code",
        parent_name="0sk",
        parent_base="0sk",
        parent_timestamp="20260925000000",
        parent_artifacts_dir="/tmp/planner",
        role_suffix="--code",
        agent_name="0sk--code",
        agent_session_role="code",
        parent_agent_session_member_name="0sk",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="demo",
        parent_is_running=running,
    )


def test_name_taken_attach_error_retries_with_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.agent_session_attach import AgentSessionAttachError
    from sase.main.plan_direct_approval import (
        _resolve_placement,
        compose_coder_prompt,
    )

    monkeypatch.chdir(tmp_path)

    calls: list[str] = []

    def _fake_attach(directive, project_name=None):
        calls.append(directive.suffix)
        if directive.suffix == "code":
            raise AgentSessionAttachError("taken", reason="name_taken")
        return _attach_plan_for_placement()

    monkeypatch.setattr(
        "sase.agent.agent_session_attach.resolve_agent_session_attach_plan",
        _fake_attach,
    )
    history = PlanGateHistory(kind="none")

    placement = _resolve_placement("0sk", "demo", history, plan_name="work")

    assert not isinstance(placement, DirectApprovalRefusal)
    assert placement.mode == "session"
    assert placement.suffix == "@"
    assert calls == ["code", "@"]
    prompt = compose_coder_prompt(
        project_tag="+demo",
        model_directive="@small",
        plan_argument="plan:202609/work.md",
        extra_prompt=None,
        wait=None,
        bead=None,
        placement=placement,
    )
    assert "%id(@, session=0sk)" in prompt


def test_recovery_ignores_parent_running_but_fresh_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.plan_direct_approval import DirectApprovalRefusal, _resolve_placement

    monkeypatch.setattr(
        "sase.agent.agent_session_attach.resolve_agent_session_attach_plan",
        lambda directive, project_name=None: _attach_plan_for_placement(running=True),
    )
    history = PlanGateHistory(kind="none")

    recovered = _resolve_placement(
        "0sk", "demo", history, plan_name="work", recovery=True
    )
    assert not isinstance(recovered, DirectApprovalRefusal)

    fresh = _resolve_placement("0sk", "demo", history, plan_name="work")
    assert isinstance(fresh, DirectApprovalRefusal)
    assert fresh.code == "planner_running"


def test_attach_name_taken_reason() -> None:
    from sase.agent.agent_session_attach import AgentSessionAttachError

    assert AgentSessionAttachError("x").reason is None
    assert AgentSessionAttachError("x", reason="name_taken").reason == "name_taken"
