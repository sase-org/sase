from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.family_attach import FamilyAttachSibling


def _artifact_record(
    *,
    name: str = "foo",
    timestamp: str = "20260701010101",
    project_name: str = "sase",
    workflow_name: str | None = None,
    agent_family: str | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
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
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
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
        "sase.agent.family_attach.agent_family_snapshot",
        lambda _project_name: SimpleNamespace(records=records),
    )
    monkeypatch.setattr(
        "sase.agent.family_attach.dismissed_identity_dicts",
        lambda: list(dismissed or []),
    )
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_agent_names",
        lambda: set(),
    )


def _in_batch_sibling(
    *,
    name: str = "foo",
    family_base: str = "foo",
    timestamp: str = "20260701010202",
    artifact_dir: str = "/tmp/sase/artifacts/ace-run/20260701010202",
    project_name: str = "sase",
    cl_name: str | None = "feature",
    workspace_dir: str | None = "/tmp/sase_8",
    workspace_num: int | None = 8,
    can_attach_parent: bool = True,
) -> FamilyAttachSibling:
    return FamilyAttachSibling(
        name=name,
        family_base=family_base,
        timestamp=timestamp,
        artifact_dir=artifact_dir,
        project_name=project_name,
        cl_name=cl_name,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        can_attach_parent=can_attach_parent,
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
