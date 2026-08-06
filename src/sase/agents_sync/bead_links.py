"""Resolve published agent runs' bead-page links for browsing pages.

Two sources feed one run's bead association, at different trust levels.
``metadata["bead_id"]`` came from the ``%id(..., bead=<id>)`` launch
directive and is trusted lexically: it always renders, linked whenever the
beads sidecar resolves to a hosted URL. A name-derived candidate is a guess
and only renders once confirmed against the bead store.

Every ``sase.bead_pages.*``, ``sase.sdd.*``, and ``sase.agent.bead_display``
import here is function-local (or ``TYPE_CHECKING``-only) on purpose:
``sase.bead_pages`` imports ``sase.agents_sync.rendering_markdown``, so a
module-level import back into ``sase.agents_sync`` would create a
partially-initialized-module cycle at interpreter start.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sase.agents_sync.v2_models import V2HoodSnapshot


class _BeadUrlResolver(Protocol):
    """Structural shape of ``HostedLinkResolver`` this module relies on."""

    def bead_url(self, bead_id: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class BeadPageLink:
    """One run's resolved bead association, ready for rendering."""

    bead_id: str
    url: str | None = None
    epic_bead_id: str | None = None
    epic_url: str | None = None


def build_bead_page_links(
    snapshots: Iterable[V2HoodSnapshot],
    *,
    primary_root: Path,
    project: str | None,
) -> tuple[Mapping[str, BeadPageLink], tuple[str, ...]]:
    """Resolve every published run's bead page link, keyed by global name."""

    try:
        from sase.bead_pages.links import known_bead_ids_for_store
        from sase.sdd.hosted_links import hosted_link_resolver
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution
        from sase.sdd.store import resolve_sdd_store

        workspace_dir, workspace_num = workspace_context_for_plan_resolution(
            primary_root
        )
        store = resolve_sdd_store(workspace_dir, workspace_num)
        resolver = hosted_link_resolver(
            store, project=project, primary_root=primary_root
        )
        known_bead_ids = known_bead_ids_for_store(store)
    except Exception as exc:  # noqa: BLE001 - bead links stay best-effort.
        return {}, (f"bead links: could not resolve beads sidecar ({exc})",)

    return _resolve_links(
        snapshots, resolver=resolver, known_bead_ids=known_bead_ids
    ), ()


def _resolve_links(
    snapshots: Iterable[V2HoodSnapshot],
    *,
    resolver: _BeadUrlResolver,
    known_bead_ids: frozenset[str] | None,
) -> dict[str, BeadPageLink]:
    links: dict[str, BeadPageLink] = {}
    for snapshot in snapshots:
        for run in snapshot.runs:
            metadata = dict(run.metadata)
            selection = _select_bead_source(run.local_name, metadata, known_bead_ids)
            if selection is None:
                continue
            bead_id, from_metadata = selection
            epic_bead_id: str | None = None
            epic_url: str | None = None
            if from_metadata:
                raw_epic = metadata.get("epic_bead_id")
                candidate_epic = raw_epic.strip() if isinstance(raw_epic, str) else None
                if candidate_epic and candidate_epic != bead_id:
                    epic_bead_id = candidate_epic
                    epic_url = resolver.bead_url(epic_bead_id)
            links[run.global_name] = BeadPageLink(
                bead_id,
                resolver.bead_url(bead_id),
                epic_bead_id,
                epic_url,
            )
    return links


def _select_bead_source(
    local_name: str,
    metadata: Mapping[str, object],
    known_bead_ids: frozenset[str] | None,
) -> tuple[str, bool] | None:
    """Return ``(bead_id, from_metadata)`` for one run, or ``None``."""

    metadata_bead_id = metadata.get("bead_id")
    if isinstance(metadata_bead_id, str) and metadata_bead_id.strip():
        return metadata_bead_id.strip(), True

    from sase.agent.bead_display import derive_agent_bead_id_from_name

    candidate = derive_agent_bead_id_from_name(local_name)
    if candidate is None or known_bead_ids is None or candidate not in known_bead_ids:
        return None
    return candidate, False


__all__ = ["BeadPageLink", "build_bead_page_links"]
