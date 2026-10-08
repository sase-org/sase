"""Command implementations for the ``sase artifact`` CLI group.

Package-level attributes are lazy re-exports (PEP 562): importing
``sase.artifact_cli`` (including implicitly, via
``import sase.artifact_cli.<submodule>``) does not import any command
handler submodule until the corresponding attribute is actually accessed.
This keeps the TUI startup closure — which only ever needs the narrow
``references`` submodule — from paying for every artifact command handler
on every launch.
"""

from __future__ import annotations

from typing import Any

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS = {
    "handle_create": ("sase.artifact_cli.create", "handle_create"),
    "handle_doctor": ("sase.artifact_cli.doctor", "handle_doctor"),
    "handle_link": ("sase.artifact_cli.link", "handle_link"),
    "handle_list": ("sase.artifact_cli.listing", "handle_list"),
    "handle_open": ("sase.artifact_cli.open", "handle_open"),
    "handle_pane": ("sase.artifact_cli.pane", "handle_pane"),
    "handle_path": ("sase.artifact_cli.path", "handle_path"),
    "handle_prune": ("sase.artifact_cli.prune", "handle_prune"),
    "handle_prune_runs": ("sase.artifact_cli.prune_runs", "handle_prune_runs"),
    "handle_read": ("sase.artifact_cli.read", "handle_read"),
    "handle_reclaim": ("sase.artifact_cli.reclaim", "handle_reclaim"),
    "handle_show": ("sase.artifact_cli.show", "handle_show"),
    "handle_stats": ("sase.artifact_cli.stats", "handle_stats"),
    "handle_trash": ("sase.artifact_cli.trash", "handle_trash"),
}


def __getattr__(name: str) -> Any:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__

__all__ = [
    "handle_create",
    "handle_doctor",
    "handle_link",
    "handle_list",
    "handle_open",
    "handle_pane",
    "handle_path",
    "handle_prune",
    "handle_prune_runs",
    "handle_read",
    "handle_reclaim",
    "handle_show",
    "handle_stats",
    "handle_trash",
]
