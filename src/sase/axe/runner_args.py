"""Argument parsing helpers shared by background runner entry points."""

from __future__ import annotations

_FALSY_BOOL_ARGS = {"", "0", "false", "no", "off"}


def parse_runner_bool_arg(value: str) -> bool:
    """Parse a shell argv boolean while preserving legacy truthy strings."""
    return value.strip().lower() not in _FALSY_BOOL_ARGS


__all__ = ["parse_runner_bool_arg"]
