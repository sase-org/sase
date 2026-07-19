"""Agents-tab entry-jump anchor helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..agents._panel_fold_intent import panel_is_collapsed
from ._entry_jump_generic import EntryJumpGenericHistoryMixin
from .jump_hints import AgentJumpAnchor

if TYPE_CHECKING:
    from ...models.agent_panels import PanelKey


class EntryJumpAgentHistoryMixin(EntryJumpGenericHistoryMixin):
    """Mixin providing Agents-tab entry-jump anchor history."""

    def _current_agents_panel_idx(self) -> int | None:
        """Return the focused agents panel index, or ``None`` if it is stale."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return 0
        panel_idx = getattr(panel_group, "focused_idx", None)
        panel_keys = getattr(panel_group, "panel_keys", [])
        if not isinstance(panel_idx, int):
            return None
        if not (0 <= panel_idx < len(panel_keys)):
            return None
        return panel_idx

    def _current_agents_panel_context(self) -> tuple[int, PanelKey] | None:
        """Return the focused rendered panel index and its stable key."""
        panel_idx = self._current_agents_panel_idx()
        if panel_idx is None:
            return None
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return (panel_idx, None)
        return (panel_idx, panel_group.panel_keys[panel_idx])

    def _current_agents_banner_is_selectable(self, group_key: tuple[str, ...]) -> bool:
        """Return whether ``group_key`` is a selectable banner in this panel."""
        stops_fn = getattr(self, "_panel_navigation_stops", None)
        if not callable(stops_fn):
            return True
        try:
            stops = stops_fn()
        except Exception:
            return True
        return any(kind == "banner" and payload == group_key for kind, payload in stops)

    def _current_agents_jump_anchor(self) -> AgentJumpAnchor | None:
        """Snapshot the agents cursor as a panel, agent row, or group banner."""
        panel_context = self._current_agents_panel_context()
        if panel_context is None:
            return None
        _panel_idx, panel_key = panel_context

        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        panel_group = getattr(self, "_panel_group", None)
        if panel_focus is not None or (
            panel_group is not None and panel_is_collapsed(self, panel_key)
        ):
            return ("panel", panel_key)

        group_key = getattr(self, "_current_group_key", None)
        if group_key is not None and self._current_agents_banner_is_selectable(
            group_key
        ):
            return ("banner", panel_key, group_key)

        if 0 <= self.current_idx < len(self._agents):
            return ("agent", self.current_idx, panel_key)
        return None

    def _entry_jump_agents_forward_stack(self) -> list[AgentJumpAnchor]:
        """Return the Agents tab's jump-forward stack."""
        stack = getattr(self, "_entry_jump_agents_forward_anchor_stack", None)
        if stack is None:
            stack = []
            self._entry_jump_agents_forward_anchor_stack = stack
        return cast("list[AgentJumpAnchor]", stack)

    def _push_agents_jump_anchor(
        self,
        stack: list[AgentJumpAnchor],
        anchor: AgentJumpAnchor,
    ) -> None:
        """Push an Agents anchor without adjacent duplicates."""
        if not stack or stack[-1] != anchor:
            stack.append(anchor)

    def _clear_agents_jump_forward_stack(self) -> None:
        """Clear Agents-tab forward history after a new explicit jump."""
        self._entry_jump_agents_forward_stack().clear()

    def _save_agents_jump_anchor(self) -> None:
        """Push the agents-tab cursor (agent or banner) for ``'`` back-jump."""
        anchor = self._current_agents_jump_anchor()
        if anchor is not None:
            self._push_agents_jump_anchor(self._entry_jump_agents_anchor_stack, anchor)
            self._clear_agents_jump_forward_stack()

    def _rebase_latest_agents_jump_anchor(
        self,
        origin_identity: tuple[object, str, str | None],
    ) -> None:
        """Re-resolve a just-saved row anchor after a structural refilter."""
        stack = getattr(self, "_entry_jump_agents_anchor_stack", None)
        if not isinstance(stack, list) or not stack or stack[-1][0] != "agent":
            return
        matches = [
            idx
            for idx, agent in enumerate(self._agents)
            if agent.identity == origin_identity
        ]
        if len(matches) != 1:
            return
        origin_idx = matches[0]
        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        if not (0 <= origin_idx < len(keys_per_agent)):
            return
        stack[-1] = ("agent", origin_idx, keys_per_agent[origin_idx])

    def _remember_agents_jump_origin_if_changed(
        self,
        *,
        target_idx: int | None,
        target_panel_key: PanelKey,
        target_group_key: tuple[str, ...] | None,
        target_is_panel: bool = False,
    ) -> None:
        """Save the current cursor when an agents jump will change focus."""
        panel_context = self._current_agents_panel_context()
        current_panel_key = panel_context[1] if panel_context is not None else None
        panel_changed = target_panel_key != current_panel_key
        row_changed = target_idx is not None and target_idx != self.current_idx
        group_changed = target_group_key != getattr(self, "_current_group_key", None)
        current_anchor = self._current_agents_jump_anchor()
        panel_focus_changed = target_is_panel and (
            current_anchor is None or current_anchor[0] != "panel"
        )
        if row_changed or panel_changed or group_changed or panel_focus_changed:
            self._save_agents_jump_anchor()

    def _agents_jump_panel_idx_for_key(self, panel_key: str | None) -> int | None:
        """Resolve a stable panel key against the current rendered panel order."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return 0 if panel_key is None else None
        try:
            return panel_group.panel_keys.index(panel_key)
        except ValueError:
            return None

    def _agents_jump_panel_anchor_is_valid(self, panel_key: str | None) -> bool:
        """Return whether a whole-panel anchor still names a split panel."""
        return (
            not getattr(self, "_agent_panels_grouped", False)
            and self._agents_jump_panel_idx_for_key(panel_key) is not None
        )

    def _agents_jump_banner_anchor_is_valid(
        self,
        *,
        panel_key: PanelKey,
        group_key: tuple[str, ...],
    ) -> bool:
        """Return whether a banner anchor still maps to a selectable banner."""
        panel_idx = self._agents_jump_panel_idx_for_key(panel_key)
        if panel_idx is None:
            return False

        panel_group = getattr(self, "_panel_group", None)
        stops_fn = getattr(self, "_panel_navigation_stops", None)
        if callable(stops_fn):
            old_focused_idx = (
                panel_group.focused_idx if panel_group is not None else None
            )
            try:
                if panel_group is not None:
                    panel_group.focused_idx = panel_idx
                stops = stops_fn()
            except Exception:
                stops = None
            finally:
                if panel_group is not None and old_focused_idx is not None:
                    panel_group.focused_idx = old_focused_idx
            if stops is not None:
                return any(
                    kind == "banner" and payload == group_key for kind, payload in stops
                )

        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ..agents._fold_scope import panel_fold_registry
        from ..agents._navigation_order import rendered_panel_slice

        registry = panel_fold_registry(self, panel_key)
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        _global_indices, panel_agents = rendered_panel_slice(self, panel_key)
        tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
        return any(
            entry.kind == "group"
            and entry.group is not None
            and entry.group.is_collapsed
            and entry.group.group_key == group_key
            for entry in tree
        )

    def _agents_jump_anchor_is_valid(self, anchor: AgentJumpAnchor) -> bool:
        """Return whether an agents jump anchor can still be restored."""
        if anchor[0] == "agent":
            _, agent_idx, panel_key = anchor
            if not (0 <= agent_idx < len(self._agents)):
                return False
            panel_idx = self._agents_jump_panel_idx_for_key(panel_key)
            if panel_idx is None:
                return False
            keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
            return (
                0 <= agent_idx < len(keys_per_agent)
                and keys_per_agent[agent_idx] == panel_key
            )

        if anchor[0] == "panel":
            return self._agents_jump_panel_anchor_is_valid(anchor[1])

        _, panel_key, group_key = anchor
        return self._agents_jump_banner_anchor_is_valid(
            panel_key=panel_key,
            group_key=group_key,
        )

    def _pop_agents_jump_anchor(
        self,
        stack: list[AgentJumpAnchor] | None = None,
    ) -> AgentJumpAnchor | None:
        """Pop and return the latest valid agents-tab jump anchor."""
        target_stack = (
            stack if stack is not None else self._entry_jump_agents_anchor_stack
        )
        while target_stack:
            anchor = target_stack.pop()
            if self._agents_jump_anchor_is_valid(anchor):
                return anchor
        return None

    def _focus_agents_jump_anchor_panel(self, panel_key: PanelKey) -> bool:
        """Focus the panel for a validated agents jump anchor."""
        panel_idx = self._agents_jump_panel_idx_for_key(panel_key)
        if panel_idx is None:
            return False
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is not None:
            panel_group.focused_idx = panel_idx
        return True

    def _restore_agents_jump_anchor_value(self, anchor: AgentJumpAnchor) -> None:
        """Restore a validated agents-tab anchor."""
        if anchor[0] == "agent":
            _, agent_idx, panel_key = anchor
            if not self._focus_agents_jump_anchor_panel(panel_key):
                return
            self._expanded_panel_focus = False
            self._current_group_key = None
            self.current_idx = agent_idx
        elif anchor[0] == "banner":
            _, panel_key, group_key = anchor
            if not self._focus_agents_jump_anchor_panel(panel_key):
                return
            self._expanded_panel_focus = False
            self._current_group_key = group_key
        else:
            _, panel_key = anchor
            if not self._focus_agents_jump_anchor_panel(panel_key):
                return
            self._expanded_panel_focus = not panel_is_collapsed(self, panel_key)
            self._current_group_key = None
            self.current_attempt_number = None
            keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
            self._snap_current_idx_to_focused_panel(  # type: ignore[attr-defined]
                keys_per_agent,
                panel_key,
            )

    def _restore_agents_jump_anchor(self) -> bool:
        """Pop and restore the latest agents-tab anchor.  Returns True on success."""
        anchor = self._pop_agents_jump_anchor()
        if anchor is None:
            return False

        current_anchor = self._current_agents_jump_anchor()
        if current_anchor is not None:
            self._push_agents_jump_anchor(
                self._entry_jump_agents_forward_stack(),
                current_anchor,
            )
        self._restore_agents_jump_anchor_value(anchor)
        return True

    def _panel_idx_for_agent_jump_target(self, agent_idx: int) -> int | None:
        """Return the current panel index that contains ``agent_idx``."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None or not (0 <= agent_idx < len(self._agents)):
            return None

        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        if not (0 <= agent_idx < len(keys_per_agent)):
            return None
        panel_key = keys_per_agent[agent_idx]
        try:
            return panel_group.panel_keys.index(panel_key)
        except ValueError:
            return None
