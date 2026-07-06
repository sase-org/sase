from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.agent_family import (
    build_handoff_event,
    evaluate_handoff_event,
    evaluate_plan_approval_transition,
    family_state_snapshot,
    load_agent_family_definition_from_mapping,
)
from sase.agent_family.custom_definitions import (
    AgentFamilyRoleDefinition,
    get_all_agent_family_definitions,
    load_agent_family_definition_from_file,
)
from sase.axe.run_agent_exec import run_execution_loop
from sase.axe.run_agent_exec_plan_accept import handle_accepted_plan
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.xprompt.load_issues import collect_xprompt_load_issues
from sase.xprompt.workflow_loader import get_all_workflows
from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state


def _definition_mapping(
    *,
    role_id: str = "tester",
    suffix: str | None = "--tester",
    prompt_template: str = "agent_family_tester:{source_artifacts}",
    after: str = "code",
    on_done: str = "terminate",
    max_visits: int = 1,
    on_failure: str = "notify_and_continue",
    auto: str = "run",
) -> dict[str, object]:
    role: dict[str, object] = {
        "prompt_template": prompt_template,
        "placement": {"after": after},
        "on_done": on_done,
        "max_visits": max_visits,
        "on_failure": on_failure,
        "auto": auto,
    }
    if suffix is not None:
        role["suffix"] = suffix
    return {
        "kind": "agent_family",
        "schema_version": 1,
        "id": role_id,
        "version": 1,
        "extends": "standard_plan_chain",
        "roles": {role_id: role},
    }


def _role(**kwargs: object) -> AgentFamilyRoleDefinition:
    definition = load_agent_family_definition_from_mapping(
        _definition_mapping(**kwargs),
        "memory.yml",
        validate_prompt_refs=False,
    )
    assert definition is not None
    return definition.roles[0]


def test_agent_family_loader_accepts_valid_custom_role() -> None:
    definition = load_agent_family_definition_from_mapping(
        _definition_mapping(role_id="improve_plan", suffix=None, after="plan"),
        "memory.yml",
        validate_prompt_refs=False,
    )

    assert definition is not None
    role = definition.roles[0]
    assert role.id == "improve_plan"
    assert role.suffix == "--improve_plan"
    assert role.placement_after == "plan"
    assert role.config_id == "improve_plan"
    assert (
        role.as_snapshot()["prompt_template"]
        == "agent_family_tester:{source_artifacts}"
    )


def test_agent_family_loader_reports_validation_issues() -> None:
    invalid = _definition_mapping()
    roles = invalid["roles"]
    assert isinstance(roles, dict)
    tester = roles["tester"]
    assert isinstance(tester, dict)
    tester.pop("auto")

    with collect_xprompt_load_issues() as issues:
        definition = load_agent_family_definition_from_mapping(
            invalid,
            "bad.yml",
            validate_prompt_refs=False,
        )

    assert definition is None
    assert [issue.kind for issue in issues] == ["agent_family"]
    assert "role 'tester' auto must be one of" in issues[0].error


def test_agent_family_loader_reports_unknown_xprompt_reference() -> None:
    with collect_xprompt_load_issues() as issues:
        definition = load_agent_family_definition_from_mapping(
            _definition_mapping(prompt_template="missing_template:{source_artifacts}"),
            "bad-ref.yml",
            validate_prompt_refs=True,
        )

    assert definition is None
    assert "unknown xprompt 'missing_template'" in issues[0].error


