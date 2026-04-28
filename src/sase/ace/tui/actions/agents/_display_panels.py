"""Panel-widget refresh helpers for the agent display mixin.

Holds the panel-collection / per-panel widget plumbing extracted from
:mod:`._display`: mounting and unmounting AgentList widgets, sizing them,
moving the focused-panel highlight, and the single-row patch path used
when an in-place mutation doesn't need a full rebuild.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...widgets import AgentList

from ...models.agent_groups import GroupingMode
from ...util.trace import tui_trace
from ._display_helpers import TabName, panel_widget_id

log = logging.getLogger(__name__)


class PanelsMixin:
    """Per-panel widget mount, layout, and highlight helpers.

    Type hints below declare attributes that are defined at runtime by
    AceApp (and by :class:`AgentDisplayMixin` in particular).
    """

    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup

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
        with tui_trace(
            "agents.refresh_panel_widgets",
            agents=len(self._agents),
            panels=len(self._panel_group.panel_keys),
        ):
            self._refresh_panel_widgets_impl(
                jump_hints=jump_hints, banner_jump_hints=banner_jump_hints
            )

    def _refresh_panel_widgets_impl(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[tuple[Literal["banner"], int, tuple[str, ...]], str]
        | None = None,
    ) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return

        panel_keys = self._panel_group.panel_keys
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        # Mount missing panels (skip index 0 — the main pane is composed
        # statically and lives at id ``agent-list-panel``).
        existing_ids = {w.id for w in container.children if isinstance(w, AgentList)}
        for idx in range(len(panel_keys)):
            wid = panel_widget_id(idx)
            if wid not in existing_ids:
                container.mount(AgentList(id=wid))
                existing_ids.add(wid)

        # Unmount stale panels (id format ``agent-list-panel-<n>`` whose
        # ``n`` is past the current panel set).
        keep_ids = {panel_widget_id(i) for i in range(len(panel_keys))}
        for w in list(container.children):
            if isinstance(w, AgentList) and w.id not in keep_ids:
                w.remove()

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
            wid = panel_widget_id(idx)
            try:
                widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
            except NoMatches:
                continue
            ordered_widgets.append(widget)

            slot = panel_index.slice_for(key)
            panel_agents = slot.agents
            global_indices = slot.global_indices
            global_to_local = slot.global_to_local

            label = "(untagged)" if key is None else f"@{key}"
            widget.border_title = f"{label} · {len(panel_agents)}"

            local_idx = -1
            if idx == focused_idx and 0 <= global_idx < len(self._agents):
                local_idx = global_to_local.get(global_idx, -1)

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

        - **Fits** (Σ natural ≤ container): the first panel (the untagged
          main pane) grows to fill leftover space via a fractional unit, so
          no dead zone is left beneath the column; later tag panels are
          pinned to their exact natural cell heights.
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
            for idx, (widget, natural) in enumerate(
                zip(widgets, natural_heights, strict=True)
            ):
                if idx == 0:
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

    # ---------------------------------------------------------------------
    # Highlights and focus
    # ---------------------------------------------------------------------

    def _refresh_panel_highlights(self) -> None:
        """Update the highlight on the focused panel without rebuilding options.

        Used by the j/k debounced refresh path — only the focused panel's
        cursor moves, so we skip the expensive list rebuild on the others.
        """
        with tui_trace("agents.refresh_panel_highlights", agents=len(self._agents)):
            self._refresh_panel_highlights_impl()

    def _refresh_panel_highlights_impl(self) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        focused_key = self._panel_group.focused_key
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        wid = panel_widget_id(self._panel_group.focused_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        local_idx = -1
        if 0 <= self.current_idx < len(self._agents):
            local_idx = panel_index.local_idx_for(focused_key, self.current_idx)
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

        wid = panel_widget_id(self._panel_group.focused_idx)
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
    # Incremental row removal (Phase 4 of plans/202604/tui_perf_v2.md)
    # ---------------------------------------------------------------------

    def _try_remove_agent_rows(
        self,
        removed_identities: set[tuple[AgentType, str, str | None]],
    ) -> bool:
        """Apply optimistic removes in place across panel widgets.

        Returns ``True`` when the in-place fast path landed for every
        affected panel; ``False`` when any conservative gate failed and
        the caller must fall back to a full ``_refresh_agents_display``.

        Conservative gates (all must hold):

        - the agents tab is active;
        - no agent search query is active;
        - grouping mode is :attr:`GroupingMode.STANDARD`;
        - all removed identities live in a single panel;
        - no removed agent is a workflow parent with visible folded children.
        """
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        if not removed_identities:
            return True
        if self.current_tab != "agents":
            return False
        if getattr(self, "_agent_search_query", ""):
            return False
        if (
            getattr(self, "_grouping_mode", GroupingMode.STANDARD)
            is not GroupingMode.STANDARD
        ):
            return False

        # All removed identities must live in a single panel widget.
        if not hasattr(self, "query_one"):
            return False
        try:
            container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return False

        panel_widgets = [w for w in container.children if isinstance(w, AgentList)]
        target_widget: AgentList | None = None
        for widget in panel_widgets:
            widget_identities = {a.identity for a in widget._agents}
            overlap = widget_identities & removed_identities
            if not overlap:
                continue
            if overlap != removed_identities:
                # Identities split across panels -- fall back.
                return False
            if target_widget is not None:
                return False
            target_widget = widget

        if target_widget is None:
            # Nothing to remove on this tab -- treat as a successful no-op
            # so the caller can skip the full rebuild.
            return True

        if not target_widget.try_remove_rows(removed_identities):
            return False

        return True

    # ---------------------------------------------------------------------
    # Single-row patch
    # ---------------------------------------------------------------------

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

        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        agent_panel_key = panel_index.keys_per_agent[agent_idx]

        # Find which panel currently displays this agent, if any.
        target_panel_idx: int | None = None
        for idx, key in enumerate(self._panel_group.panel_keys):
            if key == agent_panel_key:
                target_panel_idx = idx
                break
        if target_panel_idx is None:
            return False

        wid = panel_widget_id(target_panel_idx)
        try:
            widget = self.query_one(f"#{wid}", AgentList)  # type: ignore[attr-defined]
        except NoMatches:
            return False

        local_idx = panel_index.local_idx_for(agent_panel_key, agent_idx)
        if local_idx < 0:
            return False

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

        self._update_agents_info_panel()  # type: ignore[attr-defined]
        return True
