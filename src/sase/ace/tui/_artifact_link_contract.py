"""Shared Artifacts contract declarations for the artifact link graph."""

from __future__ import annotations

from ._artifact_tab_model import PaneRelationDecl, RelationKind

ARTIFACT_LINK_SOURCE = "artifact_links"

ARTIFACT_LINK_RELATIONS: tuple[PaneRelationDecl, ...] = (
    PaneRelationDecl(
        name="links",
        kind=RelationKind.LINK,
        label="Links",
        source=ARTIFACT_LINK_SOURCE,
        target_pane=None,
        inverse="linked_by",
        directed=True,
        transitive=False,
    ),
    PaneRelationDecl(
        name="linked_by",
        kind=RelationKind.LINK,
        label="Linked By",
        source=ARTIFACT_LINK_SOURCE,
        target_pane=None,
        inverse="links",
        directed=True,
        transitive=False,
    ),
)


def with_artifact_link_relations(
    relations: tuple[PaneRelationDecl, ...],
) -> tuple[PaneRelationDecl, ...]:
    """Append the common links/linked_by declarations when absent."""

    names = {item.name for item in relations}
    extras = tuple(item for item in ARTIFACT_LINK_RELATIONS if item.name not in names)
    return (*relations, *extras)


__all__ = [
    "ARTIFACT_LINK_RELATIONS",
    "ARTIFACT_LINK_SOURCE",
    "with_artifact_link_relations",
]
