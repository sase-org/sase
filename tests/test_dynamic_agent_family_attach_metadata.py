from __future__ import annotations

import json
import os
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.family_attach import (
    FAMILY_ATTACH_ENV,
    FamilyAttachLaunchPlan,
    prepare_family_attach_launch,
)
from sase.agent._family_promotion import promote_agent_to_family
from sase.agent.launch_executor import LaunchExecutionContext
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.axe.run_agent_directives import extract_directives_and_write_meta
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    AGENT_FAMILY_ROLE_FIELD,
    PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
)
from tests._dynamic_agent_family_attach_helpers import (
    _artifact_record,
    _patch_attach_snapshot,
    _write_agent_artifact,
)


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
        "sdd_plan_path": "sdd/plans/202607/foo.md",
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
                sdd_plan_path="sdd/plans/202607/foo.md",
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
    promoted_parent_meta = json.loads((parent_dir / "agent_meta.json").read_text())
    assert promoted_parent_meta["name"] == "foo--plan"
    assert promoted_parent_meta["workflow_name"] == "foo"
    assert promoted_parent_meta["role_suffix"] == "--plan"
    assert promoted_parent_meta[AGENT_FAMILY_FIELD] == "foo"
    assert promoted_parent_meta[AGENT_FAMILY_ROLE_FIELD] == "root"

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
    assert {member.name for member in family.members} == {
        "foo--plan",
        "foo--code",
    }

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


def test_family_attach_child_inherits_parent_clan_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_dir = tmp_path / "child"
    child_dir.mkdir()
    plan = FamilyAttachLaunchPlan(
        parent_arg="research.worker",
        suffix_arg="reviewer",
        parent_name="research.worker--0",
        parent_base="research.worker",
        parent_timestamp="20260701010101",
        parent_artifacts_dir=str(tmp_path / "parent"),
        role_suffix="--reviewer",
        agent_name="research.worker--reviewer",
        agent_family_role="reviewer",
        parent_family_member_name="research.worker--0",
        parent_family_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="sase",
        parent_cl_name="feature",
        parent_agent_clan="research",
        parent_agent_clan_generation="20260701010000",
    )
    prompt = "%n(research.worker, reviewer)\nReview"
    monkeypatch.setenv(FAMILY_ATTACH_ENV, json.dumps(asdict(plan)))
    monkeypatch.setenv(INTERNAL_AGENT_NAME_BYPASS_ENV, "1")

    with (
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
        extract_directives_and_write_meta(
            prompt,
            workspace_dir="/tmp/workspace",
            artifacts_dir=str(child_dir),
            cl_name="feature",
            raw_resolved_prompt=prompt,
        )

    child_meta = json.loads((child_dir / "agent_meta.json").read_text())
    assert child_meta["agent_clan"] == "research"
    assert child_meta["agent_clan_generation"] == "20260701010000"

    conflict_dir = tmp_path / "conflict-child"
    conflict_dir.mkdir()
    conflict_prompt = "%n(research.worker, reviewer)\n%tribe:solo\nReview"
    with (
        patch("sase.agent.names.ensure_historical_auto_name_migration"),
        patch(
            "sase.xprompt.process_xprompt_references",
            side_effect=lambda prompt, **_: prompt,
        ),
        pytest.raises(
            RuntimeError,
            match="tribe membership belongs to the inherited clan",
        ),
    ):
        extract_directives_and_write_meta(
            conflict_prompt,
            workspace_dir="/tmp/workspace",
            artifacts_dir=str(conflict_dir),
            cl_name="feature",
            raw_resolved_prompt=conflict_prompt,
        )


def test_family_parent_meta_wait_happens_before_name_lock(tmp_path: Path) -> None:
    events: list[str] = []

    @contextmanager
    def allocation_lock():
        events.append("lock")
        yield

    def read_meta(_path: Path, *, timeout_seconds: float) -> dict[str, object]:
        events.append(f"read:{timeout_seconds}")
        return {"name": "foo"}

    with (
        patch(
            "sase.agent.names.agent_name_allocation_lock",
            return_value=allocation_lock(),
        ),
        patch(
            "sase.agent._family_promotion._read_meta_with_retry",
            side_effect=read_meta,
        ),
        patch("sase.agent._family_promotion._write_json_atomic"),
        patch("sase.agent.names.convert_registered_agent_to_family"),
        patch("sase.agent._family_promotion._refresh_artifact_index"),
    ):
        promote_agent_to_family(
            tmp_path,
            "foo",
            wait_for_meta_seconds=5.0,
        )

    assert events == ["read:5.0", "lock", "read:0.0"]


def test_plan_family_promotion_is_idempotent_and_plan_suffix_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    meta_path = artifact_dir / "agent_meta.json"
    meta_path.write_text(
        json.dumps({"name": "foo", "role_suffix": "--plan"}),
        encoding="utf-8",
    )

    first = promote_agent_to_family(
        artifact_dir,
        "foo",
        root_role_suffix="--0",
    )
    second = promote_agent_to_family(
        artifact_dir,
        "foo",
        root_role_suffix="--0",
    )

    assert first == second == "foo--plan"
    assert json.loads(meta_path.read_text(encoding="utf-8"))["role_suffix"] == "--plan"
