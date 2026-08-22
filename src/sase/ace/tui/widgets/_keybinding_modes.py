"""Mode-specific footer binding update methods."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...patch import Patch
from ..keymaps import KeymapRegistry, footer_key_display

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.fold_scale import FoldScale


class KeybindingModesMixin:
    """Public ``update_*_bindings`` methods for :class:`KeybindingFooter`."""

    if TYPE_CHECKING:
        app: Any
        _runner_count: int

        def _kr(self) -> KeymapRegistry: ...

        def _kd(self, action_name: str) -> str: ...

        def _update_display(
            self,
            bindings: list[tuple[str, str]],
            mode_label: str | None = None,
        ) -> None: ...

        def _compute_available_bindings(
            self,
            patch: Patch,
            *,
            mark_count: int = 0,
        ) -> list[tuple[str, str]]: ...

        def _compute_agent_bindings(
            self,
            agent: Agent | None,
            *,
            completed_count: int = 0,
            can_jump_to_patch: bool = False,
            marked_count: int = 0,
            attempt_pinned: bool = False,
            panel_focused: bool = False,
            panel_collapsed: bool = False,
            panel_collapse_jump_available: bool = False,
            panel_restore_armed: bool = False,
            panel_isolation_available: bool = False,
            panel_fold_sweep_available: bool = False,
            panel_fold_restore_armed: bool = False,
            panel_hint_collapse_available: bool = False,
            left_navigation_kind: str | None = None,
            lane_collapse_available: bool = False,
            clan_collapse_available: bool = False,
            selected_clan_collapse_available: bool = False,
            structural_collapse_kind: str | None = None,
            group_collapse_available: bool = False,
            focused_panel_key: str | None = None,
            collapsed_panel_focused: bool = False,
            group_focused: bool = False,
            has_artifact_files: bool = False,
            artifact_file_viewer_active: bool = False,
            lane_neighbor_jump_available: bool = False,
            neighbor_count: int = 0,
            tmux_choice_count: int = 0,
            tools_visible: bool = False,
            tools_detail_level: int = 0,
        ) -> list[tuple[str, str]]: ...

        def _compute_axe_bindings(
            self,
            axe_current_view: str | int,
            *,
            selected_slot_done: bool = False,
            chop_run_total: int = 0,
            chop_selected: bool = False,
            chop_selected_running: bool = False,
            chop_selected_enabled: bool = True,
            config_row_selected: bool = False,
            description_expanded: bool = True,
        ) -> list[tuple[str, str]]: ...

    def update_bindings(self, patch: Patch, *, mark_count: int = 0) -> None:
        """Update bindings based on current Patch and app state."""
        bindings = self._compute_available_bindings(patch, mark_count=mark_count)
        bindings.append((self._kd("edit_query"), "edit query"))
        self._update_display(bindings)

    def show_empty(self, *, project_name: str | None = None) -> None:
        """Show empty state bindings.

        Args:
            project_name: If set, also show the tmux binding (sole project filter).
        """
        bindings: list[tuple[str, str]] = []
        if project_name:
            bindings.append((self._kd("open_tmux"), "tmux"))
        bindings.append((self._kd("edit_query"), "edit query"))
        self._update_display(bindings)

    def show_artifacts_pane(
        self,
        pane_key: str = "stitches",
        *,
        mark_count: int = 0,
        conditional_entries: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """Clear PR-only conditional bindings on non-PR Artifacts panes."""
        del pane_key
        bindings: list[tuple[str, str]] = [
            (self._kd(action_name), label) for action_name, label in conditional_entries
        ]
        if mark_count:
            bindings.append((self._kd("clear_marks"), f"unmark ({mark_count})"))
        self._update_display(bindings)

    def update_agent_bindings(
        self,
        agent: Agent | None,
        *,
        completed_count: int = 0,
        can_jump_to_patch: bool = False,
        marked_count: int = 0,
        attempt_pinned: bool = False,
        panel_focused: bool = False,
        panel_collapsed: bool = False,
        panel_collapse_jump_available: bool = False,
        panel_restore_armed: bool = False,
        panel_isolation_available: bool = False,
        panel_fold_sweep_available: bool = False,
        panel_fold_restore_armed: bool = False,
        panel_hint_collapse_available: bool = False,
        left_navigation_kind: str | None = None,
        lane_collapse_available: bool = False,
        clan_collapse_available: bool = False,
        selected_clan_collapse_available: bool = False,
        structural_collapse_kind: str | None = None,
        group_collapse_available: bool = False,
        focused_panel_key: str | None = None,
        collapsed_panel_focused: bool = False,
        group_focused: bool = False,
        has_artifact_files: bool = False,
        artifact_file_viewer_active: bool = False,
        lane_neighbor_jump_available: bool = False,
        neighbor_count: int = 0,
        tmux_choice_count: int = 0,
        tools_visible: bool = False,
        tools_detail_level: int = 0,
    ) -> None:
        """Update bindings for Agents tab."""
        bindings = self._compute_agent_bindings(
            agent,
            completed_count=completed_count,
            can_jump_to_patch=can_jump_to_patch,
            marked_count=marked_count,
            attempt_pinned=attempt_pinned,
            panel_focused=panel_focused,
            panel_collapsed=panel_collapsed,
            panel_collapse_jump_available=panel_collapse_jump_available,
            panel_restore_armed=panel_restore_armed,
            panel_isolation_available=panel_isolation_available,
            panel_fold_sweep_available=panel_fold_sweep_available,
            panel_fold_restore_armed=panel_fold_restore_armed,
            panel_hint_collapse_available=panel_hint_collapse_available,
            left_navigation_kind=left_navigation_kind,
            lane_collapse_available=lane_collapse_available,
            clan_collapse_available=clan_collapse_available,
            selected_clan_collapse_available=selected_clan_collapse_available,
            structural_collapse_kind=structural_collapse_kind,
            group_collapse_available=group_collapse_available,
            focused_panel_key=focused_panel_key,
            collapsed_panel_focused=collapsed_panel_focused,
            group_focused=group_focused,
            has_artifact_files=has_artifact_files,
            artifact_file_viewer_active=artifact_file_viewer_active,
            lane_neighbor_jump_available=lane_neighbor_jump_available,
            neighbor_count=neighbor_count,
            tmux_choice_count=tmux_choice_count,
            tools_visible=tools_visible,
            tools_detail_level=tools_detail_level,
        )
        self._update_display(bindings)

    def update_axe_bindings(
        self,
        *,
        axe_current_view: str | int = "axe",
        selected_slot_done: bool = False,
        chop_run_total: int = 0,
        chop_selected: bool = False,
        chop_selected_running: bool = False,
        chop_selected_enabled: bool = True,
        config_row_selected: bool = False,
        description_expanded: bool = True,
    ) -> None:
        """Update bindings for Axe tab (entry-dependent only)."""
        bindings = self._compute_axe_bindings(
            axe_current_view,
            selected_slot_done=selected_slot_done,
            chop_run_total=chop_run_total,
            chop_selected=chop_selected,
            chop_selected_running=chop_selected_running,
            chop_selected_enabled=chop_selected_enabled,
            config_row_selected=config_row_selected,
            description_expanded=description_expanded,
        )
        self._update_display(bindings)

    def update_fold_bindings(
        self,
        *,
        current_tab: str = "artifacts",
        fold_scale: FoldScale | None = None,
    ) -> None:
        """Update bindings to show the active tab's fold mode options."""
        d = footer_key_display
        keys = self._kr().fold_mode.keys

        if current_tab == "agents":
            agent_keys = keys["agents"]
            assert isinstance(agent_keys, dict)
            bindings: list[tuple[str, str]] = []
            if fold_scale is not None:
                for position in range(1, len(fold_scale) + 1):
                    subkey = agent_keys[f"set_level_{position}"]
                    bindings.append((d(subkey), f"level {position}"))
            bindings.extend(
                [
                    (d(agent_keys["cycle_level"]), "level forward"),
                    (d(agent_keys["toggle_all"]), "toggle all"),
                    (d(agent_keys["cycle_section"]), "section forward"),
                    (d(agent_keys["toggle_section"]), "toggle section"),
                ]
            )
            self._update_display(bindings, mode_label="FOLD")
            return

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings = [
            (k("set_level_1"), "level 1"),
            (k("set_level_2"), "level 2"),
            (k("set_level_3"), "level 3"),
            (k("cycle_stitches"), "stitches"),
            (k("cycle_hooks"), "hooks"),
            (k("cycle_mentors"), "mentors"),
            (k("cycle_timestamps"), "timestamps"),
            (k("cycle_deltas"), "deltas"),
            (k("toggle_stitches"), "toggle stitches"),
            (k("toggle_hooks"), "toggle hooks"),
            (k("toggle_mentors"), "toggle mentors"),
            (k("toggle_timestamps"), "toggle timestamps"),
            (k("toggle_deltas"), "toggle deltas"),
            (k("cycle_all"), "all"),
            (k("toggle_all"), "toggle"),
        ]
        self._update_display(bindings, mode_label="FOLD")

    def update_jump_bindings(self, *, has_back: bool = False) -> None:
        """Update bindings to show entry jump mode options."""
        bindings: list[tuple[str, str]] = [("'", "back" if has_back else "first")]
        bindings.append(("<esc>", "cancel"))
        self._update_display(bindings, mode_label="JUMP")

    def update_fold_hint_bindings(self, *, collapse_only: bool = False) -> None:
        """Update bindings to show single-key fold hint mode."""
        self._update_display(
            [("<esc>", "cancel")],
            mode_label="COLLAPSE" if collapse_only else "FOLDS",
        )

    def update_member_jump_bindings(
        self,
        first_digit: str,
        *,
        noun: str = "member",
    ) -> None:
        """Show a buffered roster digit and its completion/cancel hints."""
        bindings = [
            ("0-9", "second digit"),
            ("<esc>", "cancel"),
        ]
        self._update_display(bindings, mode_label=f"{noun} {first_digit}▁")

    def update_bead_issue_bindings(self) -> None:
        """Update bindings to show Beads external-issue mode options."""
        d = footer_key_display
        keys = self._kr().bead_issue_mode.keys

        def k(name: str) -> str:
            value = keys[name]
            assert isinstance(value, str)
            return d(value)

        self._update_display(
            [
                (k("view"), "view body"),
                (k("edit"), "edit issue"),
                (k("toggle_state"), "close/reopen"),
                (k("copy_url"), "copy URL"),
                (k("attach"), "attach"),
                (k("create"), "create issue"),
                ("<esc>", "cancel"),
            ],
            mode_label="ISSUE",
        )

    def update_leader_bindings(
        self,
        *,
        current_tab: str = "artifacts",
        has_comments: bool = False,
        has_notification: bool = False,
        has_mentor_results: bool = False,
        has_unread_completed_agent: bool = False,
        has_bulk_read_undo_available: bool = False,
        has_stopped_agent: bool = False,
        has_revertable_agent: bool = False,
        marked_agent_count: int = 0,
    ) -> None:
        """Update bindings to show leader mode options.

        Args:
            current_tab: The currently active tab name.
            has_comments: Whether the selected Patch has a COMMENTS field.
            has_notification: Whether the selected agent has a pending notification.
            has_mentor_results: Whether the selected Patch has mentor results.
            has_unread_completed_agent: Whether any completed agent is unread.
            has_bulk_read_undo_available: Whether the last bulk read can be undone.
            has_stopped_agent: Whether any stopped agent is loaded.
            has_revertable_agent: Whether the selected Agents-tab row is a
                done/failed agent whose commits can be reverted.
            marked_agent_count: Number of marked agents; when non-zero ``,r``
                reverts every marked agent and the footer reads
                ``revert marked (N)``.
        """
        d = footer_key_display
        current_tab = (
            "artifacts"
            if current_tab
            in {
                "patches",
                "changespecs",  # legacy compatibility alias
            }
            else current_tab
        )
        keys = self._kr().leader_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings: list[tuple[str, str]] = []
        bindings.append((k("repeat_last"), "repeat"))
        if current_tab == "agents":
            bindings.append((k("edit_query"), "edit query"))
        if current_tab == "artifacts":
            if has_comments:
                bindings.append((k("clear_comments"), "clear comments"))
            bindings.append((k("run_cmd"), "run cmd (PR)"))
            bindings.append((k("kill_mentors"), "manage mentors"))
            if has_mentor_results:
                bindings.append((k("review_mentors"), "review mentors"))
            bindings.append((k("agent_run_log"), "agent run log"))
        if self._runner_count > 0:
            bindings.append((k("runners"), f"runners ({self._runner_count})"))
        bindings.append((k("agent_home"), "agent (home)"))
        if current_tab in ("artifacts", "agents"):
            bindings.append((k("agent_from_cl"), "run agent (PR)"))
        if current_tab == "agents":
            bindings.append((k("toggle_agent_panel_grouping"), "group panels"))
            bindings.append((k("full_history_refresh"), "full history refresh"))
            if has_stopped_agent:
                bindings.append((k("jump_to_next_stopped_agent"), "next stopped"))
            if has_unread_completed_agent:
                bindings.append(
                    (k("jump_to_next_unread_done_agent"), "next unread done")
                )
                bindings.append(
                    (k("mark_all_unread_done_agents_read"), "mark all read")
                )
            elif has_bulk_read_undo_available:
                bindings.append(
                    (k("mark_all_unread_done_agents_read"), "undo mark all read")
                )
        bindings.append((k("prompt_history"), "prompt history"))
        bindings.append((k("prompt_history_edit_first"), "edit history"))
        bindings.append((k("prompt_history_cancelled"), "history (+cancelled)"))
        bindings.append((k("open_prompt_stash"), "prompt stash"))
        if current_tab == "agents":
            # ,x is contextual: it kills & edits the marked set when marks
            # exist, otherwise the focused row.
            if marked_agent_count > 0:
                bindings.append(
                    (
                        k("kill_and_edit"),
                        f"kill marked & edit ({marked_agent_count})",
                    )
                )
                bindings.append(
                    (k("revert_agent"), f"revert marked ({marked_agent_count})")
                )
            else:
                bindings.append((k("kill_and_edit"), "kill & edit"))
                if has_revertable_agent:
                    bindings.append((k("revert_agent"), "revert agent"))
            bindings.append((k("capture_agents_repro"), "capture repro"))
            bindings.append((k("toggle_agents_repro_checks"), "repro checks"))
            if has_notification:
                bindings.append((k("jump_to_notification"), "notification"))
        bindings.append((k("models_panel"), "Launch settings"))
        bindings.append((k("update_sase"), "update panel"))
        bindings.append((k("jump_to_last_error"), "last error"))
        self._update_display(bindings, mode_label="LEADER")

    def update_bang_bindings(self) -> None:
        """Update bindings to show bang mode options."""
        d = footer_key_display
        keys = self._kr().bang_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings = [
            (k("run_cmd"), "run cmd"),
            (k("toggle_axe"), "start/stop axe"),
        ]
        if "mark_pr_origin" in keys:
            bindings.append((k("mark_pr_origin"), "mark PR origin"))
        if "start_rewind" in keys:
            bindings.append((k("start_rewind"), "rewind / revive"))
        self._update_display(bindings, mode_label="BANG")

    def update_saved_query_bindings(self) -> None:
        """Update bindings to show saved-query slot mode options."""
        from ...saved_queries import KEY_ORDER

        pane_id = getattr(self.app, "current_artifacts_pane_key", "patches")
        all_saved_queries = getattr(self.app, "_saved_queries", None) or {}
        saved_queries = all_saved_queries.get(pane_id, {})
        bindings: list[tuple[str, str]] = []
        for slot in KEY_ORDER[1:] + KEY_ORDER[:1]:
            record = saved_queries.get(slot)
            if record is None:
                continue
            query = record.canonical
            label = query if len(query) <= 24 else query[:21] + "..."
            bindings.append((slot, label))
        if not bindings:
            bindings.append(("0-9", "no saved queries"))
        self._update_display(bindings, mode_label="QUERY")

    def update_custom_mode_bindings(self, mode_name: str) -> None:
        """Update bindings to show custom mode options.

        Args:
            mode_name: Name of the active custom mode.
        """
        d = footer_key_display
        mode = self._kr().modes.get(mode_name)
        if mode is None:
            return

        bindings: list[tuple[str, str]] = []
        for action_name, spec in mode.keys.items():
            if not isinstance(spec, dict):
                continue
            key = spec.get("key", "")
            desc = spec.get("description", action_name)
            bindings.append((d(key), desc))

        display_name = mode_name.upper().replace("_", " ")
        self._update_display(bindings, mode_label=display_name)

    def update_copy_bindings(
        self,
        tab: str,
        *,
        artifacts_pane_key: str | None = None,
        file_visible: bool = False,
    ) -> None:
        """Update bindings to show copy mode options for the current tab.

        Args:
            tab: Current tab name ("artifacts", "agents", or "axe").
            artifacts_pane_key: Visible leaf pane when ``tab`` is patches.
            file_visible: Whether the file panel is visible (agents tab only).
        """
        d = footer_key_display
        tab = (
            "artifacts"
            if tab
            in {
                "patches",
                "changespecs",  # legacy compatibility alias
            }
            else tab
        )
        if tab == "artifacts" and artifacts_pane_key in {"stitches", "beads", "files"}:
            key_group = f"artifacts_{artifacts_pane_key}"
        elif tab == "artifacts" and artifacts_pane_key not in {None, "patches"}:
            from sase.ace.tui.artifact_tabs import copy_keymap_group_for_artifacts_pane

            key_group = copy_keymap_group_for_artifacts_pane(str(artifacts_pane_key))
        else:
            key_group = tab
        if key_group == "artifacts_files":
            key_group = "artifacts_other"
        tab_keys = self._kr().copy_mode.keys.get(key_group, {})
        assert isinstance(tab_keys, dict)

        from ..copy_targets import copy_targets_for

        bindings: list[tuple[str, str]] = []
        for target in copy_targets_for(key_group):
            lookup = target.target
            if lookup == "pr_number" and lookup not in tab_keys:
                lookup = "cl_number"
            key = tab_keys.get(lookup)
            if not isinstance(key, str):
                continue
            if key_group == "agents" and lookup == "file_path" and not file_visible:
                continue
            bindings.append((d(key), target.footer_label))
        self._update_display(bindings, mode_label="COPY")
