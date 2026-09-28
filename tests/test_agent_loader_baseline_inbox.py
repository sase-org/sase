"""Baseline visible-inbox reads for the Agents-tab Tier 1 loader.

A baseline load (no viewport window) reads the whole visible inbox in one
cached index read and reports truncation honestly; viewport windows stay
bounded prefixes. Uses synthetic index snapshots, never the real home-dir
index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts
from sase.ace.tui.models.agent_loader import AgentLoadState, load_tiered_agents
from sase.core.agent_scan_wire import (
    AgentArtifactIndexWindowWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)
from sase.feature_flags import override_flags


def _snapshot(*, has_more: bool) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=1,
        projects_root="/tmp",
        options=loader_artifacts._TUI_SCAN_OPTIONS,
        stats=AgentArtifactScanStatsWire(),
        index_window=AgentArtifactIndexWindowWire(
            requested_limit=loader_artifacts._TIER1_VISIBLE_COMPLETED_LIMIT,
            selected_candidate_count=3,
            returned_record_count=3,
            completed_candidate_count=3,
            has_more=has_more,
        ),
        records=[],
    )


def test_baseline_read_uses_visible_cap_and_reports_no_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A baseline read windows by the safety cap but is never a prefix."""
    captured: dict[str, object] = {}

    def fake_query_index(index_path: Path, root: Path, **kwargs: object) -> object:
        captured.update(kwargs)
        return _snapshot(has_more=False)

    index_path = tmp_path / "index.sqlite"
    index_path.touch()
    monkeypatch.setattr(
        loader_artifacts,
        "_ARTIFACT_SNAPSHOT_CACHE",
        loader_artifacts._ArtifactSnapshotCache(max_entries=8),
    )

    _, state = loader_artifacts.query_artifact_index_for_loader(
        full_history=False,
        freshness="cached",
        requested_limit=None,
        default_index_path=lambda: index_path,
        projects_root=lambda: tmp_path,
        query_index=fake_query_index,  # type: ignore[arg-type]
        scan_artifacts=lambda options=None: (_ for _ in ()).throw(
            AssertionError("must not scan")
        ),
    ) or (None, None)
    assert state is not None

    query = captured["query"]
    assert query.window_limit == loader_artifacts._TIER1_VISIBLE_COMPLETED_LIMIT
    assert (
        query.recent_completed_limit == loader_artifacts._TIER1_VISIBLE_COMPLETED_LIMIT
    )
    assert state.bounded_prefix is False
    assert state.truncated is False
    assert state.complete_visible_inbox is True
    assert state.has_more is False
    assert state.requested_limit is None
    assert state.returned_count is None


def test_baseline_read_reports_truncation_and_arms_reconcile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capped baseline reports truncation so Tier 2 can settle it."""
    from sase.ace.tui.actions.agents._loading_apply_history import (
        should_arm_full_history_reconcile,
    )

    def fake_query_index(index_path: Path, root: Path, **kwargs: object) -> object:
        return _snapshot(has_more=True)

    index_path = tmp_path / "index.sqlite"
    index_path.touch()
    monkeypatch.setattr(
        loader_artifacts,
        "_ARTIFACT_SNAPSHOT_CACHE",
        loader_artifacts._ArtifactSnapshotCache(max_entries=8),
    )

    _, state = loader_artifacts.query_artifact_index_for_loader(
        full_history=False,
        freshness="cached",
        requested_limit=None,
        default_index_path=lambda: index_path,
        projects_root=lambda: tmp_path,
        query_index=fake_query_index,  # type: ignore[arg-type]
        scan_artifacts=lambda options=None: (_ for _ in ()).throw(
            AssertionError("must not scan")
        ),
    ) or (None, None)
    assert state is not None

    assert state.bounded_prefix is False
    assert state.truncated is True
    assert state.complete_visible_inbox is False
    assert state.has_more is False
    assert should_arm_full_history_reconcile(state) is True


def test_viewport_read_still_reports_bounded_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A viewport window keeps describing itself as a bounded prefix."""

    def fake_query_index(index_path: Path, root: Path, **kwargs: object) -> object:
        return AgentArtifactScanWire(
            schema_version=1,
            projects_root="/tmp",
            options=loader_artifacts._TUI_SCAN_OPTIONS,
            stats=AgentArtifactScanStatsWire(),
            index_window=AgentArtifactIndexWindowWire(
                requested_limit=100,
                selected_candidate_count=100,
                returned_record_count=100,
                completed_candidate_count=100,
                has_more=True,
            ),
            records=[],
        )

    index_path = tmp_path / "index.sqlite"
    index_path.touch()
    monkeypatch.setattr(
        loader_artifacts,
        "_ARTIFACT_SNAPSHOT_CACHE",
        loader_artifacts._ArtifactSnapshotCache(max_entries=8),
    )

    _, state = loader_artifacts.query_artifact_index_for_loader(
        full_history=False,
        freshness="cached",
        requested_limit=100,
        default_index_path=lambda: index_path,
        projects_root=lambda: tmp_path,
        query_index=fake_query_index,  # type: ignore[arg-type]
        scan_artifacts=lambda options=None: (_ for _ in ()).throw(
            AssertionError("must not scan")
        ),
    ) or (None, None)
    assert state is not None

    assert state.bounded_prefix is True
    assert state.has_more is True
    assert state.requested_limit == 100
    assert state.truncated is False


def _pushdown_miss_states(
    monkeypatch: pytest.MonkeyPatch,
    state: AgentLoadState,
) -> AgentLoadState:
    from types import SimpleNamespace

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            agents=[],
            workflow_agent_steps=[],
            state=state,
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )
    with override_flags(agents_unified_query=False):
        _, out = load_tiered_agents(search_query="(((", requested_limit=None)
    return out


def _tier1_index_state(**overrides: object) -> AgentLoadState:
    kwargs: dict[str, object] = {
        "tier": "tier1",
        "complete_history": False,
        "artifact_source": "artifact_index",
        "used_artifact_index": True,
    }
    kwargs.update(overrides)
    return AgentLoadState(**kwargs)  # type: ignore[arg-type]


def test_pushdown_miss_not_incomplete_on_whole_inbox_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-truncated baseline saw the whole inbox: not query-incomplete."""
    out = _pushdown_miss_states(
        monkeypatch,
        _tier1_index_state(
            bounded_prefix=False,
            truncated=False,
            complete_visible_inbox=True,
        ),
    )
    assert out.query_incomplete is False


def test_pushdown_miss_incomplete_on_truncated_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truncated baseline only saw recent history: still query-incomplete."""
    out = _pushdown_miss_states(
        monkeypatch,
        _tier1_index_state(
            bounded_prefix=False,
            truncated=True,
            complete_visible_inbox=False,
        ),
    )
    assert out.query_incomplete is True


def test_pushdown_miss_incomplete_on_viewport_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A viewport-bounded read only saw recent history: query-incomplete."""
    out = _pushdown_miss_states(
        monkeypatch,
        _tier1_index_state(
            bounded_prefix=True,
            requested_limit=100,
            returned_count=100,
            has_more=True,
        ),
    )
    assert out.query_incomplete is True


def test_visible_cap_is_safety_valve_not_working_set() -> None:
    """The safety valve dwarfs the old 200-row working-set cap."""
    assert (
        loader_artifacts._TIER1_VISIBLE_COMPLETED_LIMIT
        >= 6 * loader_artifacts._TIER1_RECENT_COMPLETED_LIMIT
    )
