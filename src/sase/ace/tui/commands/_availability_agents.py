"""Agents-tab applicability predicates for command palette entries."""

from __future__ import annotations

from sase.agent.status_buckets import AUTO_APPROVE_ELIGIBLE_STATUSES
from sase.ace.tui.agent_completion import agent_prompt_name
from sase.ace.tui.commands.types import CommandContext, CommandSpec
from sase.ace.tui.models.agent_panels import is_reserved_default_panel
from sase.ace.tui.models.agent_status import (
    DISMISSABLE_STATUSES,
    is_failed_agent_status,
    is_resumable_done_status,
    is_revertable_agent_status,
)
from sase.ace.tui.models.fold_scale import (
    fold_level_at_position,
    resolve_summary_fold_scale,
)


# Agent actions that require a focused agent (not a group banner).
# ``app.edit_hooks`` (fork) is deliberately excluded: unlike the rest of this
# set it also applies to proc-shell/monitor rows, which the generic
# ``is_proc_shell`` guard below would otherwise block. Its own predicate
# branch handles every row kind, including ``agent is None``.
_REQUIRES_AGENT: frozenset[str] = frozenset(
    {
        "app.edit_spec",
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


def agents_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    """Return whether an Agents-tab command is runnable."""
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

    if getattr(agent, "is_proc_shell", False) and spec.id in _REQUIRES_AGENT:
        return False

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

    # accept_proposal on agents tab -> answer/approve, only when status fits.
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
        if getattr(agent, "is_proc_shell", False):
            return bool(getattr(agent, "proc_id", None))
        if getattr(agent, "is_monitor", False):
            return bool(getattr(agent, "monitor_id", None))
        if is_failed_agent_status(agent.status):
            return agent_prompt_name(agent) is not None
        if agent.status not in DISMISSABLE_STATUSES:
            return bool(getattr(agent, "agent_name", None)) or bool(
                getattr(agent, "agent_family", None)
            )
        return is_resumable_done_status(agent.status) and bool(
            getattr(agent, "response_path", None)
        )

    # rename_cl on agents tab -> "name" - disabled for done/failed agents.
    if spec.id == "app.rename_cl":
        if agent is None:
            return False
        return agent.status not in _DONE_AGENT_STATUSES

    # tmux open - only when workspace exists.
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
