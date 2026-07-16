from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.family_membership import (
    FAMILY_MEMBERSHIP_ENV,
    FamilyMembershipPlan,
    encode_family_membership_plan,
)
from sase.axe.run_agent_directives import AgentInfo, extract_directives_and_write_meta
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    AGENT_FAMILY_PARALLEL_FIELD,
    AGENT_FAMILY_ROLE_FIELD,
    PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
)


def _write_artifact(
    sase_home: Path,
    *,
    timestamp: str,
    meta: dict[str, object],
    outcome: str | None = None,
) -> Path:
    artifact_dir = sase_home / "projects" / "sase" / "artifacts" / "ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta))
    if outcome is not None:
        (artifact_dir / "done.json").write_text(json.dumps({"outcome": outcome}))
    return artifact_dir


def _extract_runner_metadata(
    prompt: str,
    *,
    artifacts_dir: Path,
    env: dict[str, str] | None = None,
) -> AgentInfo:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    with (
        patch.dict(os.environ, env or {}, clear=False),
        patch("sase.agent.names.ensure_historical_auto_name_migration"),
        patch(
            "sase.agent.names.agent_name_allocation_lock",
            return_value=nullcontext(),
        ),
        patch("sase.agent.names.claim_agent_name"),
        patch(
            "sase.xprompt.process_xprompt_references",
            side_effect=lambda value, **_: value,
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
        return extract_directives_and_write_meta(
            prompt,
            workspace_dir="/workspace",
            artifacts_dir=str(artifacts_dir),
            cl_name="feature",
            raw_resolved_prompt=prompt,
        )


def test_runner_writes_execution_neutral_root_and_member_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    root_timestamp = "20260716010101"
    root_dir = (
        sase_home / "projects" / "sase" / "artifacts" / "ace-run" / root_timestamp
    )
    root_plan = FamilyMembershipPlan(
        family_base="root",
        root_timestamp=root_timestamp,
        root_artifacts_dir=str(root_dir),
        root_project_name="sase",
        role="root",
        is_root=True,
    )
    root_info = _extract_runner_metadata(
        "%name:root\nLead",
        artifacts_dir=root_dir,
        env={FAMILY_MEMBERSHIP_ENV: encode_family_membership_plan(root_plan)},
    )

    assert root_info.meta[AGENT_FAMILY_FIELD] == "root"
    assert root_info.meta[AGENT_FAMILY_ROLE_FIELD] == "root"
    assert root_info.meta[AGENT_FAMILY_PARALLEL_FIELD] is True
    assert "parent_timestamp" not in root_info.meta
    assert "workflow_name" not in root_info.meta
    assert "role_suffix" not in root_info.meta

    member_plan = replace(root_plan, role="phase", is_root=False)
    member_dir = root_dir.parent / "20260716010202"
    member_info = _extract_runner_metadata(
        "%name:worker\n%wait:root\n%family(root, role=phase)\nWork",
        artifacts_dir=member_dir,
        env={FAMILY_MEMBERSHIP_ENV: encode_family_membership_plan(member_plan)},
    )

    assert member_info.meta[AGENT_FAMILY_FIELD] == "root"
    assert member_info.meta[AGENT_FAMILY_ROLE_FIELD] == "phase"
    assert member_info.meta[AGENT_FAMILY_PARALLEL_FIELD] is True
    assert member_info.meta["parent_timestamp"] == root_timestamp
    assert "workflow_name" not in member_info.meta
    assert "role_suffix" not in member_info.meta
    assert PLAN_CHAIN_PARENT_TIMESTAMP_FIELD not in member_info.meta
    assert member_info.wait_identity_deps == [
        member_plan.identity_dependency(name="root")
    ]


def test_runner_fallback_joins_exact_named_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    root_timestamp = "20260716020101"
    root_dir = _write_artifact(
        sase_home,
        timestamp=root_timestamp,
        meta={"name": "existing-root", "pid": 123},
        outcome="completed",
    )
    member_dir = root_dir.parent / "20260716020202"

    info = _extract_runner_metadata(
        "%name:late-member\n%family(existing-root, role=late)\nWork",
        artifacts_dir=member_dir,
    )

    assert info.meta[AGENT_FAMILY_FIELD] == "existing-root"
    assert info.meta[AGENT_FAMILY_ROLE_FIELD] == "late"
    assert info.meta[AGENT_FAMILY_PARALLEL_FIELD] is True
    assert info.meta["parent_timestamp"] == root_timestamp


def test_member_base_reference_resolves_to_generation_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    root_timestamp = "20260716030101"
    root_dir = _write_artifact(
        sase_home,
        timestamp=root_timestamp,
        meta={
            "name": "family",
            AGENT_FAMILY_FIELD: "family",
            AGENT_FAMILY_ROLE_FIELD: "root",
            AGENT_FAMILY_PARALLEL_FIELD: True,
        },
        outcome="completed",
    )
    _write_artifact(
        sase_home,
        timestamp="20260716030202",
        meta={
            "name": "family-sibling",
            AGENT_FAMILY_FIELD: "family",
            AGENT_FAMILY_ROLE_FIELD: "sibling",
            AGENT_FAMILY_PARALLEL_FIELD: True,
            "parent_timestamp": root_timestamp,
        },
        outcome="completed",
    )
    current_dir = _write_artifact(
        sase_home,
        timestamp="20260716030303",
        meta={
            "name": "family-current",
            AGENT_FAMILY_FIELD: "family",
            AGENT_FAMILY_ROLE_FIELD: "current",
            AGENT_FAMILY_PARALLEL_FIELD: True,
            "parent_timestamp": root_timestamp,
        },
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    from sase.agent.names import resolve_resume_agent_name, resolve_wait_dependency

    resolved = resolve_resume_agent_name("family")
    assert resolved is not None
    assert Path(resolved.artifacts_dir) == root_dir
    assert resolve_wait_dependency("family") is True


def test_parallel_family_membership_survives_runner_reexec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    root_timestamp = "20260716040101"
    root_dir = (
        sase_home / "projects" / "sase" / "artifacts" / "ace-run" / root_timestamp
    )
    plan = FamilyMembershipPlan(
        family_base="reexec-root",
        root_timestamp=root_timestamp,
        root_artifacts_dir=str(root_dir),
        root_project_name="sase",
        role="root",
        is_root=True,
    )
    _extract_runner_metadata(
        "%name:reexec-root\nLead",
        artifacts_dir=root_dir,
        env={FAMILY_MEMBERSHIP_ENV: encode_family_membership_plan(plan)},
    )

    second = _extract_runner_metadata(
        "%name:reexec-root\nLead",
        artifacts_dir=root_dir,
    )
    assert second.meta[AGENT_FAMILY_FIELD] == "reexec-root"
    assert second.meta[AGENT_FAMILY_ROLE_FIELD] == "root"
    assert second.meta[AGENT_FAMILY_PARALLEL_FIELD] is True
