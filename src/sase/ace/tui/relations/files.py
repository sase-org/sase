"""Files relation source: logical-row to version family."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    artifact_link_edges,
)
from sase.ace.tui.relations._support import decls_by_name, emit_edge
from sase.ace.tui.widgets.artifacts.files_data import FilesSnapshot
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import (
    RelationEdge,
    RelationIndex,
    RelationSource,
    build_relation_index,
)


def build_files_relation_index(
    snapshot: FilesSnapshot,
    *,
    contract: ArtifactsPaneContract,
    artifact_links: ArtifactLinksSnapshot | None = None,
) -> RelationIndex:
    """Build the host-owned Files relation index for *snapshot*."""
    source = _FilesRelationSource(snapshot, contract)
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


def _file_row_target(logical_id: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="files", parts=(logical_id,))


def _file_version_target(logical_id: str, version_id: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="files", parts=(logical_id, version_id))


class _FilesRelationSource(RelationSource):
    def __init__(
        self, snapshot: FilesSnapshot, contract: ArtifactsPaneContract
    ) -> None:
        self._snapshot = snapshot
        self._contract = contract
        self._decls = decls_by_name(contract)

    @property
    def pane_id(self) -> str:
        return self._contract.id

    def relations(self) -> tuple:
        return self._contract.relations

    def known_targets(self) -> frozenset[ArtifactEntryTarget]:
        targets: set[ArtifactEntryTarget] = set()
        for row in self._snapshot.rows:
            targets.add(_file_row_target(row.logical_id))
            for version in row.versions:
                targets.add(_file_version_target(row.logical_id, version.version_id))
        return frozenset(targets)

    def raw_edges(self) -> tuple[RelationEdge, ...]:
        decl = self._decls.get("versions")
        if decl is None:
            return ()
        edges: list[RelationEdge] = []
        for row in self._snapshot.rows:
            source = _file_row_target(row.logical_id)
            for version in row.versions:
                edges.append(
                    emit_edge(
                        decl,
                        source,
                        _file_version_target(row.logical_id, version.version_id),
                    )
                )
        return tuple(edges)
