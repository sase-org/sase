"""AgentList panel-widget mounting, removal, and reorder helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._display_helpers import (
    agent_list_widgets_in,
    mark_panel_widget_retiring,
    panel_widget_id,
    panel_widget_id_for_key,
    panel_widget_is_retiring,
)
from ._display_panel_state import PanelRefreshStateMixin
from ._refresh_trace import record_agents_refresh_trace

if TYPE_CHECKING:
    from ...models.agent_panels import PanelKey
    from ...widgets import AgentList


class PanelWidgetMountMixin(PanelRefreshStateMixin):
    """Mount, remove, and reorder AgentList panel widgets."""

    def _panel_widget_id(self, panel_idx: int) -> str:
        """Test-compat wrapper: tribe-stable id for the current slot index."""
        keys = getattr(getattr(self, "_panel_group", None), "panel_keys", ())
        if 0 <= panel_idx < len(keys):
            return panel_widget_id_for_key(keys[panel_idx])
        return panel_widget_id(panel_idx)

    def _unmount_agent_list(self, container: object, widget: AgentList) -> None:
        """Retire one AgentList from *container*, including test fakes.

        The widget is hidden synchronously and marked retiring *before*
        ``remove()`` is called: Textual's ``remove()`` only schedules a prune,
        so without the marker the widget would linger visibly (and in every
        widget list) until the prune lands a pump cycle later.
        """
        try:
            widget.display = False  # type: ignore[attr-defined]
        except Exception:
            pass
        mark_panel_widget_retiring(widget)
        remove = getattr(widget, "remove", None)
        if callable(remove):
            try:
                remove()
                return
            except Exception:
                pass
        children = getattr(container, "children", None)
        if isinstance(children, list) and widget in children:
            children.remove(widget)

    def _schedule_retired_panel_refresh(self) -> None:
        """Re-run the display refresh after a retired widget's prune lands.

        Only a key re-added while its retiring widget is still mounted needs
        this: the replacement cannot mount until the prune frees the widget
        id, so the sync that observed the re-add returns without it and this
        follow-up completes the mount. The prune was queued before this
        deferral, so it lands first; if the widget is somehow still present
        the sync simply schedules again. Never raises; when no Textual
        deferral is available (tests), the next apply's sync observes the
        pruned container instead.
        """
        refresh = getattr(self, "_refresh_agents_display", None)
        if not callable(refresh):
            return

        def _fire() -> None:
            try:
                refresh(list_changed=True)  # type: ignore[operator]
            except Exception:
                pass

        for attr in ("call_after_refresh", "call_next"):
            defer = getattr(self, attr, None)
            if callable(defer):
                try:
                    defer(_fire)  # type: ignore[operator]
                    return
                except Exception:
                    continue

    def _reorder_agent_list_widgets(
        self,
        container: object,
        ordered: list[AgentList],
    ) -> None:
        """Put mounted AgentList widgets into canonical panel order."""
        if agent_list_widgets_in(container) == ordered:
            return
        move_child = getattr(container, "move_child", None)
        if callable(move_child):
            for idx, widget in enumerate(ordered):
                current = agent_list_widgets_in(container)
                if idx < len(current) and current[idx] is widget:
                    continue
                try:
                    if idx == 0:
                        if current and current[0] is not widget:
                            move_child(widget, before=current[0])
                    else:
                        move_child(widget, after=ordered[idx - 1])
                except Exception:
                    children = getattr(container, "children", None)
                    if isinstance(children, list) and widget in children:
                        children.remove(widget)
                        children.insert(min(idx, len(children)), widget)
            return
        children = getattr(container, "children", None)
        if isinstance(children, list):
            others = [child for child in children if child not in ordered]
            children[:] = list(ordered) + others

    def _sync_mounted_panel_widgets(
        self,
        container: object,
        panel_keys: list[PanelKey],
        *,
        record_costs: bool = True,
    ) -> list[AgentList] | None:
        """Insert, remove, and reorder AgentList widgets to match *panel_keys*.

        Returns ``None`` when a kept key's widget is still retiring from an
        earlier sync: mounting a replacement before the prune lands would
        raise ``DuplicateIds``, and reusing the doomed widget would vanish
        with it, so the replacement mounts in a follow-up refresh scheduled
        from the pending removal instead.
        """
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        existing = {
            widget.id: widget
            for widget in agent_list_widgets_in(container, include_retiring=True)
            if widget.id
        }
        keep_ids = {panel_widget_id_for_key(key) for key in panel_keys}
        inserted = 0
        removed = 0
        readded_pending = False
        for key in panel_keys:
            wid = panel_widget_id_for_key(key)
            if wid in existing:
                if panel_widget_is_retiring(existing[wid]):
                    # Re-added before the prune landed: the id is still taken.
                    readded_pending = True
                continue
            widget = AgentList(id=wid)
            container.mount(widget)  # type: ignore[attr-defined]
            existing[wid] = widget
            inserted += 1

        for widget in list(agent_list_widgets_in(container, include_retiring=True)):
            if widget.id in keep_ids:
                continue
            if panel_widget_is_retiring(widget):
                # An earlier sync already scheduled this widget's prune.
                continue
            self._unmount_agent_list(container, widget)
            removed += 1

        if record_costs:
            source = getattr(self, "_agents_refresh_active_source", "unknown")
            if inserted:
                record_agents_refresh_trace(
                    self,
                    stage="display_patch",
                    source=source,
                    display_cost="display_panel_insert",
                    count=inserted,
                )
            if removed:
                record_agents_refresh_trace(
                    self,
                    stage="display_patch",
                    source=source,
                    display_cost="display_panel_remove",
                    count=removed,
                )
        if readded_pending:
            self._schedule_retired_panel_refresh()
            return None

        ordered: list[AgentList] = []
        for key in panel_keys:
            wid = panel_widget_id_for_key(key)
            mounted: AgentList | None = existing.get(wid)
            if mounted is None or panel_widget_is_retiring(mounted):
                try:
                    mounted = self.query_one(  # type: ignore[attr-defined]
                        f"#{wid}", AgentList
                    )
                except NoMatches:
                    return None
                if panel_widget_is_retiring(mounted):
                    return None
            ordered.append(mounted)

        self._reorder_agent_list_widgets(container, ordered)
        return ordered
