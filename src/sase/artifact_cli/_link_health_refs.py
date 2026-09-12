"""Dangling and unpublished artifact reference checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.artifact_cli._link_health_constants import RESOLVED_STATUSES
from sase.artifact_cli.references import resolve_cli_reference
from sase.artifact_refs import ArtifactRefContext
from sase.sdd._artifact_link_store_support import kind_of_ref
from sase.sdd.artifact_link_store import ArtifactLinkStore


def dangling_refs(
    rows: list[dict[str, Any]],
    store: ArtifactLinkStore,
    *,
    context: ArtifactRefContext,
    resolve_reference: Callable[..., Any] = resolve_cli_reference,
) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    dangling: list[str] = []
    unpublished_agents: list[str] = []
    bead_ids = known_bead_ids(store)
    for row in rows:
        for key in ("source_ref", "target_ref"):
            ref = str(row.get(key) or "")
            if not ref or ref in seen:
                continue
            seen.add(ref)
            if ref.startswith("bead:") and bead_ids is not None:
                if ref.removeprefix("bead:") not in bead_ids:
                    dangling.append(ref)
                continue
            try:
                result = resolve_reference(ref, context=context)
            except (RuntimeError, ValueError):
                if kind_of_ref(ref) == "agent":
                    unpublished_agents.append(ref)
                else:
                    dangling.append(ref)
                continue
            if result.resolution.status not in RESOLVED_STATUSES:
                if kind_of_ref(ref) == "agent":
                    unpublished_agents.append(ref)
                else:
                    dangling.append(ref)
    return sorted(dangling), sorted(unpublished_agents)


def known_bead_ids(store: ArtifactLinkStore) -> set[str] | None:
    if store.beads_dir is None:
        return None
    try:
        from sase.bead.store_locator import open_bead_project_for_beads_dir

        with open_bead_project_for_beads_dir(store.beads_dir) as project:
            return {str(issue.id) for issue in project.list_issues()}
    except Exception:  # noqa: BLE001 - fall back to regular artifact resolution
        return None


__all__ = [
    "dangling_refs",
    "known_bead_ids",
]
