"""Tests for ``sase project`` deletion."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sase.main import project_handler
from tests.main.project_handler_helpers import (
    _write_project,
    lifecycle_stubs,
    projects_root,
)

__all__ = ["lifecycle_stubs", "projects_root"]


class TestDeletion:
    def test_delete_removes_entire_project_directory(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")
        project_dir = projects_root / "alpha"
        (project_dir / "alpha-archive.sase").write_text("NAME: old\n", encoding="utf-8")
        (project_dir / "sase.yml").write_text("xprompts: []\n", encoding="utf-8")
        artifact = project_dir / "artifacts" / "run" / "260601120000" / "done.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{}", encoding="utf-8")

        deleted_dir = project_handler.delete_project_locked("alpha")

        assert deleted_dir == project_dir
        assert not project_dir.exists()

    def test_delete_removes_project_directory_with_missing_active_spec(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_dir = projects_root / "alpha"
        project_dir.mkdir()
        (project_dir / "alpha-archive.sase").write_text("NAME: old\n", encoding="utf-8")
        (project_dir / "sase.yml").write_text("xprompts: []\n", encoding="utf-8")
        artifact = project_dir / "artifacts" / "run" / "260601120000" / "done.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{}", encoding="utf-8")

        deleted_dir = project_handler.delete_project_locked("alpha")

        assert deleted_dir == project_dir
        assert not project_dir.exists()

    def test_delete_missing_active_spec_rejects_live_artifact_marker(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_dir = projects_root / "alpha"
        project_dir.mkdir()
        marker = project_dir / "artifacts" / "run" / "260601120000"
        marker.mkdir(parents=True)
        (marker / "running.json").write_text("{}", encoding="utf-8")

        with pytest.raises(
            project_handler.ProjectLifecycleBlockedError,
            match="live artifact marker",
        ):
            project_handler.delete_project_locked("alpha")

        assert project_dir.is_dir()
        assert marker.is_dir()

    def test_delete_rejects_home_project(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "home", "WORKSPACE_DIR: /tmp/home\nNAME: h\n")

        with pytest.raises(
            project_handler.ProjectLifecycleError, match="system-managed"
        ):
            project_handler.delete_project_locked("home")

        assert (projects_root / "home").is_dir()

    def test_delete_rejects_live_running_claim_and_leaves_directory_intact(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nRUNNING:\n"
            "  #10 | 12345 | run | alpha_work_1 | 260601_120000\n"
            "\nNAME: a\n",
        )

        with pytest.raises(
            project_handler.ProjectLifecycleBlockedError,
            match="RUNNING claim",
        ):
            project_handler.delete_project_locked("alpha")

        assert project_file.is_file()
        assert (projects_root / "alpha").is_dir()

    def test_delete_rejects_live_artifact_marker_and_leaves_directory_intact(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )
        marker = projects_root / "alpha" / "artifacts" / "run" / "260601120000"
        marker.mkdir(parents=True)
        (marker / "running.json").write_text("{}", encoding="utf-8")

        with pytest.raises(
            project_handler.ProjectLifecycleBlockedError,
            match="live artifact marker",
        ):
            project_handler.delete_project_locked("alpha")

        assert project_file.is_file()
        assert marker.is_dir()

    def test_delete_rejects_path_traversal_and_leaves_directory_intact(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")

        with pytest.raises(project_handler.ProjectLifecycleError, match="invalid"):
            project_handler.delete_project_locked("../alpha")

        assert (projects_root / "alpha").is_dir()

    def test_delete_rejects_hidden_project_name_and_leaves_directory_intact(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        hidden_dir = projects_root / ".sase"
        hidden_dir.mkdir()
        (hidden_dir / ".sase.sase").write_text("", encoding="utf-8")

        with pytest.raises(project_handler.ProjectLifecycleError, match="invalid"):
            project_handler.delete_project_locked(".sase")

        assert hidden_dir.is_dir()
