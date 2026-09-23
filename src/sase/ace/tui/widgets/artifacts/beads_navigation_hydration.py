"""Stable-target hydration for beads missing from the current snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.bead.flag_fields import is_flag_bead
from sase.bead.model import Issue, IssueType

from .beads_data import BeadsSnapshot
from .beads_data_models import ProjectBead
from .beads_data_sources import (
    _hierarchical_id_key,
    _project_beads_dir,
    _resolve_projects,
)
from .beads_list import BeadRowKind
from .entry_navigation import (
    ArtifactEntryTarget,
    HydrationOutcome,
    HydrationResult,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class BeadsNavigationHydrationMixin(_MixinBase):
    """Resolve, merge, and reindex beads fetched outside the snapshot."""

    _snapshot: BeadsSnapshot | None
    project_scope: str | None
    _filter_index: Any
    _filter_index_source_key: Any
    _query_profile: Any
    _query_index: Any
    _query_session: Any

    def host_reveal_context(self, target: ArtifactEntryTarget) -> Any | None:
        """Return the Beads family context query for *target*."""
        from sase.ace.link_reveal_context import RevealContext

        if target.pane_id != "beads" or len(target.parts) < 3:
            return None
        snapshot = self._snapshot
        if snapshot is None:
            return None
        project, kind, bead_id = target.parts[0], target.parts[1], target.parts[2]
        if kind == "phase":
            for (phase_project, epic_id), phases in snapshot.phases_by_epic.items():
                if phase_project != project:
                    continue
                if any(phase.issue.id == bead_id for phase in phases):
                    return RevealContext(
                        alternatives=(("id", f"{epic_id}.*"),),
                        label=f"epic {epic_id}",
                        member_count=len(phases),
                    )
            return None
        if kind == "epic":
            phases = snapshot.phases_by_epic.get((project, bead_id), ())
            return RevealContext(
                alternatives=(("id", bead_id), ("id", f"{bead_id}.*")),
                label=f"epic {bead_id}",
                member_count=1 + len(phases),
                expand_target_fold=True,
            )
        if kind in ("task", "flag"):
            return RevealContext(
                alternatives=(("id", bead_id),),
                label=f"bead {bead_id}",
                member_count=1,
            )
        return None

    def host_query_row_for_target(
        self, target: ArtifactEntryTarget
    ) -> dict[str, Any] | None:
        """Return the unfiltered Beads query row backing *target*."""
        snapshot = self._snapshot
        index = getattr(self, "_filter_index", None)
        if (
            snapshot is None
            or index is None
            or target.pane_id != "beads"
            or len(target.parts) < 3
        ):
            return None
        from .beads_list import row_option_id
        from .query_rows import bead_query_entry

        project, kind, bead_id = target.parts[0], target.parts[1], target.parts[2]
        option_id = row_option_id(snapshot, kind, project, bead_id)  # type: ignore[arg-type]
        record = index.by_option_id.get(option_id)
        if record is None:
            return None
        return bead_query_entry(record)

    def hydrate_ref(self, kind: str, payload: str) -> HydrationResult:
        """Resolve one bead by exact id, searching only the current scope.

        Scoping the store search to ``self.project_scope`` (one project, or
        every enabled project when unscoped) guarantees the resolved
        project is always compatible with the current snapshot, so the
        merge in :meth:`install_hydrated_row` never has to reconcile a
        foreign project scope.
        """
        if kind != "bead":
            return HydrationResult(HydrationOutcome.UNSUPPORTED)
        from sase.core.bead_read_facade import resolve_id, show

        found: tuple[str, Issue] | None = None
        for item in _resolve_projects(self.project_scope):
            beads_dir = _project_beads_dir(item.project)
            if beads_dir is None:
                continue
            try:
                full_id = resolve_id(beads_dir, payload)
                issue = show(beads_dir, full_id)
            except KeyError:
                continue
            except Exception as exc:  # noqa: BLE001 - reported as FAILED below
                return HydrationResult(HydrationOutcome.FAILED, error=str(exc))
            found = (item.project, issue)
            break
        if found is None:
            return HydrationResult(HydrationOutcome.ABSENT)
        project, issue = found
        parent_epic: Issue | None = None
        if issue.issue_type is IssueType.PHASE and issue.parent_id:
            beads_dir = _project_beads_dir(project)
            if beads_dir is not None:
                try:
                    parent_epic = show(beads_dir, issue.parent_id)
                except KeyError:
                    parent_epic = None
                except Exception as exc:  # noqa: BLE001 - reported as FAILED below
                    return HydrationResult(HydrationOutcome.FAILED, error=str(exc))
        return HydrationResult(
            HydrationOutcome.FETCHED, payload=(project, issue, parent_epic)
        )

    def install_hydrated_row(self, payload: Any) -> ArtifactEntryTarget | None:
        """Merge one fetched bead (plus its parent epic, if needed) in.

        Rebuilds the filter and query indexes around the merged snapshot so
        the rewritten query the coordinator re-requests with can actually
        match the new row. Leaves rebuilding ``_rows``/options to the
        request that follows: the coordinator immediately re-requests the
        returned target, whose ``request_entry_target`` miss path already
        calls ``_refresh_options()`` with ``_pending_entry_target`` set,
        which expands the owning epic fold for a phase for free.
        """
        if not isinstance(payload, tuple) or len(payload) != 3:
            return None
        project, issue, parent_epic = payload
        snapshot = self._snapshot
        if snapshot is None:
            return None
        if parent_epic is not None and not any(
            bead.project == project and bead.issue.id == parent_epic.id
            for bead in snapshot.epics
        ):
            snapshot = _merge_bead_into_snapshot(snapshot, project, parent_epic)
        merged = _merge_bead_into_snapshot(snapshot, project, issue)
        if merged is not self._snapshot:
            self._snapshot = merged
            self._reindex_after_hydration()
        return ArtifactEntryTarget("beads", (project, _bead_row_kind(issue), issue.id))

    def _reindex_after_hydration(self) -> None:
        """Rebuild the filter and query indexes for the merged snapshot.

        The merged snapshot keeps its ``source_key``, so without a rebuild
        the stale indexes would keep hiding the hydrated row from the
        rewritten query. The query session cache is cleared alongside so no
        same-generation entry can answer from the pre-merge corpus.
        """
        from .query_rows import build_beads_query_index

        snapshot = self._snapshot
        profile = getattr(self, "_query_profile", None)
        index = getattr(self, "_query_index", None)
        session = getattr(self, "_query_session", None)
        if snapshot is None or profile is None or index is None or session is None:
            return
        filter_index, query_index = build_beads_query_index(
            snapshot,
            pane_id=profile.pane_id,
            generation=index.generation,
            profile=profile,
        )
        session.clear()
        self._filter_index = filter_index
        self._filter_index_source_key = filter_index.source_key
        self._query_index = query_index


def _bead_row_kind(issue: Issue) -> BeadRowKind:
    if issue.issue_type is IssueType.PLAN:
        return "epic"
    if issue.issue_type is IssueType.PHASE:
        return "phase"
    if is_flag_bead(issue):
        return "flag"
    return "task"


def _merge_bead_into_snapshot(
    snapshot: BeadsSnapshot,
    project: str,
    issue: Issue,
) -> BeadsSnapshot:
    """Append one hydrated bead into *snapshot*, preserving phase grouping."""
    from dataclasses import replace as _replace

    if issue.issue_type is IssueType.PLAN:
        if any(
            bead.project == project and bead.issue.id == issue.id
            for bead in snapshot.epics
        ):
            return snapshot
        epics = (*snapshot.epics, ProjectBead(project, issue))
        key = (project, issue.id)
        phases_by_epic = snapshot.phases_by_epic
        if key not in phases_by_epic:
            phases_by_epic = {**phases_by_epic, key: ()}
        return _replace(snapshot, epics=epics, phases_by_epic=phases_by_epic)
    if issue.issue_type is IssueType.PHASE:
        if not issue.parent_id:
            return snapshot  # an orphan phase has no epic to group under
        key = (project, issue.parent_id)
        existing = snapshot.phases_by_epic.get(key, ())
        if any(bead.issue.id == issue.id for bead in existing):
            return snapshot
        phases = tuple(
            sorted(
                (*existing, ProjectBead(project, issue)),
                key=lambda bead: _hierarchical_id_key(bead.issue.id),
            )
        )
        phases_by_epic = {**snapshot.phases_by_epic, key: phases}
        return _replace(snapshot, phases_by_epic=phases_by_epic)
    if is_flag_bead(issue):
        if any(
            bead.project == project and bead.issue.id == issue.id
            for bead in snapshot.flags
        ):
            return snapshot
        return _replace(snapshot, flags=(*snapshot.flags, ProjectBead(project, issue)))
    if any(
        bead.project == project and bead.issue.id == issue.id for bead in snapshot.tasks
    ):
        return snapshot
    return _replace(snapshot, tasks=(*snapshot.tasks, ProjectBead(project, issue)))


__all__ = ["BeadsNavigationHydrationMixin"]
