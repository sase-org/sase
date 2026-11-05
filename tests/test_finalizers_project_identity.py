"""Finalizer recovery and prepared completion agree on project storage identity."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.finalizers._failed_close_recovery_apply import _resolve_machine_project
from sase.finalizers._prepare_completion import _resolve_creator_project
from sase.finalizers.project_identity import resolve_finalizer_project_key


@pytest.fixture
def projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "projects"
    monkeypatch.setattr(
        "sase.finalizers.project_identity.sase_projects_dir", lambda: root
    )
    monkeypatch.delenv("SASE_AGENT_PROJECT_FILE", raising=False)
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), SimpleNamespace(project_name="name")),
    )
    monkeypatch.setattr(
        "sase.project_aliases.resolve_project_alias_ref", lambda _name: "gh_org__name"
    )
    return root


def test_artifact_owner_wins_over_display_marker_and_environment(
    projects: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = projects / "gh_org__name" / "artifacts" / "ace-run" / "20261105150345"
    monkeypatch.setenv(
        "SASE_AGENT_PROJECT_FILE", str(projects / "wrong" / "wrong.sase")
    )
    assert _resolve_machine_project(str(root)) == "gh_org__name"
    assert _resolve_creator_project(root) == "gh_org__name"


def test_project_file_fallback(projects: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = projects.parent / "manual-run"
    monkeypatch.setenv(
        "SASE_AGENT_PROJECT_FILE", str(projects / "gh_org__name" / "gh_org__name.sase")
    )
    assert resolve_finalizer_project_key(root) == "gh_org__name"


def test_marker_alias_requires_existing_spec(projects: Path) -> None:
    root = projects.parent / "manual-run"
    assert _resolve_machine_project(str(root)) is None
    spec = projects / "gh_org__name" / "gh_org__name.sase"
    spec.parent.mkdir(parents=True)
    spec.write_text("PROJECT_NAME: name\n")
    assert _resolve_machine_project(str(root)) == "gh_org__name"
    assert _resolve_creator_project(root) == "gh_org__name"


def test_unknown_project_does_not_invent_recovery_store(
    projects: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd", lambda _cwd: None
    )
    monkeypatch.setenv("SASE_PROJECT", "unrelated")
    root = projects.parent / "manual-run"
    assert _resolve_machine_project(str(root)) is None
    assert _resolve_creator_project(root) == "unrelated"
