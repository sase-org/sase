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


def _resolve_store(primary_root: Path) -> SddStore:
    """Resolve the local SDD store for *primary_root* without materializing it."""

    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    workspace_dir, workspace_num = workspace_context_for_plan_resolution(primary_root)
    return resolve_sdd_store(workspace_dir, workspace_num)


__all__ = ["resolve_bead_commit_tag"]
