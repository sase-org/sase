"""Archive-restore target collection and bundle hydration.

Keys seam for the Archive restore split. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_restore`, which re-exports this
module's public names.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._archive_restore_support import archive_light_name
from ._archive_restore_types import ArchiveRestoreSkip, ArchiveRestoreTargets

log = logging.getLogger(__name__)

_NO_MATCHING_MEMBERS = "no matching members under the current filter"

__all__ = [
    "capture_archive_restore_plan",
    "collect_archive_restore_targets",
    "hydrate_archive_candidate",
    "resolve_archive_restore_targets",
]


@dataclass(frozen=True, slots=True)
class _ContainerTarget:
    """One clan or session container whose matching members get restored."""

    item_key: str
    container_key: str
    name: str
    member_count: int
    group_keys: tuple[str, ...]
    loaded: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _RestorePlan:
    """What one restore acts on, captured from view state on the event loop.

    Capturing reads only in-memory state. Resolving may query the warm corpus,
    so :func:`resolve_archive_restore_targets` runs in a thread worker and
    reads only this plan, never the owner.
    """

    marked: bool = False
    run_keys: tuple[str, ...] = ()
    containers: tuple[_ContainerTarget, ...] = ()
    skipped: tuple[ArchiveRestoreSkip, ...] = ()
    corpus: Any = None
    profile: Any = None
    query: str | None = None
    grouping: str = "day"


def capture_archive_restore_plan(owner: Any) -> _RestorePlan:
    """Snapshot the restore targets: the marked set, else the cursor row.

    Marks win over the cursor, and a marked or highlighted container stands
    for its matching members. Banners, page tails, and the Inbox pulse are
    navigable but never runs, so they resolve to a skip, never to the parked
    Inbox.
    """
    from ...models.agent_archive_view import (
        ARCHIVE_SECTION_PULSE,
        is_archive_container_key,
        is_archive_row_key,
    )
    from ._archive_actions import archive_ui_active
    from ._archive_view import agents_archive_view_state

    try:
        archive = agents_archive_view_state(owner).archive
    except Exception:
        return _RestorePlan()
    controller = getattr(owner, "_agents_archive_controller", None)
    corpus = getattr(controller, "corpus", None)
    resolver: dict[str, Any] = {
        "corpus": corpus,
        "profile": getattr(controller, "profile", None),
        "query": (
            _corpus_query(archive.committed_query) if corpus is not None else None
        ),
        "grouping": archive.grouping,
    }
    marks = sorted(archive.marks) if archive_ui_active(owner) else []
    if marks:
        return _RestorePlan(
            marked=True,
            run_keys=tuple(key for key in marks if not is_archive_container_key(key)),
            containers=tuple(
                _container_target(owner, key)
                for key in marks
                if is_archive_container_key(key)
            ),
            **resolver,
        )
    key = archive.selected_key
    if archive.focused_section == ARCHIVE_SECTION_PULSE:
        key = None
    if not key or not is_archive_row_key(key):
        skip = ArchiveRestoreSkip(
            key=str(key or ""),
            name=_light_name(owner, key, fallback="selection"),
            reason="not an archived run",
        )
        return _RestorePlan(skipped=(skip,))
    if is_archive_container_key(key):
        return _RestorePlan(containers=(_container_target(owner, key),), **resolver)
    return _RestorePlan(run_keys=(key,))


def resolve_archive_restore_targets(plan: _RestorePlan) -> ArchiveRestoreTargets:
    """Expand the plan's containers into member runs, de-duplicated in order.

    Safe off the event loop: reads only the captured plan and the immutable
    published corpus handle. Never hydrates bundles to count or list members.
    """
    from ...models.agent_archive_list import archive_row_key

    keys = dict.fromkeys(plan.run_keys)
    rows: dict[str, Mapping[str, Any]] = {}
    skipped = list(plan.skipped)
    for container in plan.containers:
        members = _container_members(plan, container)
        member_keys = [(archive_row_key(member), member) for member in members]
        resolved = [(key, member) for key, member in member_keys if key]
        if not resolved:
            skipped.append(
                ArchiveRestoreSkip(
                    key=container.item_key,
                    name=container.name,
                    reason=_NO_MATCHING_MEMBERS,
                )
            )
            continue
        for key, member in resolved:
            keys.setdefault(key, None)
            rows.setdefault(key, member)
    return ArchiveRestoreTargets(
        keys=tuple(keys),
        rows=rows,
        skipped=tuple(skipped),
        marked=plan.marked,
    )


def collect_archive_restore_targets(owner: Any) -> ArchiveRestoreTargets:
    """Capture and resolve the restore targets on the calling thread.

    For loop-free callers and tests. The chooser captures on the loop and
    resolves in a thread worker instead.
    """
    return resolve_archive_restore_targets(capture_archive_restore_plan(owner))


def _corpus_query(query: str) -> str | None:
    """Strip the host ``in:`` scope token, which selects the view, not rows."""
    from ....query.profile_reference_support import ProfileQueryError
    from ....query.scope_token import ScopeTokenError, extract_scope

    try:
        return extract_scope(query)[0].strip()
    except (ScopeTokenError, ProfileQueryError, ValueError):
        log.debug("archive restore query scope rejected: %r", query, exc_info=True)
        return None


def _light_name(owner: Any, key: str | None, *, fallback: str) -> str:
    try:
        from ._archive_column import archive_light_row

        row = archive_light_row(owner, key)
    except Exception:
        return fallback
    return archive_light_name(row) if row is not None else fallback


def _container_target(owner: Any, item_key: str) -> _ContainerTarget:
    """Capture one container's identity, matching count, groups, and members."""
    from ...models.agent_archive_view import container_key_of
    from ._archive_column import (
        archive_container_members,
        archive_light_row,
        column_runtime,
    )

    container_key = container_key_of(item_key) or ""
    try:
        row = archive_light_row(owner, item_key)
    except Exception:
        row = None
    try:
        member_count = int((row or {}).get("member_count") or 0)
    except (TypeError, ValueError):
        member_count = 0
    try:
        loaded = tuple(archive_container_members(owner, container_key))
    except Exception:
        loaded = ()
    group_keys: tuple[str, ...] = ()
    try:
        model = column_runtime(owner).model
        item = model.item(item_key)
        banner_key = item.banner_key if item is not None else None
        for banner in model.banners:
            if banner_key is not None and banner.key == banner_key:
                group_keys = tuple(banner.group_keys)
                break
    except Exception:
        group_keys = ()
    return _ContainerTarget(
        item_key=item_key,
        container_key=container_key,
        name=archive_light_name(row) if row is not None else "container",
        member_count=member_count,
        group_keys=group_keys,
        loaded=loaded,
    )


