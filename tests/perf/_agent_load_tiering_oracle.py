"""Compare loader-visible rows across the source, index and production paths."""

from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Any

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts
from sase.ace.tui.models.agent_live_query_engine import apply_agents_live_query_filter
from sase.ace.tui.models.agent_live_query_pushdown import (
    compile_agents_live_query_pushdown,
)
from sase.ace.tui.models.agent_loader import load_tiered_agents
from sase.core.agent_scan_facade import query_agent_artifact_index, scan_agent_artifacts
from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire

from tests.perf._agent_load_tiering_rows import (
    _agents_from_snapshot,
    _diff_load_path,
    _nonzero_stats,
    _row_key,
    _temporary_sase_home,
    _tui_visible_agents,
    _visible_rows,
)
from tests.perf._agent_load_tiering_types import (
    AgentLoadTieringOracleResult,
    LoadPathDiff,
    LoadPathName,
    LoadPathRows,
)
from tests.perf.agent_load_tiering_fixture import SyntheticArchiveFixture

_ACTIVE_LIMIT = loader_artifacts._TIER1_ACTIVE_LIMIT
_RECENT_COMPLETED_LIMIT = loader_artifacts._TIER1_RECENT_COMPLETED_LIMIT
_TUI_SCAN_OPTIONS = loader_artifacts._TUI_SCAN_OPTIONS


