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


def test_ensure_project_file_read_only_skips_missing_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``create_missing=False`` must not register a CWD-inferred project."""
    from sase.main import utils as main_utils

    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr(main_utils, "get_workspace_name", lambda _cwd: "myrepo")

    assert main_utils.ensure_project_file_and_get_workspace_num(
        create_missing=False
    ) == (None, None, None)
    assert not (sase_home / "projects" / "myrepo").exists()


def test_ensure_project_file_default_creates_missing_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The default (creating) behavior still bootstraps a missing project."""
    import os

    from sase.main import utils as main_utils

    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr(main_utils, "get_workspace_name", lambda _cwd: "myrepo")

    project_file, workspace_num, project_name = (
        main_utils.ensure_project_file_and_get_workspace_num()
    )

    assert project_name == "myrepo"
    assert workspace_num == 1
    assert project_file is not None
    assert os.path.exists(project_file)
    assert (sase_home / "projects" / "myrepo").is_dir()


def test_ensure_project_file_read_only_returns_existing_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``create_missing=False`` still resolves an already-existing project."""
    import os

    from sase.main import utils as main_utils

    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr(main_utils, "get_workspace_name", lambda _cwd: "myrepo")

    # Bootstrap the project file first via the default (creating) path.
    created_file, _, _ = main_utils.ensure_project_file_and_get_workspace_num()
    assert created_file is not None and os.path.exists(created_file)

    # A subsequent read-only lookup returns the same project without creating.
    project_file, workspace_num, project_name = (
        main_utils.ensure_project_file_and_get_workspace_num(create_missing=False)
    )
    assert project_file == created_file
    assert workspace_num == 1
    assert project_name == "myrepo"
