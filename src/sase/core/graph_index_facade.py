"""sase.core facade for patch graph index construction.

Wraps
:func:`sase.ace.tui.models.patch_graph_index.build_patch_graph_index`.
This operation is intentionally Python-owned host logic — see the Phase 8A
handoff operation disposition. The facade exists so callers continue to
import from ``sase.core`` and see a stable signature.
"""

from __future__ import annotations

from sase.ace.patch.models import Patch
from sase.ace.tui.models.patch_graph_index import (
    PatchGraphIndex,
    build_patch_graph_index_python,
)

PatchGraphIndex = PatchGraphIndex


def build_patch_graph_index(
    patches: list[Patch],
) -> PatchGraphIndex:
    """Build a :class:`PatchGraphIndex`."""
    return build_patch_graph_index_python(patches)


build_patch_graph_index = build_patch_graph_index
