"""Artifacts Agent pane revival request tests."""

from __future__ import annotations

from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot
from sase.ace.tui.widgets.artifacts.agents_list import AgentRow, agent_row_target
from sase.ace.tui.widgets.artifacts.agents_revival import (
    AGENTS_REVIVABLE_QUERY,
    AgentsRevivalMixin,
)
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.agents.catalog import AgentCatalogRow


class _Pane(AgentsRevivalMixin):
    def __init__(self, rows: tuple[AgentCatalogRow, ...]) -> None:
        self._snapshot = AgentsSnapshot(
            project=None,
            rows=rows,
            total_row_count=len(rows),
            truncated=False,
        )
        self._rows = {row.name: AgentRow(option_id=row.name, entry=row) for row in rows}
        self._selected: AgentRow | None = None
        self._pending_entry_target: ArtifactEntryTarget | None = None
        self._refreshes: list[ArtifactEntryTarget | None] = []
        self._loads: list[bool] = []
        self._init_agents_revival()

    def selected_row(self) -> AgentRow | None:
        return self._selected

    def select(self, row: AgentCatalogRow) -> None:
        self._selected = self._rows[row.name]

    def _current_snapshot(self) -> AgentsSnapshot | None:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        from sase.ace.tui.widgets.artifacts.agents_revival import _apply_seed_query

        return _apply_seed_query(snapshot, self._seed_query)

    def _refresh_options(
        self,
        *,
        preferred_target: ArtifactEntryTarget | None = None,
    ) -> None:
        self._refreshes.append(preferred_target)

    def _request_load(self, *, force: bool) -> None:
        self._loads.append(force)


def test_single_revivable_selected_row_revives_directly() -> None:
    dismissed = _row("dismissed", dismissed=True, revivable=True)
    pane = _Pane((dismissed,))
    pane.select(dismissed)

    request = pane.revive_request(())

    assert request.rows == (dismissed,)
    assert request.preferred_target == ArtifactEntryTarget("agents", ("dismissed",))
    assert request.seed_query is None


def test_family_row_with_many_revivable_members_seeds_narrow_query() -> None:
    family = _row("feature-family", kind=("family",), dismissed=False)
    first = _row("first", family="feature-family", dismissed=True, revivable=True)
    second = _row("second", family="feature-family", dismissed=True, revivable=True)
    pane = _Pane((family, first, second))
    pane.select(family)

    request = pane.revive_request(())

    assert request.rows == ()
    assert request.seed_query == (f"{AGENTS_REVIVABLE_QUERY} AND family:feature-family")
    assert request.severity == "information"


def test_marked_rows_revive_only_revivable_visible_targets() -> None:
    first = _row("first", dismissed=True, revivable=True)
    skipped = _row("skipped", dismissed=False, revivable=False)
    second = _row("second", dismissed=True, revivable=True)
    pane = _Pane((first, skipped, second))
    marked = {agent_row_target(pane._rows[row.name]) for row in (first, skipped)}

    request = pane.revive_request(marked)

    assert request.rows == (first,)
    assert request.skipped_count == 1


def test_seed_query_filters_revivable_dismissed_rows() -> None:
    revived = _row("revived", dismissed=False, revivable=False)
    dismissed = _row("dismissed", dismissed=True, revivable=True)
    blocked = _row("blocked", dismissed=True, revivable=False)
    pane = _Pane((revived, dismissed, blocked))

    pane.apply_seed_query(AGENTS_REVIVABLE_QUERY)

    assert pane._current_snapshot() is not None
    assert tuple(row.name for row in pane._current_snapshot().rows) == ("dismissed",)
    assert pane._refreshes == [None]
    assert pane._loads == []


def _row(
    name: str,
    *,
    kind: tuple[str, ...] = ("agent",),
    state: str | None = None,
    family: str | None = None,
    clan: str | None = None,
    dismissed: bool = False,
    revivable: bool = False,
) -> AgentCatalogRow:
    return AgentCatalogRow(
        name=name,
        canonical_global_name=name,
        kind=kind,
        project="sase",
        state=state,
        family=family,
        role=None,
        clan=clan,
        tribe=None,
        workflow=None,
        parent_timestamp=None,
        raw_suffix=f"{name}-suffix",
        artifacts_dir=f"/tmp/{name}",
        bundle_path=f"/tmp/{name}.json" if dismissed else None,
        model=None,
        llm_provider=None,
        status="DONE" if dismissed else None,
        hidden=False,
        started_at=None,
        finished_at=None,
        retry_attempt=None,
        patch=None,
        dismissed=dismissed,
        revivable=revivable,
        attention=False,
        retry=False,
        has_collision_history=False,
        from_artifact_index=not dismissed,
        from_dismissed_archive=dismissed,
    )
