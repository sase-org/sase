from __future__ import annotations

import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.family_attach import (
    _FamilyAttachDirective,
    _FamilyAttachError,
    _extract_family_attach_directive,
    default_with_feedback_parent_from_family_attach,
    prepare_family_attach_launch,
    _resolve_family_attach_plan,
)
from sase.agent.launch_executor import LaunchExecutionContext, execute_launch_plan
from sase.agent.launch_validation import validate_launch_name_requests
from sase.agent.multi_prompt_reference_directives import extract_static_name_directive
from sase.agent_family import (
    STANDARD_PLAN_CHAIN_ID,
    build_handoff_event,
    evaluate_handoff_event,
    evaluate_questions_transition,
    family_state_snapshot,
)
from sase.axe.run_agent_directives import extract_directives_and_write_meta
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.core.agent_launch_facade import plan_fake_fanout
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    AGENT_FAMILY_ROLE_FIELD,
    PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
    agent_family_role_for_suffix,
    is_plan_chain_artifact_meta,
)
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def _artifact_record(
    *,
    name: str = "foo",
    timestamp: str = "20260701010101",
    project_name: str = "sase",
    workflow_name: str | None = None,
    agent_family: str | None = None,
    role_suffix: str | None = None,
    parent_timestamp: str | None = None,
    artifact_dir: Path | str | None = None,
    has_done_marker: bool = True,
    workspace_dir: str | None = "/tmp/sase_7",
    workspace_num: int | None = 7,
    cl_name: str | None = "feature",
    changespec_name: str | None = None,
    sdd_plan_path: str | None = None,
    meta_plan_path: str | None = None,
    done_plan_path: str | None = None,
    record_plan_path: str | None = None,
) -> SimpleNamespace:
    meta = SimpleNamespace(
        name=name,
        workflow_name=workflow_name or name,
        agent_family=agent_family,
        role_suffix=role_suffix,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        cl_name=cl_name,
        changespec_name=changespec_name,
        parent_timestamp=parent_timestamp,
        sdd_plan_path=sdd_plan_path,
        plan_path=meta_plan_path,
    )
    done = (
        SimpleNamespace(cl_name=cl_name, plan_path=done_plan_path)
        if has_done_marker
        else None
    )
    running = None if has_done_marker else SimpleNamespace(cl_name=cl_name)
    return SimpleNamespace(
        agent_meta=meta,
        project_name=project_name,
        artifact_dir=str(
            artifact_dir
            or Path("/tmp") / project_name / "artifacts" / "ace-run" / timestamp
        ),
        timestamp=timestamp,
        has_done_marker=has_done_marker,
        done=done,
        workflow_state=None,
        running=running,
        plan_path=(
            SimpleNamespace(plan_path=record_plan_path) if record_plan_path else None
        ),
    )


def _patch_attach_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    records: list[SimpleNamespace],
    *,
    dismissed: list[dict[str, str | None]] | None = None,
) -> None:
    monkeypatch.setattr(
        "sase.agent.family_attach._agent_family_snapshot",
        lambda _project_name: SimpleNamespace(records=records),
    )
    monkeypatch.setattr(
        "sase.agent.family_attach._dismissed_identity_dicts",
        lambda: list(dismissed or []),
    )
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_agent_names",
        lambda: set(),
    )


def _write_agent_artifact(
    sase_home: Path,
    *,
    project_name: str,
    timestamp: str,
    meta: dict[str, object],
    done_outcome: str | None = None,
) -> Path:
    artifact_dir = (
        sase_home / "projects" / project_name / "artifacts" / "ace-run" / timestamp
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )
    if done_outcome is not None:
        (artifact_dir / "done.json").write_text(
            json.dumps({"outcome": done_outcome}),
            encoding="utf-8",
        )
    return artifact_dir


def test_name_directive_family_attach_form_parses_and_strips() -> None:
    cleaned, directives = extract_prompt_directives("%n(foo, reviewer)\nDo work")

    assert cleaned == "Do work"
    assert directives.name is None
    assert directives.family_attach_parent == "foo"
    assert directives.family_attach_suffix == "reviewer"


def test_name_directive_single_positional_keeps_plain_name_behavior() -> None:
    cleaned, directives = extract_prompt_directives("%n(foo)\nDo work")

    assert cleaned == "Do work"
    assert directives.name == "foo"
    assert directives.family_attach_parent is None


