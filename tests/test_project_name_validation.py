"""Regression tests for SASE project-name validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.paths import is_valid_sase_project_name, validate_sase_project_name
from sase.workflows.commit.project_file_utils import create_project_file


@pytest.mark.parametrize(
    "project_name",
    ["sase", "beads", "bob-cli", "CV", "zorg", "home", "foo_bar", "foo.bar"],
)
def test_project_name_validation_allows_normal_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_name: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    assert is_valid_sase_project_name(project_name)
    validate_sase_project_name(project_name)


@pytest.mark.parametrize(
    "project_name",
    ["", ".", "..", ".sase", "foo/bar", r"foo\bar"],
)
def test_project_name_validation_rejects_hidden_and_path_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_name: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    assert not is_valid_sase_project_name(project_name)
    with pytest.raises(ValueError, match="invalid SASE project name"):
        validate_sase_project_name(project_name)


def test_create_project_file_rejects_hidden_project_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    assert create_project_file(".sase") is False

    assert not (sase_home / "projects" / ".sase").exists()
    assert not (sase_home / "projects" / ".sase" / ".sase.sase").exists()


def test_ensure_project_file_ignores_invalid_inferred_project_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.main import utils as main_utils

    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr(main_utils, "get_workspace_name", lambda _cwd: ".sase")

    assert main_utils.ensure_project_file_and_get_workspace_num() == (
        None,
        None,
        None,
    )
    assert not (sase_home / "projects" / ".sase").exists()
