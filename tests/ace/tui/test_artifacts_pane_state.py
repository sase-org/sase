"""Snapshot-pane wiring for the shared shell state resolver.

Covers ``ArtifactsSnapshotPane.pane_state()`` as actually wired by Beads,
Files, and Documents (``ArtifactsDocumentsPane``/Plans) — not just the pure
``resolve_pane_state`` function tested in isolation in
``test_artifacts_shell.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsDocumentsPane
from sase.ace.tui.widgets.artifacts.shell import ArtifactsPaneState
from sase.agents.catalog import AgentCatalogRow
from tests.ace.tui._artifacts_beads_helpers import snapshot as beads_snapshot
from tests.ace.tui._artifacts_files_helpers import artifact_file
from tests.ace.tui._artifacts_files_helpers import snapshot as files_snapshot
from tests.ace.tui._artifacts_plans_helpers import _snapshot as plans_snapshot


def _agent_row(name: str = "0b4--0", **overrides: Any) -> AgentCatalogRow:
    defaults: dict[str, Any] = {
        "name": name,
        "canonical_global_name": None,
        "kind": ("member",),
        "project": "alpha",
        "state": "active",
        "family": "0b4",
        "role": "code",
        "clan": None,
        "tribe": None,
        "workflow": None,
        "parent_timestamp": None,
        "raw_suffix": None,
        "artifacts_dir": None,
        "bundle_path": None,
        "model": None,
        "llm_provider": None,
        "status": "RUNNING",
        "hidden": False,
        "started_at": None,
        "finished_at": None,
        "retry_attempt": None,
        "patch": None,
        "dismissed": False,
        "revivable": False,
        "attention": False,
        "retry": False,
        "has_collision_history": False,
        "from_artifact_index": True,
        "from_dismissed_archive": False,
    }
    defaults.update(overrides)
    return AgentCatalogRow(**defaults)


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


def test_agents_pane_state_precedence() -> None:
    pane = ArtifactsAgentsPane()
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
    pane._snapshot = AgentsSnapshot(
        project="alpha",
        rows=(_agent_row(project="alpha"),),
        total_row_count=1,
        truncated=False,
    )
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

    # An empty (but current-scope) snapshot is a real empty state.
    pane.project_scope = "alpha"
    pane._snapshot = AgentsSnapshot(
        project="alpha",
        rows=(),
        total_row_count=0,
        truncated=False,
    )
    assert pane.pane_state() is ArtifactsPaneState.EMPTY
