"""Deterministic bead-mention fixtures for ACE prompt PNG snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui import AceApp
from sase.ace.tui.models.bead_preview import (
    BeadMentionEntry,
    BeadMentionIndex,
    BeadStoreDirectory,
)
from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot


def _visual_snapshot(
    workspace: Path,
    *,
    issue_prefix: str,
    project_key: str,
) -> BeadStoreSnapshot:
    return BeadStoreSnapshot(
        origin=BeadStoreOrigin(
            project_key=project_key,
            project_label=project_key,
            primary_workspace=workspace,
            beads_dir=workspace / "beads",
        ),
        store_key=project_key,
        issue_ids=frozenset(),
        issue_prefix=issue_prefix,
        project_refs=frozenset({project_key}),
    )


def _visual_directory(workspace: Path) -> BeadStoreDirectory:
    return BeadStoreDirectory(
        snapshots=(
            _visual_snapshot(workspace, issue_prefix="sase", project_key="sase"),
            _visual_snapshot(workspace, issue_prefix="bob-cli", project_key="bob-cli"),
        )
    )


def _visual_index(workspace: Path) -> BeadMentionIndex:
    index = BeadMentionIndex()
    index.store(
        "sase-1ss",
        BeadMentionEntry("in_progress", str(workspace / "beads"), "visual-token"),
    )
    index.store(
        "bob-cli-kx",
        BeadMentionEntry("closed", str(workspace / "beads"), "visual-token"),
    )
    index.store(
        "sase-9zz", BeadMentionEntry(None, str(workspace / "beads"), "visual-token")
    )
    return index


def patch_visual_bead_mentions(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    """Serve a warm bead directory and a seeded mention index to the prompt."""
    directory = _visual_directory(workspace)
    index = _visual_index(workspace)

    def _directory(
        _app: AceApp,
        *,
        schedule: bool = True,
    ) -> BeadStoreDirectory:
        del schedule
        return directory

    monkeypatch.setattr(AceApp, "get_bead_store_directory", _directory)
    monkeypatch.setattr(AceApp, "bead_mention_index_for_render", lambda _app: index)
    monkeypatch.setattr(
        AceApp, "request_bead_mention_resolution", lambda _app, _ids: None
    )
    monkeypatch.setattr(
        AceApp, "seed_bead_mention_status", lambda _app, *_a, **_k: False
    )
