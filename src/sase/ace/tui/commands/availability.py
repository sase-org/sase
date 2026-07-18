"""Pure applicability predicates for command palette entries.

The palette default-omits inapplicable commands. This module is the
single place that decides "is command X runnable given context Y".
Predicates take a :class:`CommandSpec` and a :class:`CommandContext`
and return a bool.

Phase 1 ships the entry-level scoping that mirrors the existing
footer logic and the help modal's tab buckets:

- Tab scope: a command must list the current tab in ``spec.tabs``.
- ChangeSpec-tab entry predicates: most ChangeSpec actions need a selected ChangeSpec
  with a PR number; status-gated ones (mail/rebase/sync) follow the
  same gates as the footer.
- Agents-tab predicates: kill/dismiss splits by status + group focus
  + mark count, ``edit_spec``/``edit_hooks`` reuse the footer's
  done-vs-running rules, ``run_workflow`` exposes retry-edit only with a
  focused agent, ``toggle_attempt_view`` requires history, and so on.
- Axe-tab predicates: ``edit_spec`` requires a chop with recorded output,
  ``run_workflow`` (re-run) requires a done bgcmd row, ``kill_agent`` is
  always meaningful (label changes between start/stop/kill), and the parent
  row blocks bgcmd-only commands.

Predicates are intentionally conservative — when in doubt, the
command stays visible. Phase 3 can tighten further once live context
extraction lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.agent.status_buckets import ACTIVE_PLAN_HANDOFF_STATUSES
from sase.ace.tui.commands.types import CommandContext, CommandSpec
from sase.ace.tui.models.agent_status import (
    DISMISSABLE_STATUSES,
    is_resumable_done_status,
    is_revertable_agent_status,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets.bgcmd_list import AxeItem


# Statuses used by footer for editable PR gating.
_EDITABLE_STATUSES: frozenset[str] = frozenset({"WIP", "Draft", "Ready", "Mailed"})

# ChangeSpec actions that require a selected PR with a PR number.
_REQUIRES_CL_NUMBER: frozenset[str] = frozenset(
    {
        "app.show_diff",
        "app.reword",
        "app.add_tag",
        "app.view_files",
    }
)

# ChangeSpec actions that require an editable status (WIP/Draft/Ready/Mailed).
_REQUIRES_EDITABLE_STATUS: frozenset[str] = frozenset(
    {
        "app.reword",
        "app.add_tag",
        "app.rebase",
        "app.sync",
    }
)

# ChangeSpec actions that don't apply to Submitted / Reverted ChangeSpecs.
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
        "app.plans_expand",
        "app.plans_collapse",
        "app.plans_cycle_status",
        "app.plans_edit_bead",
        "app.plans_launch_epic",
        "app.plans_approve",
        "app.plans_reject",
        "app.plans_open_bug",
        "app.plans_refresh",
    }
)

_COMMITS_ARTIFACT_COMMANDS: frozenset[str] = frozenset(
    {
        "app.commits_next",
        "app.commits_prev",
        "app.commits_view_selected",
        "app.commits_copy_sha",
        "app.commits_filters",
        "app.commits_toggle_sdd",
        "app.commits_toggle_all_projects",
        "app.commits_fetch",
        "app.commits_refresh",
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
        "app.add_agent_tag",
        "app.rename_cl",
        "app.toggle_attempt_view",
        "app.toggle_agent_unread",
        "app.start_agent_from_changespec",
        "app.jump_to_agent_changespec",
        "app.zoom_panel",
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
    """Lazy-import wrapper for ``changespec.get_base_status``.

    Avoids a hard import-time dependency from a pure predicate
    module on the heavier changespec package.
    """
    from sase.ace.changespec import get_base_status

    return get_base_status(status)


# ---------------------------------------------------------------------------
# Per-spec entry predicates
# ---------------------------------------------------------------------------


def _changespecs_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    if spec.id in _BUG_COMMANDS:
        return ctx.artifacts_subtab == "bugs"
    if spec.id in _COMMITS_ARTIFACT_COMMANDS:
        return ctx.artifacts_subtab == "commits"
    if ctx.artifacts_subtab != "prs":
        if spec.id in _PLANS_ARTIFACT_COMMANDS:
            return ctx.artifacts_subtab == "plans"
        return spec.id.startswith("artifacts.") or spec.id in _NON_PRS_ARTIFACT_COMMANDS
    if spec.id == "app.pick_artifacts_project":
        return False
    cs = ctx.changespec
    # ChangeSpec-required commands need a selected ChangeSpec.
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
    # / edit_hooks all need a selected ChangeSpec row but no further gating in
    # Phase 1 — the action methods already no-op when invalid.
    if spec.id in {
        "app.change_status",
        "app.run_workflow",
        "app.edit_spec",
        "app.toggle_mark",
        "app.rename_cl",
        "app.edit_hooks",
        "app.start_agent_from_changespec",
    }:
        return cs is not None

    # Copy-mode commands scoped to changespecs need a ChangeSpec row.
    if spec.id.startswith("copy.changespecs."):
        if cs is None:
            return False
        if (
            spec.id in {"copy.changespecs.pr_number", "copy.changespecs.cl_number"}
            and cs.pr_url is None
        ):
            return False
        if spec.id == "copy.changespecs.bug" and getattr(cs, "bug", None) is None:
            return False
        return True

    # Leader commands scoped to ChangeSpec only.
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

    # The cleanup panel is discoverable even when every row action inside it is
    # currently disabled.
    if spec.id == "app.open_agent_cleanup_panel":
        return True

    if spec.id == "app.clear_marks":
        return ctx.mark_count > 0

    if spec.id == "app.save_marked_agents":
        return ctx.mark_count > 0

    # kill_agent: marks, a collapsed whole panel, and an in-panel group banner
    # are explicit scopes. Otherwise it needs a focused agent.
    if spec.id == "app.kill_agent":
        if ctx.mark_count > 0 or ctx.collapsed_panel_focused or ctx.group_focused:
            return True
        return agent is not None

    if (
        ctx.collapsed_panel_focused
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

    # jump_to_agent_changespec needs a resolvable target.
    if spec.id == "app.jump_to_agent_changespec":
        return agent is not None and ctx.can_jump_to_changespec

    # accept_proposal on agents tab → answer/approve, only when status fits.
    if spec.id == "app.accept_proposal":
        if agent is None:
            return False
        return agent.status in {
            "WAITING INPUT",
            "STARTING",
            "RUNNING",
            "PLAN",
            *ACTIVE_PLAN_HANDOFF_STATUSES,
            "WAITING",
            "QUESTION",
        }

    # edit_spec targets marks when any exist; the action validates the
    # marked set precisely and warns when no chat transcript is usable.
    if spec.id == "app.edit_spec":
        if ctx.mark_count > 0:
            return True
        if agent is None:
            return False
        return is_resumable_done_status(agent.status)

    if spec.id == "app.edit_hooks":
        if agent is None:
            return False
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

    # Copy-mode agent commands need a focused agent.
    if spec.id.startswith("copy.agents."):
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


def _axe_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    item = ctx.axe_item

    # kill_agent label changes between start/stop axe and kill, but it's
    # always meaningful from the AXE tab.
    if spec.id == "app.kill_agent":
        return True

    if spec.id == "app.open_agent_cleanup_panel":
        return True

    if spec.id == "app.edit_spec":
        return _is_chop(item) and ctx.selected_axe_chop_run_total > 0

    # Re-run is only available on a done bgcmd row.
    if spec.id == "app.run_workflow":
        return _is_bgcmd(item) and ctx.selected_axe_slot_done

    # Copy-mode axe commands need a focused row.
    if spec.id.startswith("copy.axe."):
        return item is not None

    # Most ChangeSpec/agent actions don't apply on AXE — they're already
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

    if ctx.tab == "changespecs":
        return _changespecs_available(spec, ctx)
    if ctx.tab == "agents":
        return _agents_available(spec, ctx)
    if ctx.tab == "axe":
        return _axe_available(spec, ctx)

    return True
