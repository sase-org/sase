"""Workspace preparation must not clean the shared agents sidecar unlocked.

``prepare_workspace`` runs ``git reset --hard HEAD`` + ``git clean -fd`` + a
checkout. Against ``~/.sase/projects/<key>/repos/agents`` -- one clone shared by
every numbered workspace -- that raced agents-sync publication, which stages its
whole regenerated payload in the worktree before committing: a reset unlinks a
dirty tracked file before recreating it, and a publication pass that reads the
owner manifest inside that window sees no file and republishes from an empty
manifest, truncating it. Preparation now takes the same ``sase-agents-sync.lock``
every agents-sync mutator already serializes on.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.runner_workspace import prepare_workspace
from sase.core.paths import sase_projects_dir
from sase.vcs_provider import VCS_DEFAULT_REVISION

_LOCK_NAME = "sase-agents-sync.lock"


def _git_init(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
    )
    return repo


def _shared_agents_clone() -> Path:
    return _git_init(sase_projects_dir() / "gh_sase-org__sase" / "repos" / "agents")


def _lock_path(repo: Path) -> Path:
    return repo / ".git" / _LOCK_NAME


def _lock_is_free(path: Path) -> bool:
    """True when ``path``'s advisory lock can be taken right now."""

    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return True
    finally:
        os.close(descriptor)


def _successful_provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_parent_revision.return_value = "origin/main"
    provider.checkout.return_value = (True, None)
    provider.sync_workspace.return_value = (True, None)
    return provider


def test_prepare_workspace_skips_shared_agents_clone_while_sync_holds_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A busy agents sync blocks the clean instead of racing its payload."""

    repo = _shared_agents_clone()
    monkeypatch.setenv("SASE_AGENTS_SYNC_LOCK_TIMEOUT", "0")
    clean = MagicMock(return_value=(True, None))
    descriptor = os.open(_lock_path(repo), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        with (
            patch("sase.workflows.commit_utils.run_sase_hg_clean", clean),
            patch(
                "sase.axe.runner_workspace.get_vcs_provider",
                return_value=_successful_provider(),
            ),
        ):
            result = prepare_workspace(str(repo), "agents", VCS_DEFAULT_REVISION)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert result is False
    clean.assert_not_called()


def test_prepare_workspace_holds_agents_lock_across_the_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lock covers the clean and checkout, and is released afterwards."""

    repo = _shared_agents_clone()
    monkeypatch.setenv("SASE_AGENTS_SYNC_LOCK_TIMEOUT", "0")
    provider = _successful_provider()
    observed: list[bool] = []

    def _clean(workspace_dir: str, diff_name: str) -> tuple[bool, None]:
        assert workspace_dir and diff_name
        observed.append(_lock_is_free(_lock_path(repo)))
        return (True, None)

    with (
        patch("sase.workflows.commit_utils.run_sase_hg_clean", _clean),
        patch("sase.axe.runner_workspace.get_vcs_provider", return_value=provider),
    ):
        result = prepare_workspace(str(repo), "agents", VCS_DEFAULT_REVISION)

    assert result is True
    assert observed == [False]
    assert _lock_is_free(_lock_path(repo))
    provider.checkout.assert_called_once_with("origin/main", str(repo))


def test_prepare_workspace_leaves_workspace_scoped_agents_clone_unguarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the machine-shared clone is coordinated, not a workspace sidecar."""

    repo = _git_init(tmp_path / "sase_3" / "sase" / "repos" / "agents")
    monkeypatch.setenv("SASE_AGENTS_SYNC_LOCK_TIMEOUT", "0")
    observed: list[bool] = []

    def _clean(workspace_dir: str, diff_name: str) -> tuple[bool, None]:
        assert workspace_dir and diff_name
        observed.append(_lock_is_free(_lock_path(repo)))
        return (True, None)

    with (
        patch("sase.workflows.commit_utils.run_sase_hg_clean", _clean),
        patch(
            "sase.axe.runner_workspace.get_vcs_provider",
            return_value=_successful_provider(),
        ),
    ):
        result = prepare_workspace(str(repo), "agents", VCS_DEFAULT_REVISION)

    assert result is True
    assert observed == [True]
