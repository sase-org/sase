"""Tests for persisted last agent selection loading."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.last_agent_selection import (
    load_last_agent_selection,
    save_last_agent_selection_if_launchable,
)
from sase.ace.tui.modals import SelectionItem


def test_load_last_agent_selection_rejects_unknown_item_type(tmp_path: Path) -> None:
    selection_file = tmp_path / "last_agent_selection.json"
    selection_file.write_text(
        json.dumps(
            {
                "display_name": "bad",
                "item_type": "unexpected",
                "project_name": "proj",
                "cl_name": None,
            }
        ),
        encoding="utf-8",
    )

    with patch("sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file):
        assert load_last_agent_selection() is None


def test_load_last_agent_selection_rejects_non_string_fields(tmp_path: Path) -> None:
    selection_file = tmp_path / "last_agent_selection.json"
    selection_file.write_text(
        json.dumps(
            {
                "display_name": "bad",
                "item_type": "cl",
                "project_name": "proj",
                "cl_name": 42,
            }
        ),
        encoding="utf-8",
    )

    with patch("sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file):
        assert load_last_agent_selection() is None


def test_save_if_launchable_rejects_non_launchable_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection_file = tmp_path / "last_agent_selection.json"
    monkeypatch.setattr(
        "sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: False,
    )

    selection = SelectionItem(
        display_name="branch",
        item_type="cl",
        project_name="project",
        cl_name="branch",
    )
    assert save_last_agent_selection_if_launchable(selection) is False
    assert not selection_file.exists()


def test_save_if_launchable_accepts_home_regardless_of_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection_file = tmp_path / "last_agent_selection.json"
    monkeypatch.setattr(
        "sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file
    )

    def _fail(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("home selections must not consult is_launchable_project")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project", _fail
    )

    selection = SelectionItem(
        display_name="$HOME",
        item_type="home",
        project_name="anything",
        cl_name=None,
    )
    assert save_last_agent_selection_if_launchable(selection) is True
    data = json.loads(selection_file.read_text(encoding="utf-8"))
    assert data["item_type"] == "home"


def test_save_if_launchable_validates_home_project_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection_file = tmp_path / "last_agent_selection.json"
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file
    )

    def _is_launchable_project(name: str, projects_dir=None) -> bool:
        calls.append(name)
        return name == "home"

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        _is_launchable_project,
    )

    selection = SelectionItem(
        display_name="[P] home",
        item_type="project",
        project_name="home",
        cl_name=None,
    )
    assert save_last_agent_selection_if_launchable(selection) is True
    assert calls == ["home"]
    data = json.loads(selection_file.read_text(encoding="utf-8"))
    assert data["item_type"] == "project"
    assert data["project_name"] == "home"


def test_save_if_launchable_accepts_launchable_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection_file = tmp_path / "last_agent_selection.json"
    monkeypatch.setattr(
        "sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: True,
    )

    selection = SelectionItem(
        display_name="branch",
        item_type="cl",
        project_name="proj",
        cl_name="branch",
    )
    assert save_last_agent_selection_if_launchable(selection) is True
    data = json.loads(selection_file.read_text(encoding="utf-8"))
    assert data["project_name"] == "proj"
    assert data["cl_name"] == "branch"


def test_persisted_project_identity_survives_display_label_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = "gh_acme__widgets"
    projects = tmp_path / "sase-home" / "projects"
    project_dir = projects / canonical
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{canonical}.sase"
    project_file.write_text("PROJECT_NAME: widgets\n", encoding="utf-8")
    selection_file = tmp_path / "last_agent_selection.json"
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        "sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda name, projects_dir=None: name == canonical,
    )

    assert save_last_agent_selection_if_launchable(
        SelectionItem(
            display_name="[P] widgets",
            item_type="project",
            project_name=canonical,
            cl_name=None,
        )
    )
    stored = json.loads(selection_file.read_text(encoding="utf-8"))
    assert stored["project_name"] == canonical

    project_file.write_text("PROJECT_NAME: gadgets\n", encoding="utf-8")
    loaded = load_last_agent_selection()

    assert loaded is not None
    assert loaded.project_name == canonical
    assert loaded.display_name == "[P] gadgets"


def test_load_normalizes_legacy_display_form_project_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = "gh_acme__widgets"
    project_dir = tmp_path / "sase-home" / "projects" / canonical
    project_dir.mkdir(parents=True)
    (project_dir / f"{canonical}.sase").write_text(
        "PROJECT_NAME: widgets\n",
        encoding="utf-8",
    )
    selection_file = tmp_path / "last_agent_selection.json"
    selection_file.write_text(
        json.dumps(
            {
                "display_name": "[P] widgets",
                "item_type": "project",
                "project_name": "widgets",
                "cl_name": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))

    with patch("sase.ace.last_agent_selection._LAST_SELECTION_FILE", selection_file):
        loaded = load_last_agent_selection()

    assert loaded is not None
    assert loaded.project_name == canonical
    assert loaded.display_name == "[P] widgets"
