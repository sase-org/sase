"""Canonical skill authoring destinations."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.xprompt.skill_locations import (
    is_canonical_skill_directory,
    skill_destinations,
)


@pytest.fixture(autouse=True)
def _scoped_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("sase.xprompt.skill_locations.get_use_chezmoi", lambda: False)
    monkeypatch.setattr("sase.xprompt.skill_locations.detect_project", lambda: None)
    monkeypatch.setattr(
        "sase.xprompt.skill_locations.discover_project_root",
        lambda: tmp_path / "repo",
    )


def test_writable_scopes_come_first_in_discovery_order(tmp_path: Path) -> None:
    paths = [destination.path for destination in skill_destinations("app")]

    assert paths[:3] == [
        tmp_path / "repo" / "sase" / "skills",
        tmp_path / "home" / "sase" / "skills",
        tmp_path / "home" / "sase" / "skills" / "app",
    ]


def test_only_project_scopes_namespace_the_reference() -> None:
    namespaced = {
        destination.label: destination.project_namespaced
        for destination in skill_destinations("app")
    }

    assert namespaced["Project sase/skills/"] is True
    assert namespaced["Project home (app)"] is True
    assert namespaced["Home ~/sase/skills/"] is False


def test_the_package_directory_is_offered_as_a_dev_destination() -> None:
    builtin = [
        destination for destination in skill_destinations(None) if destination.builtin
    ]

    assert any(
        destination.path.name == "skills"
        and destination.path.parent.name == "xprompts"
        and destination.path.parent.parent.name == "sase"
        for destination in builtin
    )


def test_only_canonical_directories_accept_skill_sources(tmp_path: Path) -> None:
    assert is_canonical_skill_directory(tmp_path / "repo" / "sase" / "skills")
    assert not is_canonical_skill_directory(tmp_path / "repo" / "sase" / "xprompts")
    # A ``skills/`` directory outside a known scope is not canonical either.
    assert not is_canonical_skill_directory(tmp_path / "elsewhere" / "skills")
