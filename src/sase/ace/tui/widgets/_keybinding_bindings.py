"""Binding-computation helpers for :class:`KeybindingFooter`.

Split out of ``keybinding_footer.py`` to keep each module under the 500-line
budget. This mixin contains the pure functions that turn app/entry state into
a ``list[tuple[key, label]]`` plus the shared chip formatters. The host widget
provides ``self._kd`` (resolves an action name to its footer key display) and
``self._axe_running`` (current AXE daemon state).
"""

from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.text import Text

from sase.agent.status_buckets import AUTO_APPROVE_ELIGIBLE_STATUSES

from ...patch import Patch
from ...hooks import get_failed_hooks_file_path
from ...operations import get_available_workflows
from ..models.agent_family_members import family_roster_container
from ..models.agent_panels import is_reserved_default_panel
from ..models.agent_status import is_resumable_done_status
from .tools_panel import ToolDetailLevel

if TYPE_CHECKING:
    from ..models.agent import Agent


_CHIP_SEPARATOR = " · "
_GRID_COLUMN_GAP = 2


class KeybindingBindingsMixin:
    """Pure binding-list computation extracted from :class:`KeybindingFooter`.

    The mixin relies on the host to supply:
      - ``self._kd(action_name: str) -> str`` — footer key display resolver.
      - ``self._axe_running: bool`` — whether the AXE daemon is running.
    """

    _axe_running: bool

    def _kd(self, action_name: str) -> str:  # pragma: no cover - provided by host
        raise NotImplementedError

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
    ) -> list[tuple[str, str]]:
        """Compute entry-dependent bindings for Axe tab.

        ``x`` is entry-dependent: its label changes between "start/stop axe"
        (no selectable axe-parent row in Phase 3; daemon controls remain on
        lumberjack and chop rows) and "kill" (bgcmd rows).
        ``r`` is dispatched off the selected row: ``re-run`` on a done
        background command, ``run chop`` on an idle chop row, or ``running``
        on a chop whose newest run is still active (the backend refuses an
        overlapping launch, so the affordance reflects that).
        ``e`` edits lumberjack/base-chop configuration. ``E`` opens recorded
        chop output and is shown only when that output exists.
        Ctrl+N / Ctrl+P surface only on chop rows with at least two recorded
        runs, since with zero or one run the keys cannot do anything useful.
        """
        bindings: list[tuple[str, str]] = []
        if axe_current_view == "axe":
            label = "stop axe" if self._axe_running else "start axe"
        else:
            label = "kill"
        bindings.append((self._kd("kill_agent"), label))
        if selected_slot_done:
            bindings.append((self._kd("run_workflow"), "re-run"))
        elif chop_selected and chop_selected_enabled:
            label = "running" if chop_selected_running else "run chop"
            bindings.append((self._kd("run_workflow"), label))
        if config_row_selected:
            bindings.append((self._kd("edit_spec"), "edit config"))
            bindings.append(
                (
                    self._kd("toggle_axe_description"),
                    "collapse desc" if description_expanded else "expand desc",
                )
            )
        if chop_selected and chop_run_total >= 1:
            bindings.append((self._kd("edit_panel"), "edit output"))
        if axe_current_view == "axe" and chop_run_total >= 2:
            bindings.append(
                (
                    f"{self._kd('next_agent_file')}/{self._kd('prev_agent_file')}",
                    "chop run",
                )
            )
        return bindings

    def _compute_agent_bindings(
        self,
        agent: "Agent | None",
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

        tools_can_compact = False
        if tools_visible:
            level = ToolDetailLevel(
                max(
                    ToolDetailLevel.COMPACT,
                    min(ToolDetailLevel.FULL, int(tools_detail_level)),
                )
            )
            tools_can_compact = level > ToolDetailLevel.COMPACT
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
        if tools_can_compact:
            collapse_all_label = "compact tools"
        elif panel_focused:
            if not tools_visible and panel_hint_collapse_available:
                collapse_all_label = "collapse fold"
        elif lane_collapse_available:
            collapse_all_label = "collapse lanes"
        elif clan_collapse_available:
            collapse_all_label = (
                "collapse clan"
                if selected_clan_collapse_available
                else "collapse clans"
            )
        elif structural_collapse_kind in {"workflow", "family", "clan"}:
            collapse_all_label = f"collapse {structural_collapse_kind}"
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

        if getattr(agent, "is_monitor", False):
            # A monitor has no LLM process to kill; ``x`` only does anything
            # while its supervised command is still running.
            if (
                marked_count == 0
                and not panel_focused
                and not group_focused
                and agent.monitor_state == "running"
            ):
                bindings.append((x, "stop monitor"))
            return bindings

        if (
            not panel_focused
            and not group_focused
            and (
                agent.is_clan_container
                or agent.is_family_container_row
                or family_roster_container(agent) is not None
            )
        ):
            bindings.append(("0-9", "member"))
        elif not panel_focused and not group_focused and lane_neighbor_jump_available:
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

        bindings.append((self._kd("run_workflow"), "retry"))

        # --- Status-dependent actions ---
        if agent.status == "FAILED" or is_resumable_done_status(agent.status):
            if marked_count == 0:
                bindings.append((x, "dismiss"))
            if agent.status != "FAILED":
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
                # ``accept_proposal`` now always opens the Auto-Approve menu on
                # eligible agents (it replaced the old 3-state cycle), so the
                # footer shows one stable ``auto-approve`` label regardless of
                # the agent's current auto-approval state.
                bindings.append((self._kd("accept_proposal"), "auto-approve"))

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

        # Jump to PR (only when resolution logic found a valid Patch)
        if can_jump_to_patch:
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

        if neighbor_count > 0:
            label = (
                "neighbor" if neighbor_count == 1 else f"neighbors ({neighbor_count})"
            )
            bindings.append((self._kd("start_sibling_mode"), label))

        return bindings

    def _compute_available_bindings(
        self,
        patch: Patch,
        *,
        mark_count: int = 0,
    ) -> list[tuple[str, str]]:
        """Compute conditional bindings for Patches tab.

        Includes entry-dependent bindings (based on the selected Patch)
        and app-state bindings (e.g. marks exist).
        """
        bindings: list[tuple[str, str]] = []

        # Accept proposal (only if proposed entries exist)
        if patch.commits and any(e.is_proposed for e in patch.commits):
            bindings.append((self._kd("accept_proposal"), "accept"))

        # Diff (only if PR exists)
        if patch.pr_url is not None:
            bindings.append((self._kd("show_diff"), "diff"))

        # Get base status for visibility checks
        from ...patch import get_base_status

        base_status = get_base_status(patch.status)

        _EDITABLE = ("WIP", "Draft", "Ready", "Mailed")

        # Reword (only if PR exists AND status is editable)
        if patch.pr_url is not None:
            if base_status in _EDITABLE:
                bindings.append((self._kd("reword"), "reword"))

        # Add tag (only if PR exists AND status is editable)
        if patch.pr_url is not None:
            if base_status in _EDITABLE:
                bindings.append((self._kd("add_tag"), "add tag"))

        # Mail (only if status is Ready)
        if base_status == "Ready":
            bindings.append((self._kd("mail"), "mail"))

        # Rebase (only if status is editable)
        if base_status in _EDITABLE:
            bindings.append((self._kd("rebase"), "rebase"))

        # Rewind (only if status is not Submitted/Reverted and >=2 accepted entries)
        if base_status not in ("Submitted", "Reverted") and patch.commits:
            numeric_entries = [e for e in patch.commits if not e.is_proposed]
            if len(numeric_entries) >= 2:
                bindings.append((self._kd("start_rewind"), "rewind"))

        # Sync (only if status is editable)
        if base_status in _EDITABLE:
            bindings.append((self._kd("sync"), "sync"))

        # Rename (only if status is not Submitted or Reverted)
        if base_status not in ("Submitted", "Reverted"):
            bindings.append((self._kd("rename_cl"), "rename"))

        # View files (only if PR exists)
        if patch.pr_url is not None:
            bindings.append((self._kd("view_files"), "files"))

        # Hooks from failed targets (only if failed hooks file exists)
        if get_failed_hooks_file_path(patch):
            bindings.append((self._kd("hooks_or_collapse_all"), "hooks (failed)"))

        # Run workflows (only if workflows available for this Patch)
        workflows = get_available_workflows(patch)
        if len(workflows) == 1:
            bindings.append((self._kd("run_workflow"), f"run {workflows[0]}"))
        elif len(workflows) > 1:
            bindings.append(
                (self._kd("run_workflow"), f"run ({len(workflows)} workflows)")
            )

        # --- App-state bindings ---

        # Marks (only when marks exist)
        if mark_count > 0:
            bindings.append(
                (self._kd("bulk_change_status"), f"bulk status ({mark_count})")
            )
            bindings.append((self._kd("clear_marks"), f"unmark ({mark_count})"))

        return bindings

    # --- Chip / layout helpers ---

    @staticmethod
    def _sorted_bindings(
        bindings: list[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        """Apply the footer sort order: symbols first, then alphabetical."""

        def _is_symbol(key: str) -> bool:
            return key.startswith("<") or (len(key) == 1 and not key[0].isalpha())

        return sorted(
            bindings,
            key=lambda x: (
                0 if _is_symbol(x[0]) else 1,
                x[0].strip("<>").lower(),
                0 if x[0][0].islower() or x[0].startswith("<") else 1,
                x[0],
            ),
        )

    @staticmethod
    def _chip_text(key: str, label: str) -> Text:
        """Single ``key⎵label`` chip — non-breaking unit."""
        chip = Text(no_wrap=True)
        chip.append(key, style="bold #00D7AF")
        chip.append(" ")
        chip.append(label, style="dim")
        return chip

    @staticmethod
    def _chip_plain_width(key: str, label: str) -> int:
        """Display width of a chip (key + space + label) in terminal cells."""
        return cell_len(key) + 1 + cell_len(label)

    def _format_bindings_inline(self, bindings: list[tuple[str, str]]) -> Text:
        """Chips joined with a dim middle-dot separator on a single line."""
        text = Text(no_wrap=True)
        sorted_b = self._sorted_bindings(bindings)
        for i, (key, label) in enumerate(sorted_b):
            if i > 0:
                text.append(_CHIP_SEPARATOR, style="dim")
            text.append_text(self._chip_text(key, label))
        return text

    def _format_bindings_grid(
        self, bindings: list[tuple[str, str]], *, columns: int
    ) -> Text:
        """Chips padded to a common cell width and flowed into ``columns``."""
        sorted_b = self._sorted_bindings(bindings)
        text = Text(no_wrap=True)
        if not sorted_b or columns < 1:
            return text
        cell_w = max(self._chip_plain_width(k, lbl) for k, lbl in sorted_b)
        n = len(sorted_b)
        for i, (key, label) in enumerate(sorted_b):
            col = i % columns
            if i > 0 and col == 0:
                text.append("\n")
            text.append_text(self._chip_text(key, label))
            is_last_in_row = col == columns - 1
            is_last_overall = i == n - 1
            if not is_last_in_row and not is_last_overall:
                pad = cell_w - self._chip_plain_width(key, label) + _GRID_COLUMN_GAP
                text.append(" " * pad)
        return text
