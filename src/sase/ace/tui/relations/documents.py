"""Built-in plan document relation source: lifecycle chain and bead links."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    artifact_link_edges,
)
from sase.ace.tui.relations._support import decls_by_name, emit_edge
from sase.ace.tui.widgets.artifacts.bead_plan_links import BeadPlanLink
from sase.ace.tui.widgets.artifacts.plans_data_models import PlansSnapshot
from sase.bead.model import IssueType
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import (
    RelationEdge,
    RelationIndex,
    RelationSource,
    build_relation_index,
)

_BEAD_KIND: dict[IssueType, str] = {
    IssueType.PLAN: "epic",
    IssueType.PHASE: "phase",
    IssueType.TASK: "task",
}


def build_documents_relation_index(
    snapshot: PlansSnapshot,
    *,
    contract: ArtifactsPaneContract,
    artifact_links: ArtifactLinksSnapshot | None = None,
) -> RelationIndex:
    """Build the host-owned plan-document relation index for *snapshot*."""
    source = _DocumentsRelationSource(snapshot, contract)
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


class _DocumentsRelationSource(RelationSource):
    def __init__(
        self, snapshot: PlansSnapshot, contract: ArtifactsPaneContract
    ) -> None:
        self._snapshot = snapshot
        self._contract = contract
        self._decls = decls_by_name(contract)
        self._pane_id = contract.id
        self._rows_by_path = _rows_by_path(snapshot, self._pane_id)

    @property
    def pane_id(self) -> str:
        return self._pane_id

    def relations(self) -> tuple:
        return self._contract.relations

    def known_targets(self) -> frozenset[ArtifactEntryTarget]:
        return frozenset(
            target
            for stages in self._rows_by_path.values()
            for target in stages.values()
        )

    def raw_edges(self) -> tuple[RelationEdge, ...]:
        edges: list[RelationEdge] = []
        children = self._decls.get("children")
        if children is not None:
            for stages in self._rows_by_path.values():
                for earlier, later in (
                    ("proposal", "active"),
                    ("proposal", "archive"),
                    ("active", "archive"),
                ):
                    source = stages.get(earlier)
                    target = stages.get(later)
                    if source is None or target is None:
                        continue
                    edges.append(emit_edge(children, source, target))
        beads = self._decls.get("beads")
        if beads is not None:
            for link in self._snapshot.bead_plan_links.values():
                matching = self._rows_by_path.get(link.path)
                if not matching:
                    continue
                target = _bead_target(link)
                for source in matching.values():
                    edges.append(emit_edge(beads, source, target))
        return tuple(edges)


def _rows_by_path(
    snapshot: PlansSnapshot, pane_id: str
) -> dict[str, dict[str, ArtifactEntryTarget]]:
    grouped: dict[str, dict[str, ArtifactEntryTarget]] = {}
    for proposal in snapshot.proposals:
        grouped.setdefault(proposal.plan_path, {})["proposal"] = ArtifactEntryTarget(
            pane_id=pane_id,
            parts=(proposal.project, "proposal", proposal.notification.id),
        )
    for active in snapshot.active:
        grouped.setdefault(active.document.path, {})["active"] = ArtifactEntryTarget(
            pane_id=pane_id,
            parts=(active.project, "active", active.document.path),
        )
    for archive in snapshot.archive:
        path = archive.match.plan.path
        grouped.setdefault(path, {})["archive"] = ArtifactEntryTarget(
            pane_id=pane_id,
            parts=(archive.project, "archive", path),
        )
    return grouped


def _bead_target(link: BeadPlanLink) -> ArtifactEntryTarget:
    kind = _BEAD_KIND.get(link.bead_type, "task")
    return ArtifactEntryTarget(
        pane_id="beads",
        parts=(link.project, kind, link.bead_id),
    )
