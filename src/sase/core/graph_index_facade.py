"""sase.core facade for ChangeSpec graph index construction.

Phase 0A: thin wrapper around
:func:`sase.ace.tui.models.changespec_graph_index.build_changespec_graph_index`.
Phase 0B will route the public function through this dispatched entry point.
"""

from __future__ import annotations

from sase.ace.changespec.models import ChangeSpec
from sase.ace.tui.models.changespec_graph_index import (
    ChangeSpecGraphIndex,
    build_changespec_graph_index_python,
)
from sase.core.backend import dispatch


def build_changespec_graph_index(
    changespecs: list[ChangeSpec],
) -> ChangeSpecGraphIndex:
    """Build a :class:`ChangeSpecGraphIndex` via the active backend."""
    return dispatch(
        operation="build_changespec_graph_index",
        python_impl=build_changespec_graph_index_python,
        args=(changespecs,),
    )
