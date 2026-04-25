"""Binding-computation helpers for :class:`KeybindingFooter`.

Split out of ``keybinding_footer.py`` to keep each module under the 500-line
budget. This mixin contains the pure functions that turn app/entry state into
a ``list[tuple[key, label]]`` plus the shared formatter. The host widget
provides ``self._kd`` (resolves an action name to its footer key display) and
``self._axe_running`` (current AXE daemon state).
"""

from typing import TYPE_CHECKING

from rich.text import Text

from ...changespec import ChangeSpec
from ...hooks import get_failed_hooks_file_path
from ...operations import get_available_workflows

if TYPE_CHECKING:
    from ..models.agent import Agent


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
    ) -> list[tuple[str, str]]:
        """Compute entry-dependent bindings for Axe tab.

        ``x`` is entry-dependent: its label changes between
        "start/stop axe" (AxeParentItem) and "kill" (LumberjackItem / BgCmdItem).
        ``r`` (re-run) is shown only when a done background command is selected.
        """
        bindings: list[tuple[str, str]] = []
        if axe_current_view == "axe":
            label = "stop axe" if self._axe_running else "start axe"
        else:
            label = "kill"
        bindings.append((self._kd("kill_agent"), label))
        if selected_slot_done:
            bindings.append((self._kd("run_workflow"), "re-run"))
        return bindings

    def _compute_agent_bindings(
        self,
        agent: "Agent | None",
        *,
        completed_count: int = 0,
        can_jump_to_changespec: bool = False,
        marked_count: int = 0,
        attempt_pinned: bool = False,
        group_focused: bool = False,
    ) -> list[tuple[str, str]]:
        """Compute conditional bindings for Agents tab.

        Includes entry-dependent bindings (based on the selected agent's
        state) and app-state bindings (e.g. completed agents exist).
        """
        bindings: list[tuple[str, str]] = []
        x = self._kd("kill_agent")

        # When marks exist, x operates on the marked set and the label loses
        # its per-entry form. The unmark affordance is surfaced too.
        if marked_count > 0:
            bindings.append((x, f"kill/dismiss ({marked_count} marked)"))
            bindings.append((self._kd("clear_marks"), f"unmark ({marked_count})"))
        elif group_focused:
            # Phase 5: a focused group banner re-routes ``x`` to bulk-kill
            # every agent in the group.  Surfaces the affordance so users
            # know the key changed meaning.
            bindings.append((x, "kill/dismiss group"))

        if agent is None:
            # Even with no selected agent, show app-state bindings
            if completed_count > 0:
                bindings.append(
                    (
                        self._kd("toggle_axe"),
                        f"dismiss all ({completed_count})",
                    )
                )
            return bindings

        # --- Status-dependent actions ---
        if agent.status in ("DONE", "FAILED"):
            if marked_count == 0:
                bindings.append((x, "dismiss"))
            if agent.status != "FAILED":
                bindings.append((self._kd("edit_spec"), "edit chat"))
                if agent.response_path:
                    bindings.append((self._kd("run_workflow"), "resume"))
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
            if agent.status in ("WAITING", "RUNNING"):
                bindings.append((self._kd("reword"), "edit wait"))
            if agent.agent_name:
                bindings.append((self._kd("add_tag"), "new w/ wait"))
            _APPROVE_ELIGIBLE = {
                "RUNNING",
                "PLANNING",
                "PLAN APPROVED",
                "WAITING",
                "QUESTION",
            }
            if agent.status in _APPROVE_ELIGIBLE:
                if not agent.approve:
                    bindings.append((self._kd("accept_proposal"), "approve"))
                else:
                    bindings.append((self._kd("accept_proposal"), "unapprove"))

        # Name agent (not available for done/failed agents)
        if agent.status not in ("DONE", "FAILED"):
            bindings.append((self._kd("rename_cl"), "name"))

        # Add/remove agent tag (always available on a focused agent)
        bindings.append((self._kd("start_tmux_mode"), "tag/untag"))

        # Open tmux window (only if agent has a workspace)
        if agent.workspace_num is not None and agent.workspace_num > 0:
            bindings.append((self._kd("open_tmux"), "tmux (primary)"))

        # Jump to CL (only when resolution logic found a valid ChangeSpec)
        if can_jump_to_changespec:
            bindings.append((self._kd("jump_to_agent_changespec"), "go to CL"))

        # Attempt view toggle (only when prior attempts exist; suppressed
        # while viewing a pinned attempt since the toggle has no effect there)
        if agent and agent.attempt_history and not attempt_pinned:
            bindings.append((self._kd("toggle_attempt_view"), "attempt view"))

        # --- App-state bindings ---

        # Dismiss all completed (only when completed agents exist)
        if completed_count > 0:
            bindings.append(
                (self._kd("toggle_axe"), f"dismiss all ({completed_count})")
            )

        return bindings

    def _compute_available_bindings(
        self,
        changespec: ChangeSpec,
        *,
        mark_count: int = 0,
    ) -> list[tuple[str, str]]:
        """Compute conditional bindings for CLs tab.

        Includes entry-dependent bindings (based on the selected ChangeSpec)
        and app-state bindings (e.g. marks exist).
        """
        bindings: list[tuple[str, str]] = []

        # Accept proposal (only if proposed entries exist)
        if changespec.commits and any(e.is_proposed for e in changespec.commits):
            bindings.append((self._kd("accept_proposal"), "accept"))

        # Diff (only if CL exists)
        if changespec.cl is not None:
            bindings.append((self._kd("show_diff"), "diff"))

        # Get base status for visibility checks
        from ...changespec import get_base_status

        base_status = get_base_status(changespec.status)

        _EDITABLE = ("WIP", "Draft", "Ready", "Mailed")

        # Reword (only if CL exists AND status is editable)
        if changespec.cl is not None:
            if base_status in _EDITABLE:
                bindings.append((self._kd("reword"), "reword"))

        # Add tag (only if CL exists AND status is editable)
        if changespec.cl is not None:
            if base_status in _EDITABLE:
                bindings.append((self._kd("add_tag"), "add tag"))

        # Mail (only if status is Ready)
        if base_status == "Ready":
            bindings.append((self._kd("mail"), "mail"))

        # Rebase (only if status is editable)
        if base_status in _EDITABLE:
            bindings.append((self._kd("rebase"), "rebase"))

        # Rewind (only if status is not Submitted/Reverted and >=2 accepted entries)
        if base_status not in ("Submitted", "Reverted") and changespec.commits:
            numeric_entries = [e for e in changespec.commits if not e.is_proposed]
            if len(numeric_entries) >= 2:
                bindings.append((self._kd("start_rewind"), "rewind"))

        # Sync (only if status is editable)
        if base_status in _EDITABLE:
            bindings.append((self._kd("sync"), "sync"))

        # Rename (only if status is not Submitted or Reverted)
        if base_status not in ("Submitted", "Reverted"):
            bindings.append((self._kd("rename_cl"), "rename"))

        # View files (only if CL exists)
        if changespec.cl is not None:
            bindings.append((self._kd("view_files"), "files"))

        # Hooks from failed targets (only if failed hooks file exists)
        if get_failed_hooks_file_path(changespec):
            bindings.append((self._kd("hooks_or_collapse_all"), "hooks (failed)"))

        # Run workflows (only if workflows available for this ChangeSpec)
        workflows = get_available_workflows(changespec)
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

    def _format_bindings(self, bindings: list[tuple[str, str]]) -> Text:
        """Format bindings for display.

        Sorting: symbols first (angle-bracket keys like ``<enter>`` and
        non-alpha chars like ``.``), then alphabetical (case-insensitive,
        lowercase before uppercase for the same letter).
        """
        text = Text()

        def _is_symbol(key: str) -> bool:
            return key.startswith("<") or (len(key) == 1 and not key[0].isalpha())

        sorted_bindings = sorted(
            bindings,
            key=lambda x: (
                0 if _is_symbol(x[0]) else 1,
                x[0].strip("<>").lower(),
                0 if x[0][0].islower() or x[0].startswith("<") else 1,
                x[0],
            ),
        )

        for i, (key, label) in enumerate(sorted_bindings):
            if i > 0:
                text.append("  ")

            # Key in bold cyan
            text.append(key, style="bold #00D7AF")
            text.append(" ", style="")
            # Label in dim
            text.append(label, style="dim")

        return text
