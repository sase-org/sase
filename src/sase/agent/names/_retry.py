"""Retry-derived agent-name allocation."""

from __future__ import annotations

import re


def allocate_retry_name(
    base: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    """Return the first available ``<base>.r<N>`` retry name.

    Existing exact retry names and their active descendants both reserve the
    numeric slot, so ``foo.r1.plan`` causes the next allocation for ``foo`` to
    skip ``foo.r1``. Legacy ``<base>.<N>`` names do not reserve retry slots.
    """
    pool = _active_retry_reserved_names(base) if reserved is None else reserved
    n = 1
    while True:
        candidate = f"{base}.r{n}"
        if candidate not in pool and not _has_descendant(candidate, pool):
            pool.add(candidate)
            return candidate
        n += 1


def _has_descendant(candidate: str, pool: set[str]) -> bool:
    prefix = f"{candidate}."
    return any(name.startswith(prefix) for name in pool)


def _active_retry_reserved_names(base: str) -> set[str]:
    from sase.agent.names._auto import get_active_agent_name_map

    active = get_active_agent_name_map()
    pattern = re.compile(rf"^{re.escape(base)}\.r\d+(?:\.|$)")
    return {name for name in active if pattern.match(name)}
