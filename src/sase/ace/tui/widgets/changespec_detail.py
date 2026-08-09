"""Legacy aliases for patch detail widgets."""

from pathlib import Path
from typing import Any

from sase.running_field import get_claimed_workspaces

from ....core.patch import get_workspace_directory_for_patch
from . import patch_detail as _patch_detail
from .patch_detail import PatchDetail, SearchQueryPanel, build_query_text

get_workspace_directory_for_changespec = get_workspace_directory_for_patch


class ChangeSpecDetail(PatchDetail):
    """Patch detail widget with legacy monkeypatch hook points."""

    def _resolve_delta_workspace_dir(self, patch: Any) -> str | None:
        workspace_dir = get_workspace_directory_for_changespec(patch)
        if workspace_dir is None:
            return None
        return str(Path(workspace_dir).expanduser())

    def _build_running_field(self, text: Any, patch: Any) -> None:
        original = _patch_detail.get_claimed_workspaces
        _patch_detail.get_claimed_workspaces = get_claimed_workspaces
        try:
            super()._build_running_field(text, patch)
        finally:
            _patch_detail.get_claimed_workspaces = original


__all__ = [
    "ChangeSpecDetail",
    "PatchDetail",
    "SearchQueryPanel",
    "build_query_text",
    "get_claimed_workspaces",
    "get_workspace_directory_for_changespec",
]
