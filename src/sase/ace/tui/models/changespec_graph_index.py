"""Legacy aliases for patch graph index construction."""

from .patch_graph_index import (
    PatchGraphIndex,
    build_patch_graph_index,
    build_patch_graph_index_python,
)

ChangeSpecGraphIndex = PatchGraphIndex
build_changespec_graph_index = build_patch_graph_index
build_changespec_graph_index_python = build_patch_graph_index_python

__all__ = [
    "ChangeSpecGraphIndex",
    "build_changespec_graph_index",
    "build_changespec_graph_index_python",
]
