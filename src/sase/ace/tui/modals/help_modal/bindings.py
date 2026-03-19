"""Keybinding definitions and constants for the help modal."""

from typing import Literal

from ...keymaps import BUILTIN_MODE_NAMES, KeymapRegistry, key_display_name

TabName = Literal["changespecs", "agents", "axe"]

# Box dimensions for consistent formatting
BOX_WIDTH = 57  # Total box width in characters
CONTENT_WIDTH = 50  # Inner content width (BOX_WIDTH - borders)

# Type alias for binding sections
_Sections = list[tuple[str, list[tuple[str, str]]]]


def _sk(keys: dict[str, str | dict[str, str]], name: str) -> str:
    """Extract a string value from a mode keys dict."""
    v = keys[name]
    assert isinstance(v, str)
    return v


def cls_bindings(km: KeymapRegistry) -> _Sections:
    """Build keybinding sections for the CLs tab."""
    d = key_display_name
    a = km.app
    fm = km.fold_mode
    lm = km.leader_mode
    bm = km.bang_mode
    cm = km.copy_mode

    cs_copy = cm.keys["changespecs"]
    assert isinstance(cs_copy, dict)

    sections: _Sections = [
        (
            "Navigation",
            [
                (
                    f"{d(a.next_changespec)} / {d(a.prev_changespec)}",
                    "Move to next / previous CL",
                ),
                (
                    f"{d(a.start_ancestor_mode)} / {d(a.start_child_mode)} / {d(a.start_sibling_mode)}",
                    "Navigate to ancestor / child / sibling",
                ),
                (
                    f"{d(a.prev_changespec_history)} / {d(a.next_changespec_history)}",
                    "Jump back / forward in history",
                ),
                (
                    f"{d(a.scroll_detail_down)} / {d(a.scroll_detail_up)}",
                    "Scroll detail panel down / up",
                ),
            ],
        ),
        (
            "CL Actions",
            [
                (d(a.accept_proposal), "Accept (! = spec only, @ = mail)"),
                (d(a.rebase), "Rebase CL onto parent"),
                (
                    f"{d(a.checkout)} / {d(a.start_checkout_mode)}1-{d(a.start_checkout_mode)}9",
                    "Checkout CL (workspace 1-9)",
                ),
                (d(a.show_diff), "Show diff"),
                (d(a.hooks_or_collapse), "Edit hooks"),
                (d(a.hooks_or_collapse_all), "Add hooks from failed targets"),
                (d(a.expand_all_folds), "Agent run log"),
                (d(a.mail), "Mail CL"),
                (d(a.toggle_mark), "Mark/unmark current CL"),
                (d(a.rename_cl), "Rename CL (non-Sub/Rev)"),
                (d(a.start_rewind), "Rewind to prev commit (non-Sub/Rev)"),
                (d(a.change_status), "Change status"),
                (d(a.bulk_change_status), "Bulk status change (marked CLs)"),
                (d(a.start_tmux_mode), "Checkout + tmux (prompts ws#)"),
                (d(a.clear_marks), "Clear all marks"),
                (d(a.view_files), "View files"),
                (d(a.reword), "Reword CL description"),
                (d(a.add_tag), "Add tag to CL description"),
                (d(a.sync), "Sync workspace"),
                (d(a.edit_spec), "Edit spec file"),
            ],
        ),
        (
            f"Fold Mode ({d(fm.prefix)})",
            [
                (
                    f"{d(fm.prefix)} {d(_sk(fm.keys, 'cycle_commits'))}",
                    "Cycle commits folding",
                ),
                (
                    f"{d(fm.prefix)} {d(_sk(fm.keys, 'cycle_hooks'))}",
                    "Cycle hooks folding",
                ),
                (
                    f"{d(fm.prefix)} {d(_sk(fm.keys, 'cycle_mentors'))}",
                    "Cycle mentors folding",
                ),
                (
                    f"{d(fm.prefix)} {d(_sk(fm.keys, 'cycle_all'))}",
                    "Cycle all sections",
                ),
            ],
        ),
        (
            "Workflows & Agents",
            [
                (d(a.run_workflow), "Run workflow"),
                (d(a.start_custom_agent), "Run an agent"),
                (d(a.start_agent_from_changespec), "Repeat last @/Space selection"),
            ],
        ),
        (
            f"Bang Mode ({d(bm.prefix)})",
            [
                (
                    f"{d(bm.prefix)}{d(_sk(bm.keys, 'run_cmd'))}",
                    "Run background command",
                ),
                (
                    f"{d(bm.prefix)}{d(_sk(bm.keys, 'toggle_axe'))}",
                    "Start / stop axe (or select process)",
                ),
            ],
        ),
        (
            f"Leader Mode ({d(lm.prefix)})",
            [
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'clear_comments'))}",
                    "Clear COMMENTS field",
                ),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'run_cmd'))}",
                    "Run command (use current CL)",
                ),
                (f"{d(lm.prefix)}{d(_sk(lm.keys, 'agent_home'))}", "Run agent (home)"),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'kill_mentors'))}",
                    "Kill running mentors",
                ),
                (f"{d(lm.prefix)}{d(_sk(lm.keys, 'runners'))}", "Show runners info"),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'agent_from_cl'))}",
                    "Run agent from current CL",
                ),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'prompt_history'))}",
                    "Prompt history (last CL)",
                ),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'activity_info'))}",
                    "Activity dashboard",
                ),
            ],
        ),
        (
            "Queries",
            [
                (d(a.edit_query), "Edit search query"),
                ("0-9", "Load saved query"),
                (d(a.prev_query), "Previous query"),
                (d(a.next_query), "Next query"),
            ],
        ),
        (
            f"Copy Mode ({d(cm.prefix)})",
            [
                (f"{d(cm.prefix)}{d(cs_copy['raw'])}", "Copy ChangeSpec"),
                (
                    f"{d(cm.prefix)}{d(cs_copy['with_snapshot'])}",
                    "Copy ChangeSpec + snapshot",
                ),
                (f"{d(cm.prefix)}{d(cs_copy['bug'])}", "Copy bug number"),
                (f"{d(cm.prefix)}{d(cs_copy['cl_number'])}", "Copy CL number"),
                (f"{d(cm.prefix)}{d(cs_copy['name'])}", "Copy CL name"),
                (f"{d(cm.prefix)}{d(cs_copy['spec'])}", "Copy project spec file"),
                (f"{d(cm.prefix)}{d(cs_copy['snapshot'])}", "Copy sase ace snapshot"),
            ],
        ),
    ]
    # Insert custom mode sections before "General".
    sections.extend(_custom_mode_sections(km))
    sections.append(
        (
            "General",
            [
                (f"{d(a.next_tab)} / {d(a.prev_tab)}", "Switch tabs"),
                (d(a.mark_inactive), "Toggle idle (any key clears)"),
                (d(a.mark_inactive_pinned), "Toggle pinned idle (sticky)"),
                (d(a.toggle_hide_submitted), "Show/hide submitted CLs"),
                (d(a.toggle_hide_reverted), "Show/hide reverted CLs"),
                (d(a.browse_xprompts), "Browse xprompts"),
                (d(a.show_notifications), "Show notifications"),
                (d(a.stop_axe_and_quit), "Stop axe and quit"),
                (d(a.refresh), "Refresh"),
                (d(a.quit), "Quit"),
                (d(a.show_help), "Show this help"),
            ],
        ),
    )
    return sections


