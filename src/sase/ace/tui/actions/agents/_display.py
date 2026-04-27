"""Agent display and refresh methods for the ace TUI app."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...widgets import AgentDetail, AgentList, KeybindingFooter

from ...models.agent_groups import GroupingMode
from ...util.debounce import DetailPanelDebouncer
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

    # Debouncer for j/k navigation detail panel updates
    _agent_detail_debouncer: DetailPanelDebouncer

    _marked_agents: set[tuple[AgentType, str, str | None]]
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    # Banner-target inverse map; agents-tab jump mode populates this when
    # the user presses ``'`` and ``_jump_candidate_targets`` includes any
    # collapsed banners.
    _entry_jump_banner_to_hint: dict[
        tuple[Literal["banner"], int, tuple[str, ...]], str
    ]

    # Group fold + tag-driven panel collection (see startup.py).
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup

    # Countdown for refresh
    _countdown_remaining: int

    # Phase 2 j/k cache (initialized in StartupMixin._init_app_state).
    _panel_keys_cache: tuple[Any, ...] | None

    def _panel_keys_per_agent(self) -> list:
        """Memoized :func:`panel_key_per_agent` keyed on the agents list.

        ``self._agents`` is replaced wholesale by the loading/refilter
        paths, so ``is`` identity is a sufficient invalidation signal —
        when the list ref changes, the cache misses and rebuilds.
        Several call sites per j/k keystroke share this cache so the
        list comprehension over ``self._agents`` runs at most once per
        refresh cycle.
        """
        from ...models.agent_panels import panel_key_per_agent

        cached = getattr(self, "_panel_keys_cache", None)
        if cached is not None and cached[0] is self._agents:
            return cached[1]
        keys = panel_key_per_agent(self._agents)
        self._panel_keys_cache = (self._agents, keys)
        return keys

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
        # Cancel any pending debounced detail update — full refresh supersedes
        self._agent_detail_debouncer.cancel()

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
            banner_jump_hints = (
                dict(self._entry_jump_banner_to_hint)
                if self._entry_jump_mode_active
                else None
            )

            self._refresh_panel_widgets(
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
            )
            log.debug(
                "agents display refresh list phase: elapsed=%.3fs agents=%d",
                time.perf_counter() - list_started,
                len(self._agents),
            )
        else:
            self._refresh_panel_highlights()

        self._update_agents_info_panel()
        if defer_detail:
            self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)
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

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        """Patch a single agent's row in place when no group membership changed.

        Returns ``True`` when the patch landed; ``False`` when the caller
        should fall back to ``_refresh_agents_display(list_changed=True)``.
        Falls back when:

        - the agents tab isn't active (no widget tree to patch);
        - the agent's panel key changed (status/tag moved it across panels);
        - the agent's group key would change under the current grouping
          (e.g. ``BY_STATUS`` and the status flipped between buckets);
        - the AgentList widget rejects the patch (alignment width grew,
          row index drifted, etc.).

        Phase 3 of plans/202604/instant_jk_navigation.md: replaces
        ``_refresh_agents_display(list_changed=True)`` for true
        single-row mutations (approve toggle, mark/unmark, single-tag
        edits) so the OptionList isn't rebuilt for an unchanged shape.
        """
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        if self.current_tab != "agents":
            return False

        try:
            agent_idx = self._agents.index(agent)
        except ValueError:
            return False

        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        agent_panel_key = keys_per_agent[agent_idx]

        # Find which panel currently displays this agent, if any.
        target_panel_idx: int | None = None
        for idx, key in enumerate(self._panel_group.panel_keys):
            if key == agent_panel_key:
                target_panel_idx = idx
                break
        if target_panel_idx is None:
            return False

        wid = _panel_widget_id(target_panel_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            return False

        # Translate the global agent index to the panel-local index by
        # counting agents with the same panel key that come before it.
        local_idx = sum(1 for k in keys_per_agent[:agent_idx] if k == agent_panel_key)

        # Cross-group safety: under BY_STATUS the same agent set can be
        # split across different banners when status flips, and banner
        # chips show per-status counts. The patch path mutates one row's
        # rendered prompt only — banners are not refreshed. Callers that
        # only flip approve/mark/tag never change status, so STANDARD
        # and BY_DATE grouping are always safe; for BY_STATUS we play it
        # safe and fall back so banner counts can't drift.
        if (
            getattr(self, "_grouping_mode", GroupingMode.STANDARD)
            is GroupingMode.BY_STATUS
        ):
            return False

        # Selection state at format time encodes ``is_selected``; derive
        # it from the current cursor so a patched row's name styling
        # matches reality even when the cursor moved between renders.
        is_selected = (
            agent_idx == self.current_idx
            and self.current_attempt_number is None
            and self._current_group_key is None
        )
        ok = widget.patch_agent_row(
            local_idx,
            marked_agents=self._marked_agents,
            is_selected=is_selected,
            now=None,
        )
        if not ok:
            return False

        self._update_agents_info_panel()
        return True

    def _refresh_agents_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the agents tab.

        Updates the list highlight and position counter immediately, but
        debounces the expensive detail panel and footer updates (disk I/O,
        Rich Syntax highlighting, background workers).
        """
        self._refresh_panel_highlights()
        self._update_agents_info_panel()
        self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)

    def _fire_debounced_detail_update(self) -> None:
        """Apply the debounced detail update once the j/k burst quiesces."""
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

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
        from ...models.agent_panels import AgentPanelGroup

        prev_focused = self._panel_group.focused_key
        self._panel_group = AgentPanelGroup.from_agents(self._agents, prev_focused)

        # Make sure current_idx points at an agent in the focused panel.
        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
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

    def _refresh_panel_widgets(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[tuple[Literal["banner"], int, tuple[str, ...]], str]
        | None = None,
    ) -> None:
        """Mount/unmount AgentList widgets to match :attr:`_panel_group`.

        Calls :meth:`AgentList.update_list` on each panel with its
        agent slice.  Sets Textual focus on the focused panel.
        """
        from textual.css.query import NoMatches

        from ...models.agent_panels import agents_for_panel
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

        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
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

            local_banner_hints: dict[tuple[str, ...], str] | None = None
            if banner_jump_hints:
                local_banner_hints = {
                    group_key: hint
                    for (kind, panel_idx, group_key), hint in banner_jump_hints.items()
                    if kind == "banner" and panel_idx == idx
                }
                if not local_banner_hints:
                    local_banner_hints = None

            widget.update_list(
                panel_agents,
                local_idx,
                fold_counts=fold_counts,
                marked_agents=marked,
                jump_hints=local_jump_hints,
                banner_jump_hints=local_banner_hints,
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

        from ...widgets import AgentList

        focused_key = self._panel_group.focused_key
        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
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
        from ._grouping import _MODE_LABELS

        agent_info_panel.update_grouping_mode(
            _MODE_LABELS.get(self._grouping_mode.name, self._grouping_mode.name)
        )
        # Show current panel view mode when an agent is selected
        if self._get_selected_agent() is not None:  # type: ignore[attr-defined]
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_info_panel.update_view_mode(agent_detail.panel_mode_label)
        else:
            agent_info_panel.update_view_mode("")
