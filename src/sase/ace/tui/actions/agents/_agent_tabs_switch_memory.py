"""Per-tab selection memory and arrival tracking (tab-state-keys).

``AgentTabsSwitchMemoryMixin`` saves the active tab's selection, panel,
and scroll memory, restores the target tab's memory on switch, and marks
inactive tabs that gained new presentation roots since the last visit.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from sase.core.agent_tab import (
    DEFAULT_AGENT_TAB_KEY,
    AgentTabKey,
)

if TYPE_CHECKING:
    from ...models.agent_tab_index import AgentTabIndex

_NO_SAVED_PANEL_KEY = object()


def _selected_identity_for_owner(owner: Any) -> Any | None:
    """Return the currently selected agent identity, if any."""
    try:
        agents = getattr(owner, "_agents", ()) or ()
        if getattr(owner, "current_tab", None) == "agents":
            idx = int(getattr(owner, "current_idx", 0))
        else:
            idx = int(getattr(owner, "_agents_last_idx", 0))
        if 0 <= idx < len(agents):
            return agents[idx].identity
    except Exception:
        pass
    return getattr(owner, "_agents_last_identity", None)


def _selected_row_index_for_owner(owner: Any) -> int:
    """Return the active tab's selected row index, defaulting to its first row."""
    try:
        agents = getattr(owner, "_agents", ()) or ()
        if getattr(owner, "current_tab", None) == "agents":
            idx = int(getattr(owner, "current_idx", 0))
        else:
            idx = int(getattr(owner, "_agents_last_idx", 0))
        return max(0, idx) if agents else 0
    except Exception:
        return 0


def _focused_panel_key_for_owner(owner: Any) -> Any:
    """Return the focused whole-panel key, if any."""
    for resolver_name in ("_resolve_focused_panel", "_resolve_focused_collapsed_panel"):
        resolver = getattr(owner, resolver_name, None)
        if not callable(resolver):
            continue
        try:
            focus = resolver()
        except Exception:
            continue
        if focus is not None:
            return getattr(focus, "panel_key", _NO_SAVED_PANEL_KEY)
    return _NO_SAVED_PANEL_KEY


def _scroll_anchor_for_owner(owner: Any) -> Any | None:
    """Return the Agents list scroll offset, if queryable."""
    try:
        node = owner.query_one("#agent-list-panel")  # type: ignore[attr-defined]
        return node.scroll_y
    except Exception:
        return None


