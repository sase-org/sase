"""Tests for ``sase project set-current``."""

from __future__ import annotations

import json

import pytest

from sase.current_project import CurrentProject, SetCurrentProjectOutcome
from sase.main.project_handler import handle_project_command
from tests.main.workspace_handler_helpers import make_args


def _project() -> CurrentProject:
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin="project",
        origin_ref="sase",
        workflow_type="gh",
    )


def _install_set(
    monkeypatch: pytest.MonkeyPatch,
    outcome: SetCurrentProjectOutcome,
) -> None:
    from sase.main import project_handler

    monkeypatch.setattr(
        project_handler,
        "set_current_project",
        lambda *_args, **_kwargs: outcome,
    )
    project = outcome.project
    if project is not None:
        monkeypatch.setattr(
            project_handler,
            "_enabled_project_keys",
            lambda: [project.project_key],
        )


class TestProjectSetCurrent:
    def test_enabled_project_exits_zero_and_names_the_project(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_set(
            monkeypatch,
            SetCurrentProjectOutcome(
                status="set",
                project=_project(),
                message="sase is now the current project.",
            ),
        )
        args = make_args(
            project_subcommand="set-current",
            project="sase",
            json=False,
        )

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "sase is now the current project." in out
        assert "+sase" in out
        assert "Directory key: gh_sase-org__sase" in out

    def test_disabled_project_exits_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_set(
            monkeypatch,
            SetCurrentProjectOutcome(
                status="ineligible",
                project=None,
                message="sase is disabled; enable it first.",
            ),
        )
        args = make_args(
            project_subcommand="set-current",
            project="sase",
            json=False,
        )

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "sase is disabled; enable it first." in captured.err

    def test_json_round_trip_has_documented_keys(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_set(
            monkeypatch,
            SetCurrentProjectOutcome(
                status="set",
                project=_project(),
                message="sase is now the current project.",
            ),
        )
        args = make_args(
            project_subcommand="set-current",
            project="sase",
            json=True,
        )

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "set"
        assert payload["message"] == "sase is now the current project."
        assert payload["project"] == {
            "display_name": "sase",
            "mru_ref": "#gh:sase",
            "origin": "project",
            "origin_ref": "sase",
            "project_key": "gh_sase-org__sase",
            "workflow_type": "gh",
        }

    def test_json_null_project_on_ineligible(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_set(
            monkeypatch,
            SetCurrentProjectOutcome(
                status="ineligible",
                project=None,
                message="Project 'missing' was not found.",
            ),
        )
        args = make_args(
            project_subcommand="set-current",
            project="missing",
            json=True,
        )

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "ineligible"
        assert payload["project"] is None
        assert payload["message"] == "Project 'missing' was not found."