def agents_bindings(km: KeymapRegistry) -> _Sections:
    """Build keybinding sections for the Agents tab."""
    d = key_display_name
    a = km.app
    lm = km.leader_mode
    bm = km.bang_mode
    cm = km.copy_mode

    ag_copy = cm.keys["agents"]
    assert isinstance(ag_copy, dict)

    sections: _Sections = [
        (
            "Navigation",
            [
                (
                    f"{d(a.next_changespec)} / {d(a.prev_changespec)}",
                    "Move to next / previous agent",
                ),
                (
                    f"{d(a.scroll_to_top)} / {d(a.scroll_to_bottom)}",
                    "Scroll file panel to top / bottom",
                ),
                (
                    f"{d(a.scroll_detail_down)} / {d(a.scroll_detail_up)}",
                    "Scroll file panel down / up",
                ),
                (
                    f"{d(a.scroll_prompt_down)} / {d(a.scroll_prompt_up)}",
                    "Scroll prompt panel down / up",
                ),
            ],
        ),
        (
            "Agent Actions",
            [
                (d(a.start_custom_agent), "Run custom agent"),
                (d(a.accept_proposal), "Toggle auto-approve / answer HITL"),
                (d(a.toggle_mark), "Send message to running agent"),
                (d(a.rename_cl), "Name agent"),
                (d(a.run_workflow), "Revive chat as agent"),
                (d(a.reword), "Unwait (remove %wait, start now)"),
                (d(a.kill_agent), "Kill / dismiss agent"),
                (d(a.toggle_axe), "Dismiss all completed agents"),
                (d(a.edit_spec), "Edit chat in editor"),
                (d(a.edit_panel), "Edit panel content in editor"),
                (
                    f"{d(a.toggle_thinking)} / {d(a.toggle_thinking_reverse)}",
                    "Cycle panels: file → thinking → metadata",
                ),
                (d(a.toggle_layout), "Toggle file/prompt layout"),
                (
                    f"{d(a.next_agent_file)} / {d(a.prev_agent_file)}",
                    "Next / prev file in panel",
                ),
                (d(a.reset_file_trim), "Reset file trim to default"),
                (d(a.show_all_file_lines), "Show all file lines"),
            ],
        ),
        (
            "Workflow Folding",
            [
                (
                    f"{d(a.expand_or_layout)} / {d(a.hooks_or_collapse)}",
                    "Expand / collapse workflow steps",
                ),
                (
                    f"{d(a.expand_all_folds)} / {d(a.hooks_or_collapse_all)}",
                    "Expand / collapse all workflows",
                ),
            ],
        ),
        (
            f"Leader Mode ({d(lm.prefix)})",
            [
                (f"{d(lm.prefix)}{d(_sk(lm.keys, 'agent_home'))}", "Run agent (home)"),
                (f"{d(lm.prefix)}{d(_sk(lm.keys, 'runners'))}", "Show runners info"),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'kill_and_edit'))}",
                    "Kill agent & edit prompt",
                ),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'prompt_history'))}",
                    "Prompt history (last CL)",
                ),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'jump_to_notification'))}",
                    "Jump to agent notification",
                ),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'activity_info'))}",
                    "Activity dashboard",
                ),
            ],
        ),
        (
            f"Bang Mode ({d(bm.prefix)})",
            [
                (
                    f"{d(bm.prefix)}{d(_sk(bm.keys, 'run_cmd'))}",
                    "Run background command",
                ),
                (
                    f"{d(bm.prefix)}{d(_sk(bm.keys, 'toggle_axe'))}",
                    "Start / stop axe (or select process)",
                ),
            ],
        ),
        (
            f"Copy Mode ({d(cm.prefix)})",
            [
                (f"{d(cm.prefix)}{d(ag_copy['chat'])}", "Copy chat file path"),
                (f"{d(cm.prefix)}{d(ag_copy['prompt'])}", "Copy agent prompt"),
                (f"{d(cm.prefix)}{d(ag_copy['snapshot'])}", "Copy sase ace snapshot"),
            ],
        ),
        (
            "Search",
            [
                (d(a.edit_query), "Filter agents by name"),
            ],
        ),
    ]
    # Insert custom mode sections before "General".
    sections.extend(_custom_mode_sections(km))
    sections.append(
        (
            "General",
            [
                (f"{d(a.next_tab)} / {d(a.prev_tab)}", "Switch tabs"),
                (d(a.mark_inactive), "Toggle idle (any key clears)"),
                (d(a.mark_inactive_pinned), "Toggle pinned idle (sticky)"),
                (d(a.start_agent_from_changespec), "Repeat last @/Space selection"),
                (d(a.toggle_hide_reverted), "Show/hide non-run agents"),
                (d(a.browse_xprompts), "Browse xprompts"),
                (d(a.show_notifications), "Show notifications"),
                (d(a.stop_axe_and_quit), "Stop axe and quit"),
                (d(a.refresh), "Refresh"),
                (d(a.quit), "Quit"),
                (d(a.show_help), "Show this help"),
            ],
        ),
    )
    return sections


