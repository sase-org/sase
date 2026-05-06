from __future__ import annotations

import json
from pathlib import Path

import pytest

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
                    "project_file": str(tmp_path / ".sase/projects/alpha/alpha.gp"),
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
