"""Shared inventory constants for the disk-footprint split.

The names here are public so the sibling ``disk_footprint_inventory_*``
modules can import them without touching a ``_``-prefixed symbol across
files. Each constant keeps the value the former monolithic
:mod:`sase.core.disk_footprint_inventory` module used.
"""

from __future__ import annotations

#: Deepest level below the scan root the stray cargo-target walk descends.
STRAY_MAX_DEPTH = 6

#: Default cap on visited directories for the stray cargo-target walk.
STRAY_MAX_VISITED = 50_000

#: Default wall-clock budget in seconds for the stray cargo-target walk.
STRAY_SCAN_SECONDS = 5.0

#: Path stored on rows whose location cannot be resolved to the filesystem.
UNRESOLVED_PATH = ""


__all__ = [
    "STRAY_MAX_DEPTH",
    "STRAY_MAX_VISITED",
    "STRAY_SCAN_SECONDS",
    "UNRESOLVED_PATH",
]