def test_agent_family_discovery_uses_xprompt_dirs_without_workflow_noise(
    tmp_path: Path,
    monkeypatch,
) -> None:
    xprompts = tmp_path / "xprompts"
    xprompts.mkdir()
    family_file = xprompts / "tester.yml"
    family_file.write_text(
        """
kind: agent_family
schema_version: 1
id: tester
version: 1
roles:
  tester:
    suffix: "--tester"
    prompt_template: "agent_family_tester:{source_artifacts}"
    placement: {after: code}
    on_done: terminate
    max_visits: 1
    on_failure: notify_and_continue
    auto: run
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with collect_xprompt_load_issues() as issues:
        definitions = get_all_agent_family_definitions()
        workflows = get_all_workflows()

    assert definitions["tester"].source_path == str(family_file)
    assert "tester" not in workflows
    assert issues == []


def test_plan_transition_selects_after_plan_role_and_honors_auto_policy() -> None:
    skip_role = _role(role_id="improve_plan", suffix=None, after="plan", auto="skip")
    run_role = _role(role_id="tester", after="plan", auto="run")

    interactive = evaluate_plan_approval_transition(
        action="approve",
        commit_plan=False,
        run_coder=True,
        feedback_count=0,
        qa_round_count=0,
        custom_roles=[skip_role],
    )
    skipped_auto = evaluate_plan_approval_transition(
        action="approve",
        commit_plan=False,
        run_coder=True,
        feedback_count=0,
        qa_round_count=0,
        custom_roles=[skip_role],
        auto_mode=True,
    )
    run_auto = evaluate_plan_approval_transition(
        action="approve",
        commit_plan=False,
        run_coder=True,
        feedback_count=0,
        qa_round_count=0,
        custom_roles=[run_role],
        auto_mode=True,
    )

    assert interactive.custom_role is not None
    assert interactive.custom_role.role.id == "improve_plan"
    assert skipped_auto.custom_role is None
    assert run_auto.custom_role is not None
    assert run_auto.custom_role.role.id == "tester"


def test_role_completed_selects_after_code_role_and_enforces_cap() -> None:
    tester = _role(role_id="tester", after="code", max_visits=1)
    event = build_handoff_event(
        kind="role_completed",
        artifacts_dir="/tmp/code",
        payload={"outcome": "success", "artifacts_ref": "/tmp/code"},
        current_role_suffix="--code",
        agent_family_role="code",
    )

    selected = evaluate_handoff_event(
        event,
        family_state_snapshot(current_role_suffix="--code"),
        custom_roles=[tester],
    )
    capped = evaluate_handoff_event(
        event,
        family_state_snapshot(
            current_role_suffix="--code",
            visit_counts={"tester": 1},
        ),
        custom_roles=[tester],
    )

    assert selected.terminal is False
    assert selected.custom_role is not None
    assert selected.custom_role.role.id == "tester"
    assert (
        selected.custom_role.runtime_metadata.as_meta_fields()[
            "agent_family_custom_role"
        ]["id"]
        == "tester"
    )
    assert capped.terminal is True
    assert capped.terminal_reason == "custom_role_cap_exhausted"


def test_completed_custom_role_snapshot_terminates_after_running() -> None:
    tester = _role(role_id="tester", after="code")
    event = build_handoff_event(
        kind="role_completed",
        artifacts_dir="/tmp/tester",
        payload={"outcome": "success", "artifacts_ref": "/tmp/tester"},
        current_role_suffix="--tester",
        agent_family_role="tester",
    )

    evaluation = evaluate_handoff_event(
        event,
        family_state_snapshot(
            current_role_suffix="--tester",
            agent_family_role="tester",
            visit_counts={"tester": 1},
        ),
        custom_roles=[tester],
        custom_role_snapshot=tester.as_snapshot(),
    )

    assert evaluation.terminal is True
    assert evaluation.custom_role is None


def test_handle_accepted_plan_spawns_after_plan_custom_role(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    improve = _role(
        role_id="improve_plan",
        suffix=None,
        prompt_template="agent_family_improve_plan:{plan_file}",
        after="plan",
        on_done="re_review",
        max_visits=3,
        on_failure="notify_and_stop",
        auto="skip",
    )
    created = tmp_path / "improve_artifacts"

    def fake_create_followup_artifacts(*_args: object, **kwargs: object) -> str:
        created.mkdir()
        relationships = kwargs["relationships"]
        assert isinstance(relationships, dict)
        (created / "agent_meta.json").write_text(
            json.dumps(
                {
                    "agent_family_role": kwargs["agent_family_role"],
                    "role_suffix": "--improve_plan",
                    **relationships,
                }
            ),
            encoding="utf-8",
        )
        return str(created)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_plan_accept.active_roles_after",
        lambda *_args, **_kwargs: (improve,),
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_custom_roles.create_followup_artifacts",
        fake_create_followup_artifacts,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_custom_roles.promote_to_workflow",
        lambda *_args, **_kwargs: None,
    )

    with (
        patch("sase.sdd.beads.get_effective_sdd_config", return_value=True),
        patch("sase.sdd.files.get_sdd_dir", return_value=tmp_path),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.sdd.files.write_sdd_files",
            return_value=(tmp_path / "prompt.md", tmp_path / "sdd_plan.md"),
        ),
        patch("sase.sdd.files.expand_prompt_for_spec", lambda prompt: prompt),
        patch(
            "sase.axe.run_agent_exec_plan_accept._commit_sdd_files", return_value=True
        ),
        patch("sase.axe.run_agent_exec_plan_accept.update_meta_field"),
        patch("sase.axe.run_agent_exec_plan_accept._write_followup_effort_meta"),
    ):
        outcome = handle_accepted_plan(
            PlanApprovalResult(
                action="approve",
                plan_file=str(plan_file),
                commit_plan=False,
            ),
            ctx,
            state,
        )

    assert outcome is None
    assert state.current_artifacts_dir == str(created)
    assert state.current_role_suffix == "--improve_plan"
    assert state.current_prompt == f"#agent_family_improve_plan:{plan_file}"
    meta = json.loads((created / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["agent_family_role"] == "improve_plan"
    assert meta["agent_family_custom_role"]["id"] == "improve_plan"


def test_execution_loop_runs_after_code_custom_role(
    tmp_path: Path, monkeypatch
) -> None:
    tester = _role(role_id="tester", after="code")
    reviewer = _role(role_id="reviewer", after="code")
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    executed_prompts: list[str] = []
    code_artifacts = tmp_path / "code_artifacts"
    tester_artifacts = tmp_path / "tester_artifacts"
    code_artifacts.mkdir()
    (code_artifacts / "agent_meta.json").write_text(
        json.dumps({"agent_family_role": "code", "role_suffix": "--code"}),
        encoding="utf-8",
    )

    def execute_workflow(
        _name: str,
        _args: list[object],
        _kwargs: dict[str, object],
        *,
        workflow_obj: object,
        **_extra: object,
    ) -> MagicMock:
        executed_prompts.append(workflow_obj.steps[0].agent)
        return MagicMock(name=f"workflow-result-{len(executed_prompts)}")

    def first_kill_creates_code_prompt(_ctx: object, state: object) -> None:
        state.current_prompt = "code prompt"
        state.current_role_suffix = "--code"
        state.current_artifacts_dir = str(code_artifacts)
        state.selected_member_ids = ("tester",)
        state.agent_step = 2
        return None

    def fake_create_followup_artifacts(*_args: object, **kwargs: object) -> str:
        tester_artifacts.mkdir()
        relationships = kwargs["relationships"]
        assert isinstance(relationships, dict)
        (tester_artifacts / "agent_meta.json").write_text(
            json.dumps(
                {
                    "agent_family_role": kwargs["agent_family_role"],
                    "role_suffix": "--tester",
                    **relationships,
                }
            ),
            encoding="utf-8",
        )
        return str(tester_artifacts)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec.active_roles_after",
        lambda after, **_kwargs: (reviewer, tester) if after == "code" else (),
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_custom_roles.create_followup_artifacts",
        fake_create_followup_artifacts,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_custom_roles.promote_to_workflow",
        lambda *_args, **_kwargs: None,
    )

    with (
        patch(
            "sase.xprompt.workflow_runner.execute_workflow",
            side_effect=execute_workflow,
        ),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec.was_killed", side_effect=[True, False, False]),
        patch(
            "sase.axe.run_agent_exec._handle_killed_iteration",
            side_effect=first_kill_creates_code_prompt,
        ),
        patch("sase.axe.run_agent_exec._finalize_loop", return_value="final"),
    ):
        result = run_execution_loop(ctx, "planner prompt")

    assert result == "final"
    assert executed_prompts == [
        "planner prompt",
        "code prompt",
        f"#agent_family_tester:{code_artifacts}",
    ]
    assert (
        json.loads((tester_artifacts / "agent_meta.json").read_text())[
            "agent_family_custom_role"
        ]["id"]
        == "tester"
    )
