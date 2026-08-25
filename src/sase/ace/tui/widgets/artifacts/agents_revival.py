"""Revive selection helpers for the Artifacts Agent pane."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.agents.catalog import AgentCatalogRow

from .agents_data import AgentsSnapshot
from .agents_list import AgentRow, agent_row_target
from .entry_navigation import ArtifactEntryTarget

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object

AGENTS_REVIVABLE_QUERY = "state:dismissed AND revivable:true"


@dataclass(frozen=True, slots=True)
class AgentsRevivalRequest:
    """Pane-resolved request for an app-level revive action."""

    rows: tuple[AgentCatalogRow, ...] = ()
    preferred_target: ArtifactEntryTarget | None = None
    seed_query: str | None = None
    message: str | None = None
    severity: str = "warning"
    skipped_count: int = 0


class AgentsRevivalMixin(_MixinBase):
    """Resolve selected/marked catalog rows for the shared revive executor."""

    _rows: dict[str, AgentRow]
    _option_id_by_target: dict[ArtifactEntryTarget, str]
    _pending_entry_target: ArtifactEntryTarget | None
    _seed_query: str | None

    if TYPE_CHECKING:

        def selected_row(self) -> AgentRow | None: ...

        def _refresh_options(
            self,
            *,
            preferred_target: ArtifactEntryTarget | None = None,
        ) -> None: ...

        def _request_load(self, *, force: bool, full: bool = False) -> None: ...

    def _init_agents_revival(self) -> None:
        self._seed_query = None

    def revive_request(
        self,
        marked_targets: Iterable[ArtifactEntryTarget],
    ) -> AgentsRevivalRequest:
        """Return rows to revive, or a query seed for an expandable selection."""

        marked = tuple(marked_targets)
        if marked:
            rows, skipped = self._revivable_marked_rows(marked)
            if rows:
                return AgentsRevivalRequest(
                    rows=rows,
                    preferred_target=ArtifactEntryTarget(
                        "agents",
                        (rows[0].name,),
                    ),
                    skipped_count=skipped,
                )
            return AgentsRevivalRequest(message="No marked agents are revivable")

        row = self.selected_row()
        if row is None:
            return AgentsRevivalRequest(message="No agent selected")
        entry = row.entry
        if entry.revivable:
            return AgentsRevivalRequest(
                rows=(entry,),
                preferred_target=agent_row_target(row),
            )

        related = self._related_revivable_rows(entry)
        if len(related) == 1:
            return AgentsRevivalRequest(
                rows=related,
                preferred_target=ArtifactEntryTarget("agents", (related[0].name,)),
            )
        if len(related) > 1:
            query = _revivable_family_query(entry)
            return AgentsRevivalRequest(
                seed_query=query,
                message=(
                    f"Narrowed Agent pane to {len(related)} revivable "
                    f"{entry.name} member(s)"
                ),
                severity="information",
            )
        return AgentsRevivalRequest(message=f"{entry.name} is not revivable")

    def apply_seed_query(
        self,
        query: str,
        *,
        preferred_target: ArtifactEntryTarget | None = None,
    ) -> None:
        """Apply a query seed from revival flows.

        The query phase owns the full Rust-backed filter session. Until that
        phase is present, this method handles the exact revive seeds emitted
        by this pane and leaves every other query as an unfiltered reload.
        """

        self._seed_query = query
        self._pending_entry_target = preferred_target
        self._refresh_options(preferred_target=preferred_target)
        if self._current_snapshot() is None:
            self._request_load(force=False)

    def consume_revive_delta(
        self,
        delta: object,
        *,
        preferred_target: ArtifactEntryTarget | None,
    ) -> None:
        """Refresh the snapshot and select the row that initiated revival."""

        if not getattr(delta, "has_changes", False):
            return
        self._seed_query = None
        if preferred_target is not None:
            self._pending_entry_target = preferred_target
        self._request_load(force=True)

    def _revivable_marked_rows(
        self,
        marked_targets: Iterable[ArtifactEntryTarget],
    ) -> tuple[tuple[AgentCatalogRow, ...], int]:
        marked = set(marked_targets)
        rows: list[AgentCatalogRow] = []
        skipped = 0
        for row in self._rows.values():
            if agent_row_target(row) not in marked:
                continue
            if row.entry.revivable:
                rows.append(row.entry)
            else:
                skipped += 1
        return tuple(rows), skipped

    def _related_revivable_rows(
        self,
        entry: AgentCatalogRow,
    ) -> tuple[AgentCatalogRow, ...]:
        snapshot = self._current_snapshot()
        if snapshot is None:
            return ()
        if "family" in entry.kind:
            return tuple(
                row
                for row in snapshot.rows
                if row.revivable and row.family == entry.name
            )
        if "clan" in entry.kind:
            return tuple(
                row for row in snapshot.rows if row.revivable and row.clan == entry.name
            )
        return ()

    def _current_snapshot(self) -> AgentsSnapshot | None:
        snapshot = super()._current_snapshot()  # type: ignore[misc]
        if snapshot is None:
            return None
        return _apply_seed_query(snapshot, self._seed_query)


def _apply_seed_query(
    snapshot: AgentsSnapshot,
    query: str | None,
) -> AgentsSnapshot:
    if not query:
        return snapshot
    terms = _parse_seed_query(query)
    if terms is None:
        return snapshot
    rows = tuple(row for row in snapshot.rows if _row_matches_terms(row, terms))
    return AgentsSnapshot(
        project=snapshot.project,
        rows=rows,
        total_row_count=len(rows),
        complete=snapshot.complete,
        truncated=False,
        artifact_links=snapshot.artifact_links,
        facets=snapshot.facets,
    )


def _parse_seed_query(query: str) -> Mapping[str, str] | None:
    parts = [part.strip() for part in query.split(" AND ")]
    if not parts:
        return None
    terms: dict[str, str] = {}
    for part in parts:
        if ":" not in part:
            return None
        key, value = part.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key not in {"state", "revivable", "family", "clan"}:
            return None
        terms[key] = value
    return terms


def _row_matches_terms(row: AgentCatalogRow, terms: Mapping[str, str]) -> bool:
    for key, value in terms.items():
        if key == "revivable":
            expected = value.casefold() == "true"
            if row.revivable is not expected:
                return False
            continue
        if key == "state":
            if value == "dismissed":
                if not row.dismissed:
                    return False
                continue
            if row.state != value:
                return False
            continue
        row_value = getattr(row, key)
        if row_value != value:
            return False
    return True


def _revivable_family_query(entry: AgentCatalogRow) -> str:
    if "family" in entry.kind:
        return f"{AGENTS_REVIVABLE_QUERY} AND family:{entry.name}"
    if "clan" in entry.kind:
        return f"{AGENTS_REVIVABLE_QUERY} AND clan:{entry.name}"
    return AGENTS_REVIVABLE_QUERY


__all__ = [
    "AGENTS_REVIVABLE_QUERY",
    "AgentsRevivalMixin",
    "AgentsRevivalRequest",
]
