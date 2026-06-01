"""Regression tests for agent bead metadata lookup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.bead_display import (
    derive_agent_bead_id_from_name,
    format_agent_bead_display_for_name,
)


def test_dotted_non_bead_agent_name_is_not_a_bead() -> None:
    assert derive_agent_bead_id_from_name("aij.2") is None
    assert format_agent_bead_display_for_name("aij.2") is None


def test_land_suffix_requires_bead_shaped_epic_name() -> None:
    assert derive_agent_bead_id_from_name("aij.land") is None


def test_non_bead_agent_name_does_not_touch_bead_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_lookup(bead_id: str, *, project_name: str | None = None) -> None:
        raise AssertionError("non-bead agent names must not touch bead storage")

    monkeypatch.setattr("sase.agent.bead_display._lookup_bead_issue", fail_lookup)

    assert format_agent_bead_display_for_name("aij.2") is None


def test_agent_bead_display_ignores_legacy_sibling_store(
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

    assert format_agent_bead_display_for_name("sase-99") == "sase-99"


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


def test_agent_bead_display_uses_agent_workspace_before_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tmp_path / "sase"
    agent_workspace = tmp_path / "bob-cli"
    (current / "sdd/beads").mkdir(parents=True)
    (agent_workspace / "sdd/beads").mkdir(parents=True)
    _write_issues(
        current / "sdd/beads",
        [_issue("bob-cli-1.4", "Wrong current project title", "2026-06-01T00:00:00Z")],
    )
    _write_issues(
        agent_workspace / "sdd/beads",
        [
            _issue(
                "bob-cli-1.4",
                "Fix bob CLI parsing",
                "2026-06-01T00:00:01Z",
                description="Use the agent workspace bead store",
            )
        ],
    )
    monkeypatch.chdir(current)

    assert (
        format_agent_bead_display_for_name(
            "bob-cli-1.4",
            workspace_dir=str(agent_workspace),
        )
        == "bob-cli-1.4 - Use the agent workspace bead store"
    )


def test_agent_bead_display_uses_managed_checkout_primary_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tmp_path / "sase"
    primary = tmp_path / "bob-cli"
    managed = tmp_path / "state" / "bob-cli" / "10"
    (current / "sdd/beads").mkdir(parents=True)
    (primary / "sdd/beads").mkdir(parents=True)
    managed.mkdir(parents=True)
    _write_issues(
        current / "sdd/beads",
        [_issue("bob-cli-1.4", "Wrong current project title", "2026-06-01T00:00:00Z")],
    )
    _write_issues(
        primary / "sdd/beads",
        [_issue("bob-cli-1.4", "Primary workspace title", "2026-06-01T00:00:01Z")],
    )
    _write_marker(
        managed,
        project_name="bob-cli",
        project_key="bob-cli-key",
        primary_workspace_dir=primary,
        workspace_num=10,
    )
    monkeypatch.chdir(current)

    assert (
        format_agent_bead_display_for_name(
            "bob-cli-1.4",
            workspace_dir=str(managed),
        )
        == "bob-cli-1.4 - Primary workspace title"
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
    (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")
    return primary


def _write_issues(beads_dir: Path, issues: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(issue, separators=(",", ":")) + "\n" for issue in issues)
    (beads_dir / "issues.jsonl").write_text(text, encoding="utf-8")


def _write_marker(
    checkout_dir: Path,
    *,
    project_name: str,
    project_key: str,
    primary_workspace_dir: Path,
    workspace_num: int,
) -> None:
    marker_dir = checkout_dir / ".sase"
    marker_dir.mkdir(parents=True)
    payload = {
        "project_name": project_name,
        "project_key": project_key,
        "workspace_num": workspace_num,
        "primary_workspace_dir": str(primary_workspace_dir),
        "registry_path": "",
        "schema_version": 1,
    }
    (marker_dir / "checkout.json").write_text(json.dumps(payload), encoding="utf-8")


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
