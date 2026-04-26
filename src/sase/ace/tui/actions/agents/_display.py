"""Agent display and refresh methods for the ace TUI app."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from textual.timer import Timer

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...widgets import AgentDetail, AgentList, KeybindingFooter

from ...models.agent_groups import GroupingMode
from ._loading import DISMISSABLE_STATUSES

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]
log = logging.getLogger(__name__)

#: id of the untagged "main" panel — kept stable across panel set changes
#: so existing callers (loading shim, prompt-bar mount, tests) continue to
#: work without knowing about the dynamic side panels.
_MAIN_PANEL_ID = "agent-list-panel"


def _panel_widget_id(panel_idx: int) -> str:
    """Return the AgentList widget id for the panel at *panel_idx*.

    Index 0 is the untagged main pane; tag panels follow.
    """
    if panel_idx == 0:
        return _MAIN_PANEL_ID
    return f"{_MAIN_PANEL_ID}-{panel_idx}"


class AgentDisplayMixin:
    """Mixin providing agent display and refresh methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    refresh_interval: int
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _agent_search_query: str

    # Debounce timer for j/k navigation detail panel updates
    _detail_update_timer: Timer | None

    _marked_agents: set[tuple[AgentType, str, str | None]]
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]

    # Group fold + tag-driven panel collection (see startup.py).
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup

    # Countdown for refresh
    _countdown_remaining: int

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        """Refresh the agents tab display.

        Args:
            list_changed: If True, the agent list has changed and needs a full
                rebuild (called from _load_agents). If False, only the selection
                index moved (j/k navigation) — skip the expensive OptionList
                clear-and-rebuild.
        """
        started = time.perf_counter()
        list_started = started
        # Cancel any pending debounce timer — full refresh supersedes
        if self._detail_update_timer is not None:
            self._detail_update_timer.stop()
            self._detail_update_timer = None

        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("agents display refresh skipped: widget tree unavailable")
            return

        if list_changed:
            # Drop any marks pointing at identities that no longer exist.
            self._prune_stale_marked_agents()  # type: ignore[attr-defined]
            self._sync_panel_group()
            jump_hints = (
                dict(self._entry_jump_index_to_hint)
                if self._entry_jump_mode_active
                else None
            )

            self._refresh_panel_widgets(jump_hints=jump_hints)
            log.debug(
                "agents display refresh list phase: elapsed=%.3fs agents=%d",
                time.perf_counter() - list_started,
                len(self._agents),
            )
        else:
            self._refresh_panel_highlights()

        self._update_agents_info_panel()
        if defer_detail:
            self._detail_update_timer = self.set_timer(  # type: ignore[attr-defined]
                0.15, self._fire_debounced_detail_update
            )
            log.debug(
                "agents display refresh deferred detail: elapsed=%.3fs",
                time.perf_counter() - started,
            )
            return

        detail_started = time.perf_counter()
        self._apply_agent_detail_update(agent_detail, footer_widget)
        log.debug(
            "agents display refresh detail phase: elapsed=%.3fs total=%.3fs",
            time.perf_counter() - detail_started,
            time.perf_counter() - started,
        )

    def _refresh_agents_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the agents tab.

        Updates the list highlight and position counter immediately, but
        debounces the expensive detail panel and footer updates (disk I/O,
        Rich Syntax highlighting, background workers).
        """
        self._refresh_panel_highlights()
        self._update_agents_info_panel()

        # Cancel any pending debounce timer before scheduling a new one
        if self._detail_update_timer is not None:
            self._detail_update_timer.stop()

        self._detail_update_timer = self.set_timer(  # type: ignore[attr-defined]
            0.15, self._fire_debounced_detail_update
        )

    def _fire_debounced_detail_update(self) -> None:
        """Timer callback that applies the debounced detail update."""
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        self._detail_update_timer = None

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("debounced detail update skipped: widget tree unavailable")
            return

        self._apply_agent_detail_update(agent_detail, footer_widget)

    # ---------------------------------------------------------------------
    # Panel-collection helpers
    # ---------------------------------------------------------------------

    def _sync_panel_group(self) -> None:
        """Recompute :attr:`_panel_group` from the current :attr:`_agents`.

        Preserves the previously focused panel key when possible; falls
        back to the untagged main pane when its tag's panel disappears.
        Also re-anchors :attr:`current_idx` into the focused panel when
        the previous focus is no longer in it.
        """
        from ...models.agent_panels import AgentPanelGroup, panel_key_per_agent

        prev_focused = self._panel_group.focused_key
        self._panel_group = AgentPanelGroup.from_agents(self._agents, prev_focused)

        # Make sure current_idx points at an agent in the focused panel.
        keys_per_agent = panel_key_per_agent(self._agents)
        focused_key = self._panel_group.focused_key
        if 0 <= self.current_idx < len(self._agents):
            if keys_per_agent[self.current_idx] != focused_key:
                self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)
        else:
            self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)

    def _snap_current_idx_to_focused_panel(
        self, keys_per_agent: list[PanelKey], focused_key: PanelKey
    ) -> None:
        """Set ``current_idx`` to the first agent in the focused panel.

        When the focused panel is empty (e.g. the untagged main when
        every loaded agent is tagged) leaves ``current_idx`` at ``0``.
        """
        for i, k in enumerate(keys_per_agent):
            if k == focused_key:
                self.current_idx = i
                return
        if self._agents:
            self.current_idx = 0

    def _refresh_panel_widgets(self, *, jump_hints: dict[int, str] | None) -> None:
        """Mount/unmount AgentList widgets to match :attr:`_panel_group`.

        Calls :meth:`AgentList.update_list` on each panel with its
        agent slice.  Sets Textual focus on the focused panel.
        """
        from textual.css.query import NoMatches

        from ...models.agent_panels import (
            agents_for_panel,
            panel_key_per_agent,
        )
        from ...widgets import AgentList

        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return

        panel_keys = self._panel_group.panel_keys
        # Mount missing panels (skip index 0 — the main pane is composed
        # statically and lives at id ``agent-list-panel``).
        existing_ids = {w.id for w in container.children if isinstance(w, AgentList)}
        for idx in range(len(panel_keys)):
            wid = _panel_widget_id(idx)
            if wid not in existing_ids:
                container.mount(AgentList(id=wid))
                existing_ids.add(wid)

        # Unmount stale panels (id format ``agent-list-panel-<n>`` whose
        # ``n`` is past the current panel set).
        keep_ids = {_panel_widget_id(i) for i in range(len(panel_keys))}
        for w in list(container.children):
            if isinstance(w, AgentList) and w.id not in keep_ids:
                w.remove()

        keys_per_agent = panel_key_per_agent(self._agents)
        focused_idx = self._panel_group.focused_idx
        fold_registry = self._group_fold_registry
        marked = self._marked_agents
        fold_counts = self._fold_counts
        attempt_number = self.current_attempt_number
        current_group_key = self._current_group_key
        global_idx = self.current_idx
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)

        ordered_widgets: list[AgentList] = []
        for idx, key in enumerate(panel_keys):
            wid = _panel_widget_id(idx)
            try:
                widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
            except NoMatches:
                continue
            ordered_widgets.append(widget)

            panel_agents = agents_for_panel(self._agents, key)
            global_indices = [i for i, k in enumerate(keys_per_agent) if k == key]

            label = "(untagged)" if key is None else f"@{key}"
            widget.border_title = f"{label} · {len(panel_agents)}"

            local_idx = -1
            if idx == focused_idx and 0 <= global_idx < len(self._agents):
                try:
                    local_idx = global_indices.index(global_idx)
                except ValueError:
                    local_idx = -1

            local_jump_hints: dict[int, str] | None = None
            if jump_hints:
                local_jump_hints = {}
                for local_i, gi in enumerate(global_indices):
                    if gi in jump_hints:
                        local_jump_hints[local_i] = jump_hints[gi]

            widget.update_list(
                panel_agents,
                local_idx,
                fold_counts=fold_counts,
                marked_agents=marked,
                jump_hints=local_jump_hints,
                current_attempt_number=attempt_number if idx == focused_idx else None,
                fold_registry=fold_registry,
                current_group_key=current_group_key if idx == focused_idx else None,
                grouping_mode=grouping_mode,
            )

            if idx == focused_idx:
                widget.add_class("-focused-panel")
            else:
                widget.remove_class("-focused-panel")

        self._apply_panel_heights(container, ordered_widgets)
        self._focus_focused_panel_widget()

    # ---------------------------------------------------------------------
    # Per-panel dynamic heights
    # ---------------------------------------------------------------------

    def _apply_panel_heights(self, container: object, widgets: list[AgentList]) -> None:
        """Size each tag panel based on its content.

        Two regimes:

        - **Fits** (Σ natural ≤ container): every panel except the last is
          pinned to its exact natural cell height; the last panel grows to
          fill leftover space via a fractional unit, so no dead zone is left
          beneath the column.
        - **Overflow** (Σ natural > container): weight each panel by
          ``option_count + 1`` (border allowance keeps tiny panels from
          collapsing to nothing) using fractional units.
        """
        if not widgets:
            return

        size = getattr(container, "size", None)
        container_height = getattr(size, "height", 0) if size is not None else 0
        if not container_height:
            # Pre-mount: layout hasn't run yet. The next refresh (after
            # mount completes) will get a real height; the CSS fallback
            # ``height: 1fr`` keeps panels visible until then.
            return

        # Border allowance: ``solid`` borders contribute 2 rows (top + bottom).
        border_rows = 2
        natural_heights = [getattr(w, "option_count", 0) + border_rows for w in widgets]
        total_natural = sum(natural_heights)

        from textual.css.scalar import Scalar, Unit

        if total_natural <= container_height:
            last_idx = len(widgets) - 1
            for idx, (widget, natural) in enumerate(
                zip(widgets, natural_heights, strict=True)
            ):
                if idx == last_idx:
                    widget.styles.height = Scalar(1.0, Unit.FRACTION, Unit.HEIGHT)
                else:
                    widget.styles.height = Scalar(
                        float(natural), Unit.CELLS, Unit.HEIGHT
                    )
        else:
            for widget in widgets:
                # ``option_count + 1`` keeps an empty/tiny panel from
                # weighting to zero in the overflow regime.
                weight = float(getattr(widget, "option_count", 0) + 1)
                widget.styles.height = Scalar(weight, Unit.FRACTION, Unit.HEIGHT)

    def _reapply_panel_heights(self) -> None:
        """Re-run the panel-height computation without rebuilding options.

        Called from the container's ``on_resize`` handler — the panel set
        and option counts haven't changed, only the available height has.
        """
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return
        try:
            widgets = list(
                container.query(AgentList).results(AgentList)  # type: ignore[attr-defined]
            )
        except (AttributeError, NoMatches):
            widgets = [
                w
                for w in getattr(container, "children", [])
                if isinstance(w, AgentList)
            ]
        self._apply_panel_heights(container, widgets)

    def _refresh_panel_highlights(self) -> None:
        """Update the highlight on the focused panel without rebuilding options.

        Used by the j/k debounced refresh path — only the focused panel's
        cursor moves, so we skip the expensive list rebuild on the others.
        """
        from textual.css.query import NoMatches

        from ...models.agent_panels import (
            agents_for_panel,
            panel_key_per_agent,
        )
        from ...widgets import AgentList

        focused_key = self._panel_group.focused_key
        keys_per_agent = panel_key_per_agent(self._agents)
        global_indices = [i for i, k in enumerate(keys_per_agent) if k == focused_key]
        wid = _panel_widget_id(self._panel_group.focused_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        local_idx = -1
        if 0 <= self.current_idx < len(self._agents):
            try:
                local_idx = global_indices.index(self.current_idx)
            except ValueError:
                local_idx = -1
        widget.update_highlight(
            local_idx,
            self.current_attempt_number,
            group_key=self._current_group_key,
        )
        # Make sure the focused panel still wears the focus class even
        # when only the highlight is updated (e.g. after a tag-set
        # change that didn't go through ``_refresh_panel_widgets``).
        try:
            for w in self.query("#agent-list-container AgentList").results(AgentList):  # type: ignore[attr-defined]
                if w.id == wid:
                    w.add_class("-focused-panel")
                else:
                    w.remove_class("-focused-panel")
        except NoMatches:
            pass

    def _focus_focused_panel_widget(self) -> None:
        """Set Textual focus on the focused-panel AgentList."""
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        wid = _panel_widget_id(self._panel_group.focused_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        try:
            widget.focus()
        except Exception:
            # Focus may not be available before mount completes; harmless.
            pass

    # ---------------------------------------------------------------------
    # Detail update + info panel
    # ---------------------------------------------------------------------

    def _apply_agent_detail_update(
        self,
        agent_detail: AgentDetail,
        footer_widget: KeybindingFooter,
    ) -> None:
        """Apply the expensive agent detail panel and footer updates.

        Args:
            agent_detail: The agent detail panel widget.
            footer_widget: The keybinding footer widget.
        """
        current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if current_agent is not None:
            agent_detail.update_display(
                current_agent,
                stale_threshold_seconds=self.refresh_interval,
                attempt_number=self.current_attempt_number,
            )
        else:
            agent_detail.show_empty()

        if getattr(self, "_fold_mode_active", False):
            footer_widget.update_fold_bindings()
        elif getattr(self, "_leader_mode_active", False):
            footer_widget.update_leader_bindings(current_tab="agents")
        elif getattr(self, "_bang_mode_active", False):
            footer_widget.update_bang_bindings()
        elif getattr(self, "_copy_mode_active", False):
            file_visible = agent_detail.is_file_visible()
            footer_widget.update_copy_bindings(
                self.current_tab, file_visible=file_visible
            )
        elif (cm := getattr(self, "_custom_mode_active", None)) is not None:
            footer_widget.update_custom_mode_bindings(cm)
        else:
            completed_count = sum(
                1 for a in self._agents if a.status in DISMISSABLE_STATUSES
            )
            can_jump = (
                self._resolve_agent_cl_name(current_agent) is not None  # type: ignore[attr-defined]
                if current_agent
                else False
            )
            footer_widget.update_agent_bindings(
                current_agent,
                completed_count=completed_count,
                can_jump_to_changespec=can_jump,
                marked_count=len(self._marked_agents),
                attempt_pinned=self.current_attempt_number is not None,
                group_focused=self._current_group_key is not None,
            )

    def _update_agents_info_panel(self) -> None:
        """Update the agents info panel with current position and countdown."""
        from ...widgets import AgentDetail, AgentInfoPanel

        agent_info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)  # type: ignore[attr-defined]
        # Position is 1-based for display; exclude workflow children from count.
        non_child_indices = [
            i for i, a in enumerate(self._agents) if not a.is_workflow_child
        ]
        from bisect import bisect_right

        total = len(non_child_indices)
        if self._agents:
            position = bisect_right(non_child_indices, self.current_idx)
        else:
            position = 0
        agent_info_panel.update_position(position, total)
        agent_info_panel.update_countdown(
            self._countdown_remaining, self.refresh_interval
        )
        agent_info_panel.update_search_query(self._agent_search_query)
        # Show current panel view mode when an agent is selected
        if self._get_selected_agent() is not None:  # type: ignore[attr-defined]
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_info_panel.update_view_mode(agent_detail.panel_mode_label)
        else:
            agent_info_panel.update_view_mode("")
