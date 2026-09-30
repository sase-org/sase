"""Incremental AgentList row mutation helpers.

Public facade for the ``_agent_list_build_patching`` split. Implementation
lives in sibling modules (single-row patches, removes, inserts); this file
re-exports the names that callers historically import from
``_agent_list_build_patching``. Only public names cross module boundaries
here.
"""

from __future__ import annotations

from ._agent_list_build_insert import try_insert_rows
from ._agent_list_build_patch_single import (
    patch_row,
    patch_runtime_suffix_row,
)
from ._agent_list_build_remove import try_remove_rows

__all__ = [
    "patch_row",
    "patch_runtime_suffix_row",
    "try_insert_rows",
    "try_remove_rows",
]
