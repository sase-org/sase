"""Textual-free relation layout for Artifacts panes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from sase.ace.tui._artifact_tab_model import PaneRelationDecl, RelationKind
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import RelationEdge, RelationEdges, RelationIndex


class RelationRole(StrEnum):
    """Host-owned navigation role derived from relation declarations."""

    ANCESTOR = "ancestor"
    DESCENDANT = "descendant"
    FAMILY = "family"
    LINK = "link"


@dataclass(frozen=True, slots=True)
class RelationEntryFact:
    """Presentation facts supplied by a pane for one relation target."""

    label: str
    status: str = ""
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class RelationRow:
    """One rendered relation row."""

    key: str
    target: ArtifactEntryTarget
    label: str
    status: str
    description: str
    origin: str
    uses: int
    depth: int
    dangling: bool
    cross_pane: bool
    children: tuple[RelationRow, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationSection:
    """One declared relation section in display order."""

    relation: str
    label: str
    kind: RelationKind
    role: RelationRole
    rows: tuple[RelationRow, ...]
    hidden_count: int


@dataclass(frozen=True, slots=True)
class RelationKeymap:
    """Ordered key-to-target map for relation key modes and link actions."""

    ancestors: tuple[tuple[str, ArtifactEntryTarget], ...] = ()
    children: tuple[tuple[str, ArtifactEntryTarget], ...] = ()
    siblings: tuple[tuple[str, ArtifactEntryTarget], ...] = ()
    relation_roles: Mapping[str, RelationRole] = field(default_factory=dict)
    role_labels: Mapping[RelationRole, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.ancestors or self.children or self.siblings)

    def target_for(
        self,
        role: RelationRole,
        key: str,
    ) -> ArtifactEntryTarget | None:
        """Return the target for *role* and *key*, if present."""
        entries = self._entries_for_role(role)
        for candidate_key, target in entries:
            if candidate_key == key:
                return target
        return None

    def role_for_relation(self, relation: str) -> RelationRole | None:
        """Return the derived role for a declared relation name."""
        return self.relation_roles.get(relation)

    def label_for_role(self, role: RelationRole) -> str:
        """Return the first section label for *role*."""
        return self.role_labels.get(role, role.value)

    def _entries_for_role(
        self,
        role: RelationRole,
    ) -> tuple[tuple[str, ArtifactEntryTarget], ...]:
        if role is RelationRole.ANCESTOR:
            return self.ancestors
        if role is RelationRole.DESCENDANT:
            return self.children
        if role is RelationRole.FAMILY:
            return self.siblings
        return ()


EMPTY_RELATION_KEYMAP = RelationKeymap()


@dataclass(frozen=True, slots=True)
class RelationView:
    """Complete relation panel layout and keymap."""

    sections: tuple[RelationSection, ...]
    keymap: RelationKeymap
    roles: Mapping[str, RelationRole]

    def __bool__(self) -> bool:
        return any(section.rows or section.hidden_count for section in self.sections)


@dataclass(frozen=True, slots=True)
class RelationSummaryEntry:
    """One rail segment derived from a rendered relation section."""

    role: RelationRole
    relation: str
    label: str
    count: int
    hidden: int


@dataclass(frozen=True, slots=True)
class RelationSummary:
    """Collapsed-rail facts for a built relation view."""

    entries: tuple[RelationSummaryEntry, ...]

    def __bool__(self) -> bool:
        return bool(self.entries)

    @property
    def hidden_total(self) -> int:
        """Return the sum of per-section hidden counts."""
        return sum(entry.hidden for entry in self.entries)


def build_relation_summary(view: RelationView) -> RelationSummary:
    """Summarize visible and hidden relation rows for the collapsed rail."""
    entries: list[RelationSummaryEntry] = []
    for section in view.sections:
        if not section.rows and section.hidden_count == 0:
            continue
        entries.append(
            RelationSummaryEntry(
                role=section.role,
                relation=section.relation,
                label=section.label,
                count=_count_relation_rows(section.rows),
                hidden=section.hidden_count,
            )
        )
    return RelationSummary(entries=tuple(entries))


def _count_relation_rows(rows: tuple[RelationRow, ...]) -> int:
    return sum(1 + _count_relation_rows(row.children) for row in rows)


def assign_relation_roles(
    relations: tuple[PaneRelationDecl, ...],
) -> dict[str, RelationRole]:
    """Derive host-owned key roles from declaration order and relation kind."""
    roles: dict[str, RelationRole] = {}
    declared = {relation.name: relation for relation in relations}
    hierarchy_claimed = False
    for relation in relations:
        if relation.kind is RelationKind.HIERARCHY:
            if hierarchy_claimed:
                continue
            roles[relation.name] = RelationRole.ANCESTOR
            hierarchy_claimed = True
            inverse_name = relation.inverse
            inverse = declared.get(inverse_name or "")
            if (
                inverse_name
                and inverse is not None
                and inverse.kind is RelationKind.HIERARCHY
            ):
                roles[inverse_name] = RelationRole.DESCENDANT
            continue
        if relation.kind is RelationKind.FAMILY:
            roles[relation.name] = RelationRole.FAMILY
            continue
        if relation.kind is RelationKind.LINK:
            roles[relation.name] = RelationRole.LINK
    return roles


def build_relation_view(
    *,
    index: RelationIndex,
    origin: ArtifactEntryTarget,
    relations: tuple[PaneRelationDecl, ...],
    facts: Mapping[ArtifactEntryTarget, RelationEntryFact] | None = None,
) -> RelationView:
    """Build sections, key roles, and navigation targets for one selection.

    Typed links are an app-level concern now that the Link Rail renders them
    on every tab (``bead:sase-ug.10``): this panel only lays out the pane's
    own structure, so every ``RelationKind.LINK`` declaration is skipped.
    """
    facts = facts or {}
    roles = assign_relation_roles(relations)
    sections: list[RelationSection] = []
    ancestors: list[tuple[str, ArtifactEntryTarget]] = []
    children: list[tuple[str, ArtifactEntryTarget]] = []
    siblings: list[tuple[str, ArtifactEntryTarget]] = []
    role_labels: dict[RelationRole, str] = {}

    for decl in relations:
        if decl.kind is RelationKind.LINK:
            continue
        role = roles.get(decl.name, RelationRole.LINK)
        rows: tuple[RelationRow, ...]
        hidden_count = 0
        if decl.kind is RelationKind.HIERARCHY and role is RelationRole.ANCESTOR:
            rows, hidden_count = _build_ancestor_rows(
                index,
                origin,
                decl.name,
                facts,
            )
            ancestors.extend((row.key, row.target) for row in rows if row.key)
        elif decl.kind is RelationKind.HIERARCHY and role is RelationRole.DESCENDANT:
            counter = [0]
            rows, hidden_count = _build_descendant_rows(
                index,
                origin,
                decl.name,
                facts,
                depth=0,
                counter=counter,
            )
            children.extend(_flatten_keyed_rows(rows))
        elif decl.kind is RelationKind.FAMILY:
            rows, hidden_count = _build_family_rows(
                index,
                origin,
                decl.name,
                facts,
            )
            siblings.extend((row.key, row.target) for row in rows if row.key)
        else:
            rows = tuple(
                _row_from_edge(edge, facts=facts, key="", depth=0)
                for edge in _edges_for_relation(index, origin, decl.name)
            )
        if decl.name in roles:
            role_labels.setdefault(role, decl.label.lower())
        sections.append(
            RelationSection(
                relation=decl.name,
                label=decl.label,
                kind=decl.kind,
                role=role,
                rows=rows,
                hidden_count=hidden_count,
            )
        )

    keymap = RelationKeymap(
        ancestors=tuple(ancestors),
        children=tuple(children),
        siblings=tuple(siblings),
        relation_roles=roles,
        role_labels=role_labels,
    )
    return RelationView(sections=tuple(sections), keymap=keymap, roles=roles)


def _build_ancestor_rows(
    index: RelationIndex,
    origin: ArtifactEntryTarget,
    relation: str,
    facts: Mapping[ArtifactEntryTarget, RelationEntryFact],
) -> tuple[tuple[RelationRow, ...], int]:
    visible_edges: list[RelationEdge] = []
    hidden_count = 0
    for edge in index.chain(origin, relation):
        if _fact_for(edge.target, facts).hidden:
            hidden_count += 1
            continue
        visible_edges.append(edge)
    keys = _ancestor_keys(len(visible_edges))
    rows = tuple(
        _row_from_edge(edge, facts=facts, key=keys[index], depth=0)
        for index, edge in enumerate(visible_edges)
    )
    return rows, hidden_count


def _build_descendant_rows(
    index: RelationIndex,
    origin: ArtifactEntryTarget,
    relation: str,
    facts: Mapping[ArtifactEntryTarget, RelationEntryFact],
    *,
    depth: int,
    counter: list[int],
) -> tuple[tuple[RelationRow, ...], int]:
    child_edges = list(_edges_for_relation(index, origin, relation))
    if not child_edges:
        return (), 0

    visible_edges: list[RelationEdge] = []
    hidden_count = 0
    for edge in child_edges:
        if _fact_for(edge.target, facts).hidden:
            hidden_count += 1
            continue
        visible_edges.append(edge)
    if not visible_edges:
        return (), hidden_count

    rows: list[RelationRow] = []
    if len(visible_edges) == 1 and depth == 0:
        edge = visible_edges[0]
        if not _visible_child_edges(index, edge.target, relation, facts):
            counter[0] += 1
            return (
                (
                    _row_from_edge(
                        edge,
                        facts=facts,
                        key=">",
                        depth=depth,
                    ),
                ),
                hidden_count,
            )

    for edge in visible_edges:
        key = _descendant_key(counter[0])
        counter[0] += 1
        if key is None:
            continue
        child_rows, child_hidden = _build_descendant_rows(
            index,
            edge.target,
            relation,
            facts,
            depth=depth + 1,
            counter=counter,
        )
        hidden_count += child_hidden
        rows.append(
            _row_from_edge(
                edge,
                facts=facts,
                key=key,
                depth=depth,
                children=child_rows,
            )
        )
    return tuple(rows), hidden_count


def _visible_child_edges(
    index: RelationIndex,
    origin: ArtifactEntryTarget,
    relation: str,
    facts: Mapping[ArtifactEntryTarget, RelationEntryFact],
) -> tuple[RelationEdge, ...]:
    return tuple(
        edge
        for edge in _edges_for_relation(index, origin, relation)
        if not _fact_for(edge.target, facts).hidden
    )


def _build_family_rows(
    index: RelationIndex,
    origin: ArtifactEntryTarget,
    relation: str,
    facts: Mapping[ArtifactEntryTarget, RelationEntryFact],
) -> tuple[tuple[RelationRow, ...], int]:
    visible_edges: list[RelationEdge] = []
    hidden_count = 0
    for edge in _edges_for_relation(index, origin, relation):
        if _fact_for(edge.target, facts).hidden:
            hidden_count += 1
            continue
        visible_edges.append(edge)
    keys = _family_keys(len(visible_edges))
    rows = tuple(
        _row_from_edge(edge, facts=facts, key=keys[index], depth=0)
        for index, edge in enumerate(visible_edges)
    )
    return rows, hidden_count


def _row_from_edge(
    edge: RelationEdge,
    *,
    facts: Mapping[ArtifactEntryTarget, RelationEntryFact],
    key: str,
    depth: int,
    children: tuple[RelationRow, ...] = (),
) -> RelationRow:
    fact = _fact_for(edge.target, facts)
    return RelationRow(
        key=key,
        target=edge.target,
        label=fact.label,
        status=fact.status,
        description=edge.description,
        origin=edge.origin,
        uses=edge.uses,
        depth=depth,
        dangling=edge.dangling,
        cross_pane=edge.target.pane_id != edge.source.pane_id,
        children=children,
    )


def _edges_for_relation(
    index: RelationIndex,
    target: ArtifactEntryTarget,
    name: str,
) -> tuple[RelationEdge, ...]:
    return _matching_edges(index.edges_for(target), name)


def _matching_edges(edges: RelationEdges, name: str) -> tuple[RelationEdge, ...]:
    return tuple(
        edge
        for edge in (*edges.hierarchy, *edges.family, *edges.link)
        if edge.relation == name
    )


def _fact_for(
    target: ArtifactEntryTarget,
    facts: Mapping[ArtifactEntryTarget, RelationEntryFact],
) -> RelationEntryFact:
    fact = facts.get(target)
    if fact is not None:
        return fact
    label = target.parts[-1] if target.parts else target.pane_id
    return RelationEntryFact(label=label)


def _ancestor_keys(count: int) -> tuple[str, ...]:
    if count == 0:
        return ()
    if count == 1:
        return ("<",)
    keys = ["<<"]
    keys.extend(f"<{chr(ord('a') + index)}" for index in range(min(count - 1, 26)))
    keys.extend("" for _index in range(max(0, count - len(keys))))
    return tuple(keys)


def _descendant_key(position: int) -> str | None:
    if position == 0:
        return ">>"
    if position <= 26:
        return f">{chr(ord('a') + position - 1)}"
    return None


def _family_keys(count: int) -> tuple[str, ...]:
    if count == 0:
        return ()
    if count == 1:
        return ("~",)
    keys = ["~~"]
    keys.extend(f"~{chr(ord('a') + index)}" for index in range(min(count - 1, 26)))
    keys.extend("" for _index in range(max(0, count - len(keys))))
    return tuple(keys)


def _flatten_keyed_rows(
    rows: tuple[RelationRow, ...],
) -> tuple[tuple[str, ArtifactEntryTarget], ...]:
    pairs: list[tuple[str, ArtifactEntryTarget]] = []

    def visit(items: tuple[RelationRow, ...]) -> None:
        for row in items:
            if row.key:
                pairs.append((row.key, row.target))
            visit(row.children)

    visit(rows)
    return tuple(pairs)


__all__ = [
    "EMPTY_RELATION_KEYMAP",
    "RelationEntryFact",
    "RelationKeymap",
    "RelationRole",
    "RelationRow",
    "RelationSection",
    "RelationSummary",
    "RelationSummaryEntry",
    "RelationView",
    "assign_relation_roles",
    "build_relation_summary",
    "build_relation_view",
]
