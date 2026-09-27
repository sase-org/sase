"""Group-fold staleness detection for the incremental display path."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models.agent_panels import PanelKey


class GroupFoldStaleMixin:
    """Report panels whose rows were built under different fold state."""

    def _group_fold_stale_panel_keys(self) -> set[Any]:
        """Return panel keys whose widget rows predate the live fold state.

        Compares each widget's ``_rendered_group_folds`` snapshot (recorded
        by ``build_list`` / ``try_insert_rows``) against the live
        ``panel_fold_registry`` snapshot. No disk I/O, no tree building: this
        runs on every finalize.
        """
        from textual.css.query import NoMatches

        from ...models.group_fold import group_fold_snapshot
        from ._display_helpers import panel_widget_id_for_key, panel_widget_is_retiring
        from ._fold_scope import panel_fold_registry

        stale: set[Any] = set()
        panel_keys = list(
            getattr(getattr(self, "_panel_group", None), "panel_keys", ())
        )
        query_one = getattr(self, "query_one", None)
        if not callable(query_one):
            return stale
        for key in panel_keys:
            try:
                widget = query_one(f"#{panel_widget_id_for_key(key)}")  # type: ignore[misc]
            except NoMatches:
                continue
            except Exception:
                continue
            if panel_widget_is_retiring(widget):
                continue
            if bool(getattr(widget, "_panel_collapsed", False)):
                continue
            if not list(getattr(widget, "_agents", None) or []):
                continue
            rendered = getattr(widget, "_rendered_group_folds", None)
            current = group_fold_snapshot(panel_fold_registry(self, key))
            if rendered != current:
                stale.add(key)
        return stale


__all__ = ["GroupFoldStaleMixin"]
