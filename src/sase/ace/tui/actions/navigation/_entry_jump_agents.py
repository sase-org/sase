"""Agents-tab entry-jump anchor helpers."""

from __future__ import annotations

from typing import cast

from ._entry_jump_generic import EntryJumpGenericHistoryMixin
from .jump_hints import AgentJumpAnchor


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
        """Snapshot the agents-tab cursor as an agent row or collapsed banner."""
        panel_idx = self._current_agents_panel_idx()
        if panel_idx is None:
            return None

        group_key = getattr(self, "_current_group_key", None)
        if group_key is not None and self._current_agents_banner_is_selectable(
            group_key
        ):
            return ("banner", panel_idx, group_key)

        if 0 <= self.current_idx < len(self._agents):
            return ("agent", self.current_idx, panel_idx)
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

    def _remember_agents_jump_origin_if_changed(
        self,
        *,
        target_idx: int | None,
        target_panel_idx: int | None,
        target_group_key: tuple[str, ...] | None,
    ) -> None:
        """Save the current cursor when an agents jump will change focus."""
        current_panel_idx = self._current_agents_panel_idx()
        panel_changed = (
            target_panel_idx is not None and target_panel_idx != current_panel_idx
        )
        row_changed = target_idx is not None and target_idx != self.current_idx
        group_changed = target_group_key != getattr(self, "_current_group_key", None)
        if row_changed or panel_changed or group_changed:
            self._save_agents_jump_anchor()

    def _agents_jump_anchor_panel_is_valid(self, panel_idx: int) -> bool:
        """Return whether ``panel_idx`` can be assigned in the current panel set."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return panel_idx == 0
        return 0 <= panel_idx < len(panel_group.panel_keys)

    def _agents_jump_banner_anchor_is_valid(
        self,
        *,
        panel_idx: int,
        group_key: tuple[str, ...],
    ) -> bool:
        """Return whether a banner anchor still maps to a selectable banner."""
        if not self._agents_jump_anchor_panel_is_valid(panel_idx):
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

        panel_key = None
        if panel_group is not None:
            panel_key = panel_group.panel_keys[panel_idx]
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
            _, agent_idx, target_panel = anchor
            agent_valid = 0 <= agent_idx < len(self._agents)
            return agent_valid and self._agents_jump_anchor_panel_is_valid(target_panel)

        _, target_panel, group_key = anchor
        return self._agents_jump_banner_anchor_is_valid(
            panel_idx=target_panel,
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

    def _focus_agents_jump_anchor_panel(self, panel_idx: int) -> None:
        """Focus the panel for a validated agents jump anchor."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is not None:
            panel_group.focused_idx = panel_idx

    def _restore_agents_jump_anchor_value(self, anchor: AgentJumpAnchor) -> None:
        """Restore a validated agents-tab anchor."""
        if anchor[0] == "agent":
            _, agent_idx, target_panel = anchor
            self._focus_agents_jump_anchor_panel(target_panel)
            self._current_group_key = None
            self.current_idx = agent_idx
        else:
            _, target_panel, group_key = anchor
            self._focus_agents_jump_anchor_panel(target_panel)
            self._current_group_key = group_key

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
