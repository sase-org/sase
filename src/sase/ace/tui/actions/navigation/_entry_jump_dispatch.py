"""Entry-jump actions and key dispatch."""

from __future__ import annotations

from ._entry_jump_mode import EntryJumpModeMixin


class EntryJumpDispatchMixin(EntryJumpModeMixin):
    """Mixin providing entry-jump actions and key handling."""

    # --- Jump To Entry ---

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
            panel_target = self._entry_jump_hint_to_panel.get(key)
            agent_target = self._entry_jump_hint_to_index.get(key)
            if banner_target is None and panel_target is None and agent_target is None:
                self._exit_entry_jump_mode()
                return True
            target_panel_idx = None
            if panel_target is not None:
                target_panel_idx = self._agents_jump_panel_idx_for_key(panel_target[1])
                if target_panel_idx is None or panel_target[1] not in getattr(
                    self, "_collapsed_panel_keys", set()
                ):
                    self._exit_entry_jump_mode()
                    return True
            guard = getattr(self, "_guard_agent_navigation_for_artifact_viewer", None)
            if callable(guard) and guard():
                self._exit_entry_jump_mode()
                return True
            old_idx = self.current_idx
            old_group_key = getattr(self, "_current_group_key", None)
            panel_group = getattr(self, "_panel_group", None)
            old_panel_collapsed = (
                panel_group is not None
                and panel_group.focused_key
                in getattr(self, "_collapsed_panel_keys", set())
            )
            old_agent = (
                self._agents[old_idx]
                if (
                    old_group_key is None
                    and not old_panel_collapsed
                    and 0 <= old_idx < len(self._agents)
                )
                else None
            )
            if panel_target is not None:
                assert target_panel_idx is not None
                panel_key = panel_target[1]
                self._remember_agents_jump_origin_if_changed(
                    target_idx=None,
                    target_panel_idx=target_panel_idx,
                    target_group_key=None,
                )
                if old_agent is not None:
                    arm_manual = getattr(
                        self, "_arm_manual_unread_after_departure", None
                    )
                    if callable(arm_manual):
                        arm_manual(old_agent)
                if target_panel_idx != self._panel_group.focused_idx:
                    self._panel_group.focused_idx = target_panel_idx
                self._current_group_key = None
                self.current_attempt_number = None
                keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
                self._snap_current_idx_to_focused_panel(  # type: ignore[attr-defined]
                    keys_per_agent,
                    panel_key,
                )
            elif banner_target is not None:
                _, panel_idx, group_key = banner_target
                self._remember_agents_jump_origin_if_changed(
                    target_idx=None,
                    target_panel_idx=panel_idx,
                    target_group_key=group_key,
                )
                if old_agent is not None:
                    arm_manual = getattr(
                        self, "_arm_manual_unread_after_departure", None
                    )
                    if callable(arm_manual):
                        arm_manual(old_agent)
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
                if old_agent is not None and agent_target != old_idx:
                    arm_manual = getattr(
                        self, "_arm_manual_unread_after_departure", None
                    )
                    if callable(arm_manual):
                        arm_manual(old_agent)
                self._current_group_key = None
                self.current_idx = agent_target
                if 0 <= agent_target < len(self._agents):
                    target_agent = self._agents[agent_target]
                    ack_unread = getattr(self, "_acknowledge_agent_unread", None)
                    if callable(ack_unread):
                        ack_unread(target_agent)
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
