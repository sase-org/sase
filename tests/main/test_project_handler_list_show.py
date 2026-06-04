"""Tests for ``sase project list`` and ``sase project show``."""

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


class TestListAndShow:
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
            "core",
        ]
        assert payload[0]["aliases"] == []
        assert payload[0]["state"] == "active"
        assert payload[0]["state_source"] == "defaulted"
        assert payload[1]["state"] == "inactive"
        assert payload[1]["state_source"] == "explicit"
        assert payload[2]["state"] == "sibling"
        assert payload[2]["launchable"] is False

    def test_list_can_filter_sibling_projects(
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
        assert "core" in out
        assert "sibling*" in out
        assert "alpha" not in out

    def test_list_defaults_to_active_projects(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")
        _write_project(projects_root, "beta", "PROJECT_STATE: closed\nNAME: b\n")

        args = make_args(project_subcommand="list", state="active", json=False)
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
        assert payload["state"] == "active"
        assert payload["state_explicit"] is False
        assert payload["state_source"] == "defaulted"
        assert payload["aliases"] == []

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
