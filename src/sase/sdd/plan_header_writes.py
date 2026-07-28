"""Shared write-point helpers for plan provenance header sections."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
    remove_plan_header_section,
    upsert_plan_header_section,
)

if TYPE_CHECKING:
    from sase.sdd.associations import PlanAssociations
    from sase.sdd.store import SddStore

_LEGACY_PLAN_MARKERS = (
    ".sase/sdd/plans/",
    "sase/repos/plans/",
    "sdd/plans/",
    "plans/",
)


def upsert_parent_plan_section(
    document: str,
    parent_ref: str,
    *,
    source_path: Path | None = None,
    plans_root: Path | None = None,
    store: SddStore | None = None,
    primary_root: Path | None = None,
) -> str:
    """Seed or refresh one ``PARENT`` section from a durable plan reference."""

    label, canonical_ref = _parent_reference(parent_ref, store)
    target = _hosted_parent_target(
        canonical_ref,
        store=store,
        primary_root=primary_root,
    )
    if target is None:
        target = _relative_parent_target(
            parent_ref,
            label,
            source_path=source_path,
            plans_root=plans_root,
        )
    return upsert_plan_header_section(
        document,
        PlanHeaderSection(
            kind=PlanHeaderSectionKind.PARENT,
            label=label,
            target=target,
        ),
    )


def refresh_existing_parent_section(
    document: str,
    *,
    source_path: Path,
    plans_root: Path,
    store: SddStore | None = None,
    primary_root: Path | None = None,
) -> str:
    """Rebase an already-seeded parent link for its canonical destination."""

    parsed = parse_plan_header_block(document)
    parent = next(
        (
            section
            for section in parsed.sections
            if section.kind is PlanHeaderSectionKind.PARENT
        ),
        None,
    )
    if parent is None or parent.label is None:
        return document
    return upsert_parent_plan_section(
        document,
        parent.label,
        source_path=source_path,
        plans_root=plans_root,
        store=store,
        primary_root=primary_root,
    )


def refresh_bead_plan_section(
    document: str,
    *,
    store: SddStore | None = None,
    primary_root: Path | None = None,
    known_bead_ids: frozenset[str] | None = None,
) -> str:
    """Rebuild ``BEAD`` from the plan's durable bead frontmatter.

    Pass *known_bead_ids* to reuse one bead-store read when refreshing a whole
    tree of plans.
    """

    from sase.sdd.plan_tiers import parse_plan_frontmatter

    frontmatter, parse_error = parse_plan_frontmatter(document)
    if parse_error is not None:
        raise ValueError(parse_error)
    raw_bead = frontmatter.get("bead_id")
    if raw_bead in (None, ""):
        raw_bead = frontmatter.get("bead")
    if raw_bead in (None, ""):
        parsed = parse_plan_header_block(document)
        if not any(
            section.kind is PlanHeaderSectionKind.BEAD for section in parsed.sections
        ):
            return document
        return remove_plan_header_section(
            document,
            PlanHeaderSectionKind.BEAD,
            remove_legacy=False,
        )
    if not isinstance(raw_bead, str) or not raw_bead.strip():
        raise ValueError("plan bead frontmatter must be a non-empty string")

    bead_id = raw_bead.strip()
    from sase.bead_pages.links import resolve_bead_page_target

    target = resolve_bead_page_target(
        bead_id,
        store=store,
        primary_root=primary_root,
        known_ids=known_bead_ids,
    )
    return upsert_plan_header_section(
        document,
        PlanHeaderSection(
            kind=PlanHeaderSectionKind.BEAD,
            label=bead_id,
            target=target,
        ),
        remove_legacy=False,
    )


def refresh_association_sections(
    document: str,
    associations: PlanAssociations,
) -> str:
    """Replace the derived ``AGENTS`` and ``COMMITS`` sections."""

    updated = _refresh_list_section(
        document,
        PlanHeaderSectionKind.AGENTS,
        tuple(
            PlanHeaderEntry(
                label=agent.label,
                target=agent.target,
                trailing_text=agent.trailing_text,
            )
            for agent in associations.agents
        ),
    )
    return _refresh_list_section(
        updated,
        PlanHeaderSectionKind.COMMITS,
        tuple(
            PlanHeaderEntry(
                label=commit.label,
                target=commit.target,
                trailing_text=commit.trailing_text,
            )
            for commit in associations.commits
        ),
    )


def _refresh_list_section(
    document: str,
    kind: PlanHeaderSectionKind,
    entries: tuple[PlanHeaderEntry, ...],
) -> str:
    parsed = parse_plan_header_block(document)
    exists = any(section.kind is kind for section in parsed.sections)
    if not entries and not exists:
        return document
    return upsert_plan_header_section(
        document,
        PlanHeaderSection(kind=kind, entries=entries),
    )


def _parent_reference(
    parent_ref: str,
    store: SddStore | None,
) -> tuple[str, str | None]:
    raw = parent_ref.strip()
    canonical = None
    if store is not None:
        from sase.sdd.plan_refs import (
            canonicalize_plan_reference_from_roots,
            resolve_plan_reference_from_roots,
        )

        resolution = resolve_plan_reference_from_roots(
            raw,
            roots=(store.kind_root("plans"),),
        )
        if resolution.resolved_path is not None:
            canonical = canonicalize_plan_reference_from_roots(
                resolution.resolved_path,
                roots=(store.kind_root("plans"),),
            )
    if canonical is None:
        try:
            from sase.sdd.plan_refs import parse_plan_reference

            parsed = parse_plan_reference(raw)
        except Exception:
            parsed = None
        if parsed is not None and not parsed.legacy and parsed.kind == "plans":
            canonical = parsed.rendered
    if canonical is not None:
        return canonical.removeprefix("plans:"), canonical

    normalized = Path(raw).as_posix().removeprefix("./")
    for marker in _LEGACY_PLAN_MARKERS:
        if normalized.startswith(marker):
            label = normalized.removeprefix(marker)
            return label, f"plans:{label}"
        embedded = f"/{marker}"
        if embedded in normalized:
            label = normalized.split(embedded, 1)[1]
            return label, f"plans:{label}"
    return normalized, None


def _hosted_parent_target(
    canonical_ref: str | None,
    *,
    store: SddStore | None,
    primary_root: Path | None,
) -> str | None:
    if canonical_ref is None or store is None:
        return None
    from sase.sdd.hosted_links import hosted_link_resolver

    return hosted_link_resolver(
        store,
        primary_root=primary_root,
    ).plan_url(canonical_ref)


def _relative_parent_target(
    parent_ref: str,
    label: str,
    *,
    source_path: Path | None,
    plans_root: Path | None,
) -> str:
    if source_path is None or plans_root is None:
        return label
    raw_path = Path(parent_ref).expanduser()
    if raw_path.is_absolute():
        target_path = raw_path
    else:
        target_path = plans_root / label
    return Path(
        os.path.relpath(
            target_path.resolve(strict=False),
            source_path.parent.resolve(strict=False),
        )
    ).as_posix()


__all__ = [
    "refresh_association_sections",
    "refresh_bead_plan_section",
    "refresh_existing_parent_section",
    "upsert_parent_plan_section",
]
