"""Entry-jump actions and key dispatch."""

from __future__ import annotations

from ..agents._panel_fold_intent import panel_is_collapsed
from ._entry_jump_mode import EntryJumpModeMixin
from .jump_hints import JumpHintMatchOutcome, match_jump_hint


class EntryJumpDispatchMixin(EntryJumpModeMixin):
    """Mixin providing entry-jump actions and key handling."""

    # --- Jump To Entry ---

    def action_jump_to_entry_fast(self) -> None:
        """Jump as if ``'`` then ``'`` were pressed, without painting hints.

        A non-empty link trail means the most recent navigation was a ``$``
        link-follow, so this walks back along it instead; otherwise it falls
        through to the per-surface anchor stacks below, unchanged
        (bead:sase-ug.8).
        """
        walk_back = getattr(self, "_walk_link_trail_back", None)
        if callable(walk_back) and walk_back():
            return
        if self.current_tab == "agents":
            prepared = self._prepare_agents_jump_maps()
        elif self.current_tab in {
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            prepared = self._prepare_patch_jump_maps()
        else:
            prepared = self._prepare_entry_jump_index_maps(
                self._jump_candidate_indices()
            )
        if not prepared:
            return

        self._entry_jump_mode_active = True
        self._handle_entry_jump_key("apostrophe")

    def action_jump_to_entry_forward(self) -> None:
        """Walk forward through jump points after a back-jump.

        Redoes a link-trail back-hop first when one is pending; otherwise
        falls through to the per-surface forward stacks below, unchanged
        (bead:sase-ug.8).
        """
        walk_forward = getattr(self, "_walk_link_trail_forward", None)
        if callable(walk_forward) and walk_forward():
            return
        if self.current_tab == "agents":
            forward_stack = self._entry_jump_agents_forward_stack()
            guard = getattr(
                self, "_guard_agent_navigation_for_artifact_file_viewer", None
            )
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
        """Handle one keypress or prefix character while jump mode is active."""
        if not self._entry_jump_mode_active:
            return False
        handle_artifacts = getattr(self, "_handle_non_pr_artifacts_jump_key", None)
        if getattr(self, "_artifacts_jump_mode_subtab", None) is not None and callable(
            handle_artifacts
        ):
            return bool(handle_artifacts(key))
        if key == "escape":
            self._exit_entry_jump_mode()
            return True

        resolved_target: object | None = None
        if key == "apostrophe":
            if self.current_tab == "agents":
                guard = getattr(
                    self, "_guard_agent_navigation_for_artifact_file_viewer", None
                )
                if self._entry_jump_agents_anchor_stack and callable(guard) and guard():
                    self._exit_entry_jump_mode()
                    return True
                if self._restore_agents_jump_anchor():
                    self._exit_entry_jump_mode()
                    refresh_detail = getattr(self, "_refresh_agent_focus_detail", None)
                    if callable(refresh_detail):
                        refresh_detail()
                    return True
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

            resolved_target = next(
                iter(self._active_entry_jump_target_map().values()),
                None,
            )
        else:
            match = match_jump_hint(
                self._active_entry_jump_target_map(),
                getattr(self, "_entry_jump_pending_prefix", ""),
                key,
            )
            if match.outcome is JumpHintMatchOutcome.PENDING:
                self._entry_jump_pending_prefix = match.prefix
                return True
            if match.outcome is JumpHintMatchOutcome.INVALID:
                self._exit_entry_jump_mode()
                return True
            resolved_target = match.target
            self._entry_jump_pending_prefix = ""

        if resolved_target is None:
            self._exit_entry_jump_mode()
            return True

        if self.current_tab == "agents":
            banner_target = (
                resolved_target
                if isinstance(resolved_target, tuple) and resolved_target[0] == "banner"
                else None
            )
            panel_target = (
                resolved_target
                if isinstance(resolved_target, tuple) and resolved_target[0] == "panel"
                else None
            )
            agent_target = (
                resolved_target[1]
                if isinstance(resolved_target, tuple) and resolved_target[0] == "agent"
                else None
            )
            if banner_target is None and panel_target is None and agent_target is None:
                self._exit_entry_jump_mode()
                return True
            target_panel_idx = None
            if panel_target is not None:
                target_panel_idx = self._agents_jump_panel_idx_for_key(panel_target[1])
                if target_panel_idx is None or getattr(
                    self, "_agent_panels_grouped", False
                ):
                    self._exit_entry_jump_mode()
                    return True
            guard = getattr(
                self, "_guard_agent_navigation_for_artifact_file_viewer", None
            )
            if callable(guard) and guard():
                self._exit_entry_jump_mode()
                return True
            old_idx = self.current_idx
            old_group_key = getattr(self, "_current_group_key", None)
            panel_group = getattr(self, "_panel_group", None)
            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            old_panel_focus = resolve_panel() if callable(resolve_panel) else None
            old_panel_collapsed = panel_group is not None and panel_is_collapsed(
                self, panel_group.focused_key
            )
            old_agent = (
                self._agents[old_idx]
                if (
                    old_group_key is None
                    and not old_panel_collapsed
                    and old_panel_focus is None
                    and 0 <= old_idx < len(self._agents)
                )
                else None
            )
            if panel_target is not None:
                assert target_panel_idx is not None
                panel_key = panel_target[1]
                remember_selection = getattr(
                    self, "_remember_focused_panel_selection", None
                )
                if (
                    callable(remember_selection)
                    and old_panel_focus is None
                    and not old_panel_collapsed
                ):
                    remember_selection()
                self._remember_agents_jump_origin_if_changed(
                    target_idx=None,
                    target_panel_key=panel_key,
                    target_group_key=None,
                    target_is_panel=True,
                )
                if old_agent is not None:
                    arm_manual = getattr(
                        self, "_arm_manual_unread_after_departure", None
                    )
                    if callable(arm_manual):
                        arm_manual(old_agent)
                if target_panel_idx != self._panel_group.focused_idx:
                    self._panel_group.focused_idx = target_panel_idx
                self._expanded_panel_focus = not panel_is_collapsed(self, panel_key)
                self._current_group_key = None
                self.current_attempt_number = None
                keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
                self._snap_current_idx_to_focused_panel(  # type: ignore[attr-defined]
                    keys_per_agent,
                    panel_key,
                )
            elif banner_target is not None:
                _, panel_idx, group_key = banner_target
                panel_key = self._panel_group.panel_keys[panel_idx]
                self._remember_agents_jump_origin_if_changed(
                    target_idx=None,
                    target_panel_key=panel_key,
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
                self._expanded_panel_focus = False
                self._current_group_key = group_key
            else:
                assert agent_target is not None
                agent_panel_idx = self._panel_idx_for_agent_jump_target(agent_target)
                agent_panel_key = (
                    self._panel_group.panel_keys[agent_panel_idx]
                    if agent_panel_idx is not None
                    else None
                )
                self._remember_agents_jump_origin_if_changed(
                    target_idx=agent_target,
                    target_panel_key=agent_panel_key,
                    target_group_key=None,
                )
                if (
                    agent_panel_idx is not None
                    and agent_panel_idx != self._panel_group.focused_idx
                ):
                    self._panel_group.focused_idx = agent_panel_idx
                self._expanded_panel_focus = False
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
            if panel_target is not None:
                refresh_detail = getattr(self, "_refresh_agent_focus_detail", None)
                if callable(refresh_detail):
                    refresh_detail()
            return True

        if self.current_tab in {
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            banner_key = (
                resolved_target[1]
                if isinstance(resolved_target, tuple) and resolved_target[0] == "banner"
                else None
            )
            agent_target = (
                resolved_target[1]
                if (
                    isinstance(resolved_target, tuple)
                    and resolved_target[0]
                    in {
                        "patch",
                        "changespec",  # legacy compatibility alias
                    }
                )
                else None
            )
            if banner_key is None and agent_target is None:
                self._exit_entry_jump_mode()
                return True
            if banner_key is not None:
                self._push_entry_jump_index_origin_if_changed(
                    target_idx=None,
                    target_group_key=banner_key,
                )
                self._current_patch_group_key = banner_key  # type: ignore[attr-defined]
                if hasattr(self, "_current_patch_group_key"):
                    self._current_patch_group_key = banner_key  # type: ignore[attr-defined]
            else:
                assert agent_target is not None
                self._push_entry_jump_index_origin_if_changed(
                    target_idx=agent_target,
                    target_group_key=None,
                )
                self._current_patch_group_key = None  # type: ignore[attr-defined]
                if hasattr(self, "_current_patch_group_key"):
                    self._current_patch_group_key = None  # type: ignore[attr-defined]
                self.current_idx = agent_target
            self._exit_entry_jump_mode()
            self._refresh_display()  # type: ignore[attr-defined]
            return True

        if not isinstance(resolved_target, int):
            self._exit_entry_jump_mode()
            return True

        target = resolved_target
        self._push_entry_jump_index_origin_if_changed(target_idx=target)
        self.current_idx = target
        self._exit_entry_jump_mode()
        return True

    def _active_entry_jump_target_map(self) -> dict[str, object]:
        """Return the unified active map, with compatibility for small harnesses."""
        unified = getattr(self, "_entry_jump_hint_to_target", None)
        if unified:
            return unified

        if self.current_tab == "agents":
            targets: dict[str, object] = {
                hint: ("agent", index)
                for hint, index in self._entry_jump_hint_to_index.items()
            }
            targets.update(self._entry_jump_hint_to_banner)
            targets.update(self._entry_jump_hint_to_panel)
            return targets
        if self.current_tab == "artifacts":
            targets = {
                hint: ("patch", index)
                for hint, index in self._entry_jump_hint_to_index.items()
            }
            targets.update(
                (hint, ("banner", group_key))
                for hint, group_key in self._entry_jump_hint_to_patch_banner.items()
            )
            return targets
        return dict(self._entry_jump_hint_to_index)
