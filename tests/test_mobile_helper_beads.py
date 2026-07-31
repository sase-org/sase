from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from tests._mobile_helper_bridge_helpers import (
    run_bridge,
    seed_bead_project,
    seed_known_projects,
)


def test_beads_list_bridge_lists_known_project_beads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha_root = tmp_path / "workspaces" / "alpha"
    beta_root = tmp_path / "workspaces" / "beta"
    alpha_dir, alpha_epic, alpha_phase, alpha_closed = seed_bead_project(alpha_root)
    beta_dir, beta_epic, _, _ = seed_bead_project(beta_root)
    seed_known_projects(tmp_path, {"alpha": alpha_dir, "beta": beta_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    code, data, stderr = run_bridge({"schema_version": 1}, "beads-list")

    assert code == 0
    assert stderr == ""
    assert data["context"] == {"project": None, "scope": "all_known"}
    assert data["result"]["status"] == "success"  # type: ignore[index]
    ids = {row["id"] for row in data["beads"]}  # type: ignore[index]
    assert alpha_epic.id in ids
    assert alpha_phase.id in ids
    assert beta_epic.id in ids
    assert alpha_closed.id not in ids
    alpha_summary = next(
        row
        for row in data["beads"]  # type: ignore[index]
        if row["id"] == alpha_epic.id
    )
    assert alpha_summary["project"] == "alpha"
    assert alpha_summary["bead_type"] == "plan"
    assert alpha_summary["tier"] == "epic"
    assert alpha_summary["child_count"] == 1
    assert alpha_summary["block_count"] == 1
    assert alpha_summary["plan_path_display"] == "plans/alpha.md"
    assert alpha_summary["changespec_name"] == "alpha_changespec"


def test_beads_list_bridge_filters_explicit_project_status_type_and_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha_dir, alpha_epic, _, _ = seed_bead_project(tmp_path / "alpha")
    beta_dir, _, _, _ = seed_bead_project(tmp_path / "beta")
    seed_known_projects(tmp_path, {"alpha": alpha_dir, "beta": beta_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    code, data, stderr = run_bridge(
        {
            "schema_version": 1,
            "project": "alpha",
            "status": "in_progress",
            "bead_type": "plan",
            "tier": "epic",
        },
        "beads-list",
    )

    assert code == 0
    assert stderr == ""
    assert data["context"] == {"project": "alpha", "scope": "explicit"}
    assert [row["id"] for row in data["beads"]] == [alpha_epic.id]  # type: ignore[index]


def test_beads_list_bridge_uses_only_first_canonical_project_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.bead.config.infer_project_name_from_cwd", lambda: None)
    alpha_dir, alpha_epic, _, _ = seed_bead_project(tmp_path / "alpha")
    sibling_dir, sibling_epic, _, _ = seed_bead_project(tmp_path / "alpha_101")
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.get_project_beads_dirs_for_project",
        lambda project: [alpha_dir, sibling_dir],
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha"}, "beads-list"
    )

    assert code == 0
    assert stderr == ""
    ids = {row["id"] for row in data["beads"]}  # type: ignore[index]
    assert alpha_epic.id in ids
    assert sibling_epic.id not in ids


def test_beads_list_bridge_all_known_projects_ignores_orphan_bead_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.bead.config.infer_project_name_from_cwd", lambda: None)
    alpha_dir, alpha_epic, _, _ = seed_bead_project(tmp_path / "alpha")
    sibling_dir, sibling_epic, _, _ = seed_bead_project(tmp_path / "alpha_101")
    seed_known_projects(tmp_path, {"alpha": alpha_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.get_all_project_beads_dirs",
        lambda: [sibling_dir],
    )

    code, data, stderr = run_bridge({"schema_version": 1}, "beads-list")

    assert code == 0
    assert stderr == ""
    ids = {row["id"] for row in data["beads"]}  # type: ignore[index]
    assert alpha_epic.id in ids
    assert sibling_epic.id not in ids


def test_beads_list_bridge_all_known_projects_ignores_disabled_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha_dir, alpha_epic, _, _ = seed_bead_project(tmp_path / "alpha")
    beta_dir, beta_epic, _, _ = seed_bead_project(tmp_path / "beta")
    seed_known_projects(
        tmp_path,
        {"alpha": alpha_dir, "beta": beta_dir},
        states={"beta": "disabled"},
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    code, data, stderr = run_bridge({"schema_version": 1}, "beads-list")

    assert code == 0
    assert stderr == ""
    ids = {row["id"] for row in data["beads"]}  # type: ignore[index]
    assert alpha_epic.id in ids
    assert beta_epic.id not in ids


def test_beads_list_bridge_uses_remembered_device_project_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha_dir, alpha_epic, _, _ = seed_bead_project(tmp_path / "alpha")
    beta_dir, _, _, _ = seed_bead_project(tmp_path / "beta")
    seed_known_projects(tmp_path, {"alpha": alpha_dir, "beta": beta_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    context_dir = tmp_path / ".sase/mobile_gateway/device_project_contexts"
    context_dir.mkdir(parents=True)
    (context_dir / "dev-123.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "device_id": "dev-123",
                "project_context": {
                    "context_id": "project:alpha",
                    "mode": "project",
                    "project": "alpha",
                    "project_file": str(tmp_path / ".sase/projects/alpha/alpha.sase"),
                },
            }
        ),
        encoding="utf-8",
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "device_id": "dev-123"}, "beads-list"
    )

    assert code == 0
    assert stderr == ""
    assert data["context"] == {"project": "alpha", "scope": "device_default"}
    assert {
        row["id"]
        for row in data["beads"]  # type: ignore[index]
    } == {alpha_epic.id, f"{alpha_epic.id}.1"}


def test_beads_show_bridge_returns_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha_dir, alpha_epic, alpha_phase, _ = seed_bead_project(tmp_path / "alpha")
    seed_known_projects(tmp_path, {"alpha": alpha_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha", "bead_id": alpha_epic.id},
        "beads-show",
    )

    assert code == 0
    assert stderr == ""
    assert data["bead"]["summary"]["id"] == alpha_epic.id  # type: ignore[index]
    assert data["bead"]["description"] == "Alpha description"  # type: ignore[index]
    assert data["bead"]["notes"] == "Alpha note"  # type: ignore[index]
    assert data["bead"]["design_path_display"] == "plans/alpha.md"  # type: ignore[index]
    assert data["bead"]["children"] == [alpha_phase.id]  # type: ignore[index]
    assert data["bead"]["blocks"] == [alpha_phase.id]  # type: ignore[index]
    assert data["bead"]["workspace_display"] == str(tmp_path / "alpha")  # type: ignore[index]


def test_beads_show_bridge_returns_stored_references_it_cannot_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.project import BeadProject
    from sase.bead.model import IssueType

    alpha_root = tmp_path / "alpha"
    alpha_dir, _, _, _ = seed_bead_project(alpha_root)
    with BeadProject(alpha_root) as project:
        cited = project.create(
            "Cited",
            IssueType.PLAN,
            refs=["research:202607/capture.md", "bead:nowhere-1"],
        )
    seed_known_projects(tmp_path, {"alpha": alpha_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha", "bead_id": cited.id},
        "beads-show",
    )

    assert code == 0
    assert stderr == ""
    assert data["bead"]["refs"] == [  # type: ignore[index]
        "research:202607/capture.md",
        "bead:nowhere-1",
    ]


def test_beads_show_bridge_omits_refs_for_a_bead_without_any(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha_dir, alpha_epic, _, _ = seed_bead_project(tmp_path / "alpha")
    seed_known_projects(tmp_path, {"alpha": alpha_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha", "bead_id": alpha_epic.id},
        "beads-show",
    )

    assert code == 0
    assert stderr == ""
    assert data["bead"]["refs"] == []  # type: ignore[index]


def test_bead_reference_displays_prefer_the_path_a_reference_resolves_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.artifact_ref_lists import ArtifactRefListEntry
    from sase.artifact_ref_models import ArtifactRefResolution
    from sase.bead.model import Issue
    from sase.integrations import _mobile_helper_beads as helper

    resolved = tmp_path / "research" / "202607" / "capture.md"
    entries = (
        ArtifactRefListEntry(
            rendered="research:202607/capture.md",
            resolution=ArtifactRefResolution(
                schema_version=3,
                status="exact",
                rendered="research:202607/capture.md",
                locator=None,
                resolved_path=resolved,
                candidates=(),
            ),
        ),
        ArtifactRefListEntry(
            rendered="bead:nowhere-1",
            resolution=ArtifactRefResolution(
                schema_version=3,
                status="missing",
                rendered="bead:nowhere-1",
                locator=None,
                resolved_path=None,
                candidates=(),
            ),
        ),
    )
    monkeypatch.setattr(
        helper,
        "_plan_resolution_workspace",
        lambda *_args: tmp_path,
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_context",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        "sase.artifact_ref_lists.resolve_artifact_ref_list",
        lambda *_args, **_kwargs: entries,
    )
    issue = Issue(
        "alpha-1", "Cited", refs=["research:202607/capture.md", "bead:nowhere-1"]
    )

    displays = helper._issue_reference_displays(issue, project="alpha", beads_dir=None)

    assert displays == [str(resolved), "bead:nowhere-1"]


def test_beads_bridge_returns_resolved_plan_path_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha_root = tmp_path / "alpha"
    alpha_dir, alpha_epic, _, _ = seed_bead_project(alpha_root)
    plan = alpha_root / "sdd/plans/alpha.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Alpha plan\n", encoding="utf-8")
    seed_known_projects(tmp_path, {"alpha": alpha_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_roots",
        lambda *_args: (plan.parent,),
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha", "bead_id": alpha_epic.id},
        "beads-show",
    )

    assert code == 0
    assert stderr == ""
    assert data["bead"]["design_path_display"] == str(plan.resolve())  # type: ignore[index]
    assert data["bead"]["summary"]["plan_path_display"] == str(plan.resolve())  # type: ignore[index]


def test_beads_show_bridge_does_not_search_extra_project_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.bead.config.infer_project_name_from_cwd", lambda: None)
    alpha_dir, _, _, _ = seed_bead_project(tmp_path / "alpha")
    sibling_dir, sibling_epic, _, _ = seed_bead_project(tmp_path / "alpha_101")
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.get_project_beads_dirs_for_project",
        lambda project: [alpha_dir, sibling_dir],
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha", "bead_id": sibling_epic.id},
        "beads-show",
    )

    assert code == 4
    assert data == {}
    assert sibling_epic.id in stderr


def test_beads_show_bridge_returns_not_found_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha_dir, _, _, _ = seed_bead_project(tmp_path / "alpha")
    seed_known_projects(tmp_path, {"alpha": alpha_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha", "bead_id": "missing"},
        "beads-show",
    )

    assert code == 4
    assert data == {}
    assert "missing" in stderr


def test_beads_list_bridge_lists_ready_task_beads_by_default_and_by_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha_root = tmp_path / "alpha"
    alpha_dir, _, _, _ = seed_bead_project(alpha_root)
    with BeadProject.init(alpha_root) as project:
        task = project.create("Alpha Task", IssueType.TASK, description="Follow-up")
        project.update(task.id, status=Status.READY.value)
    seed_known_projects(tmp_path, {"alpha": alpha_dir})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha"}, "beads-list"
    )

    assert code == 0
    assert stderr == ""
    # A ready task bead is active work awaiting triage, so the default
    # (non-closed) listing must surface it alongside open/in-progress beads.
    summary = next(
        row
        for row in data["beads"]  # type: ignore[index]
        if row["id"] == task.id
    )
    assert summary["bead_type"] == "task"
    assert summary["status"] == "ready"
    assert summary["tier"] is None

    filtered_code, filtered, _ = run_bridge(
        {
            "schema_version": 1,
            "project": "alpha",
            "status": "ready",
            "bead_type": "task",
        },
        "beads-list",
    )

    assert filtered_code == 0
    assert [row["id"] for row in filtered["beads"]] == [task.id]  # type: ignore[index]


def test_beads_list_bridge_reports_partial_project_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_dir = tmp_path / "missing/sdd/beads"
    monkeypatch.setattr(
        "sase.integrations.mobile_helpers.get_project_beads_dirs_for_project",
        lambda project: [missing_dir],
    )

    code, data, stderr = run_bridge(
        {"schema_version": 1, "project": "alpha"}, "beads-list"
    )

    assert code == 0
    assert stderr == ""
    assert data["result"]["status"] == "partial_success"  # type: ignore[index]
    assert data["result"]["partial_failure_count"] == 1  # type: ignore[index]
    assert data["result"]["skipped"][0]["target"] == str(missing_dir)  # type: ignore[index]
