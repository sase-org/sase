"""Shared foreground-executor helpers needed by more than one split module.

Helpers here carry public names (never ``_``-prefixed) so the split
``executor_*`` modules can import them without tripping the private-import
gate; the leading-``_`` module name keeps them out of the public API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.tool.argv import ResolvedToolArgv


def default_continuation_mode(resolved: ResolvedToolArgv) -> str | None:
    """Return the normal continuation handshake for a resolved named tool."""

    is_run_silent = (
        not resolved.adhoc
        and resolved.tool_name is not None
        and str(resolved.definition.get("stages") or "none") == "run_silent"
    )
    return "never" if is_run_silent else None


__all__ = ["default_continuation_mode"]
