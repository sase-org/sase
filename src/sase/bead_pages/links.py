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
    from sase.sdd.checkout_anchor import resolve_checkout_anchor

    anchor = resolve_checkout_anchor(cwd or os.getcwd())
    primary_root = anchor.primary_root

    try:
        resolved_store = store or _resolve_store(primary_root)
        from sase.sdd.hosted_links import hosted_link_resolver

        resolver = (
            hosted_link_resolver(resolved_store, primary_root=primary_root)
            if anchor.project_name is None
            else hosted_link_resolver(
                resolved_store,
                project=anchor.project_name,
                primary_root=primary_root,
            )
        )
        destination = resolver.bead_url(label)
    except Exception:
        return label
    if destination is None:
        return label
    return LinkedCommitTagValue(label, destination)


def known_bead_ids_for_store(store: SddStore) -> frozenset[str] | None:
    """Return canonical and compatibility bead IDs, or ``None`` if unreadable."""

    try:
        if not store.is_sidecar_storage or store.beads_dir is None:
            return None
        from sase.bead.store_locator import open_bead_project_for_beads_dir

        with open_bead_project_for_beads_dir(store.kind_root("beads")) as project:
            canonical = frozenset(issue.id for issue in project.list_issues())
        aliases = bead_id_aliases_for_store(store)
        return canonical | frozenset(
            old_id
            for old_id, canonical_id in aliases.items()
            if canonical_id in canonical
        )
    except Exception:  # noqa: BLE001 - existence checks stay best-effort.
        return None


def bead_id_aliases_for_store(store: SddStore) -> dict[str, str]:
    """Return the store's well-shaped old-to-canonical bead ID aliases."""

    if not store.is_sidecar_storage or store.beads_dir is None:
        return {}
    from sase.bead.config import load_config

    raw = load_config(store.kind_root("beads")).get("id_aliases", {})
    if not isinstance(raw, dict):
        return {}
    return {
        old_id: canonical_id
        for old_id, canonical_id in raw.items()
        if isinstance(old_id, str)
        and old_id.strip() == old_id
        and isinstance(canonical_id, str)
        and canonical_id.strip() == canonical_id
    }


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
    from sase.sdd.checkout_anchor import resolve_checkout_anchor

    anchor = resolve_checkout_anchor(primary_root)
    resolver = (
        hosted_link_resolver(store, primary_root=anchor.primary_root)
        if anchor.project_name is None
        else hosted_link_resolver(
            store,
            project=anchor.project_name,
            primary_root=anchor.primary_root,
        )
    )
    destination = resolver.bead_url(bead_id)
    if destination is None:
        return None
    resolved_ids = (
        known_ids if known_ids is not None else known_bead_ids_for_store(store)
    )
    if resolved_ids is not None and bead_id not in resolved_ids:
        return None
    return destination


def resolve_bead_page_url_from_cwd(
    bead_id: str,
    *,
    cwd: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return *bead_id*'s hosted page URL for the checkout at *cwd*, or ``None``.

    Unlike :func:`sase.bead.cli_detail.resolve_bead_page_url`, which
    deliberately skips the bead-existence check for ``sase bead show``, this
    helper delegates to :func:`resolve_bead_page_target` so it does not return
    a URL for a page that cannot be published.
    """

    label = str(bead_id).strip()
    if not label:
        return None
    try:
        from sase.sdd.checkout_anchor import resolve_checkout_anchor

        anchor = resolve_checkout_anchor(cwd or os.getcwd())
        primary_root = anchor.primary_root
        store = _resolve_store(primary_root)
        return resolve_bead_page_target(
            label,
            store=store,
            primary_root=primary_root,
        )
    except Exception:
        return None


def _resolve_store(primary_root: Path) -> SddStore:
    """Resolve the local SDD store for *primary_root* without materializing it."""

    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    workspace_dir, workspace_num = workspace_context_for_plan_resolution(primary_root)
    return resolve_sdd_store(workspace_dir, workspace_num)


__all__ = [
    "bead_id_aliases_for_store",
    "known_bead_ids_for_store",
    "resolve_bead_commit_tag",
    "resolve_bead_page_target",
    "resolve_bead_page_url_from_cwd",
]
