"""Pure applicability predicates for command palette entries.

The palette default-omits inapplicable commands. This module is the
single place that decides "is command X runnable given context Y".
Predicates take a :class:`CommandSpec` and a :class:`CommandContext`
and return a bool.

Phase 1 ships the entry-level scoping that mirrors the existing
footer logic and the help modal's tab buckets:

- Tab scope: a command must list the current tab in ``spec.tabs``.
- Patch-tab entry predicates: most Patch actions need a selected Patch
  with a PR number; status-gated ones (mail/rebase/sync) follow the
  same gates as the footer.
- Agents-tab predicates: kill/dismiss splits by status + group focus
  + mark count, ``edit_spec``/``edit_hooks`` reuse the footer's
  done-vs-running rules, ``run_workflow`` exposes retry-edit only with a
  focused agent, ``toggle_attempt_view`` requires history, and so on.
- Axe-tab predicates: ``edit_spec`` and ``toggle_axe_description`` require an
  editable AXE config row, ``edit_panel`` requires a chop with recorded output,
  ``run_workflow`` (re-run) requires a done bgcmd row, ``kill_agent`` is
  always meaningful (label changes between start/stop/kill), and the parent
  row blocks bgcmd-only commands.

Predicates are intentionally conservative — when in doubt, the
command stays visible. Phase 3 can tighten further once live context
extraction lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.agent.status_buckets import AUTO_APPROVE_ELIGIBLE_STATUSES
from sase.ace.tui.agent_completion import agent_prompt_name
from sase.ace.tui.commands.types import CommandContext, CommandSpec
from sase.ace.tui.models.agent_panels import is_reserved_default_panel
from sase.ace.tui.models.agent_status import (
    DISMISSABLE_STATUSES,
    is_resumable_done_status,
    is_revertable_agent_status,
)
from sase.ace.tui.models.fold_scale import (
    fold_level_at_position,
    resolve_summary_fold_scale,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets.bgcmd_list import AxeItem


# Statuses used by footer for editable PR gating.
_EDITABLE_STATUSES: frozenset[str] = frozenset({"WIP", "Draft", "Ready", "Mailed"})

# Patch actions that require a selected PR with a PR number.
_REQUIRES_CL_NUMBER: frozenset[str] = frozenset(
    {
        "app.show_diff",
        "app.reword",
        "app.add_tag",
        "app.view_files",
        "app.mark_pr_origin",
    }
)

# Patch actions that require an editable status (WIP/Draft/Ready/Mailed).
_REQUIRES_EDITABLE_STATUS: frozenset[str] = frozenset(
    {
        "app.reword",
        "app.add_tag",
        "app.rebase",
        "app.sync",
    }
)

# Patch actions that don't apply to Submitted / Reverted Patches.
_REQUIRES_NON_TERMINAL_STATUS: frozenset[str] = frozenset(
    {
        "app.start_rewind",
        "app.rename_cl",
    }
)

_NON_PRS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.cycle_artifacts_subtab",
        "app.cycle_artifacts_subtab_reverse",
        "app.cycle_files_subtab",
        "app.cycle_files_subtab_reverse",
        "app.pick_artifacts_project",
        "app.next_tab",
        "app.prev_tab",
        "app.quit",
        "app.stop_axe_and_quit",
        "app.start_custom_agent",
        "app.start_agent_home",
        "app.start_last_vcs_xprompt_in_editor",
        "app.restore_prompt_stash",
        "app.show_notifications",
        "app.show_help",
        "app.open_config_center",
        "app.open_command_palette",
        "app.dismiss_toasts",
        "app.refresh",
        "projects",
        "logs",
        "tasks",
    }
)

_PLANS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.plans_next",
        "app.plans_prev",
        "app.plans_view_selected",
        "app.plans_filters",
        "app.plans_approve",
        "app.plans_reject",
        "app.plans_open_bead",
        "app.plans_refresh",
    }
)

_BEADS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.beads_next",
        "app.beads_prev",
        "app.beads_view_selected",
        "app.beads_filters",
        "app.beads_expand",
        "app.beads_collapse",
        "app.beads_cycle_status",
        "app.beads_edit",
        "app.beads_add_note",
        "app.beads_create",
        "app.beads_close",
        "app.beads_snooze",
        "app.beads_launch_work",
        "app.beads_open_bug",
        "app.beads_open_plan",
        "app.beads_refresh",
    }
)

_CHATS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.chats_next",
        "app.chats_prev",
        "app.chats_view_selected",
        "app.chats_filters",
        "app.chats_cycle_provenance",
        "app.chats_open_agent",
        "app.chats_open_external",
        "app.chats_copy_path",
        "app.chats_refresh",
    }
)

_FILES_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.files_next",
        "app.files_prev",
        "app.files_view_selected",
        "app.files_open_viewer",
        "app.files_open_external",
        "app.files_open_agent",
        "app.files_filters",
        "app.files_cycle_kind",
        "app.files_copy_reference",
        "app.files_copy_path",
        "app.files_refresh",
    }
)

_STITCHES_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.stitches_next",
        "app.stitches_prev",
        "app.stitches_view_selected",
        "app.stitches_copy_sha",
        "app.stitches_filters",
        "app.stitches_toggle_sdd",
        "app.stitches_cycle_merges",
        "app.stitches_toggle_all_projects",
        "app.stitches_fetch",
        "app.stitches_refresh",
    }
)

_BUG_COMMANDS: frozenset[str] = frozenset(
    {
        "app.next_bug",
        "app.prev_bug",
        "app.cycle_bug_filter",
        "app.create_bug",
        "app.edit_bug",
        "app.toggle_bug_state",
        "app.open_bug",
        "app.copy_bug",
        "app.start_agent_from_bug",
        "app.focus_bug_links",
        "app.activate_bug_link",
        "app.refresh_bugs",
    }
)

# Agent actions that require a focused agent (not a group banner).
_REQUIRES_AGENT: frozenset[str] = frozenset(
    {
        "app.edit_spec",
        "app.edit_hooks",
        "app.run_workflow",
        "app.edit_agent_tribe",
        "app.rename_cl",
        "app.toggle_attempt_view",
        "app.toggle_agent_unread",
        "app.start_agent_from_patch",
        "app.jump_to_agent_patch",
    }
)

_COLLAPSED_PANEL_HIDDEN_AGENT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.edit_panel",
        "app.next_agent_file",
        "app.prev_agent_file",
        "app.next_agent_metadata_section",
        "app.prev_agent_metadata_section",
        "app.open_artifact_files",
        "app.open_tmux",
        "app.start_tmux_mode",
        "app.start_sibling_mode",
        "app.toggle_mark",
        "leader.agent_from_cl",
    }
)

# Agent statuses considered "done" (no active process, no edits).
_DONE_AGENT_STATUSES: frozenset[str] = frozenset({"DONE", "FAILED"})


def _get_base_status(status: str) -> str:
    """Lazy-import wrapper for ``patch.get_base_status``.

    Avoids a hard import-time dependency from a pure predicate
    module on the heavier patch package.
    """
    from sase.ace.patch import get_base_status

    return get_base_status(status)


# ---------------------------------------------------------------------------
# Per-spec entry predicates
# ---------------------------------------------------------------------------


def _patches_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    if spec.id.startswith("copy.artifacts_"):
        if not spec.id.startswith(f"copy.artifacts_{ctx.artifacts_subtab}."):
            return False
        if ctx.artifact_selection_present is False:
            return False
        if ctx.artifact_available_targets is not None:
            return spec.id.rsplit(".", 1)[-1] in ctx.artifact_available_targets
        return True
    if spec.id == "app.edit_query":
        return ctx.artifacts_subtab in {"prs", "stitches", "plans"}
    if spec.id in {"app.cycle_files_subtab", "app.cycle_files_subtab_reverse"}:
        return ctx.artifacts_subtab in {"plans", "chats", "other"}
    if spec.id in _BUG_COMMANDS:
        return ctx.artifacts_subtab == "bugs"
    if spec.id in _STITCHES_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "stitches"
    if spec.id in _PLANS_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "plans"
    if spec.id in _BEADS_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "beads"
    if spec.id in _CHATS_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "chats"
    if spec.id in _FILES_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "other"
    if ctx.artifacts_subtab != "prs":
        return spec.id.startswith("artifacts.") or spec.id in _NON_PRS_ARTIFACT_COMMANDS
    if spec.id == "app.pick_artifacts_project":
        return False
    cs = ctx.patch
    # Patch-required commands need a selected Patch.
    if spec.id in _REQUIRES_CL_NUMBER and (cs is None or cs.pr_url is None):
        return False

    # Mail requires Ready status.
    if spec.id == "app.mail":
        if cs is None or cs.pr_url is None:
            return False
        return _get_base_status(cs.status) == "Ready"

    # Editable-status gates (reword, add_tag, rebase, sync).
    if spec.id in _REQUIRES_EDITABLE_STATUS:
        if cs is None:
            return False
        # sync also needs a PR number? Footer requires editable only.
        if spec.id in _REQUIRES_CL_NUMBER and cs.pr_url is None:
            return False
        return _get_base_status(cs.status) in _EDITABLE_STATUSES

    # Non-terminal-status gates.
    if spec.id in _REQUIRES_NON_TERMINAL_STATUS:
        if cs is None:
            return False
        return _get_base_status(cs.status) not in {"Submitted", "Reverted"}

    # accept_proposal needs a proposed entry.
    if spec.id == "app.accept_proposal":
        if cs is None or not cs.commits:
            return False
        return any(getattr(e, "is_proposed", False) for e in cs.commits)

    # bulk_change_status / clear_marks only when marks exist.
    if spec.id in {"app.bulk_change_status", "app.clear_marks"}:
        return ctx.mark_count > 0

    # change_status / run_workflow / edit_spec / toggle_mark / rename_cl
    # / edit_hooks all need a selected Patch row but no further gating in
    # Phase 1 — the action methods already no-op when invalid.
    if spec.id in {
        "app.change_status",
        "app.run_workflow",
        "app.edit_spec",
        "app.toggle_mark",
        "app.rename_cl",
        "app.edit_hooks",
        "app.start_agent_from_patch",
    }:
        return cs is not None

    # Copy-mode commands scoped to patches need a Patch row.
    if spec.id.startswith("copy.patches."):
        if cs is None:
            return False
        if (
            spec.id in {"copy.patches.pr_number", "copy.patches.cl_number"}
            and not cs.pr_url
        ):
            return False
        if spec.id == "copy.patches.link" and not cs.pr_url:
            return False
        if spec.id == "copy.patches.bug" and not getattr(cs, "bug", None):
            return False
        return True

    # Leader commands scoped to Patch only.
    if spec.id in {
        "leader.run_cmd",
        "leader.kill_mentors",
        "leader.review_mentors",
        "leader.clear_comments",
        "leader.agent_run_log",
    }:
        return cs is not None

    # Default: visible.
    return True


def _agents_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    agent = ctx.agent
    panel_focused = ctx.panel_focused or ctx.collapsed_panel_focused
    summary_scale = resolve_summary_fold_scale(
        whole_panel_focused=panel_focused,
        group_focused=ctx.group_focused,
        agent=agent,
    )

    if spec.id == "app.start_fold_mode" or spec.id.startswith("fold.agents."):
        if summary_scale is None:
            return False
        direct_prefix = "fold.agents.set_level_"
        if spec.id.startswith(direct_prefix):
            try:
                position = int(spec.id.removeprefix(direct_prefix))
            except ValueError:
                return False
            return fold_level_at_position(position, summary_scale) is not None

    # The cleanup panel is discoverable even when every row action inside it is
    # currently disabled.
    if spec.id == "app.open_agent_cleanup_panel":
        return True

    if spec.id == "app.search_reverse":
        return ctx.agents_metadata_search_active

    if spec.id == "app.clear_marks":
        return ctx.mark_count > 0

    if spec.id == "app.save_marked_agents":
        return ctx.mark_count > 0

    if spec.id == "app.zoom_panel":
        return panel_focused or agent is not None

    if spec.id == "app.isolate_panels":
        return ctx.split_panel_count >= 2

    if spec.id == "app.collapse_panel_folds":
        return panel_focused or agent is not None

    # add_tag on Agents starts a new prompt with a wait dependency. Marks
    # take precedence over every focused row/scope, matching the action.
    if spec.id == "app.add_tag":
        if ctx.mark_count > 0:
            return True
        if panel_focused:
            return not is_reserved_default_panel(ctx.focused_panel_key)
        if ctx.group_focused or agent is None:
            return False
        if getattr(agent, "is_clan_container", False):
            return bool(getattr(agent, "agent_clan", None))
        if not getattr(agent, "is_agent_entry", False) or getattr(
            agent,
            "is_synthetic_planner",
            False,
        ):
            return False
        return bool(agent_prompt_name(agent))

    # kill_agent: marks, a whole panel, and an in-panel group banner
    # are explicit scopes. Otherwise it needs a focused agent.
    if spec.id == "app.kill_agent":
        if ctx.mark_count > 0 or panel_focused or ctx.group_focused:
            return True
        return agent is not None

    if (
        panel_focused
        and agent is None
        and spec.id in _COLLAPSED_PANEL_HIDDEN_AGENT_COMMANDS
    ):
        return False

    # toggle_attempt_view needs an agent with prior attempts and not
    # already pinned to one.
    if spec.id == "app.toggle_attempt_view":
        if agent is None or ctx.attempt_pinned:
            return False
        return bool(getattr(agent, "attempt_history", None))

    # jump_to_agent_patch needs a resolvable target.
    if spec.id == "app.jump_to_agent_patch":
        return agent is not None and ctx.can_jump_to_patch

    # accept_proposal on agents tab → answer/approve, only when status fits.
    if spec.id == "app.accept_proposal":
        if agent is None:
            return False
        return agent.status == "WAITING INPUT" or (
            agent.status in AUTO_APPROVE_ELIGIBLE_STATUSES
        )

    # edit_spec targets marks when any exist; the action validates the
    # marked set precisely and warns when no chat transcript is usable.
    if spec.id == "app.edit_spec":
        if ctx.mark_count > 0:
            return True
        if agent is None:
            return False
        return is_resumable_done_status(agent.status)

    if spec.id == "app.edit_hooks":
        if panel_focused:
            return not is_reserved_default_panel(ctx.focused_panel_key)
        if ctx.group_focused:
            return False
        if agent is None:
            return False
        if getattr(agent, "is_clan_container", False):
            return bool(getattr(agent, "agent_clan", None))
        if agent.status not in DISMISSABLE_STATUSES:
            return bool(getattr(agent, "agent_name", None)) or bool(
                getattr(agent, "agent_family", None)
            )
        return is_resumable_done_status(agent.status) and bool(
            getattr(agent, "response_path", None)
        )

    # rename_cl on agents tab → "name" — disabled for done/failed agents.
    if spec.id == "app.rename_cl":
        if agent is None:
            return False
        return agent.status not in _DONE_AGENT_STATUSES

    # tmux open — only when workspace exists.
    if spec.id in {"app.open_tmux", "app.start_tmux_mode"}:
        if agent is None:
            return True  # global mode prefix still usable
        ws = getattr(agent, "workspace_num", None)
        return ws is not None and ws > 0

    # Generic: agent-required commands need a focused agent.
    if spec.id in _REQUIRES_AGENT and agent is None:
        return False

    # Copy-mode agent commands need a focused agent. Row-specific warm state
    # further filters paths that the visible detail pane cannot currently copy.
    if spec.id.startswith("copy.agents."):
        if spec.id == "copy.agents.chat":
            return agent is not None and bool(getattr(agent, "response_path", None))
        if spec.id == "copy.agents.file_path":
            return agent is not None and ctx.file_panel_visible
        return agent is not None

    # Leader commands scoped to agents.
    if spec.id == "leader.jump_to_next_unread_done_agent":
        return ctx.unread_completed_agent_count > 0

    if spec.id == "leader.jump_to_next_stopped_agent":
        return ctx.stopped_agent_count > 0

    if spec.id == "leader.jump_to_notification":
        return agent is not None

    if spec.id == "leader.kill_and_edit":
        # ,x is contextual: it acts on the marked set when marks exist
        # (runnable regardless of the focused row), otherwise on the
        # focused agent.
        if ctx.mark_count > 0:
            return True
        return agent is not None

    if spec.id == "leader.revert_agent":
        # Marks drive a bulk revert of every marked agent, so the command is
        # runnable when marks exist even if the focused row is a group banner
        # or a non-revertable agent.
        if ctx.mark_count > 0:
            return True
        return agent is not None and is_revertable_agent_status(agent.status)

    return True


def _is_bgcmd(item: AxeItem | None) -> bool:
    if item is None:
        return False
    from sase.ace.tui.widgets.bgcmd_list import BgCmdItem

    return isinstance(item, BgCmdItem)


def _is_chop(item: AxeItem | None) -> bool:
    if item is None:
        return False
    from sase.ace.tui.widgets.bgcmd_list import ChopItem

    return isinstance(item, ChopItem)


def _is_lumberjack(item: AxeItem | None) -> bool:
    if item is None:
        return False
    from sase.ace.tui.widgets.bgcmd_list import LumberjackItem

    return isinstance(item, LumberjackItem)


def _axe_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    item = ctx.axe_item

    # kill_agent label changes between start/stop axe and kill, but it's
    # always meaningful from the AXE tab.
    if spec.id == "app.kill_agent":
        return True

    if spec.id == "app.open_agent_cleanup_panel":
        return True

    if spec.id == "app.edit_spec":
        return _is_lumberjack(item) or _is_chop(item)

    if spec.id == "app.toggle_axe_description":
        return _is_lumberjack(item) or _is_chop(item)

    if spec.id == "app.edit_panel":
        return _is_chop(item) and ctx.selected_axe_chop_run_total > 0

    if spec.id == "app.add_axe_item":
        return True

    # Re-run is only available on a done bgcmd row.
    if spec.id == "app.run_workflow":
        if _is_bgcmd(item):
            return ctx.selected_axe_slot_done
        return (
            _is_chop(item)
            and ctx.selected_axe_chop_enabled
            and not ctx.selected_axe_chop_running
        )

    # Copy-mode axe commands need a focused row.
    if spec.id.startswith("copy.axe."):
        return item is not None

    # Most Patch/agent actions don't apply on AXE — they're already
    # filtered by spec.tabs, so this branch only sees commands that
    # listed "axe" in their tabs (mode prefixes, navigation, etc.).
    return True


# ---------------------------------------------------------------------------
# Top-level predicate
# ---------------------------------------------------------------------------


def is_command_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    """Return ``True`` if *spec* is runnable given *ctx*.

    Composes tab-scope filtering with per-tab entry predicates.
    Default: visible. Predicates only return ``False`` when a real
    precondition is violated.
    """
    if ctx.tab not in spec.tabs:
        return False

    if ctx.tab == "artifacts":
        return _patches_available(spec, ctx)
    if ctx.tab == "agents":
        return _agents_available(spec, ctx)
    if ctx.tab == "axe":
        return _axe_available(spec, ctx)

    return True
