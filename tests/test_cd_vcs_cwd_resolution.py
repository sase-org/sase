"""CWD-resolution tests for built-in ``#cd`` and related launch refs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests._cd_launch_resolution_helpers import patch_cd_metadata


def test_resolve_vcs_cwd_uses_known_project_workspace_without_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.main.query_handler._query import _resolve_vcs_cwd

    workspace = tmp_path / "sase"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"sase": workspace},
    )

    with patch("sase.xprompt.loader.detect_project") as detect_project:
        result = _resolve_vcs_cwd("#gh:sase #!sase/fix_just")

    assert result == ("sase", "sase")
    assert Path.cwd() == workspace
    detect_project.cache_clear.assert_called_once_with()


def test_resolve_vcs_cwd_normalizes_owner_repo_ref_to_known_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``#gh:sase-org/sase`` falls back to the known ``sase`` workspace."""
    patch_cd_metadata(monkeypatch)
    from sase.main.query_handler._query import _resolve_vcs_cwd

    workspace = tmp_path / "sase"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"sase": workspace},
    )

    with patch("sase.xprompt.loader.detect_project") as detect_project:
        result = _resolve_vcs_cwd("#gh:sase-org/sase #!sase/refresh_docs")

    assert result == ("sase", "sase-org/sase")
    assert Path.cwd() == workspace
    detect_project.cache_clear.assert_called_once_with()


def test_resolve_vcs_cwd_unknown_owner_repo_ref_leaves_cwd_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An owner/repo ref pointing at a non-registered project does not chdir."""
    patch_cd_metadata(monkeypatch)
    from sase.main.query_handler._query import _resolve_vcs_cwd

    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"sase": tmp_path / "sase"},
    )

    starting_cwd = Path.cwd()
    with (
        patch("os.chdir") as chdir,
        patch("sase.xprompt.loader.detect_project"),
    ):
        result = _resolve_vcs_cwd("#gh:other-org/other do something")

    assert result == ("other-org/other", "other-org/other")
    chdir.assert_not_called()
    assert Path.cwd() == starting_cwd


def test_resolve_vcs_cwd_cd_changes_to_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.main.query_handler._query import _resolve_vcs_cwd

    with (
        patch("os.chdir") as chdir,
        patch("sase.xprompt.loader.detect_project") as detect_project,
    ):
        result = _resolve_vcs_cwd(f"#cd:{tmp_path} do work")

    assert result == (tmp_path.name, str(tmp_path))
    chdir.assert_called_once_with(str(tmp_path.resolve()))
    detect_project.cache_clear.assert_called_once_with()


def test_resolve_vcs_cwd_cd_bad_path_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.main.query_handler._query import _resolve_vcs_cwd

    with pytest.raises(ValueError, match="does not exist"):
        _resolve_vcs_cwd(f"#cd:{tmp_path / 'missing'} do work")
