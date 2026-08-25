"""Agents relation source: family, clan, retry chain, and workflow parent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract, PaneRelationDecl
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    artifact_link_edges,
)
from sase.ace.tui.relations._support import decls_by_name, emit_edge
from sase.agents.catalog import AgentCatalogRow
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import (
    RelationEdge,
    RelationIndex,
    RelationSource,
    build_relation_index,
)

if TYPE_CHECKING:
    # Deferred: ``widgets.artifacts.agents_data`` imports ``relations.artifact_links``
    # at module scope, so an eager import here would cycle back into this
    # package before it finishes initializing.
    from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot

AGENTS_PANE_ID = "agents"


def build_agents_relation_index(
    snapshot: AgentsSnapshot,
    *,
    contract: ArtifactsPaneContract,
    artifact_links: ArtifactLinksSnapshot | None = None,
) -> RelationIndex:
    """Build the host-owned Agents relation index for *snapshot*."""
    source = _AgentsRelationSource(snapshot, contract)
    known = source.known_targets()
    return build_relation_index(
        pane_id=source.pane_id,
        relations=source.relations(),
        edges=(
            *source.raw_edges(),
            *artifact_link_edges(
                artifact_links or snapshot.artifact_links,
                contract=contract,
                known_targets=known,
                project_hint=snapshot.project,
            ),
        ),
        known_targets=known,
    )


def _agent_target(name: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id=AGENTS_PANE_ID, parts=(name,))


class _AgentsRelationSource(RelationSource):
    def __init__(
        self, snapshot: AgentsSnapshot, contract: ArtifactsPaneContract
    ) -> None:
        self._snapshot = snapshot
        self._contract = contract
        self._decls = decls_by_name(contract)
        self._rows = snapshot.rows
        self._by_name: dict[str, AgentCatalogRow] = {
            row.name: row for row in self._rows
        }
        self._by_raw_suffix: dict[str, AgentCatalogRow] = {
            row.raw_suffix: row for row in self._rows if row.raw_suffix
        }

    @property
    def pane_id(self) -> str:
        return self._contract.id

    def relations(self) -> tuple:
        return self._contract.relations

    def known_targets(self) -> frozenset[ArtifactEntryTarget]:
        return frozenset(_agent_target(row.name) for row in self._rows)

    def raw_edges(self) -> tuple[RelationEdge, ...]:
        edges: list[RelationEdge] = []
        family_decl = self._decls.get("family")
        clan_decl = self._decls.get("clan")
        parent_decl = self._decls.get("parent")
        retry_decl = self._decls.get("retry_chain")

        for row in self._rows:
            source = _agent_target(row.name)
            if family_decl is not None and row.family:
                container = self._by_name.get(row.family)
                if container is not None and container.name != row.name:
                    edges.append(
                        emit_edge(family_decl, source, _agent_target(container.name))
                    )
            if clan_decl is not None and row.clan:
                container = self._by_name.get(row.clan)
                if container is not None and container.name != row.name:
                    edges.append(
                        emit_edge(clan_decl, source, _agent_target(container.name))
                    )
            if parent_decl is not None and row.parent_timestamp:
                parent = self._by_raw_suffix.get(row.parent_timestamp)
                if parent is not None and parent.name != row.name:
                    edges.append(
                        emit_edge(parent_decl, source, _agent_target(parent.name))
                    )

        if retry_decl is not None:
            edges.extend(self._retry_chain_edges(retry_decl))

        return tuple(edges)

    def _retry_chain_edges(
        self, retry_decl: PaneRelationDecl
    ) -> tuple[RelationEdge, ...]:
        """Emit one undirected edge per pair of rows sharing a retry chain.

        The chain identity is the root's ``raw_suffix``: every non-root
        attempt carries it directly as ``retry_chain_root_timestamp``, and a
        root attempt (the one nothing points at as a predecessor) is
        identified by its own ``raw_suffix`` once it is known to participate
        (it carries a forward pointer, ``retried_as_timestamp``, or is
        pointed at by another row's ``retry_of_timestamp``).
        """
        chain_by_row: dict[str, str] = {}
        for row in self._rows:
            if row.retry_chain_root_timestamp:
                chain_by_row[row.name] = row.retry_chain_root_timestamp
        for row in self._rows:
            if row.name in chain_by_row or not row.raw_suffix:
                continue
            participates = bool(row.retried_as_timestamp) or any(
                other.retry_of_timestamp == row.raw_suffix for other in self._rows
            )
            if participates:
                chain_by_row[row.name] = row.raw_suffix

        members_by_chain: dict[str, list[str]] = {}
        for name, chain in chain_by_row.items():
            members_by_chain.setdefault(chain, []).append(name)

        edges: list[RelationEdge] = []
        for members in members_by_chain.values():
            if len(members) < 2:
                continue
            for index, name in enumerate(members):
                for other in members[index + 1 :]:
                    edges.append(
                        emit_edge(retry_decl, _agent_target(name), _agent_target(other))
                    )
        return tuple(edges)


__all__ = ["AGENTS_PANE_ID", "build_agents_relation_index"]
