"""Provider document relation source: declared properties plus filename family."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract, PaneRelationDecl
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    artifact_link_edges,
)
from sase.ace.tui.relations._support import decls_by_name, emit_edge
from sase.ace.tui.widgets.artifacts.plans_data_models import (
    PlansSnapshot,
    ProjectArchive,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import (
    RelationEdge,
    RelationIndex,
    RelationSource,
    build_relation_index,
)

_BUNDLE_SOURCE = "document_filename_family"


def build_provider_relation_index(
    snapshot: PlansSnapshot,
    *,
    contract: ArtifactsPaneContract,
    artifact_links: ArtifactLinksSnapshot | None = None,
) -> RelationIndex:
    """Build the host-owned provider-document relation index for *snapshot*."""
    source = _ProviderRelationSource(snapshot, contract)
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


class _ProviderRelationSource(RelationSource):
    def __init__(
        self, snapshot: PlansSnapshot, contract: ArtifactsPaneContract
    ) -> None:
        self._snapshot = snapshot
        self._contract = contract
        self._decls = decls_by_name(contract)
        self._pane_id = contract.id
        self._docs = tuple(
            _ProviderDoc.from_archive(self._pane_id, entry)
            for entry in snapshot.archive
        )

    @property
    def pane_id(self) -> str:
        return self._pane_id

    def relations(self) -> tuple:
        return self._contract.relations

    def known_targets(self) -> frozenset[ArtifactEntryTarget]:
        return frozenset(doc.target for doc in self._docs)

    def raw_edges(self) -> tuple[RelationEdge, ...]:
        edges: list[RelationEdge] = []
        for decl in self._contract.relations:
            if decl.source == _BUNDLE_SOURCE:
                edges.extend(_filename_family_edges(decl, self._docs))
                continue
            edges.extend(self._property_edges(decl))
        return tuple(edges)

    def _property_edges(self, decl: PaneRelationDecl) -> list[RelationEdge]:
        edges: list[RelationEdge] = []
        for doc in self._docs:
            value = (doc.frontmatter.get(decl.source) or "").strip()
            if not value:
                continue
            if decl.target_pane:
                target = ArtifactEntryTarget(decl.target_pane, (value,))
            else:
                resolved = _resolve_same_pane(value, self._docs)
                target = (
                    resolved
                    if resolved is not None
                    else ArtifactEntryTarget(self._pane_id, (value,))
                )
            edges.append(emit_edge(decl, doc.target, target))
        return edges


class _ProviderDoc:
    def __init__(
        self,
        *,
        target: ArtifactEntryTarget,
        path: str,
        relpath: str,
        stem: str,
        frontmatter: dict[str, str],
    ) -> None:
        self.target = target
        self.path = path
        self.relpath = relpath
        self.stem = stem
        self.frontmatter = frontmatter

    @classmethod
    def from_archive(cls, pane_id: str, entry: ProjectArchive) -> _ProviderDoc:
        plan = entry.match.plan
        relpath = plan.relpath or Path(plan.path).name
        stem = Path(relpath).stem or Path(plan.path).stem
        return cls(
            target=ArtifactEntryTarget(
                pane_id=pane_id,
                parts=(entry.project, "archive", plan.path),
            ),
            path=plan.path,
            relpath=relpath,
            stem=stem,
            frontmatter=dict(plan.frontmatter),
        )


def _resolve_same_pane(
    value: str, docs: tuple[_ProviderDoc, ...]
) -> ArtifactEntryTarget | None:
    folded = value.casefold()
    for doc in docs:
        if doc.relpath.casefold() == folded:
            return doc.target
    for doc in docs:
        if doc.path.casefold() == folded:
            return doc.target
    for doc in docs:
        if doc.stem.casefold() == folded:
            return doc.target
    return None


def _filename_family_edges(
    decl: PaneRelationDecl, docs: tuple[_ProviderDoc, ...]
) -> list[RelationEdge]:
    groups: dict[str, list[_ProviderDoc]] = defaultdict(list)
    for doc in docs:
        groups[_family_base(doc.stem)].append(doc)
    edges: list[RelationEdge] = []
    for base, members in groups.items():
        ordered = sorted(members, key=lambda item: (item.path, item.relpath))
        parents = [item for item in ordered if item.stem == base]
        children = [item for item in ordered if item.stem != base]
        if parents:
            parent = parents[0]
            for child in children:
                edges.append(emit_edge(decl, parent.target, child.target))
            continue
        for index, left in enumerate(children):
            for right in children[index + 1 :]:
                edges.append(emit_edge(decl, left.target, right.target))
    return edges


def _family_base(stem: str) -> str:
    if "__" not in stem:
        return stem
    base, suffix = stem.rsplit("__", 1)
    if base and suffix:
        return base
    return stem