def _container_members(
    plan: _RestorePlan, container: _ContainerTarget
) -> tuple[Mapping[str, Any], ...]:
    """Return a container's matching members: loaded ones, else the corpus's.

    An expanded container's members are already in the column. A collapsed
    one (or one whose members are only partly paged in) asks the corpus for
    the container's group with that container expanded, the same rows and
    window path the column uses when the user expands it.
    """
    if container.loaded and len(container.loaded) >= container.member_count:
        return container.loaded
    corpus = plan.corpus
    if corpus is None or plan.query is None or not container.container_key:
        return container.loaded
    expanded = (container.container_key,)
    try:
        summary = corpus.summary(
            plan.query, group_by=plan.grouping, profile=plan.profile
        )
    except Exception:
        log.debug("archive restore summary failed", exc_info=True)
        return container.loaded
    wanted = frozenset(container.group_keys)
    for group in summary.get("groups", ()):
        if not isinstance(group, Mapping):
            continue
        group_key = group.get("key")
        if not isinstance(group_key, str) or (wanted and group_key not in wanted):
            continue
        try:
            limit = int(group.get("count", 0) or 0) + container.member_count
            if container.member_count <= 0:
                probe = corpus.rows(
                    plan.query,
                    group_by=plan.grouping,
                    group_key=group_key,
                    offset=0,
                    limit=0,
                    expanded_container_keys=expanded,
                    profile=plan.profile,
                )
                limit = int(probe.get("total", 0) or 0)
            payload = corpus.rows(
                plan.query,
                group_by=plan.grouping,
                group_key=group_key,
                offset=0,
                limit=limit,
                expanded_container_keys=expanded,
                profile=plan.profile,
            )
        except Exception:
            log.debug("archive restore member rows failed", exc_info=True)
            continue
        members = tuple(
            dict(row)
            for row in payload.get("rows", ())
            if isinstance(row, Mapping)
            and row.get("container") is not True
            and row.get("container_key") == container.container_key
        )
        if members:
            return members
    return container.loaded


def hydrate_archive_candidate(
    owner: Any, key: str, light_row: Mapping[str, Any] | None = None
) -> tuple[Any | None, Any | None, str | None]:
    """Return ``(agent, light_row, skip_reason)`` for one restore key.

    ``light_row`` is the resolved row of a container member the column never
    loaded; without it the column's row for ``key`` is used. The bundle read
    is one small JSON file, the same order of work as the existing revive
    path's artifact restore. Never writes. The agent is returned even when
    unrestorable so the chooser can still offer Open chat, Fork, and Copy;
    only an unreadable bundle yields no agent. The light row's ``restorable``
    chip never decides: the corpus row may be stale, so the hydrated agent's
    capability is re-checked just before submitting.
    """
    try:
        from ._archive_column import archive_light_row
        from ._archive_reader import load_archive_bundle

        if light_row is None:
            light_row = archive_light_row(owner, key)
    except Exception:
        return None, None, "row is no longer listed"
    if light_row is None:
        return None, None, "row is no longer listed"
    try:
        bundle = load_archive_bundle(owner, light_row)
    except Exception:
        return None, light_row, "bundle unreadable"
    agent = bundle.get("agent") if bundle else None
    if bundle is None or bundle.get("unreadable") or agent is None:
        return None, light_row, "bundle unreadable"
    if not bool(getattr(agent, "durably_revivable", True)):
        return agent, light_row, "can't restore"
    return agent, light_row, None
