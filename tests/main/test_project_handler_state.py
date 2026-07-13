"""Tests for ``sase project`` lifecycle state mutations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sase.main.project_handler import handle_project_command
from tests.main.project_handler_helpers import (
    _write_project,
    lifecycle_stubs,
    projects_root,
)
from tests.main.workspace_handler_helpers import make_args

__all__ = ["lifecycle_stubs", "projects_root"]


class TestMutation:
    def test_set_state_inserts_before_running(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nRUNNING:\n\nNAME: a\n",
        )

        args = make_args(project_subcommand="deactivate", project="alpha", force=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert (
            "WORKSPACE_DIR: /tmp/alpha\nPROJECT_STATE: disabled\nRUNNING:\n"
            in project_file.read_text(encoding="utf-8")
        )
        assert "state is now disabled" in capsys.readouterr().out

    def test_legacy_aliases_normalize_to_disabled(
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

        args = make_args(project_subcommand="archive", project="alpha", force=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert "PROJECT_STATE: disabled\n" in project_file.read_text(encoding="utf-8")

        args = make_args(
            project_subcommand="set-state",
            project="alpha",
            state="closed",
            force=True,
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert "PROJECT_STATE: disabled\n" in project_file.read_text(encoding="utf-8")

    def test_set_state_replaces_existing_state(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "PROJECT_STATE: archived\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )

        args = make_args(
            project_subcommand="set-state",
            project="alpha",
            state="active",
            force=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert project_file.read_text(encoding="utf-8").startswith(
            "PROJECT_STATE: enabled\n"
        )

    def test_set_state_accepts_project_name(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "gh_acme__widgets",
            "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/widgets\nNAME: a\n",
        )

        args = make_args(
            project_subcommand="disable",
            project="widgets",
            force=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert "PROJECT_STATE: disabled\n" in project_file.read_text(encoding="utf-8")

    def test_set_state_accepts_sibling(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "core",
            "WORKSPACE_DIR: /tmp/core\nNAME: c\n",
        )

        args = make_args(
            project_subcommand="set-state",
            project="core",
            state="sibling",
            force=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert "PROJECT_STATE: sibling\n" in project_file.read_text(encoding="utf-8")
        assert "state is now sibling" in capsys.readouterr().out

    def test_rejects_live_running_claim_without_force(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nRUNNING:\n"
            "  #10 | 12345 | run | alpha_work_1 | 260601_120000\n"
            "\nNAME: a\n",
        )

        args = make_args(project_subcommand="disable", project="alpha", force=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "RUNNING claim" in capsys.readouterr().err
        assert "PROJECT_STATE" not in project_file.read_text(encoding="utf-8")

    def test_force_allows_live_running_claim(
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

        args = make_args(project_subcommand="disable", project="alpha", force=True)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert "PROJECT_STATE: disabled\n" in project_file.read_text(encoding="utf-8")

    def test_rejects_live_artifact_marker_without_force(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )
        marker = projects_root / "alpha" / "artifacts" / "run" / "260601120000"
        marker.mkdir(parents=True)
        (marker / "waiting.json").write_text("{}", encoding="utf-8")

        args = make_args(project_subcommand="disable", project="alpha", force=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "live artifact marker" in capsys.readouterr().err
        assert "PROJECT_STATE" not in project_file.read_text(encoding="utf-8")

    def test_set_state_rejects_hidden_project_name(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        hidden_dir = projects_root / ".sase"
        hidden_dir.mkdir()
        (hidden_dir / ".sase.sase").write_text("", encoding="utf-8")

        args = make_args(project_subcommand="disable", project=".sase", force=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "invalid project name" in capsys.readouterr().err
        assert hidden_dir.is_dir()

    def test_home_project_mutation_is_rejected(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "home", "WORKSPACE_DIR: /tmp/home\nNAME: h\n")

        args = make_args(project_subcommand="disable", project="home", force=True)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "system-managed" in capsys.readouterr().err

    def test_legacy_activate_and_deactivate_commands_remain_aliases(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "PROJECT_STATE: disabled\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )

        with pytest.raises(SystemExit) as enabled:
            handle_project_command(
                make_args(
                    project_subcommand="activate",
                    project="alpha",
                    force=False,
                )
            )
        assert enabled.value.code == 0
        assert "PROJECT_STATE: enabled\n" in project_file.read_text(encoding="utf-8")

        with pytest.raises(SystemExit) as disabled:
            handle_project_command(
                make_args(
                    project_subcommand="deactivate",
                    project="alpha",
                    force=False,
                )
            )
        assert disabled.value.code == 0
        assert "PROJECT_STATE: disabled\n" in project_file.read_text(encoding="utf-8")
