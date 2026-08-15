"""Snapshot-pane wiring for the shared shell state resolver.

Covers ``ArtifactsSnapshotPane.pane_state()`` as actually wired by Beads,
Files, and Documents (``ArtifactsDocumentsPane``/Plans) — not just the pure
``resolve_pane_state`` function tested in isolation in
``test_artifacts_shell.py``.
"""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsDocumentsPane
from sase.ace.tui.widgets.artifacts.shell import ArtifactsPaneState
from tests.ace.tui._artifacts_beads_helpers import snapshot as beads_snapshot
from tests.ace.tui._artifacts_files_helpers import artifact_file
from tests.ace.tui._artifacts_files_helpers import snapshot as files_snapshot
from tests.ace.tui._artifacts_plans_helpers import _snapshot as plans_snapshot


def test_beads_pane_state_precedence(tmp_path: Path) -> None:
    pane = ArtifactsBeadsPane()
    pane.project_scope = "alpha"

    # Nothing loaded yet, first load in flight.
    pane._loading = True
    assert pane.pane_state() is ArtifactsPaneState.LOADING

    # First load failed with nothing cached.
    pane._loading = False
    pane._load_error = "boom"
    assert pane.pane_state() is ArtifactsPaneState.DEGRADED

    # A populated snapshot for the current scope settles to results.
    pane._load_error = None
    pane._snapshot = beads_snapshot(tmp_path, project="alpha")
    assert pane.pane_state() is ArtifactsPaneState.RESULTS

    # Refreshing with cached content preserves it as stale, not loading.
    pane._loading = True
    assert pane.pane_state() is ArtifactsPaneState.STALE

    # A refresh error with cached content is also stale, not degraded.
    pane._loading = False
    pane._load_error = "refresh failed"
    assert pane.pane_state() is ArtifactsPaneState.STALE

    # A snapshot from a different (stale) scope is not usable content.
    pane._load_error = None
    pane.project_scope = "beta"
    assert pane.pane_state() is ArtifactsPaneState.EMPTY


def test_files_pane_state_precedence() -> None:
    pane = ArtifactsFilesPane()
    pane.project_scope = "alpha"

    pane._loading = True
    assert pane.pane_state() is ArtifactsPaneState.LOADING

    pane._loading = False
    row = artifact_file("one", project="alpha")
    pane._snapshot = files_snapshot((row,), project="alpha")
    assert pane.pane_state() is ArtifactsPaneState.RESULTS

    pane._loading = True
    assert pane.pane_state() is ArtifactsPaneState.STALE

    pane._loading = False
    pane._snapshot = files_snapshot((), project="alpha")
    assert pane.pane_state() is ArtifactsPaneState.EMPTY


def test_documents_pane_state_precedence(tmp_path: Path) -> None:
    pane = ArtifactsDocumentsPane()
    pane.project_scope = "alpha"

    pane._loading = True
    assert pane.pane_state() is ArtifactsPaneState.LOADING

    pane._loading = False
    pane._snapshot = plans_snapshot(tmp_path)
    pane.project_scope = pane._snapshot.project
    assert pane.pane_state() is ArtifactsPaneState.RESULTS

    pane._load_error = "boom"
    assert pane.pane_state() is ArtifactsPaneState.STALE
