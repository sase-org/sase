"""Shared ArtifactsSnapshotPane lifecycle coverage."""

from __future__ import annotations

from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsDocumentsPane
from sase.ace.tui.widgets.artifacts.snapshot_pane import ArtifactsSnapshotPane


def test_shared_base_never_collects_on_the_event_loop() -> None:
    assert ArtifactsSnapshotPane._collects_snapshots_on_event_loop is False
    for pane_type in (ArtifactsBeadsPane, ArtifactsFilesPane, ArtifactsDocumentsPane):
        assert issubclass(pane_type, ArtifactsSnapshotPane)
        assert pane_type._collects_snapshots_on_event_loop is False
        assert callable(pane_type._build_snapshot)
        assert callable(pane_type._accept_snapshot)
        assert callable(pane_type._apply_snapshot)
