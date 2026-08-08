"""Tests for ``sase project list`` and ``sase project show``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


class TestListAndShow:
    def test_project_handler_imports_in_fresh_interpreter(
        self,
        tmp_path: Path,
    ) -> None:
        env = os.environ.copy()
        env["SASE_HOME"] = str(tmp_path / ".sase")

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sase.main.project_handler; print('ok')",
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ok"

    def test_list_json_includes_all_states(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")
        _write_project(
            projects_root,
            "beta",
            "PROJECT_STATE: inactive\nWORKSPACE_DIR: /tmp/beta\nNAME: b\n",
        )
        _write_project(
            projects_root,
            "core",
            "PROJECT_STATE: sibling\nWORKSPACE_DIR: /tmp/core\nNAME: c\n",
        )

        args = make_args(project_subcommand="list", state="all", json=True)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert [item["project_name"] for item in payload] == [
            "alpha",
            "beta",
        ]
        assert payload[0]["aliases"] == []
        assert payload[0]["display_name"] is None
        assert payload[0]["effective_project_name"] == "alpha"
        assert payload[0]["state"] == "enabled"
        assert payload[0]["is_project"] is True
        assert payload[0]["state_source"] == "defaulted"
        assert payload[1]["state"] == "disabled"
        assert payload[1]["state_source"] == "explicit"

    def test_list_excludes_sibling_backing_records(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")
        _write_project(
            projects_root,
            "core",
            "PROJECT_STATE: sibling\nWORKSPACE_DIR: /tmp/core\nNAME: c\n",
        )

        args = make_args(project_subcommand="list", state="sibling", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "No sibling projects." in out
        assert "core" not in out
        assert "alpha" not in out

    def test_list_defaults_to_enabled_projects(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")
        _write_project(projects_root, "beta", "PROJECT_STATE: closed\nNAME: b\n")

        args = make_args(project_subcommand="list", state="enabled", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "beta" not in out

    def test_show_json_reports_missing_state_default(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")

        args = make_args(project_subcommand="show", project="alpha", json=True)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["project_name"] == "alpha"
        assert payload["state"] == "enabled"
        assert payload["state_explicit"] is False
        assert payload["state_source"] == "defaulted"
        assert payload["aliases"] == []
        assert payload["display_name"] is None
        assert payload["effective_project_name"] == "alpha"

    def test_show_text_reports_aliases(
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

        args = make_args(project_subcommand="show", project="alpha", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Aliases: bob, docs" in out

    def test_show_accepts_project_name_and_reports_directory_key(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(
            projects_root,
            "gh_x__widgets",
            "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/widgets\nNAME: a\n",
        )

        args = make_args(project_subcommand="show", project="widgets", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Project: widgets" in out
        assert "Directory key: gh_x__widgets" in out

    def test_list_text_shows_project_name_with_directory_key(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(
            projects_root,
            "gh_x__widgets",
            "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/widgets\nNAME: a\n",
        )

        args = make_args(project_subcommand="list", state="enabled", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "widgets (gh_x__widgets)" in out

    def test_show_missing_project_exits_one(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()

        args = make_args(project_subcommand="show", project="ghost", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "ghost" in capsys.readouterr().err

    def test_list_invalid_state_exits_one(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()

        args = make_args(project_subcommand="list", state="paused", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "invalid project state" in capsys.readouterr().err
