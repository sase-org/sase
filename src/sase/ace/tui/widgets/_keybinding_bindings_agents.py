"""Agents-tab binding computation for :class:`KeybindingFooter`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.agent.status_buckets import AUTO_APPROVE_ELIGIBLE_STATUSES
from sase.gate_shell.state import gate_state_is_terminal
from sase.procs import ACTIVE_PROC_STATUSES

from ..keymaps.key_validation import is_unbound_key
from ..models.agent_family_members import family_roster_container
from ..models.agent_panels import is_reserved_default_panel
from ..models.agent_status import is_resumable_done_status
from .llm_calls_panel import ToolDetailLevel

if TYPE_CHECKING:
    from ..keymaps import KeymapRegistry
    from ..models.agent import Agent


class AgentBindingsMixin:
    """Entry-dependent bindings for the Agents tab."""

    if TYPE_CHECKING:

        def _kd(self, action_name: str) -> str: ...

        def _kr(self) -> KeymapRegistry: ...

    def _compute_agent_bindings(
        self,
        agent: Agent | None,
        *,
        completed_count: int = 0,
        can_jump_to_patch: bool = False,
        enter_action_label: str | None = None,
        marked_count: int = 0,
        attempt_pinned: bool = False,
        panel_focused: bool = False,
        panel_collapsed: bool = False,
        panel_collapse_jump_available: bool = False,
        panel_restore_armed: bool = False,
        panel_isolation_available: bool = False,
        panel_fold_sweep_available: bool = False,
        panel_fold_restore_armed: bool = False,
        all_panel_fold_sweep_available: bool = False,
        all_panel_fold_restore_armed: bool = False,
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
        tmux_choice_count: int = 0,
        llm_calls_visible: bool = False,
        llm_calls_detail_level: int = 0,
    ) -> list[tuple[str, str]]:
        """Compute conditional bindings for Agents tab.

        Includes entry-dependent bindings (based on the selected agent's
        state) and app-state bindings (e.g. completed agents exist).
        """
        bindings: list[tuple[str, str]] = []
        x = self._kd("kill_agent")
        panel_focused = panel_focused or collapsed_panel_focused
        panel_collapsed = panel_collapsed or collapsed_panel_focused

        # When marks exist, x operates on the marked set and the label loses
        # its per-entry form. The unmark affordance is surfaced too.
        if marked_count > 0:
            bindings.append((x, f"kill/dismiss ({marked_count} marked)"))
            bindings.append(
                (
                    self._kd("save_marked_agents"),
                    f"save/dismiss ({marked_count} marked)",
                )
            )
            bindings.append((self._kd("clear_marks"), f"unmark ({marked_count})"))
            bindings.append(
                (self._kd("edit_spec"), f"edit chats ({marked_count} marked)")
            )
            bindings.append((self._kd("add_tag"), f"wait for {marked_count} marked"))
        elif panel_focused:
            # Whole panels are first-class selections; their remembered row is
            # intentionally not exposed as the selected agent.
            bindings.append((x, "kill/dismiss panel"))
        elif group_focused:
            # Phase 5: a focused group banner re-routes ``x`` to bulk-kill
            # every agent in the group.  Surfaces the affordance so users
            # know the key changed meaning.
            bindings.append((x, "kill/dismiss group"))

        if panel_focused and not is_reserved_default_panel(focused_panel_key):
            bindings.append((self._kd("edit_hooks"), "fork tribe"))
            if marked_count == 0:
                bindings.append((self._kd("add_tag"), "wait for tribe"))

        if artifact_file_viewer_active:
            bindings.append((self._kd("next_tab"), "focus artifact pane"))
            bindings.append((self._kd("quit"), "close artifact pane"))

        llm_calls_can_compact = False
        if llm_calls_visible:
            level = ToolDetailLevel(
                max(
                    ToolDetailLevel.COMPACT,
                    min(ToolDetailLevel.FULL, int(llm_calls_detail_level)),
                )
            )
            llm_calls_can_compact = level > ToolDetailLevel.COMPACT
            if level < ToolDetailLevel.FULL:
                bindings.append((self._kd("expand_or_layout"), "more detail"))

        if panel_focused:
            bindings.append(
                (
                    f"{self._kd('next_patch')}/{self._kd('prev_patch')}",
                    "panel",
                )
            )
            bindings.append(("0-9", "member"))
            if panel_collapsed:
                bindings.append((self._kd("expand_or_layout"), "expand panel"))
                if panel_collapse_jump_available:
                    bindings.append(
                        (
                            self._kd("hooks_or_collapse"),
                            "last expanded panel",
                        )
                    )
            else:
                bindings.append((self._kd("hooks_or_collapse"), "collapse panel"))
                bindings.append((self._kd("expand_or_layout"), "enter panel"))
                bindings.append(("Esc", "enter panel"))

        if panel_isolation_available:
            bindings.append(
                (
                    self._kd("isolate_panels"),
                    "restore panels" if panel_restore_armed else "only panel",
                )
            )

        if panel_fold_sweep_available:
            bindings.append((self._kd("collapse_panel_folds"), "collapse folds"))
        elif panel_fold_restore_armed:
            bindings.append((self._kd("collapse_panel_folds"), "restore folds"))

        if all_panel_fold_sweep_available:
            bindings.append(
                (self._kd("collapse_all_panel_folds"), "collapse all folds")
            )
        elif all_panel_fold_restore_armed:
            bindings.append((self._kd("collapse_all_panel_folds"), "restore all folds"))

        if (
            left_navigation_kind in {"workflow", "family", "clan", "tribe"}
            and not panel_focused
        ):
            bindings.append(
                (
                    self._kd("hooks_or_collapse"),
                    f"parent {left_navigation_kind}",
                )
            )

        collapse_all_label: str | None = None
        if llm_calls_can_compact:
            collapse_all_label = "compact LLM Calls"
        elif panel_focused:
            if not llm_calls_visible and panel_hint_collapse_available:
                collapse_all_label = "collapse fold"
        elif structural_collapse_kind in {"workflow", "family"}:
            collapse_all_label = f"collapse {structural_collapse_kind}"
        elif lane_collapse_available:
            collapse_all_label = "collapse sase agents"
        elif clan_collapse_available:
            collapse_all_label = (
                "collapse clan"
                if selected_clan_collapse_available
                else "collapse clans"
            )
        elif structural_collapse_kind == "clan":
            collapse_all_label = "collapse clan"
        elif group_collapse_available:
            collapse_all_label = "collapse group"
        if collapse_all_label is not None:
            bindings.append((self._kd("hooks_or_collapse_all"), collapse_all_label))

        # When marks exist, A operates on the union of marked-agent artifacts.
        # Surface the affordance even if the focused agent has none of its own.
        if marked_count > 0:
            bindings.append(
                (self._kd("open_artifact_files"), "artifact files (marked)")
            )

        if agent is None:
            # Even with no selected agent, show app-state bindings
            if completed_count > 0:
                bindings.append(
                    (
                        self._kd("open_agent_cleanup_panel"),
                        f"cleanup ({completed_count} done)",
                    )
                )
            return bindings

        if not getattr(agent, "fleet_origin_alias", None):
            bindings.append((self._kd("view_agent_metadata"), "metadata"))

        if getattr(agent, "is_monitor", False):
            # A monitor has no LLM process to kill; ``x`` only stops the
            # supervised command while it is still running, and otherwise
            # dismisses the settled row. Retry/edit-chat/name are agent-chat
            # controls a monitor never supports, so they are omitted here
            # rather than inherited from the fallthrough agent bindings below.
            if marked_count == 0 and not panel_focused and not group_focused:
                if agent.monitor_state == "running":
                    bindings.append((x, "stop monitor"))
                else:
                    bindings.append((x, "dismiss"))
                if agent.monitor_id:
                    bindings.append((self._kd("edit_hooks"), "fork"))
            if (
                not panel_focused
                and not group_focused
                and family_roster_container(agent) is not None
            ):
                bindings.append(("0-9", "shell"))
            if completed_count > 0:
                bindings.append(
                    (
                        self._kd("open_agent_cleanup_panel"),
                        f"cleanup ({completed_count} done)",
                    )
                )
            return bindings

        if getattr(agent, "is_proc_shell", False):
            if marked_count == 0 and not panel_focused and not group_focused:
                if agent.proc_status in ACTIVE_PROC_STATUSES:
                    bindings.append((x, "kill proc"))
                else:
                    bindings.append((x, "dismiss proc"))
                if agent.proc_id:
                    bindings.append((self._kd("edit_hooks"), "fork"))
            if completed_count > 0:
                bindings.append(
                    (
                        self._kd("open_agent_cleanup_panel"),
                        f"cleanup ({completed_count} done)",
                    )
                )
            return bindings

        if getattr(agent, "is_gate", False):
            if (
                marked_count == 0
                and not panel_focused
                and not group_focused
                and (gate_state_is_terminal(agent.gate_state) or agent.stop_time)
            ):
                bindings.append((x, "dismiss gate"))
            if (
                not panel_focused
                and not group_focused
                and family_roster_container(agent) is not None
            ):
                bindings.append(("0-9", "shell"))
            if completed_count > 0:
                bindings.append(
                    (
                        self._kd("open_agent_cleanup_panel"),
                        f"cleanup ({completed_count} done)",
                    )
                )
            return bindings

        if getattr(agent, "fleet_origin_alias", None):
            if marked_count == 0 and not panel_focused and not group_focused:
                from ..actions.agents._remote_attention import (
                    has_pending_remote_attention,
                )
                from ..actions.agents._remote_content import remote_content_available
                from ..actions.agents._remote_lifecycle import remote_capability_enabled

                alias = str(getattr(agent, "fleet_origin_alias", None) or "remote")
                if remote_capability_enabled(agent, "lifecycle.stop"):
                    bindings.append((x, f"stop {alias}"))
                if remote_capability_enabled(agent, "lifecycle.retry"):
                    bindings.append((self._kd("agents_retry"), "retry"))
                if remote_capability_enabled(agent, "lifecycle.fork"):
                    bindings.append((self._kd("edit_hooks"), "fork"))
                if remote_content_available(agent):
                    bindings.append((self._kd("edit_spec"), "content"))
                if has_pending_remote_attention(agent):
                    attention = getattr(agent, "fleet_attention", None)
                    kind = (
                        attention.get("kind") if isinstance(attention, dict) else None
                    )
                    label = "approve" if kind == "gate" else "answer"
                    bindings.append((self._kd("accept_proposal"), label))
            if completed_count > 0:
                bindings.append(
                    (
                        self._kd("open_agent_cleanup_panel"),
                        f"cleanup ({completed_count} done)",
                    )
                )
            return bindings

        if not panel_focused and not group_focused:
            if agent.is_clan_container:
                bindings.append(("0-9", "member"))
            elif (
                agent.is_family_container_row
                or family_roster_container(agent) is not None
            ):
                bindings.append(("0-9", "shell"))
            elif lane_neighbor_jump_available:
                bindings.append(("0-9", "neighbor"))

        if agent.is_clan_container:
            if marked_count == 0 and not panel_focused and not group_focused:
                bindings.append((x, "kill/dismiss clan"))
            if not panel_focused and not group_focused:
                bindings.append((self._kd("edit_hooks"), "fork clan"))
                if marked_count == 0:
                    bindings.append((self._kd("add_tag"), "wait for clan"))
            if completed_count > 0:
                bindings.append(
                    (
                        self._kd("open_agent_cleanup_panel"),
                        f"cleanup ({completed_count} done)",
                    )
                )
            return bindings

        bindings.append((self._kd("agents_retry"), "retry"))

        # --- Status-dependent actions ---
        if agent.status == "FAILED" or is_resumable_done_status(agent.status):
            if marked_count == 0:
                bindings.append((x, "dismiss"))
            if agent.status == "FAILED":
                bindings.append((self._kd("edit_hooks"), "fork"))
            else:
                if marked_count == 0 and is_resumable_done_status(agent.status):
                    bindings.append((self._kd("edit_spec"), "edit chat"))
                if agent.response_path:
                    bindings.append((self._kd("edit_hooks"), "fork"))
        elif agent.status == "WAITING INPUT":
            bindings.append((self._kd("accept_proposal"), "answer"))
            if marked_count == 0:
                if agent.pid is None:
                    bindings.append((x, "dismiss"))
                else:
                    bindings.append((x, "kill"))
        else:
            # RUNNING or other active statuses
            if marked_count == 0:
                if agent.pid is None:
                    bindings.append((x, "dismiss"))
                else:
                    bindings.append((x, "kill"))
            if agent.status in ("STARTING", "WAITING", "QUEUED", "RUNNING"):
                bindings.append((self._kd("reword"), "edit wait"))
            if agent.agent_name:
                bindings.append((self._kd("add_tag"), "new w/ wait"))
            if agent.status in AUTO_APPROVE_ELIGIBLE_STATUSES:
                # ``accept_proposal`` toggles bare ``%auto`` on eligible
                # agents, so the footer names what the key will do.
                auto_on = bool(
                    getattr(agent, "approve", False)
                    or getattr(agent, "auto_approve_plan_action", None)
                )
                bindings.append(
                    (
                        self._kd("accept_proposal"),
                        "unapprove" if auto_on else "auto-approve",
                    )
                )

        # Name agent (not available for done/failed agents)
        if agent.status not in ("DONE", "FAILED"):
            bindings.append((self._kd("rename_cl"), "name"))

        # Edit agent tribe (always available on a focused agent)
        bindings.append((self._kd("edit_agent_tribe"), "edit tribe"))

        # Open tmux window (only if agent has a workspace). When opened-workspace
        # context is cached for the selection, ``t`` opens a chooser instead of
        # the agent workspace directly, so the label advertises the target count
        # (which includes CURRENT).
        if agent.workspace_num is not None and agent.workspace_num > 0:
            if tmux_choice_count > 0:
                bindings.append(
                    (
                        self._kd("start_tmux_mode"),
                        f"tmux choices ({tmux_choice_count})",
                    )
                )
            else:
                bindings.append((self._kd("start_tmux_mode"), "tmux"))
            bindings.append((self._kd("open_tmux"), "tmux (primary)"))

        # Context-aware Enter (primary hint from the resolver).
        if enter_action_label:
            bindings.append((self._kd("act_on_agent"), enter_action_label))
        # Direct Patch jump only when rebound to a real key.
        if can_jump_to_patch:
            try:
                configured = self._kr().app.jump_to_agent_patch  # type: ignore[attr-defined]
            except Exception:
                configured = "unbound"
            if not is_unbound_key(configured):
                bindings.append((self._kd("jump_to_agent_patch"), "go to PR"))

        if has_artifact_files and marked_count == 0:
            bindings.append((self._kd("open_artifact_files"), "artifact files"))
        if agent and agent.attempt_history and not attempt_pinned:
            bindings.append((self._kd("toggle_attempt_view"), "attempt view"))

        # --- App-state bindings ---

        # Dismiss all completed (only when completed agents exist)
        if completed_count > 0:
            bindings.append(
                (
                    self._kd("open_agent_cleanup_panel"),
                    f"cleanup ({completed_count} done)",
                )
            )

        return bindings
