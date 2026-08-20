"""App actions that raise or lower the Artifacts host-owned ``limit:`` cap."""

from __future__ import annotations

from typing import Any, Literal

from sase.ace import config as ace_config
from sase.ace.query.limit_token import (
    LimitTokenError,
    adjust_limit,
    extract_limit,
    replace_limit,
)

from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts.entry_navigation import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
)

LimitDirection = Literal["load_more", "unload"]


def restore_selection_after_limit(
    pane: ArtifactEntryNavigator,
    preferred: ArtifactEntryTarget | None,
) -> None:
    """Keep the current row when it remains visible; otherwise take the last."""

    if preferred is None:
        return
    if pane.selected_entry_target() == preferred:
        return
    if preferred in pane.entry_targets():
        pane.select_entry_target(preferred)
        return
    targets = pane.entry_targets()
    if targets:
        pane.select_entry_target(targets[-1])


class ArtifactsLimitActionsMixin:
    """Ctrl+J / Ctrl+K paging for every Artifacts sub-tab."""

    current_tab: Any
    query_string: str

    def action_artifacts_load_more(self) -> None:
        """Raise the active pane's committed ``limit:`` by one page."""

        self._adjust_artifacts_limit("load_more")

    def action_artifacts_unload(self) -> None:
        """Lower the active pane's committed ``limit:`` by one page."""

        self._adjust_artifacts_limit("unload")

    def _adjust_artifacts_limit(self, direction: LimitDirection) -> None:
        if self.current_tab != ARTIFACTS_TAB:
            return
        query = self._active_artifacts_limit_query()
        if query is None:
            return
        try:
            _remainder, cap = extract_limit(query)
        except LimitTokenError:
            return
        page_size = ace_config.get_ace_page_size()
        new_cap = adjust_limit(cap, page_size, direction)
        if new_cap == cap or new_cap is None:
            return
        new_query = replace_limit(query, new_cap)
        self._commit_artifacts_limit_query(new_query, direction=direction)

    def _active_artifacts_limit_query(self) -> str | None:
        pane_key = getattr(self, "current_artifacts_pane_key", "patches")
        if pane_key == "patches":
            display = getattr(self, "_display_patch_query", None)
            if callable(display):
                return str(display())
            return self.query_string
        pane = self._artifacts_limit_pane()
        if pane is None:
            return None
        host_query = getattr(pane, "host_limit_query", None)
        if callable(host_query):
            return str(host_query())
        return None

    def _commit_artifacts_limit_query(
        self,
        query: str,
        *,
        direction: LimitDirection,
    ) -> None:
        pane_key = getattr(self, "current_artifacts_pane_key", "patches")
        if pane_key == "patches":
            self._commit_patches_limit_query(query)
            return
        pane = self._artifacts_limit_pane()
        if pane is None:
            return
        apply = getattr(pane, "apply_host_limit_query", None)
        if not callable(apply):
            return
        if pane_key == "files" or _is_document_pane_key(pane_key):
            apply(query, grow=direction == "load_more")
            return
        apply(query)

    def _commit_patches_limit_query(self, query: str) -> None:
        pane = self._artifacts_entry_navigator("patches")  # type: ignore[attr-defined]
        preferred = None if pane is None else pane.selected_entry_target()
        from sase.ace.query import QueryParseError

        try:
            self._commit_patch_query(query, notify=False)  # type: ignore[attr-defined]
        except QueryParseError:
            return
        if pane is not None and getattr(pane, "_patch_filter_session_open", False):
            from ..widgets.artifacts.patch_filter_bar import PatchFilterBar

            pane.query_one(PatchFilterBar).set_query(query)
        if pane is not None:
            restore_selection_after_limit(pane, preferred)

    def _artifacts_limit_pane(self) -> Any | None:
        pane_key = getattr(self, "current_artifacts_pane_key", "patches")
        if pane_key == "stitches":
            return self._commits_pane()  # type: ignore[attr-defined]
        if pane_key == "beads":
            return self._beads_pane()  # type: ignore[attr-defined]
        if pane_key == "files":
            return self._files_pane()  # type: ignore[attr-defined]
        if _is_document_pane_key(pane_key):
            return self._active_documents_pane()  # type: ignore[attr-defined]
        return self._artifacts_entry_navigator()  # type: ignore[attr-defined]


def _is_document_pane_key(pane_key: object) -> bool:
    if not isinstance(pane_key, str):
        return False
    from ..artifact_tabs import is_document_artifacts_pane

    return is_document_artifacts_pane(pane_key)


__all__ = [
    "ArtifactsLimitActionsMixin",
    "restore_selection_after_limit",
]
