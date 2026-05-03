"""Regression tests for agent bead metadata lookup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.bead_display import format_agent_bead_display_for_name


def test_agent_bead_display_finds_description_in_legacy_sibling_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "sase"
    sibling = tmp_path / "sase_106"
    primary.mkdir()
    legacy_store = sibling / ".sase_beads"
    legacy_store.mkdir(parents=True)
    _write_issues(
        legacy_store,
        [
            _issue(
                "sase-99",
                "Legacy epic",
                "2026-05-02T00:00:00Z",
                description="Only present in the migrated legacy store",
            )
        ],
    )

    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace",
        lambda: primary,
    )

    assert (
        format_agent_bead_display_for_name("sase-99")
        == "sase-99 - Only present in the migrated legacy store"
    )


def test_agent_bead_display_finds_bead_in_another_known_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    current = _write_project(tmp_path, "sase")
    zorg = _write_project(tmp_path, "zorg")
    _write_issues(current / "sdd/beads", [])
    _write_issues(
        zorg / "sdd/beads",
        [
            _issue(
                "zorg-4.3.6",
                "Phase 6: count() MVP And Final Epic Hardening",
                "2026-05-02T00:00:00Z",
            )
        ],
    )
    monkeypatch.chdir(current)

    assert (
        format_agent_bead_display_for_name("zorg-4.3.6")
        == "zorg-4.3.6 - Phase 6: count() MVP And Final Epic Hardening"
    )


def test_agent_bead_display_uses_explicit_project_before_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    current = _write_project(tmp_path, "sase")
    zorg = _write_project(tmp_path, "zorg")
    _write_issues(
        current / "sdd/beads",
        [
            _issue(
                "zorg-4.3.6",
                "Wrong project title",
                "2026-05-02T00:00:00Z",
            )
        ],
    )
    _write_issues(
        zorg / "sdd/beads",
        [
            _issue(
                "zorg-4.3.6",
                "Right project title",
                "2026-05-03T00:00:00Z",
            )
        ],
    )
    monkeypatch.chdir(current)

    assert (
        format_agent_bead_display_for_name("zorg-4.3.6", project_name="zorg")
        == "zorg-4.3.6 - Right project title"
    )


def _write_project(tmp_path: Path, project_name: str) -> Path:
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / project_name
    (primary / "sdd/beads").mkdir(parents=True)
    (project_dir / f"{project_name}.gp").write_text(f"WORKSPACE_DIR: {primary}\n")
    return primary


def _write_issues(beads_dir: Path, issues: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(issue, separators=(",", ":")) + "\n" for issue in issues)
    (beads_dir / "issues.jsonl").write_text(text, encoding="utf-8")


def _issue(
    issue_id: str,
    title: str,
    updated_at: str,
    *,
    description: str = "",
) -> dict[str, object]:
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": "plan",
        "parent_id": None,
        "owner": "",
        "assignee": "",
        "created_at": updated_at,
        "created_by": "",
        "updated_at": updated_at,
        "closed_at": None,
        "close_reason": None,
        "description": description,
        "notes": "",
        "design": "",
        "is_ready_to_work": False,
        "changespec_name": "",
        "changespec_bug_id": "",
        "dependencies": [],
    }
