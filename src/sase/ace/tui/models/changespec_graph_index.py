"""Legacy aliases for patch graph index construction."""

from .patch_graph_index import (
    PatchGraphIndex,
    build_patch_graph_index,
    build_patch_graph_index_python,
)

ChangeSpecGraphIndex = PatchGraphIndex  # legacy compatibility alias
build_changespec_graph_index = build_patch_graph_index  # legacy compatibility alias
build_changespec_graph_index_python = (  # legacy compatibility alias
    build_patch_graph_index_python
)

__all__ = [
    "PatchGraphIndex",
    "build_patch_graph_index",
    "build_patch_graph_index_python",
    "ChangeSpecGraphIndex",  # legacy compatibility alias
    "build_changespec_graph_index",  # legacy compatibility alias
    "build_changespec_graph_index_python",  # legacy compatibility alias
]
