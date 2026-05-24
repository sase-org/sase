"""One-key entry jump navigation for the ace TUI app."""

from __future__ import annotations

from typing import cast

from ._types import NavigationMixinBase
from .jump_hints import (
    AgentJumpAnchor,
    BannerJumpTarget,
    EntryJumpAnchor,
    JumpTarget,
    build_jump_hint_maps,
)


class EntryJumpNavigationMixin(NavigationMixinBase):
    """Mixin providing one-key entry jump navigation."""

    # --- Jump To Entry ---

    def action_jump_to_entry(self) -> None:
        """Enter one-key jump mode for the current tab's left-panel entries."""
        if self.current_tab == "agents":
            self._begin_agents_jump_mode()
            return
        if self.current_tab == "changespecs":
            self._begin_changespec_jump_mode()
            return

        if not self._prepare_entry_jump_index_maps(self._jump_candidate_indices()):
            return
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_current_tab()  # type: ignore[attr-defined]

    def action_jump_to_entry_fast(self) -> None:
        """Jump as if ``'`` then ``'`` were pressed, without painting hints."""
        if self.current_tab == "agents":
            prepared = self._prepare_agents_jump_maps()
        elif self.current_tab == "changespecs":
            prepared = self._prepare_changespec_jump_maps()
        else:
            prepared = self._prepare_entry_jump_index_maps(
                self._jump_candidate_indices()
            )
        if not prepared:
            return

        self._entry_jump_mode_active = True
        self._handle_entry_jump_key("apostrophe")

    def action_jump_to_entry_forward(self) -> None:
        """Walk forward through jump points after a back-jump."""
        if self.current_tab == "agents":
            forward_stack = self._entry_jump_agents_forward_stack()
            guard = getattr(self, "_guard_agent_navigation_for_artifact_viewer", None)
            if forward_stack and callable(guard) and guard():
                return

            agent_anchor = self._pop_agents_jump_anchor(forward_stack)
            if agent_anchor is None:
                self._notify_no_next_jump_point()
                return

            current_agent_anchor = self._current_agents_jump_anchor()
            if current_agent_anchor is not None:
                self._push_agents_jump_anchor(
                    self._entry_jump_agents_anchor_stack,
                    current_agent_anchor,
                )
            self._restore_agents_jump_anchor_value(agent_anchor)
            self._refresh_after_entry_jump_restore()
            return

        entry_anchor = self._pop_entry_jump_anchor_from(
            self._entry_jump_forward_stack_map()
        )
        if entry_anchor is None:
            self._notify_no_next_jump_point()
            return

        current_entry_anchor = self._current_entry_jump_anchor()
        if current_entry_anchor is not None:
            self._push_entry_jump_anchor_to_stack(
                self._entry_jump_index_stack,
                current_entry_anchor,
            )
        self._restore_entry_jump_anchor(entry_anchor)
        self._refresh_after_entry_jump_restore()

    def _prepare_entry_jump_index_maps(self, indices: list[int]) -> bool:
        """Allocate generic entry hints without entering/rendering jump mode."""
        if not indices:
            return False
        self._entry_jump_hint_to_index, self._entry_jump_index_to_hint = (
            build_jump_hint_maps(indices)
        )
        return bool(self._entry_jump_hint_to_index)

    def _prepare_changespec_jump_maps(self) -> bool:
        """Allocate CL-row and collapsed-banner hints without rendering them."""
        targets = self._changespec_jump_targets()  # type: ignore[attr-defined]
        if not targets:
            return False
        hint_to_target, _ = build_jump_hint_maps(targets)
        if not hint_to_target:
            return False

        cs_hint_to_idx: dict[str, int] = {}
        cs_idx_to_hint: dict[int, str] = {}
        banner_hint_to_key: dict[str, tuple[str, ...]] = {}
        banner_key_to_hint: dict[tuple[str, ...], str] = {}
        for hint, target in hint_to_target.items():
            kind, payload = target
            if kind == "changespec":
                assert isinstance(payload, int)
                cs_hint_to_idx[hint] = payload
                cs_idx_to_hint[payload] = hint
            else:
                assert isinstance(payload, tuple)
                banner_hint_to_key[hint] = payload
                banner_key_to_hint[payload] = hint

        self._entry_jump_hint_to_index = cs_hint_to_idx
        self._entry_jump_index_to_hint = cs_idx_to_hint
        self._entry_jump_hint_to_changespec_banner = banner_hint_to_key
        self._entry_jump_changespec_banner_to_hint = banner_key_to_hint
        return True

    def _begin_changespec_jump_mode(self) -> None:
        """Allocate hints across visible CLs + collapsed banners (CLs tab, grouped)."""
        if not self._prepare_changespec_jump_maps():
            return
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_current_tab()  # type: ignore[attr-defined]

    def _prepare_agents_jump_maps(self) -> bool:
        """Allocate agent-row and collapsed-banner hints without rendering them."""
        guard = getattr(self, "_guard_agent_navigation_for_artifact_viewer", None)
        if callable(guard) and guard():
            return False
        targets = self._jump_candidate_targets()
        if not targets:
            return False
        hint_to_target, _ = build_jump_hint_maps(targets)
        if not hint_to_target:
            return False

        agent_hint_to_idx: dict[str, int] = {}
        agent_idx_to_hint: dict[int, str] = {}
        banner_hint_to_target: dict[str, BannerJumpTarget] = {}
        banner_to_hint: dict[BannerJumpTarget, str] = {}
        for hint, target in hint_to_target.items():
            if target[0] == "agent":
                agent_hint_to_idx[hint] = target[1]
                agent_idx_to_hint[target[1]] = hint
            else:
                banner_hint_to_target[hint] = target
                banner_to_hint[target] = hint

        self._entry_jump_hint_to_index = agent_hint_to_idx
        self._entry_jump_index_to_hint = agent_idx_to_hint
        self._entry_jump_hint_to_banner = banner_hint_to_target
        self._entry_jump_banner_to_hint = banner_to_hint
        return True

    def _begin_agents_jump_mode(self) -> None:
        """Allocate hints across visible agents + collapsed banners (agents tab)."""
        if not self._prepare_agents_jump_maps():
            return
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _jump_candidate_indices(self) -> list[int]:
        """Return target indices for jump mode in visual order (CLs / AXE only)."""
        if self.current_tab == "changespecs":
            return list(range(len(self.changespecs)))
        if self.current_tab == "agents":
            # Kept for backward compatibility with tests / callers that
            # only need the agent indices (no banner targets).
            return [t[1] for t in self._jump_candidate_targets() if t[0] == "agent"]
        return list(range(len(self._axe_items)))  # type: ignore[attr-defined]

    def _jump_candidate_targets(self) -> list[JumpTarget]:
        """Return jump targets for the agents tab in render order.

        Walks each tag panel's grouping tree (mirroring
        :func:`_refresh_panel_widgets`) so hint characters march down the
        screen in the same order they're rendered.  Collapsed banners
        contribute ``("banner", panel_idx, group_key)`` targets;
        non-collapsed banners are non-selectable and excluded.
        """
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ..agents._navigation_order import rendered_panel_slice

        registry = self._group_fold_registry
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        panel_group = getattr(self, "_panel_group", None)
        panel_keys = panel_group.panel_keys if panel_group is not None else [None]
        targets: list[JumpTarget] = []
        for panel_idx, key in enumerate(panel_keys):
            global_indices, panel_agents = rendered_panel_slice(self, key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "group" and entry.group is not None:
                    if entry.group.is_collapsed:
                        targets.append(("banner", panel_idx, entry.group.group_key))
                elif entry.kind == "agent" and entry.agent_idx is not None:
                    targets.append(("agent", global_indices[entry.agent_idx]))
        return targets

    def _exit_entry_jump_mode(self) -> None:
        """Clear jump mode state and remove hint overlays."""
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}
        self._entry_jump_hint_to_banner = {}
        self._entry_jump_banner_to_hint = {}
        self._entry_jump_hint_to_changespec_banner = {}
        self._entry_jump_changespec_banner_to_hint = {}
        if self.current_tab == "agents":
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _entry_jump_index_stack_for_current_tab(self) -> list[EntryJumpAnchor]:
        """Return the current non-Agents tab's jump-back stack."""
        return self._entry_jump_index_stack.setdefault(self.current_tab, [])

    def _entry_jump_forward_stack_map(self) -> dict[str, list[EntryJumpAnchor]]:
        """Return the non-Agents tab forward stacks, creating them for old harnesses."""
        stacks = getattr(self, "_entry_jump_forward_index_stack", None)
        if stacks is None:
            stacks = {}
            self._entry_jump_forward_index_stack = stacks
        return cast("dict[str, list[EntryJumpAnchor]]", stacks)

    def _entry_jump_forward_stack_for_current_tab(self) -> list[EntryJumpAnchor]:
        """Return the current non-Agents tab's jump-forward stack."""
        return self._entry_jump_forward_stack_map().setdefault(self.current_tab, [])

    def _entry_jump_index_stack_has_current_tab_history(self) -> bool:
        """Return whether the current non-Agents tab has jump-back history."""
        return bool(self._entry_jump_index_stack.get(self.current_tab))

    def _entry_jump_index_is_valid(self, tab: str, idx: int) -> bool:
        """Return whether ``idx`` still identifies a row in ``tab``."""
        if tab == "changespecs":
            return 0 <= idx < len(self.changespecs)
        if tab == "axe":
            return 0 <= idx < len(self._axe_items)  # type: ignore[attr-defined]
        return False

    def _changespec_banner_anchor_is_valid(
        self,
        group_key: tuple[str, ...],
    ) -> bool:
        """Return whether ``group_key`` is a selectable CL banner right now."""
        stops_fn = getattr(self, "_changespec_navigation_stops", None)
        if not callable(stops_fn):
            return False
        try:
            stops = stops_fn()
        except Exception:
            return False
        return any(kind == "banner" and payload == group_key for kind, payload in stops)

    def _entry_jump_anchor_is_valid(
        self,
        tab: str,
        anchor: EntryJumpAnchor,
    ) -> bool:
        """Return whether a non-Agents jump anchor can be restored."""
        if isinstance(anchor, int):
            return self._entry_jump_index_is_valid(tab, anchor)
        kind, group_key = anchor
        return (
            kind == "changespec_banner"
            and tab == "changespecs"
            and self._changespec_banner_anchor_is_valid(group_key)
        )

    def _current_entry_jump_anchor(self) -> EntryJumpAnchor | None:
        """Snapshot the current non-Agents cursor as a row or CL banner."""
        if self.current_tab == "changespecs":
            group_key = getattr(self, "_current_changespec_group_key", None)
            if group_key is not None:
                banner_anchor: EntryJumpAnchor = (
                    "changespec_banner",
                    tuple(group_key),
                )
                if self._entry_jump_anchor_is_valid(self.current_tab, banner_anchor):
                    return banner_anchor

        if self._entry_jump_index_is_valid(self.current_tab, self.current_idx):
            return self.current_idx
        return None

    def _push_entry_jump_anchor_to_stack(
        self,
        stacks: dict[str, list[EntryJumpAnchor]],
        anchor: EntryJumpAnchor,
    ) -> None:
        """Push ``anchor`` onto the current tab's stack without adjacent duplicates."""
        stack = stacks.setdefault(self.current_tab, [])
        if not stack or stack[-1] != anchor:
            stack.append(anchor)

    def _clear_current_entry_jump_forward_stack(self) -> None:
        """Clear forward history for the current non-Agents tab."""
        stack = self._entry_jump_forward_stack_map().get(self.current_tab)
        if stack is not None:
            stack.clear()

    def _push_entry_jump_index_origin_if_changed(
        self,
        *,
        target_idx: int | None,
        target_group_key: tuple[str, ...] | None = None,
    ) -> None:
        """Push the current non-Agents row when a jump will move focus."""
        row_changed = target_idx is not None and target_idx != self.current_idx
        group_changed = (
            self.current_tab == "changespecs"
            and target_group_key != getattr(self, "_current_changespec_group_key", None)
        )
        if not row_changed and not group_changed:
            return
        anchor = self._current_entry_jump_anchor()
        if anchor is None:
            return
        self._push_entry_jump_anchor_to_stack(self._entry_jump_index_stack, anchor)
        self._clear_current_entry_jump_forward_stack()

    def _pop_entry_jump_anchor_from(
        self,
        stacks: dict[str, list[EntryJumpAnchor]],
    ) -> EntryJumpAnchor | None:
        """Pop the latest valid anchor for the current non-Agents tab."""
        stack = stacks.get(self.current_tab)
        if not stack:
            return None
        while stack:
            anchor = stack.pop()
            if self._entry_jump_anchor_is_valid(self.current_tab, anchor):
                return anchor
        stacks.pop(self.current_tab, None)
        return None

    def _pop_entry_jump_index(self) -> EntryJumpAnchor | None:
        """Pop the latest valid anchor for the current non-Agents tab."""
        return self._pop_entry_jump_anchor_from(self._entry_jump_index_stack)

    def _restore_entry_jump_anchor(self, anchor: EntryJumpAnchor) -> bool:
        """Restore a non-Agents jump anchor. Returns True when it was valid."""
        if not self._entry_jump_anchor_is_valid(self.current_tab, anchor):
            return False
        if isinstance(anchor, int):
            if self.current_tab == "changespecs":
                self._current_changespec_group_key = None  # type: ignore[attr-defined]
            self.current_idx = anchor
            return True

        _, group_key = anchor
        self._current_changespec_group_key = group_key  # type: ignore[attr-defined]
        return True

    def _refresh_after_entry_jump_restore(self) -> None:
        """Refresh the tab after a direct jump-stack restore."""
        if self.current_tab == "agents":
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        elif self.current_tab == "changespecs":
            self._refresh_display()  # type: ignore[attr-defined]
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _notify_no_next_jump_point(self) -> None:
        """Notify the user that the jump-forward stack is empty."""
        notify = getattr(self, "notify", None)
        if callable(notify):
            notify("No next jump point", severity="information")

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
        from ..agents._navigation_order import rendered_panel_slice

        panel_key = None
        if panel_group is not None:
            panel_key = panel_group.panel_keys[panel_idx]
        registry = getattr(self, "_group_fold_registry", None)
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

    def _handle_entry_jump_key(self, key: str) -> bool:
        """Handle one keypress while jump mode is active."""
        if not self._entry_jump_mode_active:
            return False
        if key == "escape":
            self._exit_entry_jump_mode()
            return True

        if key == "apostrophe":
            if self.current_tab == "agents":
                guard = getattr(
                    self, "_guard_agent_navigation_for_artifact_viewer", None
                )
                if self._entry_jump_agents_anchor_stack and callable(guard) and guard():
                    self._exit_entry_jump_mode()
                    return True
                if self._restore_agents_jump_anchor():
                    self._exit_entry_jump_mode()
                    return True
                key = "1"
            else:
                last_anchor = self._pop_entry_jump_index()
                if last_anchor is not None:
                    current_anchor = self._current_entry_jump_anchor()
                    if current_anchor is not None:
                        self._push_entry_jump_anchor_to_stack(
                            self._entry_jump_forward_stack_map(),
                            current_anchor,
                        )
                    self._restore_entry_jump_anchor(last_anchor)
                    self._exit_entry_jump_mode()
                    return True
                key = "1"

        if self.current_tab == "agents":
            banner_target = self._entry_jump_hint_to_banner.get(key)
            agent_target = self._entry_jump_hint_to_index.get(key)
            if banner_target is None and agent_target is None:
                self._exit_entry_jump_mode()
                return True
            guard = getattr(self, "_guard_agent_navigation_for_artifact_viewer", None)
            if callable(guard) and guard():
                self._exit_entry_jump_mode()
                return True
            if banner_target is not None:
                _, panel_idx, group_key = banner_target
                self._remember_agents_jump_origin_if_changed(
                    target_idx=None,
                    target_panel_idx=panel_idx,
                    target_group_key=group_key,
                )
                if 0 <= panel_idx < len(self._panel_group.panel_keys):
                    if panel_idx != self._panel_group.focused_idx:
                        self._panel_group.focused_idx = panel_idx
                self._current_group_key = group_key
            else:
                assert agent_target is not None
                agent_panel_idx = self._panel_idx_for_agent_jump_target(agent_target)
                self._remember_agents_jump_origin_if_changed(
                    target_idx=agent_target,
                    target_panel_idx=agent_panel_idx,
                    target_group_key=None,
                )
                if (
                    agent_panel_idx is not None
                    and agent_panel_idx != self._panel_group.focused_idx
                ):
                    self._panel_group.focused_idx = agent_panel_idx
                self._current_group_key = None
                self.current_idx = agent_target
            self._exit_entry_jump_mode()
            return True

        if self.current_tab == "changespecs":
            banner_key = self._entry_jump_hint_to_changespec_banner.get(key)
            agent_target = self._entry_jump_hint_to_index.get(key)
            if banner_key is None and agent_target is None:
                self._exit_entry_jump_mode()
                return True
            if banner_key is not None:
                self._push_entry_jump_index_origin_if_changed(
                    target_idx=None,
                    target_group_key=banner_key,
                )
                self._current_changespec_group_key = banner_key  # type: ignore[attr-defined]
            else:
                assert agent_target is not None
                self._push_entry_jump_index_origin_if_changed(
                    target_idx=agent_target,
                    target_group_key=None,
                )
                self._current_changespec_group_key = None  # type: ignore[attr-defined]
                self.current_idx = agent_target
            self._exit_entry_jump_mode()
            self._refresh_display()  # type: ignore[attr-defined]
            return True

        target = self._entry_jump_hint_to_index.get(key)
        if target is None:
            self._exit_entry_jump_mode()
            return True

        self._push_entry_jump_index_origin_if_changed(target_idx=target)
        self.current_idx = target
        self._exit_entry_jump_mode()
        return True

    def _update_jump_footer(self) -> None:
        """Update the footer to show jump mode bindings."""
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            if self.current_tab == "agents":
                has_back = bool(self._entry_jump_agents_anchor_stack)
            else:
                has_back = self._entry_jump_index_stack_has_current_tab_history()
            footer.update_jump_bindings(has_back=has_back)
        except Exception:
            pass
