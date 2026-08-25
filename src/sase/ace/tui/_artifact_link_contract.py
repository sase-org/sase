"""Shared Artifacts contract declarations for the artifact link graph."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.sdd.artifact_link_store import assembled_artifact_relations

from ._artifact_tab_model import PaneRelationDecl, RelationKind

ARTIFACT_LINK_SOURCE = "artifact_links"


def with_artifact_link_relations(
    relations: tuple[PaneRelationDecl, ...],
) -> tuple[PaneRelationDecl, ...]:
    """Append typed artifact-link relation declarations when absent."""

    names = {item.name for item in relations}
    extras = tuple(item for item in ARTIFACT_LINK_RELATIONS if item.name not in names)
    return (*relations, *extras)


def _artifact_link_relation_declarations() -> tuple[PaneRelationDecl, ...]:
    """Return pane relation declarations backed by the closed relation registry."""

    declarations: list[PaneRelationDecl] = []
    seen: set[str] = set()
    for relation in assembled_artifact_relations():
        declarations.extend(_declarations_for_relation(relation, seen))
    return tuple(declarations)


def _declarations_for_relation(
    relation: Mapping[str, Any],
    seen: set[str],
) -> tuple[PaneRelationDecl, ...]:
    slug = str(relation.get("slug") or "").strip()
    if not slug:
        return ()
    inverse = str(relation.get("inverse") or "").strip() or None
    directed = bool(relation.get("directed"))
    declarations: list[PaneRelationDecl] = []
    primary = _declaration(
        slug,
        label=slug,
        inverse=inverse,
        directed=directed,
        seen=seen,
    )
    if primary is not None:
        declarations.append(primary)
    if inverse and inverse != slug:
        inverse_decl = _declaration(
            inverse,
            label=inverse,
            inverse=slug,
            directed=directed,
            seen=seen,
        )
        if inverse_decl is not None:
            declarations.append(inverse_decl)
    return tuple(declarations)


def _declaration(
    name: str,
    *,
    label: str,
    inverse: str | None,
    directed: bool,
    seen: set[str],
) -> PaneRelationDecl | None:
    if name in seen:
        return None
    seen.add(name)
    return PaneRelationDecl(
        name=name,
        kind=RelationKind.LINK,
        label=label,
        source=ARTIFACT_LINK_SOURCE,
        target_pane=None,
        inverse=inverse,
        directed=directed,
        transitive=False,
    )


ARTIFACT_LINK_RELATIONS: tuple[PaneRelationDecl, ...] = (
    _artifact_link_relation_declarations()
)


__all__ = [
    "ARTIFACT_LINK_RELATIONS",
    "ARTIFACT_LINK_SOURCE",
    "with_artifact_link_relations",
]
