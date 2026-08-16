"""Live inline-filter session behavior for the Artifacts Patches pane."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

from sase.ace.query import QueryParseError

from .entry_navigation import ArtifactEntryTarget
from .patch_filter_bar import PatchFilterBar

if TYPE_CHECKING:
    from textual.containers import Horizontal as _MixinBase
else:
    _MixinBase = object


class PatchesFilterSessionMixin(_MixinBase):
    """Own inline Patch filter-bar session state."""

    _patch_filter_session_open: bool
    _patch_filter_restore_query: str | None
    _patch_filter_restore_selection: ArtifactEntryTarget | None

    if TYPE_CHECKING:

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def select_entry_target(self, target: ArtifactEntryTarget) -> bool: ...

    def _init_patches_filter_session(self) -> None:
        self._patch_filter_session_open = False
        self._patch_filter_restore_query = None
        self._patch_filter_restore_selection = None

    def show_filters(self) -> None:
        """Open and focus the inline Patch filter bar."""

        bar = self.query_one(PatchFilterBar)
        app = cast(Any, self.app)
        if self._patch_filter_session_open:
            bar.query_one("#patch-filter-input").focus()
            return

        self._patch_filter_session_open = True
        self._patch_filter_restore_query = app.query_string
        self._patch_filter_restore_selection = self.selected_entry_target()
        index = getattr(app, "_patch_query_index", None)
        if index is not None:
            bar.set_observed_facets(index.facets)
        bar.open(app.query_string)
        bar.set_status(len(app.patches), exact=True, error=None)

    def on_patch_filter_bar_query_changed(
        self,
        event: PatchFilterBar.QueryChanged,
    ) -> None:
        event.stop()
        app = cast(Any, self.app)
        bar = self.query_one(PatchFilterBar)
        if re.match(r"^#(\d)?(.*)$", event.text.strip()):
            bar.set_status(None, exact=False, error=None, coverage_label="save")
            return
        try:
            parsed = app._parse_patch_query(event.text)
        except QueryParseError as exc:
            bar.set_status(None, exact=False, error=exc)
            return

        app._set_patch_live_query(event.text, parsed)
        bar.set_status(len(app.patches), exact=True, error=None)

    def on_patch_filter_bar_submitted(
        self,
        event: PatchFilterBar.Submitted,
    ) -> None:
        event.stop()
        app = cast(Any, self.app)
        bar = self.query_one(PatchFilterBar)
        if re.match(r"^#(\d)?(.*)$", event.text.strip()):
            app._save_patch_query_slot(event.text)
            return
        try:
            app._parse_patch_query(event.text)
        except QueryParseError as exc:
            bar.set_status(None, exact=False, error=exc)
            app.notify(f"Invalid query: {exc}", severity="error")
            return

        app._commit_patch_query(event.text)
        self._close_patch_filter_session()
        self.query_one("#list-panel").focus()

    def on_patch_filter_bar_dismissed(
        self,
        event: PatchFilterBar.Dismissed,
    ) -> None:
        event.stop()
        app = cast(Any, self.app)
        restore_selection = self._patch_filter_restore_selection
        app._clear_patch_live_query()
        if restore_selection is not None:
            self.select_entry_target(restore_selection)
        self._close_patch_filter_session()
        self.query_one("#list-panel").focus()

    def _close_patch_filter_session(self) -> None:
        self.query_one(PatchFilterBar).close()
        self._patch_filter_session_open = False
        self._patch_filter_restore_query = None
        self._patch_filter_restore_selection = None


__all__ = ["PatchesFilterSessionMixin"]