def test_name_directive_rejects_extra_positionals_and_keywords() -> None:
    with pytest.raises(DirectiveError, match="at most two positional"):
        extract_prompt_directives("%n(foo, reviewer, extra)\nDo work")

    with pytest.raises(DirectiveError, match="Unsupported keyword"):
        extract_prompt_directives("%n(foo, run_status=DONE)\nDo work")


def test_name_directive_rejects_legacy_family_suffix_spellings() -> None:
    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%n(foo, .reviewer)\nDo work")

    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%n(foo, -reviewer)\nDo work")


def test_prelaunch_name_helpers_ignore_family_attach_form() -> None:
    prompt = "%n(foo, reviewer)\nDo work"

    assert extract_static_name_directive(prompt) is None
    validate_launch_name_requests([prompt])


def test_extract_family_attach_directive() -> None:
    directive = _extract_family_attach_directive("%model:codex/gpt-5\n%n(foo, @)")

    assert directive == _FamilyAttachDirective(parent="foo", suffix="@")


def test_with_feedback_parent_default_uses_family_attach_directive() -> None:
    args: dict[str, str] = {"feedback": "tighten tests"}

    default_with_feedback_parent_from_family_attach(
        "with_feedback",
        args,
        prompt="%n(foo, @) #with_feedback:: tighten tests",
    )

    assert args["parent"] == "foo"


def test_custom_family_role_classifies_plan_chain_metadata() -> None:
    meta = {
        "name": "foo--reviewer",
        "workflow_name": "foo",
        "role_suffix": "--reviewer",
        "agent_family_role": "reviewer",
    }

    assert agent_family_role_for_suffix("--reviewer", agent_family_role="reviewer") == (
        "reviewer"
    )
    assert is_plan_chain_artifact_meta(meta)


def test_custom_family_role_is_standard_chain_evaluator_compatible() -> None:
    event = build_handoff_event(
        kind="questions_submitted",
        artifacts_dir="/tmp/foo-reviewer",
        payload={"questions": [{"question": "Clarify scope?"}]},
        current_role_suffix="--reviewer",
        agent_family_role="reviewer",
    )
    snapshot = family_state_snapshot(
        current_role_suffix="--reviewer",
        agent_family_role="reviewer",
    )

    evaluation = evaluate_handoff_event(event, snapshot)
    transition = evaluate_questions_transition(
        interrupted_suffix="--reviewer",
        interrupted_role="reviewer",
        feedback_count=0,
        qa_round_count=1,
    )

    assert event.interrupted_role == "reviewer"
    assert evaluation.gate_id == "user_questions"
    assert evaluation.runtime_metadata.as_meta_fields()["agent_family_config_id"] == (
        STANDARD_PLAN_CHAIN_ID
    )
    assert transition.followup_role == "reviewer"
    assert transition.suffix_template == "--reviewer-@"


def test_family_attach_collision_message_suggests_auto_suffix() -> None:
    from sase.agent.family_attach import _ensure_family_name_available

    with patch("sase.agent.names.get_reserved_agent_names", return_value={"foo--bar"}):
        with pytest.raises(_FamilyAttachError, match=r"%n\(foo, @\)"):
            _ensure_family_name_available(
                "foo--bar",
                _FamilyAttachDirective(parent="foo", suffix="bar"),
            )


def test_family_attach_absent_parent_error_uses_rust_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(monkeypatch, [])

    with pytest.raises(_FamilyAttachError) as exc_info:
        _resolve_family_attach_plan(
            _FamilyAttachDirective(parent="missing", suffix="reviewer"),
            project_name="sase",
        )

    assert "parent agent 'missing' was not found in project 'sase'" in str(
        exc_info.value
    )


def test_family_attach_dismissed_parent_error_names_revive_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _artifact_record(name="foo", timestamp="20260701010101")
    _patch_attach_snapshot(
        monkeypatch,
        [parent],
        dismissed=[
            {
                "agent_type": "workflow",
                "cl_name": "feature",
                "raw_suffix": "20260701010101",
            }
        ],
    )

    with pytest.raises(_FamilyAttachError) as exc_info:
        _resolve_family_attach_plan(
            _FamilyAttachDirective(parent="foo", suffix="reviewer"),
            project_name="sase",
        )

    message = str(exc_info.value)
    assert "dismissed parent 'foo'" in message
    assert "Revive the parent from the Agents tab" in message


