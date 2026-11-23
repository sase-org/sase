"""Compare ACE surface tokens for drift and consumed-kind changes."""

from __future__ import annotations

from ._models import SurfaceToken

_AXE_DETAIL_KINDS = frozenset({"status", "metrics", "log"})
_AXE_ALWAYS_KINDS = frozenset({"membership", "pid", "service", "content"})


def surface_token_drifted(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
) -> bool:
    """Return True when *current* cannot be treated as unchanged."""
    if current is None or last is None:
        return True
    if current.indeterminate or last.indeterminate:
        return True
    return current != last


def surface_token_changed_kinds(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
    *,
    consumed_kinds: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Return bounded part-kind labels for changed token inputs.

    Missing or indeterminate inputs are reported as ``("unknown",)`` so
    callers can explain fail-open refreshes without logging file paths.
    """
    if current is None or last is None or current.indeterminate or last.indeterminate:
        return ("unknown",)
    current_map = _part_map(current)
    last_map = _part_map(last)
    changed_kinds: set[str] = set()
    for path in current_map.keys() | last_map.keys():
        current_entry = current_map.get(path)
        last_entry = last_map.get(path)
        if current_entry == last_entry:
            continue
        kind = (
            current_entry[3]
            if current_entry is not None
            else last_entry[3]
            if last_entry is not None
            else "content"
        )
        if consumed_kinds is None or kind in consumed_kinds:
            changed_kinds.add(kind)
    return tuple(sorted(changed_kinds))


def _consumed_axe_part_kinds(*, consume_details: bool) -> frozenset[str]:
    """Return axe token kinds the current consumer actually reads."""
    if consume_details:
        return _AXE_ALWAYS_KINDS | _AXE_DETAIL_KINDS
    return _AXE_ALWAYS_KINDS


def axe_token_consumer_drifted(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
    *,
    consume_details: bool,
) -> bool:
    """Return True when consumed axe parts cannot be treated as unchanged.

    Lumberjack ``status.json`` / ``metrics.json`` / ``output.log`` rewrite
    every tick with heartbeat fields the Agents tab does not display.
    Those parts only invalidate the Services dashboard and visible logs.
    """
    if current is None or last is None:
        return True
    if current.indeterminate or last.indeterminate:
        return True
    kinds = _consumed_axe_part_kinds(consume_details=consume_details)
    return _parts_for_kinds(current, kinds) != _parts_for_kinds(last, kinds)


def axe_token_changed_kinds(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
    *,
    consume_details: bool,
) -> tuple[str, ...]:
    """Return changed, currently consumed AXE token-part labels."""
    return surface_token_changed_kinds(
        current,
        last,
        consumed_kinds=_consumed_axe_part_kinds(consume_details=consume_details),
    )


def agents_token_reload_kind(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
    *,
    watcher_active: bool,
) -> str:
    """Return ``skip`` or ``load`` for an Agents token pair.

    Index-only metadata churn is not a roster change. With a watcher the
    exact artifact-dir path is already queued; without one the poll
    fallback still loads. Pulse, artifacts-dir, and membership parts stay
    load signals.
    """
    if current is None or last is None:
        return "load"
    if current.indeterminate or last.indeterminate:
        return "load"
    changed = _surface_token_changed_entries(current, last)
    if not changed:
        return "skip"
    kinds = {kind for _path, kind in changed}
    if kinds <= {"index"}:
        return "skip" if watcher_active else "load"
    return "load"


def _surface_token_changed_entries(
    current: SurfaceToken,
    last: SurfaceToken,
) -> tuple[tuple[str, str], ...]:
    """Return ``(path, kind)`` for parts whose metadata differs."""
    current_map = _part_map(current)
    last_map = _part_map(last)
    changed: list[tuple[str, str]] = []
    for path in sorted(set(current_map) | set(last_map)):
        current_entry = current_map.get(path)
        last_entry = last_map.get(path)
        if current_entry == last_entry:
            continue
        kind = (
            current_entry[3]
            if current_entry is not None
            else last_entry[3]
            if last_entry is not None
            else "content"
        )
        changed.append((path, kind))
    return tuple(changed)


def _kind_at(token: SurfaceToken, index: int) -> str:
    if index < len(token.part_kinds) and token.part_kinds[index]:
        return token.part_kinds[index]
    return "content"


def _part_map(
    token: SurfaceToken,
) -> dict[str, tuple[bool, int | None, int | None, str]]:
    mapped: dict[str, tuple[bool, int | None, int | None, str]] = {}
    for index, (path, exists, mtime_ns, size) in enumerate(token.parts):
        mapped[path] = (exists, mtime_ns, size, _kind_at(token, index))
    return mapped


def _parts_for_kinds(
    token: SurfaceToken, kinds: frozenset[str]
) -> tuple[tuple[str, bool, int | None, int | None], ...]:
    return tuple(
        part
        for index, part in enumerate(token.parts)
        if _kind_at(token, index) in kinds
    )


__all__ = [
    "agents_token_reload_kind",
    "axe_token_changed_kinds",
    "axe_token_consumer_drifted",
    "surface_token_changed_kinds",
    "surface_token_drifted",
]
