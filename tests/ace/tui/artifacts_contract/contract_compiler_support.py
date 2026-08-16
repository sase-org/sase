"""Shared builders for artifact contract compiler tests."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_model import (
    PaneCapability,
    PaneDeclaredFacts,
)
from sase.ace.tui._artifact_tab_contract_rules import derive_capability_verdicts


def facts(**overrides: object) -> PaneDeclaredFacts:
    values: dict[str, object] = {
        "source": "provider",
        "adapter": None,
        "is_degraded": False,
        "has_inventory": True,
        "has_fields": True,
        "has_stable_identity": True,
        "has_revisions": False,
        "can_mutate": False,
        "is_plan_adapter": False,
        "project_scoped": True,
        "has_detail": True,
        "suppressions": {},
    }
    values.update(overrides)
    return PaneDeclaredFacts(**values)  # type: ignore[arg-type]


def enabled(facts: PaneDeclaredFacts) -> set[PaneCapability]:
    return {
        verdict.capability
        for verdict in derive_capability_verdicts(facts)
        if verdict.enabled
    }


def verdict(facts: PaneDeclaredFacts, capability: PaneCapability):
    return next(
        item
        for item in derive_capability_verdicts(facts)
        if item.capability == capability
    )


def document_spec(
    *,
    kind: str = "notes",
    properties: dict[str, object] | None = None,
    identity: dict[str, object] | None = None,
    inventory: dict[str, object] | None = None,
    capabilities: dict[str, object] | None = None,
    relations: list[object] | None = None,
    grouping: dict[str, object] | None = None,
    pane: dict[str, object] | None = None,
) -> dict[str, object]:
    ref: dict[str, object] = {
        "kind": kind,
        "icon": "¶",
        "expansion_format": "@{checkout_path}",
        "properties": properties
        if properties is not None
        else {
            "title": {"type": "string", "source": "markdown_frontmatter"},
            "status": {"type": "string", "source": "markdown_frontmatter"},
        },
        "detail": {"fields": ["title", "status"]},
        "identity": {} if identity is None else identity,
        "inventory": {"globs": ["**/*.md"]} if inventory is None else inventory,
        "publication": {
            "link": "vcs_permalink",
            "referenced_by": "markdown_table",
        },
    }
    if capabilities is not None:
        ref["capabilities"] = capabilities
    if relations is not None:
        ref["relations"] = relations
    if grouping is not None:
        ref["grouping"] = grouping
    if pane is not None:
        ref["pane"] = pane
    return {
        "schema_version": 1,
        "provider": kind,
        "ref": ref,
    }