def test_family_attach_ambiguous_parent_error_lists_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = "20260701010101"
    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(
                name="foo--plan",
                workflow_name="foo",
                timestamp=timestamp,
                artifact_dir="/tmp/foo-plan",
            ),
            _artifact_record(
                name="foo--code",
                workflow_name="foo",
                timestamp=timestamp,
                artifact_dir="/tmp/foo-code",
            ),
        ],
    )

    with pytest.raises(_FamilyAttachError) as exc_info:
        _resolve_family_attach_plan(
            _FamilyAttachDirective(parent="foo", suffix="reviewer"),
            project_name="sase",
        )

    message = str(exc_info.value)
    assert "multiple newest parent candidates matched" in message
    assert f"foo--plan@{timestamp}" in message
    assert f"foo--code@{timestamp}" in message


def test_family_attach_resolution_uses_newest_match_with_project_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(name="foo", timestamp="20260701010101"),
            _artifact_record(name="foo", timestamp="20260701010202"),
            _artifact_record(
                name="foo",
                timestamp="20260701030303",
                project_name="other",
                artifact_dir="/tmp/other/foo",
            ),
        ],
    )

    plan = _resolve_family_attach_plan(
        _FamilyAttachDirective(parent="foo", suffix="reviewer"),
        project_name="sase",
    )

    assert plan.parent_project_name == "sase"
    assert plan.parent_timestamp == "20260701010202"
    assert plan.parent_artifacts_dir != "/tmp/other/foo"


def test_family_attach_running_parent_builds_queued_plan(monkeypatch) -> None:
    record = _artifact_record(
        name="foo",
        timestamp="20260701010101",
        has_done_marker=False,
    )
    _patch_attach_snapshot(monkeypatch, [record])

    plan = _resolve_family_attach_plan(
        _FamilyAttachDirective(parent="foo", suffix="reviewer"),
        project_name="sase",
    )

    assert plan.parent_is_running is True
    assert plan.parent_project_name == "sase"
    assert plan.parent_timestamp == "20260701010101"
    assert plan.agent_name == "foo--reviewer"
    assert plan.parent_workspace_num == 7


@pytest.mark.parametrize(
    ("suffix", "expected_role"),
    [
        ("plan", "plan"),
        ("q", "q"),
        ("code", "code"),
        ("epic", "epic"),
        ("legend", "legend"),
        ("commit", "commit"),
        ("reviewer", "reviewer"),
    ],
)
def test_family_attach_role_mapping_through_attach_path(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    expected_role: str,
) -> None:
    _patch_attach_snapshot(monkeypatch, [_artifact_record(name="foo")])

    plan = _resolve_family_attach_plan(
        _FamilyAttachDirective(parent="foo", suffix=suffix),
        project_name="sase",
    )

    assert plan.role_suffix == f"--{suffix}"
    assert plan.agent_family_role == expected_role


@pytest.mark.parametrize(
    ("suffix", "parent_plan_path", "expected_sase_plan"),
    [
        ("code", "sdd/tales/202607/foo.md", "sdd/tales/202607/foo.md"),
        ("q", "sdd/tales/202607/foo.md", None),
        ("code", None, None),
    ],
)
def test_family_attach_sase_plan_env_only_for_code_with_parent_plan(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    parent_plan_path: str | None,
    expected_sase_plan: str | None,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [_artifact_record(name="foo", sdd_plan_path=parent_plan_path)],
    )
    _, env = prepare_family_attach_launch(
        f"%n(foo, {suffix})\nDo work",
        LaunchExecutionContext(
            cl_name="launcher",
            project_file="/tmp/sase.sase",
            project_name="sase",
            is_home_mode=True,
        ),
        {},
    )

    assert env is not None
    if expected_sase_plan is None:
        assert "SASE_PLAN" not in env
    else:
        assert env["SASE_PLAN"] == expected_sase_plan


