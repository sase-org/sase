"""sase.core facade for ChangeSpec graph index construction.

Wraps
:func:`sase.ace.tui.models.changespec_graph_index.build_changespec_graph_index`.
This operation is intentionally Python-owned host logic — see the Phase 8A
handoff operation disposition. The facade exists so callers continue to
import from ``sase.core`` and see a stable signature.
"""

from __future__ import annotations

from sase.ace.changespec.models import ChangeSpec
from sase.ace.tui.models.changespec_graph_index import (
    ChangeSpecGraphIndex,
    build_changespec_graph_index_python,
)


def build_changespec_graph_index(
    changespecs: list[ChangeSpec],
) -> ChangeSpecGraphIndex:
    """Build a :class:`ChangeSpecGraphIndex`."""
    return build_changespec_graph_index_python(changespecs)
