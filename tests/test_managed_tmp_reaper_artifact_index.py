"""Artifact-index interactions for the managed-tmp reaper."""

from __future__ import annotations

from pathlib import Path

import pytest
from sase.core.managed_tmp_reaper import RUN_ARTIFACT_HORIZON_SECONDS
from tests._managed_tmp_reaper_helpers import (
    HOUR,
    NOW,
    _aged_dir,
    _aged_file,
    _fail_on_call,
    reap_managed_tmpdir,
)


def test_reaped_directories_drop_their_artifact_index_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A reaped ``workflow-artifacts/`` entry may have been an agents_dir."""
    stale = _aged_dir(
        tmp_path,
        "workflow-artifacts/workflow-simple-abc",
        age_seconds=RUN_ARTIFACT_HORIZON_SECONDS + HOUR,
    )
    _aged_file(tmp_path, "editors/note.md", age_seconds=13 * HOUR)
    deleted: list[list[Path]] = []
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle_mutations."
        "delete_agent_artifact_index_artifacts",
        lambda dirs: deleted.append(list(dirs)) or len(deleted[-1]),
    )

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    # Only the directory is de-indexed; the reaped editor file never had a row.
    assert deleted == [[stale]]
    assert result.deindexed == 1


def test_a_file_only_pass_never_touches_the_artifact_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _aged_file(tmp_path, "editors/note.md", age_seconds=13 * HOUR)
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle_mutations."
        "delete_agent_artifact_index_artifacts",
        _fail_on_call,
    )

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert result.removed == 1
    assert result.deindexed == 0


def test_workflow_artifact_directories_are_pruned_whole(tmp_path: Path) -> None:
    stale = _aged_dir(
        tmp_path,
        "workflow-artifacts/workflow-refresh_docs-abc",
        age_seconds=RUN_ARTIFACT_HORIZON_SECONDS + HOUR,
    )
    fresh = _aged_dir(
        tmp_path,
        "workflow-artifacts/workflow-refresh_docs-def",
        age_seconds=RUN_ARTIFACT_HORIZON_SECONDS - HOUR,
    )

    reap_managed_tmpdir(tmp_path, now=NOW)

    assert not stale.exists()
    assert (fresh / "state.json").exists()