def test_family_attach_metadata_matches_runner_followup_and_tui_family_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_name = "sase"
    parent_ts = "20260701010101"
    member_ts = "20260701010202"
    workspace_dir = str(tmp_path / "workspace")
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    parent_meta: dict[str, object] = {
        "pid": 123,
        "name": "foo",
        "workflow_name": "foo",
        "agent_family": "foo",
        "agent_family_role": "root",
        "role_suffix": "--plan",
        "workspace_dir": workspace_dir,
        "workspace_num": 7,
        "cl_name": "feature",
        "changespec_name": "feature",
        "sdd_plan_path": "sdd/tales/202607/foo.md",
    }
    parent_dir = _write_agent_artifact(
        sase_home,
        project_name=project_name,
        timestamp=parent_ts,
        meta=parent_meta,
        done_outcome="completed",
    )
    member_dir = (
        sase_home / "projects" / project_name / "artifacts" / "ace-run" / member_ts
    )
    member_dir.mkdir(parents=True)

    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(
                name="foo",
                workflow_name="foo",
                agent_family="foo",
                role_suffix="--plan",
                timestamp=parent_ts,
                artifact_dir=parent_dir,
                workspace_dir=workspace_dir,
                workspace_num=7,
                cl_name="feature",
                changespec_name="feature",
                sdd_plan_path="sdd/tales/202607/foo.md",
            )
        ],
    )

    prompt = "%n(foo, code)\nDo work"
    prepared_context, env = prepare_family_attach_launch(
        prompt,
        LaunchExecutionContext(
            cl_name="launcher",
            project_file="/tmp/sase.sase",
            project_name=project_name,
            is_home_mode=False,
        ),
        {},
    )

    assert prepared_context.cl_name == "feature"
    assert prepared_context.workspace_dir == workspace_dir
    assert prepared_context.workspace_num == 7

    with (
        patch.dict(os.environ, env or {}, clear=False),
        patch("sase.agent.names.ensure_historical_auto_name_migration"),
        patch(
            "sase.agent.names.agent_name_allocation_lock", return_value=nullcontext()
        ),
        patch("sase.agent.names.claim_agent_name"),
        patch(
            "sase.xprompt.process_xprompt_references",
            side_effect=lambda prompt, **_: prompt,
        ),
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch(
            "sase.llm_provider.config.resolve_effective_effort",
            return_value=(None, None),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        info = extract_directives_and_write_meta(
            prompt,
            workspace_dir="/tmp/launcher",
            artifacts_dir=str(member_dir),
            cl_name="launcher",
            raw_resolved_prompt=prompt,
        )

    assert info.name == "foo--code"
    member_meta = json.loads((member_dir / "agent_meta.json").read_text())

    followup_dir = tmp_path / "followup"
    followup_dir.mkdir()
    with (
        patch(
            "sase.axe.run_agent_helpers.create_artifacts_directory",
            return_value=str(followup_dir),
        ),
        patch(
            "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        create_followup_artifacts(
            project_name,
            parent_meta,
            "--code",
            parent_ts,
            workspace_num=7,
            agent_name_override="foo--code",
            workflow_name="foo",
        )
    followup_meta = json.loads((followup_dir / "agent_meta.json").read_text())

    parity_keys = (
        "name",
        "workflow_name",
        "role_suffix",
        "parent_timestamp",
        PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
        AGENT_FAMILY_FIELD,
        AGENT_FAMILY_ROLE_FIELD,
        "workspace_dir",
        "workspace_num",
        "changespec_name",
        "cl_name",
    )
    for key in parity_keys:
        assert member_meta.get(key) == followup_meta.get(key)

    from sase.agent.names import find_agent_family

    family = find_agent_family("foo")
    assert family is not None
    assert family.root is not None
    assert family.root.timestamp == parent_ts
    assert {member.name for member in family.members} == {"foo", "foo--code"}

    tui_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=str(member_meta["cl_name"]),
        project_file="/tmp/sase.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix=member_ts,
        parent_timestamp=str(member_meta["parent_timestamp"]),
        role_suffix=str(member_meta["role_suffix"]),
        agent_name=str(member_meta["name"]),
        agent_family=str(member_meta[AGENT_FAMILY_FIELD]),
        agent_family_role=str(member_meta[AGENT_FAMILY_ROLE_FIELD]),
    )
    assert tui_agent.is_family_member_child is True


def test_family_attach_prep_failure_prevents_spawn(monkeypatch) -> None:
    spawned: list[object] = []

    def fail_resolve(_directive: object, *, project_name: str) -> object:
        assert project_name == "sase"
        raise _FamilyAttachError("Cannot attach family member to 'missing'")

    monkeypatch.setattr(
        "sase.agent.family_attach._resolve_family_attach_plan",
        fail_resolve,
    )

    with pytest.raises(_FamilyAttachError, match="Cannot attach family member"):
        execute_launch_plan(
            plan_fake_fanout("single", ["%n(missing, reviewer)\nDo work"]),
            LaunchExecutionContext(
                cl_name="sase",
                project_file="/tmp/sase.sase",
                project_name="sase",
                is_home_mode=True,
            ),
            spawn=lambda request: spawned.append(request),  # type: ignore[arg-type]
        )

    assert spawned == []
