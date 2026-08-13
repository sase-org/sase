"""Cross-surface agreement tests for the shared plan-reference resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models._agent_associated_plan_paths import (
    _resolve_plan_reference_resolution as resolve_agent_plan_reference_resolution,
    resolve_plan_reference as resolve_agent_plan_reference,
)
from sase.bead.cli_work_plan_snapshot import epic_plan_source_path
from sase.bead.project import BeadProject
from sase.core.artifact_file_facade import synthesize_default_artifact_files
from sase.scripts.sase_clan_summary_plan import (
    _resolve_plan_reference as resolve_clan_plan_reference,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.artifact_file_facade.helpers import agent_dir, write_json


def _synthesized_plan_path(
    tmp_path: Path,
    *,
    reference: str,
    workspace: Path,
) -> str | None:
    artifacts_dir = agent_dir(tmp_path)
    write_json(
        artifacts_dir / "agent_meta.json",
        {
            "sdd_plan_path": reference,
            "plan_committed": True,
            "workspace_dir": str(workspace),
        },
    )
    synthesized = synthesize_default_artifact_files(artifacts_dir)
    plan_rows = [artifact.path for artifact in synthesized if artifact.kind == "plan"]
    assert len(plan_rows) == 1
    return plan_rows[0]


@pytest.mark.parametrize(
    "reference_kind",
    (
        "typed",
        "absolute",
        "sdd",
        "sidecar",
        "month-relative",
    ),
)
def test_store_plan_resolves_identically_across_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    store_root = tmp_path / "store"
    local_root = tmp_path / "local"
    plan = store_root / "202607/shared.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Shared plan\n", encoding="utf-8")
    reference = {
        "typed": "plan:202607/shared.md",
        "absolute": str(plan),
        "sdd": "sdd/plans/202607/shared.md",
        "sidecar": "sase/repos/plans/202607/shared.md",
        "month-relative": "202607/shared.md",
    }[reference_kind]
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_roots",
        lambda *_args: (store_root, local_root),
    )
    with BeadProject.init(workspace) as project:
        monkeypatch.chdir(workspace)
        snapshot_path = epic_plan_source_path(project, reference)

    agent = make_agent(workspace_dir=str(workspace), workspace_num=1)

    assert snapshot_path == plan.resolve()
    assert resolve_agent_plan_reference(reference, agent) == plan.resolve()
    agent_resolution = resolve_agent_plan_reference_resolution(reference, agent)
    assert agent_resolution.status == "exact"
    assert agent_resolution.resolved_path == plan.resolve()
    assert resolve_clan_plan_reference(reference) == plan.resolve()
    assert _synthesized_plan_path(
        tmp_path, reference=reference, workspace=workspace
    ) == str(plan.resolve())


def test_local_archive_plan_resolves_identically_across_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    store_root = tmp_path / "store"
    local_root = tmp_path / "local"
    plan = local_root / "202607/local-only.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Local plan\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_roots",
        lambda *_args: (store_root, local_root),
    )
    with BeadProject.init(workspace) as project:
        monkeypatch.chdir(workspace)
        snapshot_path = epic_plan_source_path(
            project,
            "plan:202607/local-only.md",
        )

    agent = make_agent(workspace_dir=str(workspace), workspace_num=1)

    assert snapshot_path == plan.resolve()
    assert (
        resolve_agent_plan_reference("plan:202607/local-only.md", agent)
        == plan.resolve()
    )
    assert resolve_clan_plan_reference("plan:202607/local-only.md") == plan.resolve()
    assert _synthesized_plan_path(
        tmp_path, reference="plan:202607/local-only.md", workspace=workspace
    ) == str(plan.resolve())
