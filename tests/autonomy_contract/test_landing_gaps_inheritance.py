"""Landing-gap contracts for autonomy inheritance and launch paths."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.autonomy.record import read_record
from tests.autonomy_contract import harness
from tests.autonomy_contract._landing_gaps_helpers import inputs


def _host_composed_plan(parent_dir: Path, parent_meta: dict[str, Any]):
    from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan

    return AgentSessionAttachLaunchPlan(
        parent_arg="parent",
        suffix_arg="@",
        parent_name=str(parent_meta.get("name", "contract-agent")),
        parent_base="contract-agent",
        parent_timestamp="20260711120000",
        parent_artifacts_dir=str(parent_dir),
        role_suffix="--1",
        agent_name="contract-agent--1",
        agent_session_role="coder",
        parent_agent_session_member_name="contract-agent",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="contract-proj",
        host_composed=True,
    )


def _build_with_prompt(
    prompt: str, tmp_path: Path, plan=None, preserved: dict[str, Any] | None = None
):
    from sase.axe.run_agent_directive_metadata import build_agent_meta
    from sase.macro.directives import extract_prompt_directives

    _, directives = extract_prompt_directives(prompt)
    return build_agent_meta(
        inputs(tmp_path, preserved),
        directives=directives,
        agent_name="contract-agent--1",
        agent_tribe=None,
        agent_session_attach_plan=plan,
        clan_membership_plan=None,
    )


def test_host_composed_explicit_manual_narrows(tmp_path: Path) -> None:
    """Explicit ``%auto:manual``/``:off`` narrows a tale parent to manual."""
    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    parent_meta = harness.read_meta(parent_dir)
    plan = _host_composed_plan(parent_dir, parent_meta)
    for prompt in ("%auto:manual\nDo the work", "%auto:off\nDo the work"):
        meta = _build_with_prompt(prompt, tmp_path, plan=plan)
        record = read_record(meta)
        assert record is not None
        assert record["profile"] == "manual"
        assert record["source"] == "inherited"


def test_host_composed_bare_widening_refused(tmp_path: Path) -> None:
    """Bare ``%auto`` on a tale child keeps the inherited tale record."""
    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    parent_meta = harness.read_meta(parent_dir)
    plan = _host_composed_plan(parent_dir, parent_meta)
    meta = _build_with_prompt("%auto\nDo the work", tmp_path, plan=plan)
    record = read_record(meta)
    assert record is not None
    assert record["profile"] == "tale"
    assert record["selection"] == "tale"
    assert record["source"] == "inherited"


def test_host_composed_unreadable_predecessor_fails_closed(tmp_path: Path) -> None:
    """An unreadable parent never lets a host-composed child widen."""
    missing = tmp_path / "missing-parent"
    plan = _host_composed_plan(missing, {"name": "gone"})
    meta = _build_with_prompt("%auto\nDo the work", tmp_path, plan=plan)
    record = read_record(meta)
    assert record is not None
    assert record["profile"] == "manual"


def _direct_approval_plan(tmp_path: Path, *, recovery: bool = False):
    from sase.main.plan_direct_approval import (
        CoderPlacement,
        DirectApprovalPlan,
        DirectApprovalRequest,
    )

    source = tmp_path / "approved-plan.md"
    source.write_text("# Approved plan\n", encoding="utf-8")
    fields: dict[str, Any] = {}
    if recovery:
        from sase.main.plan_direct_approval_recovery import CoderRecovery

        fields["recovery"] = CoderRecovery(
            verdict="recover",
            approved_action="approve",
            approved_age="1m ago",
            plan_argument="plan:202610/approved-plan.md",
        )
    return DirectApprovalPlan(
        request=DirectApprovalRequest(selector=str(source), project="contract-proj"),
        kind="approve",
        source_path=source,
        location="proposal",
        name="approved-plan",
        title="Approved plan",
        size="small",
        project="contract-proj",
        project_tag="+contract-proj",
        planner="contract-agent",
        gate=None,
        placement=CoderPlacement(
            mode="session",
            parent="contract-agent",
            member_name="contract-agent--code",
            agent_session="contract-agent",
        ),
        model_directive="@small",
        predicted_plan_ref="plan:202610/approved-plan.md",
        **fields,
    )


@pytest.mark.parametrize("caller", ["direct", "recovery"])
@pytest.mark.parametrize("cwd_project", ["contract-proj", "other-proj", None])
@pytest.mark.parametrize("parent_mode", ["tale", "off"])
def test_direct_approval_and_recovery_inherit_from_target_project(
    tmp_path: Path,
    monkeypatch,
    caller: str,
    cwd_project: str | None,
    parent_mode: str,
) -> None:
    """Direct approval and recovery retain inheritance across unrelated CWDs."""
    from types import SimpleNamespace

    from sase.agent._agent_session_attach_launch import (
        load_agent_session_attach_plan_from_env,
        prepare_agent_session_attach_launch,
    )
    from sase.agent import _agent_session_attach_resolution as attach_resolution
    from sase.agent.launch_types import AgentLaunchResult
    from sase.axe.run_agent_directive_metadata import build_agent_meta
    from sase.macro.directives import extract_prompt_directives
    from sase.main.plan_direct_approval_run import (
        execute_coder_recovery,
        execute_direct_approval,
    )

    monkeypatch.delenv("SASE_AGENT", raising=False)
    workdir = tmp_path / "work"
    workdir.mkdir()
    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", workdir)
    if parent_mode == "off":
        harness.adapt_a_off(parent_dir)
    parent_meta = harness.read_meta(parent_dir)
    parent_record = read_record(parent_meta)
    assert parent_record is not None

    unresolved_plan = replace(
        _host_composed_plan(parent_dir, parent_meta), host_composed=False
    )
    resolved_projects: list[str] = []

    def _resolve(directive, *, project_name: str, **_kwargs):
        resolved_projects.append(project_name)
        if project_name != "contract-proj":
            raise RuntimeError(f"unrecognized session project: {project_name}")
        return unresolved_plan

    monkeypatch.setattr(
        attach_resolution, "resolve_agent_session_attach_plan", _resolve
    )
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: (None, 0, cwd_project),
    )
    monkeypatch.setattr(
        "sase.config._owner.require_agent_owner_identity", lambda: object()
    )
    built: list[dict[str, Any]] = []

    def _fake_process_launch(prompt: str, extra_env=None, **_kwargs):
        context = SimpleNamespace(project_name="contract-proj", is_home_mode=True)
        pre_resolved = load_agent_session_attach_plan_from_env(dict(extra_env or {}))
        assert pre_resolved is not None and pre_resolved.host_composed is True
        _context, child_env = prepare_agent_session_attach_launch(
            prompt,
            context,
            dict(extra_env or {}),
            resolve_agent_session_attach_plan=_resolve,
        )
        attach_plan = load_agent_session_attach_plan_from_env(child_env)
        assert attach_plan is not None and attach_plan.host_composed is True
        _, directives = extract_prompt_directives(prompt)
        child_meta = build_agent_meta(
            inputs(workdir),
            directives=directives,
            agent_name=attach_plan.agent_name,
            agent_tribe=None,
            agent_session_attach_plan=attach_plan,
            clan_membership_plan=None,
        )
        built.append(child_meta)
        return [
            AgentLaunchResult(
                pid=123,
                workspace_num=0,
                workspace_dir=str(workdir),
                output_path=str(tmp_path / "coder.out"),
                agent_name=attach_plan.agent_name,
            )
        ]

    monkeypatch.setattr(
        "sase.agent.launch_cwd.launch_agents_from_cwd", _fake_process_launch
    )
    plan = _direct_approval_plan(tmp_path, recovery=caller == "recovery")
    outcome = (
        execute_coder_recovery(plan)
        if caller == "recovery"
        else execute_direct_approval(plan)
    )

    assert outcome.coder is not None
    assert len(built) == 1
    child_record = read_record(built[0])
    assert child_record is not None
    assert child_record["profile"] == parent_record["profile"]
    assert child_record["selection"] == parent_record["selection"]
    assert child_record["policy"] == parent_record["policy"]
    assert child_record["source"] == "inherited"
    assert child_record["revision"] == parent_record["revision"]
    assert child_record["last"] == parent_record["last"]
    assert child_record["digest"] == parent_record["digest"]
    assert set(resolved_projects) == {"contract-proj"}


def test_human_session_attach_uses_its_prompt_and_standalone_stays_standalone(
    tmp_path: Path,
) -> None:
    """Human attaches resolve their prompt; standalone coders need no attach."""
    from types import SimpleNamespace

    from sase.agent._agent_session_attach_launch import (
        load_agent_session_attach_plan_from_env,
        prepare_agent_session_attach_launch,
    )
    from sase.main.plan_direct_approval_launch import launch_coder_once
    from sase.main.plan_direct_approval_types import CoderPlacement

    _, _, parent_dir = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    prompt = "%id(code, session=contract-agent)\n%auto:manual\nHuman work"
    context = SimpleNamespace(project_name="contract-proj", is_home_mode=True)
    _context, env = prepare_agent_session_attach_launch(
        prompt,
        context,
        None,
        resolve_agent_session_attach_plan=lambda _directive, **_kwargs: replace(
            _host_composed_plan(parent_dir, {"name": "contract-agent"}),
            host_composed=False,
        ),
    )
    human_meta = _build_with_prompt(
        prompt, tmp_path, plan=load_agent_session_attach_plan_from_env(env)
    )
    human_record = read_record(human_meta)
    assert human_record is not None
    assert human_record["profile"] == "manual"
    assert human_record["source"] == "prompt"

    seen: list[dict[str, str]] = []

    def _launch(_prompt: str, extra_env=None, **_kwargs):
        seen.append(dict(extra_env or {}))
        return [object()]

    with patch("sase.agent.launch_cwd.launch_agents_from_cwd", _launch):
        launch_coder_once(
            "+contract-proj #coder(plan)",
            tmp_path / "standalone.md",
            project_name="contract-proj",
            placement=CoderPlacement(mode="standalone"),
        )
    assert seen and "SASE_AGENT_SESSION_ATTACH" not in seen[0]


def test_in_process_explicit_narrowing_via_real_helper(tmp_path: Path) -> None:
    """Agent-authored ``%auto:manual`` narrows an in-process successor."""
    import uuid

    from unittest.mock import patch as _patch

    from sase.axe.run_agent_helpers_artifacts import create_followup_artifacts

    _, live_meta, _ = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    followup = tmp_path / f"followup-{uuid.uuid4().hex[:8]}"
    followup.mkdir()
    with _patch(
        "sase.axe.run_agent_helpers_artifacts.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "contract-proj",
            dict(live_meta),
            "--pipe",
            "20260711120000",
            relationships={"autonomy_explicit_selection": "manual"},
        )
    record = read_record(harness.read_meta(followup))
    assert record is not None
    assert record["profile"] == "manual"


def test_in_process_widening_refused_via_real_helper(tmp_path: Path) -> None:
    """Bare ``%auto`` never widens an in-process tale successor."""
    import uuid

    from unittest.mock import patch as _patch

    from sase.axe.run_agent_helpers_artifacts import create_followup_artifacts

    _, live_meta, _ = harness.launch_meta("%auto:tale\nDo the work", tmp_path)
    followup = tmp_path / f"followup-{uuid.uuid4().hex[:8]}"
    followup.mkdir()
    with _patch(
        "sase.axe.run_agent_helpers_artifacts.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "contract-proj",
            dict(live_meta),
            "--pipe",
            "20260711120000",
            relationships={"autonomy_explicit_selection": ""},
        )
    record = read_record(harness.read_meta(followup))
    assert record is not None
    assert record["profile"] == "tale"
    assert record["selection"] == "tale"


def test_successor_prompt_extraction_covers_manual(tmp_path: Path) -> None:
    """The in-process entry point extracts explicit manual/off as narrowing."""
    from sase.axe.run_agent_successor import _explicit_autonomy_selection

    assert _explicit_autonomy_selection("%auto:manual\nwork") == "manual"
    assert _explicit_autonomy_selection("%auto:off\nwork") == "manual"
    assert _explicit_autonomy_selection("%auto\nwork") == ""
    assert _explicit_autonomy_selection("plain work") is None
