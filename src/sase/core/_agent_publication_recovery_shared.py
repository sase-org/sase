"""Shared wire helpers for agent publication recovery.

The names here are public so the sibling ``agent_publication_recovery_*``
modules can import them without touching a ``_``-prefixed symbol across
files. Each value keeps the behavior the former monolithic
:mod:`sase.core.agent_publication_recovery` module used.
"""

from __future__ import annotations

from typing import Any

PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION = 1


def require_str_field(raw: dict[str, Any], key: str) -> str:
    """Return ``raw[key]`` when it is a string, else raise a wire error."""
    value = raw[key]
    if not isinstance(value, str):
        raise RuntimeError(
            f"sase_core_rs publication recovery field {key!r} is not str"
        )
    return value


def require_int(raw: dict[str, Any], key: str) -> int:
    """Return ``raw[key]`` when it is an int, else raise a wire error."""
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(
            f"sase_core_rs publication recovery field {key!r} is not int"
        )
    return value


def require_bool(raw: dict[str, Any], key: str) -> bool:
    """Return ``raw[key]`` when it is a bool, else raise a wire error."""
    value = raw[key]
    if not isinstance(value, bool):
        raise RuntimeError(
            f"sase_core_rs publication recovery field {key!r} is not bool"
        )
    return value


def require_str_tuple(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    """Return ``raw[key]`` when it is a list of strings, else raise."""
    value = raw[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(
            f"sase_core_rs publication recovery field {key!r} is not list[str]"
        )
    return tuple(value)


__all__ = [
    "PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION",
    "require_bool",
    "require_int",
    "require_str_field",
    "require_str_tuple",
]
