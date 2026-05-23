"""One-key entry jump navigation for the ace TUI app."""

from __future__ import annotations

from ._types import NavigationMixinBase
from .jump_hints import (
    AgentJumpAnchor,
    BannerJumpTarget,
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

    def _save_agents_jump_anchor(self) -> None:
        """Snapshot the agents-tab cursor (agent or banner) for ``'`` back-jump."""
        anchor = self._current_agents_jump_anchor()
        if anchor is not None:
            self._entry_jump_last_agents_anchor = anchor

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

    def _focus_agents_jump_anchor_panel(self, panel_idx: int) -> None:
        """Focus the panel for a validated agents jump anchor."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is not None:
            panel_group.focused_idx = panel_idx

    def _restore_agents_jump_anchor(self) -> bool:
        """Restore the saved agents-tab anchor.  Returns True on success."""
        anchor = self._entry_jump_last_agents_anchor
        if anchor is None:
            return False
        if anchor[0] == "agent":
            _, agent_idx, target_panel = anchor
            if not (0 <= agent_idx < len(self._agents)):
                return False
            if not self._agents_jump_anchor_panel_is_valid(target_panel):
                return False
        else:
            _, target_panel, _group_key = anchor
            if not self._agents_jump_anchor_panel_is_valid(target_panel):
                return False

        # Capture the current spot as the new anchor before jumping back so
        # a third ``'`` press toggles back to where we were.
        new_anchor = self._current_agents_jump_anchor()
        if new_anchor is None:
            return False
        self._entry_jump_last_agents_anchor = new_anchor

        if anchor[0] == "agent":
            _, agent_idx, target_panel = anchor
            self._focus_agents_jump_anchor_panel(target_panel)
            self._current_group_key = None
            self.current_idx = agent_idx
        else:
            _, target_panel, group_key = anchor
            self._focus_agents_jump_anchor_panel(target_panel)
            self._current_group_key = group_key
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
                if (
                    self._entry_jump_last_agents_anchor is not None
                    and callable(guard)
                    and guard()
                ):
                    self._exit_entry_jump_mode()
                    return True
                if self._restore_agents_jump_anchor():
                    self._exit_entry_jump_mode()
                    return True
                key = "1"
            else:
                last_idx = self._entry_jump_last_index.get(self.current_tab)
                if last_idx is not None:
                    # Save current position before jumping back
                    self._entry_jump_last_index[self.current_tab] = self.current_idx
                    self.current_idx = last_idx
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
            self._entry_jump_last_index[self.current_tab] = self.current_idx
            if banner_key is not None:
                self._current_changespec_group_key = banner_key  # type: ignore[attr-defined]
            else:
                assert agent_target is not None
                self._current_changespec_group_key = None  # type: ignore[attr-defined]
                self.current_idx = agent_target
            self._exit_entry_jump_mode()
            self._refresh_display()  # type: ignore[attr-defined]
            return True

        target = self._entry_jump_hint_to_index.get(key)
        if target is None:
            self._exit_entry_jump_mode()
            return True

        self._entry_jump_last_index[self.current_tab] = self.current_idx
        self.current_idx = target
        self._exit_entry_jump_mode()
        return True

    def _update_jump_footer(self) -> None:
        """Update the footer to show jump mode bindings."""
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            if self.current_tab == "agents":
                has_back = self._entry_jump_last_agents_anchor is not None
            else:
                has_back = self.current_tab in self._entry_jump_last_index
            footer.update_jump_bindings(has_back=has_back)
        except Exception:
            pass
