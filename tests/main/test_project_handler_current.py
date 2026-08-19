"""Tests for ``sase project current``."""

from __future__ import annotations

import json
from typing import Literal

import pytest

from sase.ace.tui.project_styles import project_accent
from sase.current_project import CurrentProject
from sase.main.project_handler import handle_project_command
from tests.main.workspace_handler_helpers import make_args

_Origin = Literal["project", "patch"]


def _project(
    *,
    origin: _Origin = "project",
    origin_ref: str = "sase",
    workflow_type: str = "gh",
) -> CurrentProject:
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin=origin,
        origin_ref=origin_ref,
        workflow_type=workflow_type,
    )


def _install_current(
    monkeypatch: pytest.MonkeyPatch,
    current: CurrentProject | None,
) -> None:
    from sase.main import project_handler_current

    monkeypatch.setattr(
        project_handler_current, "resolve_current_project", lambda **_kwargs: current
    )
    if current is not None:
        monkeypatch.setattr(
            project_handler_current,
            "_enabled_project_keys",
            lambda: [current.project_key],
        )


class TestProjectCurrent:
    def test_resolved_project_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_current(monkeypatch, _project())
        args = make_args(project_subcommand="current", json=False)

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "+sase" in out
        assert "Directory key: gh_sase-org__sase" in out
        assert "Origin: project" in out
        assert "MRU ref: #gh:sase" in out

    def test_patch_origin_names_the_patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_current(
            monkeypatch,
            _project(origin="patch", origin_ref="my_patch"),
        )
        args = make_args(project_subcommand="current", json=False)

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "+sase" in out
        assert "Origin: patch (my_patch)" in out
        assert "MRU ref: #gh:my_patch" in out

    def test_empty_mru_explains_how_to_set_current(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_current(monkeypatch, None)
        args = make_args(project_subcommand="current", json=False)

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "No current project." in out
        assert "Launch an agent on a project" in out
        assert "sase project set-current" in out

    def test_json_shape_for_resolved_project(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_current(monkeypatch, _project())
        args = make_args(project_subcommand="current", json=True)

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {
            "display_name": "sase",
            "mru_ref": "#gh:sase",
            "origin": "project",
            "origin_ref": "sase",
            "project_key": "gh_sase-org__sase",
            "workflow_type": "gh",
        }

    def test_json_shape_for_patch_origin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_current(
            monkeypatch,
            _project(origin="patch", origin_ref="my_patch"),
        )
        args = make_args(project_subcommand="current", json=True)

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["origin"] == "patch"
        assert payload["origin_ref"] == "my_patch"
        assert payload["mru_ref"] == "#gh:my_patch"
        assert payload["display_name"] == "sase"
        assert payload["project_key"] == "gh_sase-org__sase"

    def test_json_null_when_nothing_resolves(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _install_current(monkeypatch, None)
        args = make_args(project_subcommand="current", json=True)

        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert json.loads(capsys.readouterr().out) is None

    def test_human_output_uses_project_accent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from rich.console import Console

        from sase.main import project_handler_current

        current = _project()
        _install_current(monkeypatch, current)
        console = Console(record=True, force_terminal=True, color_system="truecolor")

        project_handler_current._print_current_human(current, console=console)

        accent = project_accent(current.project_key, among=[current.project_key])
        html = console.export_html(inline_styles=True)
        assert current.display_name in html
        assert accent.lstrip("#").lower() in html.lower()
