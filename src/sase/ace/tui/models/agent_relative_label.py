"""Relative agent labels shared by the rail and the jump legend."""

from __future__ import annotations

__all__ = ["relative_agent_label"]


def relative_agent_label(name: str | None, prefix: str | None) -> str:
    """Return *name* relative to *prefix* when it extends it.

    When *name* starts with *prefix* and the remainder starts with ``.``
    or ``--`` and is longer than that separator, the remainder is
    returned (``.cld``, ``--plan``). Otherwise the full name is
    returned. ``None`` anchors give the full name.
    """
    full = name or ""
    if not prefix or not full.startswith(prefix):
        return full
    remainder = full[len(prefix) :]
    for separator in ("--", "."):
        if remainder.startswith(separator) and len(remainder) > len(separator):
            return remainder
    return full
