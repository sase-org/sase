"""Best-effort cycle facts for epic-follow targets.

An epic ``E`` is a cycle for a waiter ``W`` when a live agent in ``E``'s clan
already waits on ``W`` — its ``waiting.json`` ``waiting_for`` or its
``agent_meta.json`` ``wait_for`` contains ``W``'s name or session, for example
through the approval "Wait for" field. A cycle can never self-resolve, so the
reducer parks the target in ``blocked`` with reason ``cycle``; nothing here
ever releases on a timeout.

Everything is best-effort: unreadable markers, unknown waiter names, and
missing clan generations yield no cycles rather than errors.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def waiter_wait_names(waiter_meta: Mapping[str, Any] | object) -> frozenset[str]:
    """Return the waiter names a clan member's wait may reference.

    Covers the waiter's agent name and its session base: waits name either.
    """
    names: set[str] = set()
    for key in ("name", "cl_name"):
        value = _field(waiter_meta, key)
        if isinstance(value, str) and value.strip():
            names.add(value.strip())
    session = _waiter_session(waiter_meta)
    if session is not None:
        names.add(session)
    return frozenset(names)


def _waiter_session(waiter_meta: Mapping[str, Any] | object) -> str | None:
    try:
        from sase.core.wait_dependency_resolution._artifact_state import (
            agent_session_base_from_meta,
        )
    except Exception:
        return None
    if not isinstance(waiter_meta, Mapping):
        return None
    try:
        session = agent_session_base_from_meta(dict(waiter_meta))
    except Exception:
        return None
    return session if isinstance(session, str) and session.strip() else None


def _field(source: object, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _member_wait_targets(member_dir: Path) -> frozenset[str]:
    """Read one member's wait lists from ``waiting.json`` and ``agent_meta.json``."""
    targets: set[str] = set()
    try:
        waiting = json.loads((member_dir / "waiting.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        waiting = None
    if isinstance(waiting, dict):
        targets.update(_str_list(waiting.get("waiting_for")))
    try:
        meta = json.loads((member_dir / "agent_meta.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        meta = None
    if isinstance(meta, dict):
        targets.update(_str_list(meta.get("wait_for")))
    return frozenset(targets)


def _is_own_bead(own_bead_ids: Iterable[str], epic: str) -> bool:
    """Mirror the reducer's deadlock guard: own bead equals or nests under ``epic``."""
    candidate = epic.strip()
    if not candidate:
        return False
    for own in own_bead_ids:
        if not isinstance(own, str):
            continue
        trimmed = own.strip()
        if not trimmed:
            continue
        if trimmed == candidate or trimmed.startswith(f"{candidate}."):
            return True
    return False


def _candidate_epics(
    members: Iterable[object],
    waiter_own_bead_ids: Iterable[str],
) -> list[str]:
    """Mirror the reducer's epic union plus the deadlock guard.

    Recorded and attributed epics win; legacy IDs cover non-worker members
    only when nothing was recorded. Guard-skipped own beads never count as
    cycles: the reducer drops them before consulting ``cycle_epic_ids``.
    """
    recorded: list[str] = []
    legacy: list[str] = []
    for member in members:
        for id_list in (
            _field(member, "recorded_epic_ids") or (),
            _field(member, "attributed_epic_ids") or (),
        ):
            if isinstance(id_list, str) or not isinstance(id_list, Iterable):
                continue
            for entry in id_list:
                if (
                    isinstance(entry, str)
                    and entry.strip()
                    and entry.strip() not in recorded
                ):
                    recorded.append(entry.strip())
        if not _field(member, "is_epic_worker"):
            legacy_id = _field(member, "legacy_epic_bead_id")
            if (
                isinstance(legacy_id, str)
                and legacy_id.strip()
                and legacy_id.strip() not in legacy
            ):
                legacy.append(legacy_id.strip())
    union = recorded or legacy
    return [epic for epic in union if not _is_own_bead(waiter_own_bead_ids, epic)]


def cycle_epic_ids_for_members(
    index: Any,
    members: Iterable[object],
    *,
    waiter_own_bead_ids: Iterable[str] = (),
    waiter_names: frozenset[str] | None = None,
    waiter_dir: str | Path | None = None,
) -> tuple[str, ...]:
    """Return the candidate epics whose clan already waits on the waiter.

    ``members`` are the target's collected member facts; the epic union is
    derived from them so callers never duplicate reducer rule order. Done
    members no longer wait, so only live clan members count. File reads are
    memoized per call through an internal cache.
    """
    if waiter_names is None:
        return ()
    names = frozenset(name for name in waiter_names if name)
    if not names:
        return ()
    waiter_key: str | None = None
    if waiter_dir is not None:
        try:
            from sase.core.wait_dependency_resolution._artifact_state import (
                artifact_dir_key,
            )

            waiter_key = artifact_dir_key(str(waiter_dir))
        except Exception:
            waiter_key = None
    clans = getattr(index, "clans", None)
    if not isinstance(clans, dict):
        return ()
    cache: dict[str, frozenset[str]] = {}
    cycles: list[str] = []
    for epic in _candidate_epics(members, waiter_own_bead_ids):
        generations = clans.get(epic)
        if not isinstance(generations, dict):
            continue
        if _clan_waits_on(generations, names, waiter_key, cache):
            cycles.append(epic)
    return tuple(cycles)


def _clan_waits_on(
    generations: dict[str, list[Any]],
    waiter_names: frozenset[str],
    waiter_key: str | None,
    cache: dict[str, frozenset[str]],
) -> bool:
    for members in generations.values():
        if not isinstance(members, list):
            continue
        for member in members:
            member_dir = _field(member, "artifact_dir")
            if not isinstance(member_dir, str) or not member_dir.strip():
                continue
            if _field(member, "has_done_marker"):
                continue
            if waiter_key is not None and _same_dir(member_dir, waiter_key):
                continue
            cached = cache.get(member_dir)
            if cached is None:
                try:
                    cached = _member_wait_targets(Path(member_dir))
                except Exception:
                    cached = frozenset()
                cache[member_dir] = cached
            if not cached.isdisjoint(waiter_names):
                return True
    return False


def _same_dir(member_dir: str, waiter_key: str) -> bool:
    try:
        from sase.core.wait_dependency_resolution._artifact_state import (
            artifact_dir_key,
        )

        return bool(artifact_dir_key(member_dir) == waiter_key)
    except Exception:
        return False


__all__ = [
    "cycle_epic_ids_for_members",
    "waiter_wait_names",
]
