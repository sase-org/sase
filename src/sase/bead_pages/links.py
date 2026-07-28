"""Best-effort commit-footer links to generated bead pages."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.commit_footer_facade import LinkedCommitTagValue

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def resolve_bead_commit_tag(
    bead_id: str,
    *,
    store: SddStore | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> str | LinkedCommitTagValue:
    """Return *bead_id*, linked when its beads sidecar is hosted.

    Resolution is deliberately local-only and best-effort. A missing store,
    beads sidecar, hosted remote, or resolvable branch keeps the bare bead ID
    instead of raising or inventing a destination.
    """

    label = str(bead_id).strip()
    if not label:
        return label
    primary_root = Path(cwd or os.getcwd()).expanduser().resolve(strict=False)

    try:
        resolved_store = store or _resolve_store(primary_root)
        from sase.sdd.hosted_links import hosted_link_resolver

        destination = hosted_link_resolver(
            resolved_store,
            primary_root=primary_root,
        ).bead_url(label)
    except Exception:
        return label
    if destination is None:
        return label
    return LinkedCommitTagValue(label, destination)


def known_bead_ids_for_store(store: SddStore) -> frozenset[str] | None:
    """Return every bead ID *store* holds, or ``None`` when it cannot be read."""

    try:
        if not store.is_sidecar_storage or store.beads_dir is None:
            return None
        from sase.bead.store_locator import open_bead_project_for_beads_dir

        with open_bead_project_for_beads_dir(store.kind_root("beads")) as project:
            return frozenset(issue.id for issue in project.list_issues())
    except Exception:  # noqa: BLE001 - existence checks stay best-effort.
        return None


def resolve_bead_page_target(
    bead_id: str,
    *,
    store: SddStore | None,
    primary_root: Path | str | None = None,
    known_ids: frozenset[str] | None = None,
) -> str | None:
    """Return *bead_id*'s page URL only when that page can actually exist.

    Page addresses are lexical, so a URL resolves for any well-formed ID —
    including one the store no longer holds, which is common in plans stamped
    with legacy bead IDs. Publication only ever renders pages for beads that
    exist, so linking one of those would publish a dead link. Pass *known_ids*
    to reuse one store read across many beads. An unreadable store keeps the
    link rather than stripping every good link on a transient failure.
    """

    if store is None:
        return None
    from sase.sdd.hosted_links import hosted_link_resolver

    destination = hosted_link_resolver(
        store,
        primary_root=primary_root,
    ).bead_url(bead_id)
    if destination is None:
        return None
    resolved_ids = (
        known_ids if known_ids is not None else known_bead_ids_for_store(store)
    )
    if resolved_ids is not None and bead_id not in resolved_ids:
        return None
    return destination


def _resolve_store(primary_root: Path) -> SddStore:
    """Resolve the local SDD store for *primary_root* without materializing it."""

    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    workspace_dir, workspace_num = workspace_context_for_plan_resolution(primary_root)
    return resolve_sdd_store(workspace_dir, workspace_num)


__all__ = [
    "known_bead_ids_for_store",
    "resolve_bead_commit_tag",
    "resolve_bead_page_target",
]
