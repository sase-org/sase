"""Archive-restore target collection and bundle hydration.

Keys seam for the Archive restore split. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_restore`, which re-exports this
module's public names.
"""

from __future__ import annotations

from typing import Any

from ._archive_restore_support import archive_light_name
from ._archive_restore_types import ArchiveRestoreSkip

__all__ = [
    "collect_archive_restore_keys",
    "hydrate_archive_candidate",
]


def collect_archive_restore_keys(
    owner: Any,
) -> tuple[list[str], list[ArchiveRestoreSkip]]:
    """Return the restore target keys in priority order plus nav-item skips.

    Marked runs (containers expanded to their loaded members) win over the
    cursor. A container cursor restores its loaded members. Banners, page
    tails, and the Inbox pulse are navigable but never runs, so they resolve
    to a skip, never to the parked Inbox.
    """
    from ...models.agent_archive_list import archive_row_key
    from ...models.agent_archive_view import (
        ARCHIVE_SECTION_PULSE,
        container_key_of,
        is_archive_container_key,
        is_archive_row_key,
    )

    skipped: list[ArchiveRestoreSkip] = []
    try:
        from ._archive_actions import archive_marked_run_keys

        marked = [key for key in archive_marked_run_keys(owner) if key]
    except Exception:
        marked = []
    if marked:
        keys = [key for key in marked if not is_archive_container_key(key)]
        return keys, skipped

    try:
        from ._archive_view import agents_archive_view_state

        state = agents_archive_view_state(owner)
        key = state.archive.selected_key
        pulse_focused = state.archive.focused_section == ARCHIVE_SECTION_PULSE
    except Exception:
        return [], skipped
    if pulse_focused:
        key = None
    if not key or not is_archive_row_key(key):
        label = "selection"
        try:
            from ._archive_column import archive_light_row

            label = archive_light_name(archive_light_row(owner, key))
        except Exception:
            pass
        return [], [
            ArchiveRestoreSkip(
                key=str(key or ""), name=label, reason="not an archived run"
            )
        ]
    if is_archive_container_key(key):
        container_key = container_key_of(key)
        members: tuple[Any, ...] = ()
        if container_key is not None:
            try:
                from ._archive_column import archive_container_members

                members = archive_container_members(owner, container_key)
            except Exception:
                members = ()
        member_keys = []
        for member in members:
            try:
                member_key = archive_row_key(member)
            except Exception:
                member_key = None
            if member_key:
                member_keys.append(member_key)
        if not member_keys:
            try:
                from ._archive_column import archive_light_row

                name = archive_light_name(archive_light_row(owner, key))
            except Exception:
                name = "container"
            return [], [
                ArchiveRestoreSkip(
                    key=key,
                    name=name,
                    reason="no loaded members — expand the container (l) first",
                )
            ]
        return member_keys, skipped
    return [key], skipped


def hydrate_archive_candidate(
    owner: Any, key: str
) -> tuple[Any | None, Any | None, str | None]:
    """Return ``(agent, light_row, skip_reason)`` for one restore key.

    The bundle read is one small JSON file, the same order of work as the
    existing revive path's artifact restore. Never writes. The agent is
    returned even when unrestorable so the chooser can still offer Open
    chat, Fork, and Copy; only an unreadable bundle yields no agent. The
    light row's ``restorable`` chip never decides: the corpus row may be
    stale, so the hydrated agent's capability is re-checked just before
    submitting.
    """
    try:
        from ._archive_column import archive_light_row
        from ._archive_reader import load_archive_bundle

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
