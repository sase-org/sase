from __future__ import annotations

import json
import os
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.family_attach import prepare_family_attach_launch
from sase.agent.launch_executor import LaunchExecutionContext
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
