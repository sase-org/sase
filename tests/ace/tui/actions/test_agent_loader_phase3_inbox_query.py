"""Phase 3 contract tests for the visibility-aware Tier 1 inbox loader.

Phase 3 of bead ``sase-3r`` (Fast Agents Tab Disk Loading) makes the
ordinary Agents-tab refresh:

* call :func:`query_agent_artifact_index` with a visibility-aware inbox
  query (``include_dismissed=False``, no fixed completed-row limit);
* keep an active search query inside the Tier 1 inbox instead of
  promoting it to a full-history Tier 2 source scan;
* skip the source-tree walk entirely when the persistent index is
  absent — the loader returns an empty Tier 1 snapshot flagged with
  ``index_missing`` and the apply layer schedules a one-off rebuild;
* still source-scan when the caller explicitly opts into ``full_history``
  (e.g. revive, archive search, doctor/repair).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent_loader import (
    AgentLoadState,
    _artifact_snapshot_for_tui_load,
    _query_artifact_index_for_loader,
    _tui_inbox_query,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)


def _snapshot_with_stats(
    *,
    records: int = 0,
    artifact_dirs_visited: int = 0,
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(
            artifact_dirs_visited=artifact_dirs_visited,
        ),
        records=[None] * records,  # type: ignore[list-item]
    )


_SOURCE_PATCH_TARGETS: tuple[tuple[str, object], ...] = (
    ("sase.ace.tui.models.agent_loader.find_all_changespecs", []),
    ("sase.ace.tui.models.agent_loader.get_all_project_files", []),
    ("sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot", []),
    ("sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot", []),
    ("sase.ace.tui.models.agent_loader.load_agents_from_running_field", []),
    (
        "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
        ([], {}),
    ),
    ("sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot", []),
    ("sase.ace.agent_tags.load_agent_tags", {}),
)


def _enter_empty_sources(stack: contextlib.ExitStack) -> None:
    for target, value in _SOURCE_PATCH_TARGETS:
        stack.enter_context(patch(target, return_value=value))


# ---------------------------------------------------------------------------
# Visibility-aware inbox query knobs
# ---------------------------------------------------------------------------


def test_tui_inbox_query_excludes_dismissed_and_drops_recent_completed_limit() -> None:
    """The new Tier 1 query asks the index for the visibility-aware inbox."""

    query = _tui_inbox_query()
    assert isinstance(query, AgentArtifactIndexQueryWire)
    assert query.include_active is True
    assert query.include_recent_completed is True
    assert query.include_full_history is False
    assert query.include_hidden is False
    # Dismissal visibility is now enforced server-side rather than via a
    # fixed completed-row limit.
    assert query.include_dismissed is False
    assert query.recent_completed_limit is None


def test_index_path_load_passes_visibility_aware_query_to_facade(
    tmp_path: Path,
) -> None:
    """Successful Tier 1 loads call the index facade with the inbox query."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _snapshot_with_stats(records=2)

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as mock_query,
    ):
        result = _query_artifact_index_for_loader(
            full_history=False, agent_search_active=False
        )

    assert result is not None
    _, state = result
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is True
    assert state.index_missing is False

    mock_query.assert_called_once()
    kwargs = mock_query.call_args.kwargs
    query: AgentArtifactIndexQueryWire = kwargs["query"]
    assert query.include_dismissed is False
    assert query.recent_completed_limit is None
    assert query.include_active is True
    assert query.include_recent_completed is True
    assert query.include_full_history is False
    assert query.include_hidden is False


# ---------------------------------------------------------------------------
# Missing index: no source scan
# ---------------------------------------------------------------------------


def test_missing_index_returns_empty_snapshot_with_index_missing_flag(
    tmp_path: Path,
) -> None:
    """A missing artifact index returns ``index_missing=True`` and skips scan."""

    missing_index = tmp_path / "agent_artifact_index.sqlite"

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=missing_index,
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as mock_scan,
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
        ) as mock_query,
    ):
        snapshot, state = _artifact_snapshot_for_tui_load(
            full_history=False, agent_search_active=False
        )

    assert snapshot.records == []
    assert state.tier == "tier1"
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is False
    assert state.index_missing is True
    assert state.index_error is None
    assert state.snapshot_records == 0
    mock_scan.assert_not_called()
    mock_query.assert_not_called()


def test_missing_index_does_not_trigger_full_history_reconcile_flag(
    tmp_path: Path,
) -> None:
    """Missing-index Tier 1 loads do not flag ``needs_full_history_reconcile``.

    The apply layer reads :attr:`AgentLoadState.needs_full_history_reconcile`
    to decide whether to schedule a Tier 2 source scan. After Phase 3 of
    ``sase-3r`` the missing-index branch should drive an index rebuild
    rather than a source scan, so this property must stay ``False``.
    """

    missing_index = tmp_path / "agent_artifact_index.sqlite"

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=missing_index,
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
        ),
    ):
        _, state = _artifact_snapshot_for_tui_load(
            full_history=False, agent_search_active=False
        )

    assert state.index_missing is True
    assert state.needs_full_history_reconcile is False


