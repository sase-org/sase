"""Beads relation source: parent, dependencies, and plan links."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract
from sase.ace.tui.relations._support import decls_by_name, emit_edge
from sase.ace.tui.widgets.artifacts.beads_data_models import BeadsSnapshot, ProjectBead
from sase.bead.model import IssueType, Status
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import (
    RelationEdge,
    RelationIndex,
    RelationSource,
    build_relation_index,
)

_KIND: dict[IssueType, str] = {
    IssueType.TASK: "task",
    IssueType.PLAN: "epic",
    IssueType.PHASE: "phase",
    IssueType.FLAG: "flag",
}


def build_beads_relation_index(
    snapshot: BeadsSnapshot,
    *,
    contract: ArtifactsPaneContract,
) -> RelationIndex:
    """Build the host-owned Beads relation index for *snapshot*."""
    source = _BeadsRelationSource(snapshot, contract)
    return build_relation_index(
        pane_id=source.pane_id,
        relations=source.relations(),
        edges=source.raw_edges(),
        known_targets=source.known_targets(),
    )


def _bead_target(project: str, kind: str, bead_id: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="beads", parts=(project, kind, bead_id))


def _kind_for(issue_type: IssueType) -> str:
    return _KIND.get(issue_type, "task")


class _BeadsRelationSource(RelationSource):
    def __init__(
        self, snapshot: BeadsSnapshot, contract: ArtifactsPaneContract
    ) -> None:
        self._snapshot = snapshot
        self._contract = contract
        self._decls = decls_by_name(contract)
        self._beads = _all_beads(snapshot)
        self._by_id = {
            (item.project, item.issue.id): _bead_target(
                item.project, _kind_for(item.issue.issue_type), item.issue.id
            )
            for item in self._beads
        }

    @property
    def pane_id(self) -> str:
        return self._contract.id

    def relations(self) -> tuple:
        return self._contract.relations

    def known_targets(self) -> frozenset[ArtifactEntryTarget]:
        return frozenset(self._by_id.values())

    def raw_edges(self) -> tuple[RelationEdge, ...]:
        edges: list[RelationEdge] = []
        parent_decl = self._decls.get("parent")
        deps_decl = self._decls.get("dependencies")
        plans_decl = self._decls.get("plans")
        for item in self._beads:
            source = self._by_id[(item.project, item.issue.id)]
            if parent_decl is not None and item.issue.parent_id:
                edges.append(
                    emit_edge(
                        parent_decl,
                        source,
                        self._lookup(item.project, item.issue.parent_id),
                    )
                )
            if deps_decl is not None:
                for dep in item.issue.dependencies:
                    if not dep.depends_on_id:
                        continue
                    edges.append(
                        emit_edge(
                            deps_decl,
                            source,
                            self._lookup(item.project, dep.depends_on_id),
                        )
                    )
            if plans_decl is None:
                continue
            path = self._snapshot.plan_links.get((item.project, item.issue.id))
            if not path:
                continue
            stage = "archive" if item.issue.status is Status.CLOSED else "active"
            edges.append(
                emit_edge(
                    plans_decl,
                    source,
                    ArtifactEntryTarget(
                        pane_id="ref:plan",
                        parts=(item.project, stage, path),
                    ),
                )
            )
        return tuple(edges)

    def _lookup(self, project: str, bead_id: str) -> ArtifactEntryTarget:
        found = self._by_id.get((project, bead_id))
        if found is not None:
            return found
        return _bead_target(project, "epic", bead_id)


def _all_beads(snapshot: BeadsSnapshot) -> tuple[ProjectBead, ...]:
    beads: list[ProjectBead] = []
    beads.extend(snapshot.epics)
    beads.extend(snapshot.flags)
    for key in sorted(snapshot.phases_by_epic):
        beads.extend(snapshot.phases_by_epic[key])
    beads.extend(snapshot.tasks)
    return tuple(beads)
