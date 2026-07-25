"""Mode-specific footer binding update methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...changespec import ChangeSpec
from ..keymaps import KeymapRegistry, footer_key_display

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.fold_scale import FoldScale


class KeybindingModesMixin:
    """Public ``update_*_bindings`` methods for :class:`KeybindingFooter`."""

    if TYPE_CHECKING:
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
            changespec: ChangeSpec,
            *,
            mark_count: int = 0,
        ) -> list[tuple[str, str]]: ...

        def _compute_agent_bindings(
            self,
            agent: Agent | None,
            *,
            completed_count: int = 0,
            can_jump_to_changespec: bool = False,
            marked_count: int = 0,
            attempt_pinned: bool = False,
            panel_focused: bool = False,
            panel_collapsed: bool = False,
            panel_collapse_jump_available: bool = False,
            panel_restore_armed: bool = False,
            left_navigation_kind: str | None = None,
            house_collapse_available: bool = False,
            clan_collapse_available: bool = False,
            structural_collapse_kind: str | None = None,
            group_collapse_available: bool = False,
            focused_panel_key: str | None = None,
            collapsed_panel_focused: bool = False,
            group_focused: bool = False,
            has_artifact_files: bool = False,
            artifact_file_viewer_active: bool = False,
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
        ) -> list[tuple[str, str]]: ...

    def update_bindings(self, changespec: ChangeSpec, *, mark_count: int = 0) -> None:
        """Update bindings based on current ChangeSpec and app state."""
        bindings = self._compute_available_bindings(changespec, mark_count=mark_count)
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

    def show_artifacts_pane(self) -> None:
        """Clear PR-only conditional bindings on non-PR Artifacts panes."""
        self._update_display([])

    def update_agent_bindings(
        self,
        agent: Agent | None,
        *,
        completed_count: int = 0,
        can_jump_to_changespec: bool = False,
        marked_count: int = 0,
        attempt_pinned: bool = False,
        panel_focused: bool = False,
        panel_collapsed: bool = False,
        panel_collapse_jump_available: bool = False,
        panel_restore_armed: bool = False,
        left_navigation_kind: str | None = None,
        house_collapse_available: bool = False,
        clan_collapse_available: bool = False,
        structural_collapse_kind: str | None = None,
        group_collapse_available: bool = False,
        focused_panel_key: str | None = None,
        collapsed_panel_focused: bool = False,
        group_focused: bool = False,
        has_artifact_files: bool = False,
        artifact_file_viewer_active: bool = False,
        neighbor_count: int = 0,
        tmux_choice_count: int = 0,
        tools_visible: bool = False,
        tools_detail_level: int = 0,
    ) -> None:
        """Update bindings for Agents tab."""
        bindings = self._compute_agent_bindings(
            agent,
            completed_count=completed_count,
            can_jump_to_changespec=can_jump_to_changespec,
            marked_count=marked_count,
            attempt_pinned=attempt_pinned,
            panel_focused=panel_focused,
            panel_collapsed=panel_collapsed,
            panel_collapse_jump_available=panel_collapse_jump_available,
            panel_restore_armed=panel_restore_armed,
            left_navigation_kind=left_navigation_kind,
            house_collapse_available=house_collapse_available,
            clan_collapse_available=clan_collapse_available,
            structural_collapse_kind=structural_collapse_kind,
            group_collapse_available=group_collapse_available,
            focused_panel_key=focused_panel_key,
            collapsed_panel_focused=collapsed_panel_focused,
            group_focused=group_focused,
            has_artifact_files=has_artifact_files,
            artifact_file_viewer_active=artifact_file_viewer_active,
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
        )
        self._update_display(bindings)

    def update_fold_bindings(
        self,
        *,
        current_tab: str = "changespecs",
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
            (k("cycle_commits"), "commits"),
            (k("cycle_hooks"), "hooks"),
            (k("cycle_mentors"), "mentors"),
            (k("cycle_timestamps"), "timestamps"),
            (k("cycle_deltas"), "deltas"),
            (k("toggle_commits"), "toggle commits"),
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

    def update_member_jump_bindings(self, first_digit: str) -> None:
        """Show a buffered member digit and its completion/cancel hints."""
        bindings = [
            ("0-9", "second digit"),
            ("<esc>", "cancel"),
        ]
        self._update_display(bindings, mode_label=f"member {first_digit}▁")

    def update_leader_bindings(
        self,
        *,
        current_tab: str = "changespecs",
        has_comments: bool = False,
        has_notification: bool = False,
        has_mentor_results: bool = False,
        has_unread_completed_agent: bool = False,
        has_stopped_agent: bool = False,
        has_revertable_agent: bool = False,
        marked_agent_count: int = 0,
    ) -> None:
        """Update bindings to show leader mode options.

        Args:
            current_tab: The currently active tab name.
            has_comments: Whether the selected ChangeSpec has a COMMENTS field.
            has_notification: Whether the selected agent has a pending notification.
            has_mentor_results: Whether the selected ChangeSpec has mentor results.
            has_unread_completed_agent: Whether any completed agent is unread.
            has_stopped_agent: Whether any stopped agent is loaded.
            has_revertable_agent: Whether the selected Agents-tab row is a
                done/failed agent whose commits can be reverted.
            marked_agent_count: Number of marked agents; when non-zero ``,r``
                reverts every marked agent and the footer reads
                ``revert marked (N)``.
        """
        d = footer_key_display
        keys = self._kr().leader_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings: list[tuple[str, str]] = []
        bindings.append((k("repeat_last"), "repeat"))
        if current_tab == "agents":
            bindings.append((k("edit_query"), "edit query"))
        bindings.append((k("show_help"), "help"))
        if current_tab == "changespecs":
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
        if current_tab in ("changespecs", "agents"):
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
        bindings.append((k("models_panel"), "models panel"))
        bindings.append((k("update_sase"), "update SASE + CLIs + hood cache"))
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
        self._update_display(bindings, mode_label="BANG")

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

    def update_copy_bindings(self, tab: str, *, file_visible: bool = False) -> None:
        """Update bindings to show copy mode options for the current tab.

        Args:
            tab: Current tab name ("changespecs", "agents", or "axe").
            file_visible: Whether the file panel is visible (agents tab only).
        """
        d = footer_key_display
        tab_keys = self._kr().copy_mode.keys.get(tab, {})
        assert isinstance(tab_keys, dict)

        def k(name: str) -> str:
            lookup = (
                "cl_number" if name == "pr_number" and name not in tab_keys else name
            )
            v = tab_keys[lookup]
            assert isinstance(v, str)
            return d(v)

        if tab == "changespecs":
            bindings = [
                (k("raw"), "raw"),
                (k("with_snapshot"), "+snap"),
                (k("bug"), "bug"),
                (k("pr_number"), "PR#"),
                (k("name"), "name"),
                (k("spec"), "spec"),
                (k("snapshot"), "snap"),
            ]
        elif tab == "agents":
            bindings = [
                (k("chat"), "chat"),
                (k("name"), "name"),
                (k("prompt"), "prompt"),
                (k("snapshot"), "snap"),
            ]
            if file_visible:
                bindings.append((k("file_path"), "file path"))
        else:  # axe
            bindings = [
                (k("visible"), "visible"),
                (k("full"), "full"),
                (k("snapshot"), "snap"),
            ]
        self._update_display(bindings, mode_label="COPY")
