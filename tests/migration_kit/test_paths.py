"""Write-containment invariant tests for the migration kit's backup root."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.migration_kit.paths import (
    CUTOVER_BACKUP_DIR_ENV_VAR,
    _cutover_backup_root,
    _default_cutover_backup_root,
    backups_dir,
    is_contained_backup_root,
)


def test_default_backup_root_is_contained() -> None:
    assert is_contained_backup_root(_default_cutover_backup_root())


@pytest.mark.parametrize(
    "candidate",
    [
        "~/.sase",
        "~/.sase/tasks",
        "~/.local/state/sase",
        "~/.local/state/sase/workspaces/foo",
        "~/sase",
        "~/sase/repos/foo",
    ],
)
def test_runtime_roots_are_not_contained(candidate: str) -> None:
    assert not is_contained_backup_root(Path(candidate))


@pytest.mark.parametrize(
    "candidate",
    ["~/cutover-backups", "~/other-dir", "/mnt/backup"],
)
def test_unrelated_roots_are_contained(candidate: str) -> None:
    assert is_contained_backup_root(Path(candidate))


@pytest.mark.parametrize(
    "candidate",
    [
        "~/.sase/tasks",
        "~/.local/state/sase/workspaces/foo",
        "~/sase/repos/foo",
    ],
)
def test_already_expanded_runtime_roots_are_not_contained(candidate: str) -> None:
    """Regression test: the check must expand ``~`` on both sides.

    A caller in production always passes an already-``expanduser()``-ed
    absolute path (``backups_dir()`` expands before returning), not a literal
    ``~``-prefixed string. Comparing an expanded path against unexpanded
    prefixes would silently report every real path as contained.
    """
    assert not is_contained_backup_root(Path(candidate).expanduser())


def test_cutover_backup_root_honors_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "cutover"
    monkeypatch.setenv(CUTOVER_BACKUP_DIR_ENV_VAR, str(override))
    assert _cutover_backup_root() == override
    assert override.is_dir()


def test_cutover_backup_root_creates_mode_0700(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "cutover"
    monkeypatch.setenv(CUTOVER_BACKUP_DIR_ENV_VAR, str(override))
    root = _cutover_backup_root()
    assert oct(root.stat().st_mode)[-3:] == "700"


def test_backups_dir_is_created_on_first_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CUTOVER_BACKUP_DIR_ENV_VAR, str(tmp_path / "cutover"))
    assert backups_dir().is_dir()