class AgentTabsSwitchMemoryMixin:
    """Per-tab selection memory and arrival tracking."""

    _active_agent_tab: AgentTabKey
    _agent_tab_index: AgentTabIndex | None
    _agent_tab_memory: dict[AgentTabKey, tuple[Any | None, int, Any, Any | None]]
    _agent_tab_arrivals: set[AgentTabKey]
    _agent_tab_seen_identities: set[Any]
    _agent_tab_arrivals_baselined: bool

    def _ensure_agent_tabs_state(self) -> None:
        """Initialize tab-switch fields for mixin tests that skip startup."""
        defaults: tuple[tuple[str, object], ...] = (
            ("_active_agent_tab", DEFAULT_AGENT_TAB_KEY),
            ("_agent_tab_index", None),
            ("_agent_tab_memory", {}),
            ("_agent_tab_latched_key", None),
            ("_agent_tab_known_labels", {}),
            ("_agent_tab_prev_catalog_keys", ()),
            ("_agent_tabs_reconciled_once", False),
            ("_agent_tabs_user_switched", False),
            ("_agent_tab_load_started", False),
            ("_agent_tab_load_resolved", False),
            ("_agent_tab_loaded_key", None),
            ("_agent_tab_load_worker", None),
            ("_agent_tab_save_pending", None),
            ("_agent_tab_save_task", None),
            ("_agent_tab_save_generation", 0),
            ("_agent_tab_save_completed_generation", 0),
            ("_agent_tab_strip_signature", None),
            ("_agent_tab_arrivals", set()),
            ("_agent_tab_seen_identities", set()),
            ("_agent_tab_arrivals_baselined", False),
            ("_agent_tab_jump_hints", {}),
        )
        for name, value in defaults:
            if not hasattr(self, name):
                setattr(self, name, value)
        active = getattr(self, "_active_agent_tab", None)
        if not isinstance(active, AgentTabKey):
            self._active_agent_tab = DEFAULT_AGENT_TAB_KEY  # type: ignore[attr-defined]

    def _remember_active_tab_memory(self) -> None:
        """Save the active tab's selection, panel, and scroll memory."""
        self._ensure_agent_tabs_state()
        active = self._active_agent_tab  # type: ignore[attr-defined]
        self._agent_tab_memory[active] = (  # type: ignore[attr-defined]
            _selected_identity_for_owner(self),
            _selected_row_index_for_owner(self),
            _focused_panel_key_for_owner(self),
            _scroll_anchor_for_owner(self),
        )

    def _restore_tab_memory(self, key: AgentTabKey) -> None:
        """Restore *key*'s remembered selection with nearest-row fallback."""
        self._ensure_agent_tabs_state()
        memory = self._agent_tab_memory.get(key)  # type: ignore[attr-defined]
        if memory is None:
            identity, remembered_idx, panel_key, scroll_anchor = (
                None,
                0,
                _NO_SAVED_PANEL_KEY,
                None,
            )
        else:
            identity, remembered_idx, panel_key, scroll_anchor = memory
        agents = list(getattr(self, "_agents", ()) or [])
        prior_row: int | None = None
        if identity is not None:
            for pos, row in enumerate(agents):
                try:
                    if row.identity == identity:
                        prior_row = pos
                        break
                except Exception:
                    continue
        if prior_row is None and agents:
            try:
                from ...util.selection import restore_selection_by_identity

                prior_row = restore_selection_by_identity(
                    agents,
                    prior_identity=identity,
                    prior_visual_row=int(remembered_idx or 0),
                    identity_fn=lambda row: row.identity,
                )
            except Exception:
                prior_row = 0
            if prior_row is None or not 0 <= prior_row < len(agents):
                prior_row = 0
        new_idx = prior_row if prior_row is not None else 0
        if not agents:
            new_idx = 0
        if getattr(self, "current_tab", None) == "agents":
            try:
                self.current_idx = new_idx  # type: ignore[attr-defined]
            except Exception:
                pass
        self._agents_last_idx = new_idx  # type: ignore[attr-defined]
        if agents and 0 <= new_idx < len(agents):
            try:
                self._agents_last_identity = agents[new_idx].identity  # type: ignore[attr-defined]
            except Exception:
                self._agents_last_identity = identity  # type: ignore[attr-defined]
        else:
            self._agents_last_identity = None  # type: ignore[attr-defined]
        restored_saved_panel = False
        if panel_key is None or isinstance(panel_key, str):
            panel_group = getattr(self, "_panel_group", None)
            if panel_group is not None:
                panel_keys = getattr(panel_group, "panel_keys", ())
                try:
                    from ...models.agent_panels import normalize_panel_key

                    normalized_panel_key = normalize_panel_key(panel_key)
                    if normalized_panel_key in panel_keys:
                        panel_group.focused_idx = panel_keys.index(normalized_panel_key)
                        from ._panel_fold_intent import panel_is_collapsed

                        if not panel_is_collapsed(self, normalized_panel_key):
                            self._expanded_panel_focus = True  # type: ignore[attr-defined]
                        focus_panel = getattr(self, "_focus_focused_panel_widget", None)
                        if callable(focus_panel):
                            focus_panel()
                        restored_saved_panel = True
                except Exception:
                    pass
        if not restored_saved_panel:
            # First visit, or the remembered panel is gone: select the
            # panel that holds the restored row and drop expanded-panel
            # focus so a previous tab's panel focus cannot carry over.
            self._expanded_panel_focus = False  # type: ignore[attr-defined]
            panel_group = getattr(self, "_panel_group", None)
            keys_for = getattr(self, "_panel_keys_per_agent", None)
            if (
                panel_group is not None
                and callable(keys_for)
                and agents
                and 0 <= new_idx < len(agents)
            ):
                try:
                    per_agent = keys_for()
                    if 0 <= new_idx < len(per_agent):
                        target_key = per_agent[new_idx]
                        panel_keys = getattr(panel_group, "panel_keys", ())
                        if target_key in panel_keys:
                            panel_group.focused_idx = panel_keys.index(target_key)
                    focus_panel = getattr(self, "_focus_focused_panel_widget", None)
                    if callable(focus_panel):
                        focus_panel()
                except Exception:
                    pass
        if scroll_anchor is not None:
            try:
                node = self.query_one("#agent-list-panel")  # type: ignore[attr-defined]
                node.scroll_y = scroll_anchor
            except Exception:
                pass

    def _track_tab_arrivals(self) -> None:
        """Mark inactive tabs that gained a new root since the last visit.

        New presentation-root identities on a non-active tab raise its
        arrival dot; visiting a tab clears its dot. The first catalog
        only baselines what exists so startup paints no dots. Pure
        in-memory work over the already-loaded roster.
        """
        self._ensure_agent_tabs_state()
        index = getattr(self, "_agent_tab_index", None)
        if index is None:
            return
        key_for = getattr(index, "key_for", None)
        if not callable(key_for):
            return
        roster = list(getattr(self, "_agents_with_children", ()) or [])
        try:
            from ...models._agent_tree_anchor import presentation_anchor_lookup

            anchors = presentation_anchor_lookup(roster)
        except Exception:
            return
        active = self._active_agent_tab  # type: ignore[attr-defined]
        seen = self._agent_tab_seen_identities  # type: ignore[attr-defined]
        arrivals = self._agent_tab_arrivals  # type: ignore[attr-defined]
        baselined = bool(getattr(self, "_agent_tab_arrivals_baselined", False))
        current_identities: set[Any] = set()
        seen_root_ids: set[int] = set()
        for row in roster:
            try:
                anchor = anchors.get(id(row), row)
            except Exception:
                anchor = row
            if id(anchor) in seen_root_ids:
                continue
            seen_root_ids.add(id(anchor))
            try:
                identity = anchor.identity
            except Exception:
                continue
            current_identities.add(identity)
            if identity in seen:
                continue
            seen.add(identity)
            if not baselined:
                continue
            try:
                key = key_for(anchor)
            except Exception:
                continue
            if key != active:
                arrivals.add(key)
        try:
            seen.intersection_update(current_identities)
        except Exception:
            pass
        self._agent_tab_arrivals_baselined = True  # type: ignore[attr-defined]
        try:
            arrivals.discard(active)
        except Exception:
            pass


__all__ = [
    "AgentTabsSwitchMemoryMixin",
]
