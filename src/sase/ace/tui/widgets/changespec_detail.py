"""Legacy aliases for patch detail widgets."""

from sase.running_field import get_claimed_workspaces

from ....core.patch import get_workspace_directory_for_patch
from .patch_detail import PatchDetail, SearchQueryPanel, build_query_text

get_workspace_directory_for_changespec = (
    get_workspace_directory_for_patch  # legacy compatibility alias
)

ChangeSpecDetail = PatchDetail  # legacy compatibility alias


__all__ = [
    "ChangeSpecDetail",  # legacy compatibility alias
    "PatchDetail",
    "SearchQueryPanel",
    "build_query_text",
    "get_claimed_workspaces",
    "get_workspace_directory_for_changespec",  # legacy compatibility alias
]