def axe_bindings(km: KeymapRegistry) -> _Sections:
    """Build keybinding sections for the AXE tab."""
    d = key_display_name
    a = km.app
    lm = km.leader_mode
    bm = km.bang_mode
    cm = km.copy_mode

    axe_copy = cm.keys["axe"]
    assert isinstance(axe_copy, dict)

    sections: _Sections = [
        (
            "Navigation",
            [
                (
                    f"{d(a.next_changespec)} / {d(a.prev_changespec)}",
                    "Move to next / previous command",
                ),
                (
                    f"{d(a.next_agent_file)} / {d(a.prev_agent_file)}",
                    "Next / prev lumberjack output",
                ),
                (d(a.scroll_to_top), "Scroll to top"),
                (d(a.scroll_to_bottom), "Scroll to bottom"),
            ],
        ),
        (
            "Background Commands",
            [
                (d(a.start_custom_agent), "Run agent"),
                (d(a.toggle_axe), "Clear output"),
            ],
        ),
        (
            f"Leader Mode ({d(lm.prefix)})",
            [
                (f"{d(lm.prefix)}{d(_sk(lm.keys, 'agent_home'))}", "Run agent (home)"),
                (f"{d(lm.prefix)}{d(_sk(lm.keys, 'runners'))}", "Show runners info"),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'prompt_history'))}",
                    "Prompt history (last CL)",
                ),
                (
                    f"{d(lm.prefix)}{d(_sk(lm.keys, 'activity_info'))}",
                    "Activity dashboard",
                ),
            ],
        ),
        (
            f"Bang Mode ({d(bm.prefix)})",
            [
                (
                    f"{d(bm.prefix)}{d(_sk(bm.keys, 'run_cmd'))}",
                    "Run background command",
                ),
                (
                    f"{d(bm.prefix)}{d(_sk(bm.keys, 'toggle_axe'))}",
                    "Start / stop axe (or select process)",
                ),
            ],
        ),
        (
            f"Copy Mode ({d(cm.prefix)})",
            [
                (f"{d(cm.prefix)}{d(axe_copy['visible'])}", "Copy visible output"),
                (f"{d(cm.prefix)}{d(axe_copy['full'])}", "Copy full output"),
                (f"{d(cm.prefix)}{d(axe_copy['snapshot'])}", "Copy sase ace snapshot"),
            ],
        ),
        (
            "Axe Control",
            [
                (d(a.kill_agent), "Start / stop axe (or kill command)"),
                (d(a.toggle_axe), "Clear output"),
                (d(a.stop_axe_and_quit), "Stop axe and quit"),
            ],
        ),
    ]
    # Insert custom mode sections before "General".
    sections.extend(_custom_mode_sections(km))
    sections.append(
        (
            "General",
            [
                (f"{d(a.next_tab)} / {d(a.prev_tab)}", "Switch tabs"),
                (d(a.mark_inactive), "Toggle idle (any key clears)"),
                (d(a.mark_inactive_pinned), "Toggle pinned idle (sticky)"),
                (d(a.start_agent_from_changespec), "Repeat last @/Space selection"),
                (d(a.browse_xprompts), "Browse xprompts"),
                (d(a.show_notifications), "Show notifications"),
                (d(a.refresh), "Refresh"),
                (d(a.quit), "Quit"),
                (d(a.show_help), "Show this help"),
            ],
        ),
    )
    return sections


def _custom_mode_sections(km: KeymapRegistry) -> _Sections:
    """Build help sections for user-defined (non-builtin) custom modes."""
    d = key_display_name
    sections: _Sections = []
    for mode_name, mode in km.modes.items():
        if mode_name in BUILTIN_MODE_NAMES:
            continue
        display_name = mode_name.replace("_", " ").title()
        bindings: list[tuple[str, str]] = []
        for action_name, spec in mode.keys.items():
            if not isinstance(spec, dict):
                continue
            key = spec.get("key", "")
            desc = spec.get("description", action_name)
            bindings.append((f"{d(mode.prefix)}{d(key)}", desc))
        if bindings:
            sections.append((f"{display_name} ({d(mode.prefix)})", bindings))
    return sections


TAB_DISPLAY_NAMES = {
    "changespecs": "CLs",
    "agents": "Agents",
    "axe": "Axe",
}

# Column split indices for each tab (left column gets indices < split, right gets >= split)
COLUMN_SPLITS = {
    "changespecs": 2,  # Left: Navigation, CL Actions; Right: rest
    "agents": 3,  # Left: Navigation, Agent Actions, Workflow Folding; Right: rest
    "axe": 3,  # Left: Navigation, BgCmds, Leader Mode; Right: rest
}
