"""Owner-aware Node Finder snapshot builder.

Compatibility facade: the implementation lives in sibling modules
(:mod:`_node_finder_facets`, :mod:`_node_finder_folds`,
:mod:`_node_finder_rows`, :mod:`_node_finder_finalize`, and
:mod:`_node_finder_builder`). This module re-exports the public entry
point so the original import path keeps working.
"""

from __future__ import annotations

from ._node_finder_builder import build_node_finder_snapshot

__all__ = [
    "build_node_finder_snapshot",
]
