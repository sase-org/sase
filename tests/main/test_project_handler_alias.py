"""Tests for ``sase project alias``."""

from __future__ import annotations

import json
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


class TestAliasCommands:
    def test_alias_list_project_json(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(
            projects_root,
            "alpha",
            "PROJECT_ALIASES: docs, bob\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="list",
            project="alpha",
            json=True,
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert json.loads(capsys.readouterr().out) == {
            "project_name": "alpha",
            "aliases": ["bob", "docs"],
        }

    def test_alias_list_all_text_only_projects_with_aliases(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(
            projects_root,
            "alpha",
            "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )
        _write_project(projects_root, "beta", "WORKSPACE_DIR: /tmp/beta\nNAME: b\n")

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="list",
            project=None,
            json=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "alpha: bob" in out
        assert "beta" not in out

    def test_alias_add_inserts_before_running(
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

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="add",
            project="alpha",
            alias="bob",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert (
            "WORKSPACE_DIR: /tmp/alpha\nPROJECT_ALIASES: bob\nRUNNING:\n"
            in project_file.read_text(encoding="utf-8")
        )
        assert "aliases: bob" in capsys.readouterr().out

    def test_alias_add_deduplicates_and_sorts(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "PROJECT_ALIASES: docs\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="add",
            project="alpha",
            alias="bob",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert "PROJECT_ALIASES: bob, docs\n" in project_file.read_text(
            encoding="utf-8"
        )

    def test_alias_remove_updates_header(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "PROJECT_ALIASES: bob, docs\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="remove",
            project="alpha",
            alias="bob",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        content = project_file.read_text(encoding="utf-8")
        assert "PROJECT_ALIASES: docs\n" in content
        assert "bob" not in content

    def test_alias_clear_removes_header(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="clear",
            project="alpha",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert "PROJECT_ALIASES:" not in project_file.read_text(encoding="utf-8")

    def test_alias_add_rejects_existing_project_name(
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
        _write_project(projects_root, "beta", "WORKSPACE_DIR: /tmp/beta\nNAME: b\n")

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="add",
            project="alpha",
            alias="beta",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "real project name" in capsys.readouterr().err
        assert "PROJECT_ALIASES" not in project_file.read_text(encoding="utf-8")

    def test_alias_add_rejects_alias_owned_by_another_project(
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
        _write_project(
            projects_root,
            "beta",
            "PROJECT_ALIASES: docs\nWORKSPACE_DIR: /tmp/beta\nNAME: b\n",
        )

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="add",
            project="alpha",
            alias="docs",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "assigned to both" in capsys.readouterr().err
        assert "PROJECT_ALIASES" not in project_file.read_text(encoding="utf-8")

    def test_alias_add_rejects_invalid_alias(
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

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="add",
            project="alpha",
            alias=".hidden",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "invalid project alias" in capsys.readouterr().err
        assert "PROJECT_ALIASES" not in project_file.read_text(encoding="utf-8")

    def test_alias_add_rejects_missing_project(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="add",
            project="ghost",
            alias="bob",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "ghost" in capsys.readouterr().err

    def test_alias_add_rejects_home_project(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "home", "WORKSPACE_DIR: /tmp/home\nNAME: h\n")

        args = make_args(
            project_subcommand="alias",
            alias_subcommand="add",
            project="home",
            alias="bob",
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "system-managed" in capsys.readouterr().err