class AgentLoadTieringOracle:
    """Compare loader-visible rows across the source, index and production paths.

    ``index_bounded``/``index_full_history`` call the query facade directly
    with a harness-chosen ``freshness``, which is useful for isolating the
    index contract but is not what the TUI actually does in production (it
    forces ``revalidate`` for full-history loads and derives freshness/
    candidate filters from its own query-pushdown compilation). The
    ``production_*`` paths call :func:`load_tiered_agents`, the real TUI
    entry point, so they are the primary paths later acceptance phases
    should hold to a zero-diff bar.
    """

    def __init__(self, fixture: SyntheticArchiveFixture) -> None:
        self.fixture = fixture

    def evaluate(
        self,
        query: str,
        *,
        requested_limit: int | None = None,
        candidate_filter_override: Mapping[str, object] | None = None,
    ) -> AgentLoadTieringOracleResult:
        pushdown = compile_agents_live_query_pushdown(query)
        if candidate_filter_override is not None:
            candidate_filter = dict(candidate_filter_override)
        else:
            candidate_filter = (
                pushdown.candidate_filter if pushdown.window_safe else None
            )

        source_scan = self._load_source_scan(query)
        index_bounded = self._load_index_bounded(
            query,
            requested_limit=requested_limit,
            candidate_filter=candidate_filter,
        )
        index_full_history = self._load_index_full_history(
            query,
            candidate_filter=candidate_filter,
        )
        # Unlike the two raw paths above, these never take a
        # ``candidate_filter_override``: production always derives its own
        # candidate filter from ``query``, which is the point of routing
        # through the real entry point instead of re-implementing it here.
        production_bounded = self._load_production_bounded(
            query,
            requested_limit=requested_limit,
        )
        production_full_history = self._load_production_full_history(query)
        diffs: dict[LoadPathName, LoadPathDiff] = {
            "index_bounded": _diff_load_path(source_scan, index_bounded),
            "index_full_history": _diff_load_path(source_scan, index_full_history),
            "production_bounded": _diff_load_path(source_scan, production_bounded),
            "production_full_history": _diff_load_path(
                source_scan, production_full_history
            ),
        }
        return AgentLoadTieringOracleResult(
            query=query,
            pushdown_window_safe=pushdown.window_safe,
            pushdown_unsupported_reason=pushdown.unsupported_reason,
            source_scan=source_scan,
            index_bounded=index_bounded,
            index_full_history=index_full_history,
            production_bounded=production_bounded,
            production_full_history=production_full_history,
            diffs=diffs,
        )

    def _load_source_scan(self, query: str) -> LoadPathRows:
        return self._measure(
            "source_scan",
            query,
            lambda: scan_agent_artifacts(self.fixture.projects_root, _TUI_SCAN_OPTIONS),
        )

    def _load_index_bounded(
        self,
        query: str,
        *,
        requested_limit: int | None,
        candidate_filter: Mapping[str, object] | None,
    ) -> LoadPathRows:
        wire = AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=True,
            include_full_history=False,
            active_limit=_ACTIVE_LIMIT,
            recent_completed_limit=_RECENT_COMPLETED_LIMIT,
            include_hidden=False,
            freshness="cached",
            record_shape="list",
            window_limit=requested_limit,
            candidate_filter=dict(candidate_filter) if candidate_filter else None,
        )
        return self._measure(
            "index_bounded",
            query,
            lambda: query_agent_artifact_index(
                self.fixture.index_path,
                self.fixture.projects_root,
                wire,
                _TUI_SCAN_OPTIONS,
            ),
        )

    def _load_index_full_history(
        self,
        query: str,
        *,
        candidate_filter: Mapping[str, object] | None,
    ) -> LoadPathRows:
        wire = AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            include_full_history=True,
            active_limit=None,
            recent_completed_limit=None,
            include_hidden=False,
            freshness="cached",
            record_shape="list",
            candidate_filter=dict(candidate_filter) if candidate_filter else None,
        )
        return self._measure(
            "index_full_history",
            query,
            lambda: query_agent_artifact_index(
                self.fixture.index_path,
                self.fixture.projects_root,
                wire,
                _TUI_SCAN_OPTIONS,
            ),
        )

    def _load_production_bounded(
        self,
        query: str,
        *,
        requested_limit: int | None,
    ) -> LoadPathRows:
        return self._measure_production(
            "production_bounded",
            query,
            full_history=False,
            requested_limit=requested_limit,
        )

    def _load_production_full_history(self, query: str) -> LoadPathRows:
        return self._measure_production(
            "production_full_history",
            query,
            full_history=True,
            requested_limit=None,
        )

    def _measure_production(
        self,
        name: LoadPathName,
        query: str,
        *,
        full_history: bool,
        requested_limit: int | None,
    ) -> LoadPathRows:
        """Load through :func:`load_tiered_agents`, the real TUI entry point.

        ``load_tiered_agents`` already applies the committed query's final
        tree-aware semantics for a bounded (Tier 1) load, but a full-history
        load intentionally skips that step (the TUI's finalize pipeline
        applies it separately once the load settles). Re-apply the same
        ``apply_agents_live_query_filter`` finalize step here so the two
        production paths are comparable.
        """
        with _temporary_sase_home(self.fixture.sase_home):
            start = time.perf_counter()
            agents, state = load_tiered_agents(
                full_history=full_history,
                search_query=query,
                requested_limit=requested_limit,
            )
            agents = _tui_visible_agents(agents)
            if full_history:
                filtered, _facade, error = apply_agents_live_query_filter(query, agents)
            else:
                filtered, error = agents, None
            visible_rows = _visible_rows(filtered)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
        return LoadPathRows(
            name=name,
            snapshot_record_count=state.record_count or 0,
            loaded_row_count=len(filtered),
            visible_rows=visible_rows,
            loaded_keys=frozenset(_row_key(agent) for agent in filtered),
            query_error=error,
            elapsed_ms=elapsed_ms,
            load_state=state,
        )

    def _measure(
        self,
        name: LoadPathName,
        query: str,
        load_snapshot: Any,
    ) -> LoadPathRows:
        with _temporary_sase_home(self.fixture.sase_home):
            start = time.perf_counter()
            snapshot = load_snapshot()
            agents = _tui_visible_agents(_agents_from_snapshot(snapshot))
            filtered, _facade, error = apply_agents_live_query_filter(query, agents)
            visible_rows = _visible_rows(filtered)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
        return LoadPathRows(
            name=name,
            snapshot_record_count=len(snapshot.records),
            loaded_row_count=len(agents),
            visible_rows=visible_rows,
            loaded_keys=frozenset(_row_key(agent) for agent in agents),
            query_error=error,
            elapsed_ms=elapsed_ms,
            scan_stats=_nonzero_stats(snapshot.stats),
        )
