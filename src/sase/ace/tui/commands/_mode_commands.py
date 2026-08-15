"""Mode command builders for the ace TUI command catalog."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from sase.ace.tui.commands._formatting import format_key_sequence
from sase.ace.tui.commands._tabs import ALL_TABS, CL_AGENTS, CL_ONLY, AGENTS_ONLY
from sase.ace.tui.commands.types import CommandExecutor, CommandSpec, CommandTab
from sase.ace.tui.copy_targets import copy_target_for
from sase.ace.tui.keymaps.mode_keymaps import BUILTIN_MODE_NAMES

if TYPE_CHECKING:
    from sase.ace.tui.keymaps import KeymapRegistry


# label per command_id within each built-in mode. Tabs default to all
# three; copy_mode subkeys are scoped per-tab by their nesting and have
# their tabs derived in ``iter_mode_commands``.
_FOLD_LABELS: dict[str, str] = {
    "cycle_stitches": "Cycle stitches fold",
    "cycle_hooks": "Cycle hooks fold",
    "cycle_mentors": "Cycle mentors fold",
    "cycle_timestamps": "Cycle timestamps fold",
    "cycle_deltas": "Cycle deltas summary/files/lines",
    "toggle_stitches": "Toggle stitches fold",
    "toggle_hooks": "Toggle hooks fold",
    "toggle_mentors": "Toggle mentors fold",
    "toggle_timestamps": "Toggle timestamps fold",
    "toggle_deltas": "Toggle deltas fold",
    "cycle_all": "Cycle all folds",
    "toggle_all": "Toggle all folds",
    "set_level_1": "Set all folds to level 1",
    "set_level_2": "Set all folds to level 2",
    "set_level_3": "Set all folds to level 3",
}

_AGENT_FOLD_LABELS: dict[str, str] = {
    "cycle_level": "Cycle metadata panel fold level",
    "toggle_all": "Toggle all metadata folds",
    "cycle_section": "Cycle current foldable section/member",
    "toggle_section": "Toggle current foldable section/member",
    "set_level_1": "Set metadata panel fold level 1",
    "set_level_2": "Set metadata panel fold level 2",
    "set_level_3": "Set metadata panel fold level 3",
    "set_level_4": "Set metadata panel fold level 4",
}

_LEADER_LABELS: dict[str, str] = {
    "repeat_last": "Repeat last leader command",
    "edit_query": "Edit query",
    "run_cmd": "Run background command",
    "runners": "Show runners",
    "revert_agent": "Revert agent + opened repos",
    "kill_mentors": "Kill mentor workflows",
    "review_mentors": "Review mentor results",
    "agent_home": "Agent (home mode)",
    "agent_from_cl": "Agent from Patch (quick)",
    "toggle_agent_panel_grouping": "Toggle agent panel grouping",
    "jump_to_next_unread_done_agent": "Jump to next unread completed agent",
    "jump_to_next_stopped_agent": "Jump to next stopped agent",
    "full_history_refresh": "Refresh Agents from full history",
    "mark_all_unread_done_agents_read": "Mark all unread completed agents read or undo",
    "kill_and_edit": "Kill agent and edit",
    "clear_comments": "Clear Patch comments",
    "open_prompt_stash": "Open prompt stash",
    "prompt_history": "Prompt history",
    "prompt_history_edit_first": "Edit first prompt history entry",
    "prompt_history_cancelled": "Prompt history (cancelled)",
    "agent_run_log": "Agent run log",
    "jump_to_notification": "Jump to notification",
    "models_panel": "Launch Control",
    # Back-compat: a user keymap may still bind the pre-rename action id.
    "temporary_llm_override": "Launch Control",
    "update_sase": "Update SASE, agent CLIs, and cached agent hoods",
    "capture_agents_repro": "Capture Agents-tab repro bundle",
    "toggle_agents_repro_checks": "Toggle Agents-tab repro checks",
}

_BANG_LABELS: dict[str, str] = {
    "run_cmd": "Run command (bang)",
    "toggle_axe": "Toggle AXE (bang)",
    "mark_pr_origin": "Mark PR origin (bang)",
}

_BEAD_ISSUE_LABELS: dict[str, str] = {
    "view": "Beads: view cached issue body",
    "edit": "Beads: edit linked issue",
    "toggle_state": "Beads: close or reopen linked issue",
    "copy_url": "Beads: copy linked issue URL",
    "attach": "Beads: attach existing issue",
    "create": "Beads: create issue for bead",
}

# Per-mode fallback tab scoping (refined per-command for copy_mode).
_LEADER_TABS: dict[str, tuple[CommandTab, ...]] = {
    "edit_query": AGENTS_ONLY,
    "run_cmd": CL_ONLY,
    "kill_mentors": CL_ONLY,
    "review_mentors": CL_ONLY,
    "agent_run_log": CL_ONLY,
    "kill_and_edit": AGENTS_ONLY,
    "revert_agent": AGENTS_ONLY,
    "toggle_agent_panel_grouping": AGENTS_ONLY,
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
        "artifacts": "artifacts",
        "artifacts_stitches": "artifacts",
        "artifacts_plans": "artifacts",
        "artifacts_documents": "artifacts",
        "artifacts_beads": "artifacts",
        "artifacts_other": "artifacts",
        "patches": "artifacts",
        "agents": "agents",
        "axe": "axe",
    }
    for tab_name, sub in copy.keys.items():
        if not isinstance(sub, dict):
            continue
        ctab = tab_to_command_tab.get(tab_name)
        if ctab is None:
            continue
        for command_id, subkey in sub.items():
            if not isinstance(subkey, str):
                continue
            target = copy_target_for(tab_name, command_id)
            label = (
                target.palette_label
                if target is not None
                else command_id.replace("_", " ").title()
            )
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


def _iter_bead_issue_commands(registry: KeymapRegistry) -> Iterator[CommandSpec]:
    mode = registry.bead_issue_mode
    prefix = mode.prefix
    for command_id, subkey in mode.keys.items():
        if not isinstance(subkey, str):
            continue
        label = _BEAD_ISSUE_LABELS.get(
            command_id,
            command_id.replace("_", " ").title(),
        )
        seq = (prefix, subkey)
        yield CommandSpec(
            id=f"bead_issue.{command_id}",
            label=label,
            key_sequence=seq,
            key_display=format_key_sequence(seq),
            category="Bugs",
            tabs=CL_ONLY,
            executor=CommandExecutor(kind="bead_issue_mode_key", subkey=subkey),
            aliases=("beads", "issue", command_id),
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
    yield from _iter_bead_issue_commands(registry)
    yield from _iter_bang_commands(registry)
    yield from _iter_custom_mode_commands(registry)
