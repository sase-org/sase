"""Navigation state and row modeling for the artifact panel modal."""

from __future__ import annotations

from .artifact_panel_state_models import (
    ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
    ARTIFACT_PANEL_GROUP_PAGE_SIZE,
    ARTIFACT_PANEL_SHOW_MORE_ACTION,
    ArtifactPanelNavigationState,
    ArtifactPanelPagedModel,
    ArtifactPanelRelationPageKey,
    ArtifactPanelRow,
    ArtifactPanelRows,
)
from .artifact_panel_state_paging import (
    merge_relation_page_into_model,
    page_request_for_group,
    paged_model_from_legacy_detail,
    paged_model_from_paged_detail,
    parent_id_from_detail,
)
from .artifact_panel_state_rows import (
    build_artifact_panel_rows,
    build_artifact_search_rows,
)

_ArtifactPanelRelationPageKey = ArtifactPanelRelationPageKey
_ArtifactPanelRows = ArtifactPanelRows

__all__ = [
    "ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT",
    "ARTIFACT_PANEL_GROUP_PAGE_SIZE",
    "ARTIFACT_PANEL_SHOW_MORE_ACTION",
    "ArtifactPanelNavigationState",
    "ArtifactPanelPagedModel",
    "ArtifactPanelRelationPageKey",
    "ArtifactPanelRow",
    "ArtifactPanelRows",
    "_ArtifactPanelRelationPageKey",
    "_ArtifactPanelRows",
    "build_artifact_panel_rows",
    "build_artifact_search_rows",
    "merge_relation_page_into_model",
    "page_request_for_group",
    "paged_model_from_legacy_detail",
    "paged_model_from_paged_detail",
    "parent_id_from_detail",
]
