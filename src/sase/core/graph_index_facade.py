"""sase.core facade for ChangeSpec graph index construction.

Wraps
:func:`sase.ace.tui.models.changespec_graph_index.build_changespec_graph_index`
behind :func:`sase.core.backend.dispatch`. A future Rust implementation can
build the same parent/sibling/by-name maps from wire records and register as
``rust_impl``; the call signature stays a list of :class:`ChangeSpec` so
existing TUI callers do not have to change.
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
        rust_unavailable="python",
        args=(changespecs,),
    )
