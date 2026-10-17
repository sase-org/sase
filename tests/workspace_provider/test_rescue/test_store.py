"""Rescue-store empty, reap, and quarantine tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sase.workspace_provider._rescue_store import reap_rescue_store
from sase.workspace_provider.rescue import (
    quarantine_directory,
    rescue_git_repo,
)
from tests.workspace_provider.test_rescue._helpers import (
    redirect_state,
    rescue_entries,
    seed_remote_clone,
)


def test_rescue_returns_none_when_nothing_to_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)

    assert (
        rescue_git_repo(
            clone,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="clean",
            include_worktree=True,
        )
        is None
    )
    assert (
        rescue_git_repo(
            tmp_path,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="not a repo",
            include_worktree=True,
        )
        is None
    )
    assert rescue_entries(home) == []
    assert notified == []


def test_reap_deletes_only_aged_entries(tmp_path: Path) -> None:
    root = tmp_path / "rescue"
    month = root / "202601"
    young = month / "young"
    old_bundle = month / "old-bundle"
    old_quarantine = month / "old-quarantine"
    young_quarantine = month / "young-quarantine"
    for entry in (young, old_bundle, old_quarantine, young_quarantine):
        entry.mkdir(parents=True)
        (entry / "manifest.json").write_text("{}\n", encoding="utf-8")
    for entry in (old_quarantine, young_quarantine):
        (entry / "quarantined-clone").mkdir()
    now = time.time()
    aged_bundle = now - 31 * 86400
    aged_quarantine = now - 8 * 86400
    os.utime(old_bundle, (aged_bundle, aged_bundle))
    os.utime(old_quarantine, (aged_quarantine, aged_quarantine))

    reap_rescue_store(rescue_roots=[root], now=now)

    assert young.is_dir()
    assert young_quarantine.is_dir()
    assert not old_bundle.exists()
    assert not old_quarantine.exists()


def test_quarantine_directory_moves_clone_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)

    record = quarantine_directory(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="damaged",
    )

    assert record is not None
    assert record.quarantined_path is not None
    assert not clone.exists()
    assert (record.quarantined_path / ".git").is_dir()
    assert record.quarantined_path.parent == record.rescue_dir
    assert workspace not in record.rescue_dir.parents
    assert (record.rescue_dir / "manifest.json").is_file()
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"

    assert (
        quarantine_directory(
            tmp_path / "missing",
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="missing",
        )
        is None
    )
    assert rescue_entries(home) != []
