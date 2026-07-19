"""Mode command builders for the ace TUI command catalog."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from sase.ace.tui.commands._formatting import format_key_sequence
from sase.ace.tui.commands._tabs import ALL_TABS, CL_AGENTS, CL_ONLY, AGENTS_ONLY
from sase.ace.tui.commands.types import CommandExecutor, CommandSpec, CommandTab
from sase.ace.tui.keymaps.types import BUILTIN_MODE_NAMES

if TYPE_CHECKING:
    from sase.ace.tui.keymaps import KeymapRegistry


# label per command_id within each built-in mode. Tabs default to all
# three; copy_mode subkeys are scoped per-tab by their nesting and have
# their tabs derived in ``iter_mode_commands``.
_FOLD_LABELS: dict[str, str] = {
    "cycle_commits": "Cycle commits fold",
    "cycle_hooks": "Cycle hooks fold",
    "cycle_mentors": "Cycle mentors fold",
    "cycle_timestamps": "Cycle timestamps fold",
    "cycle_deltas": "Cycle deltas summary/files/lines",
    "toggle_commits": "Toggle commits fold",
    "toggle_hooks": "Toggle hooks fold",
    "toggle_mentors": "Toggle mentors fold",
    "toggle_timestamps": "Toggle timestamps fold",
    "toggle_deltas": "Toggle deltas fold",
    "cycle_all": "Cycle all folds",
    "toggle_all": "Toggle all folds",
}

_AGENT_FOLD_LABELS: dict[str, str] = {
    "cycle_level": "Cycle metadata panel fold level",
    "cycle_level_back": "Cycle metadata panel fold level backward",
    "cycle_section": "Cycle current metadata section fold",
    "toggle_section": "Toggle current metadata section fold",
}

_COPY_LABELS: dict[str, dict[str, str]] = {
    "changespecs": {
        "raw": "Copy raw line",
        "with_snapshot": "Copy line + snapshot",
        "bug": "Copy bug id",
        "pr_number": "Copy PR number",
        "cl_number": "Copy PR number",
        "name": "Copy ChangeSpec name",
        "spec": "Copy spec text",
        "snapshot": "Copy snapshot",
    },
    "agents": {
        "chat": "Copy chat path",
        "file_path": "Copy file path",
        "name": "Copy agent name",
        "prompt": "Copy prompt",
        "snapshot": "Copy snapshot",
    },
    "axe": {
        "visible": "Copy visible output",
        "full": "Copy full output",
        "snapshot": "Copy snapshot",
    },
}

_LEADER_LABELS: dict[str, str] = {
    "repeat_last": "Repeat last leader command",
    "run_cmd": "Run background command",
    "runners": "Show runners",
    "revert_agent": "Revert agent + opened repos",
    "kill_mentors": "Kill mentor workflows",
    "review_mentors": "Review mentor results",
    "agent_home": "Agent (home mode)",
    "agent_from_cl": "Agent from PR (quick)",
    "toggle_agent_panel_grouping": "Toggle agent panel grouping",
    "toggle_selected_agent_panels": "Toggle visible agent folds",
    "jump_to_next_unread_done_agent": "Jump to next unread completed agent",
    "jump_to_next_stopped_agent": "Jump to next stopped agent",
    "full_history_refresh": "Refresh Agents from full history",
    "mark_all_unread_done_agents_read": "Mark all unread completed agents read",
    "kill_and_edit": "Kill agent and edit",
    "clear_comments": "Clear PR comments",
    "open_prompt_stash": "Open prompt stash",
    "prompt_history": "Prompt history",
    "prompt_history_edit_first": "Edit first prompt history entry",
    "prompt_history_cancelled": "Prompt history (cancelled)",
    "agent_run_log": "Agent run log",
    "jump_to_notification": "Jump to notification",
    "models_panel": "Models panel",
    # Back-compat: a user keymap may still bind the pre-rename action id.
    "temporary_llm_override": "Models panel",
    "update_sase": "Update sase, core, and plugins",
    "capture_agents_repro": "Capture Agents-tab repro bundle",
    "toggle_agents_repro_checks": "Toggle Agents-tab repro checks",
}

_BANG_LABELS: dict[str, str] = {
    "run_cmd": "Run command (bang)",
    "toggle_axe": "Toggle AXE (bang)",
}

# Per-mode fallback tab scoping (refined per-command for copy_mode).
_LEADER_TABS: dict[str, tuple[CommandTab, ...]] = {
    "run_cmd": CL_ONLY,
    "kill_mentors": CL_ONLY,
    "review_mentors": CL_ONLY,
    "agent_run_log": CL_ONLY,
    "kill_and_edit": AGENTS_ONLY,
    "revert_agent": AGENTS_ONLY,
    "toggle_agent_panel_grouping": AGENTS_ONLY,
    "toggle_selected_agent_panels": AGENTS_ONLY,
    "jump_to_next_unread_done_agent": AGENTS_ONLY,
    "jump_to_next_stopped_agent": AGENTS_ONLY,
    "full_history_refresh": AGENTS_ONLY,
    "mark_all_unread_done_agents_read": AGENTS_ONLY,
    "clear_comments": CL_ONLY,
    "jump_to_notification": AGENTS_ONLY,
    "agent_from_cl": CL_AGENTS,
    "capture_agents_repro": AGENTS_ONLY,
    "toggle_agents_repro_checks": AGENTS_ONLY,
}


def _iter_fold_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    fold = registry.fold_mode
    prefix = fold.prefix
    for command_id, subkey in fold.keys.items():
        if not isinstance(subkey, str):
            continue
        label = _FOLD_LABELS.get(command_id, command_id.replace("_", " ").title())
        seq = (prefix, subkey)
        yield CommandSpec(
            id=f"fold.{command_id}",
            label=label,
            key_sequence=seq,
            key_display=format_key_sequence(seq),
            category="Fold",
            tabs=CL_ONLY,
            executor=CommandExecutor(kind="fold_mode_key", subkey=subkey),
            aliases=("fold", command_id),
        )

    agent_keys = fold.keys.get("agents")
    if not isinstance(agent_keys, dict):
        return
    for command_id, subkey in agent_keys.items():
        label = _AGENT_FOLD_LABELS.get(
            command_id,
            command_id.replace("_", " ").title(),
        )
        seq = (prefix, subkey)
        yield CommandSpec(
            id=f"fold.agents.{command_id}",
            label=label,
            key_sequence=seq,
            key_display=format_key_sequence(seq),
            category="Fold",
            tabs=AGENTS_ONLY,
            executor=CommandExecutor(kind="fold_mode_key", subkey=subkey),
            aliases=("fold", "metadata", command_id),
        )


def _iter_copy_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    copy = registry.copy_mode
    prefix = copy.prefix
    tab_to_command_tab: dict[str, CommandTab] = {
        "changespecs": "changespecs",
        "agents": "agents",
        "axe": "axe",
    }
    for tab_name, sub in copy.keys.items():
        if not isinstance(sub, dict):
            continue
        ctab = tab_to_command_tab.get(tab_name)
        if ctab is None:
            continue
        labels = _COPY_LABELS.get(tab_name, {})
        for command_id, subkey in sub.items():
            if not isinstance(subkey, str):
                continue
            label = labels.get(command_id, command_id.replace("_", " ").title())
            seq = (prefix, subkey)
            yield CommandSpec(
                id=f"copy.{tab_name}.{command_id}",
                label=label,
                key_sequence=seq,
                key_display=format_key_sequence(seq),
                category="Copy",
                tabs=(ctab,),
                executor=CommandExecutor(
                    kind="copy_mode_key", subkey=subkey, copy_tab=ctab
                ),
                aliases=("copy", command_id),
            )


def _iter_leader_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    leader = registry.leader_mode
    prefix = leader.prefix
    for command_id, subkey in leader.keys.items():
        if not isinstance(subkey, str):
            continue
        label = _LEADER_LABELS.get(command_id, command_id.replace("_", " ").title())
        tabs = _LEADER_TABS.get(command_id, ALL_TABS)
        seq = (prefix, subkey)
        yield CommandSpec(
            id=f"leader.{command_id}",
            label=label,
            key_sequence=seq,
            key_display=format_key_sequence(seq),
            category="Leader",
            tabs=tabs,
            executor=CommandExecutor(kind="leader_mode_key", subkey=subkey),
            aliases=("leader", command_id),
        )


def _iter_bang_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    bang = registry.bang_mode
    prefix = bang.prefix
    for command_id, subkey in bang.keys.items():
        if not isinstance(subkey, str):
            continue
        label = _BANG_LABELS.get(command_id, command_id.replace("_", " ").title())
        seq = (prefix, subkey)
        yield CommandSpec(
            id=f"bang.{command_id}",
            label=label,
            key_sequence=seq,
            key_display=format_key_sequence(seq),
            category="Bang",
            tabs=ALL_TABS,
            executor=CommandExecutor(kind="bang_mode_key", subkey=subkey),
            aliases=("bang", command_id),
        )


def _iter_custom_mode_commands(
    registry: KeymapRegistry,
) -> Iterator[CommandSpec]:
    for mode_name, mode in registry.modes.items():
        if mode_name in BUILTIN_MODE_NAMES:
            continue
        if not mode.prefix:
            continue
        for command_id, payload in mode.keys.items():
            if not isinstance(payload, dict):
                continue
            subkey = payload.get("key")
            if not subkey:
                continue
            label = payload.get("description", command_id.replace("_", " ").title())
            seq = (mode.prefix, subkey)
            yield CommandSpec(
                id=f"custom.{mode_name}.{command_id}",
                label=label,
                key_sequence=seq,
                key_display=format_key_sequence(seq),
                category="Custom",
                tabs=ALL_TABS,
                executor=CommandExecutor(
                    kind="custom_mode_key",
                    mode_name=mode_name,
                    command_id=command_id,
                    subkey=subkey,
                ),
                aliases=("custom", mode_name, command_id),
            )


def iter_mode_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    """Yield one CommandSpec for every mode subkey (built-in + custom)."""
    yield from _iter_fold_commands(registry)
    yield from _iter_copy_commands(registry)
    yield from _iter_leader_commands(registry)
    yield from _iter_bang_commands(registry)
    yield from _iter_custom_mode_commands(registry)