def test_index_query_success_does_not_trigger_full_history_reconcile(
    tmp_path: Path,
) -> None:
    """Inbox-query success keeps ``needs_full_history_reconcile`` False."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _snapshot_with_stats(records=1)

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as mock_scan,
    ):
        _, state = _artifact_snapshot_for_tui_load(
            full_history=False, agent_search_active=False
        )

    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is True
    assert state.complete_history is False
    assert state.needs_full_history_reconcile is False
    mock_scan.assert_not_called()


def test_index_query_error_still_triggers_full_history_reconcile(
    tmp_path: Path,
) -> None:
    """Bounded source-scan fallback flags ``needs_full_history_reconcile``."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    fallback = _snapshot_with_stats(records=1)

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            side_effect=RuntimeError("index corrupt"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=fallback,
        ),
    ):
        _, state = _artifact_snapshot_for_tui_load(
            full_history=False, agent_search_active=False
        )

    assert state.artifact_source == "source_scan"
    assert state.index_error == "index corrupt"
    assert state.index_missing is False
    assert state.needs_full_history_reconcile is True


# ---------------------------------------------------------------------------
# Search no longer forces full history; explicit full_history still scans
# ---------------------------------------------------------------------------


def test_explicit_full_history_still_runs_source_scan(tmp_path: Path) -> None:
    """``full_history=True`` keeps the explicit Tier 2 source scan path."""

    snapshot = _snapshot_with_stats(records=3)
    with contextlib.ExitStack() as stack:
        mock_scan = stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
                return_value=snapshot,
            )
        )
        mock_query = stack.enter_context(
            patch("sase.ace.tui.models.agent_loader.query_agent_artifact_index")
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
                return_value=tmp_path / "index.sqlite",
            )
        )
        _enter_empty_sources(stack)
        result = load_agents_from_disk_with_state(
            set(),
            full_history=True,
            agent_search_active=False,
        )

    state = result.load_state
    assert state.tier == "tier2"
    assert state.full_history is True
    assert state.complete_history is True
    assert state.artifact_source == "source_scan"
    mock_scan.assert_called_once()
    # Tier 2 source scan must walk the whole tree, not the bounded fallback.
    options = mock_scan.call_args.args[0] if mock_scan.call_args.args else None
    assert options is None or options.max_records is None
    mock_query.assert_not_called()


def test_search_query_with_present_index_stays_in_tier1_inbox(
    tmp_path: Path,
) -> None:
    """Search filters the cached inbox instead of promoting to Tier 2.

    With a present index and a non-empty Agents-tab search query, the
    loader stays on the index-backed Tier 1 inbox path and never invokes
    the source-tree scan.
    """

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    indexed_snapshot = _snapshot_with_stats(records=4)
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
                return_value=index_path,
            )
        )
        mock_scan = stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
                return_value=indexed_snapshot,
            )
        )
        _enter_empty_sources(stack)
        result = load_agents_from_disk_with_state(
            set(),
            full_history=False,
            agent_search_active=True,
        )

    state = result.load_state
    assert state.tier == "tier1"
    assert state.full_history is False
    assert state.agent_search_active is True
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is True
    mock_scan.assert_not_called()


def test_search_query_with_missing_index_stays_in_tier1_no_source_scan(
    tmp_path: Path,
) -> None:
    """Search with a missing index keeps the empty Tier 1 path — no scan."""

    missing_index = tmp_path / "agent_artifact_index.sqlite"
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
                return_value=missing_index,
            )
        )
        mock_scan = stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            )
        )
        _enter_empty_sources(stack)
        result = load_agents_from_disk_with_state(
            set(),
            full_history=False,
            agent_search_active=True,
        )

    state = result.load_state
    assert state.tier == "tier1"
    assert state.full_history is False
    assert state.agent_search_active is True
    assert state.index_missing is True
    assert state.artifact_source == "artifact_index"
    mock_scan.assert_not_called()


# ---------------------------------------------------------------------------
# Stale cached preservation during incomplete loads
# ---------------------------------------------------------------------------


def test_missing_index_load_state_signals_apply_layer_cache_preservation() -> None:
    """``AgentLoadState`` exposes the inputs the apply layer needs.

    ``merge_incomplete_load_after_complete_history`` keeps cached
    visible agents in place when the apply layer sees a non-complete
    load state after previously observing a complete history. The
    Phase 3 missing-index path produces exactly that shape: complete
    history False, no error, and an explicit ``index_missing`` flag the
    apply layer can use to schedule a rebuild.
    """

    state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=False,
        index_missing=True,
    )
    assert state.needs_full_history_reconcile is False
    assert state.index_missing is True
