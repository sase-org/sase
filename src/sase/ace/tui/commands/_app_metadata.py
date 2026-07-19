"""App action metadata for the ace TUI command catalog."""

from __future__ import annotations

from dataclasses import fields

from sase.ace.tui.commands._tabs import (
    AGENTS_AXE,
    AGENTS_ONLY,
    ALL_TABS,
    CL_AGENTS,
    CL_AXE,
    CL_ONLY,
)
from sase.ace.tui.commands.types import CommandCategory, CommandTab
from sase.ace.tui.keymaps.types import AppKeymaps

type AppCommandMeta = tuple[
    str, str, CommandCategory, tuple[CommandTab, ...], tuple[str, ...]
]


# (action, label, category, tabs, aliases).  Action name MUST match an
# AppKeymaps field. Labels are tuned for the palette; categories mirror
# the help modal sections; tabs encode where the binding can ever fire
# (entry-level applicability is layered on by ``availability.py``).
APP_COMMAND_META: tuple[AppCommandMeta, ...] = (
    # Navigation
    ("next_changespec", "Next entry", "Navigation", ALL_TABS, ("down", "j")),
    ("prev_changespec", "Previous entry", "Navigation", ALL_TABS, ("up", "k")),
    ("scroll_to_top", "Scroll to top", "Navigation", ALL_TABS, ("g",)),
    ("scroll_to_bottom", "Scroll to bottom", "Navigation", ALL_TABS, ("G",)),
    ("scroll_detail_down", "Scroll detail down", "Navigation", ALL_TABS, ()),
    ("scroll_detail_up", "Scroll detail up", "Navigation", ALL_TABS, ()),
    ("scroll_prompt_down", "Scroll prompt down", "Navigation", AGENTS_ONLY, ()),
    ("scroll_prompt_up", "Scroll prompt up", "Navigation", AGENTS_ONLY, ()),
    (
        "next_agent_metadata_section",
        "Next metadata section",
        "Navigation",
        AGENTS_ONLY,
        ("section", "heading", "ctrl+j"),
    ),
    (
        "prev_agent_metadata_section",
        "Previous metadata section",
        "Navigation",
        AGENTS_ONLY,
        ("section", "heading", "ctrl+k"),
    ),
    ("next_agent_file", "Next file / chop run", "Navigation", AGENTS_AXE, ()),
    ("prev_agent_file", "Previous file / chop run", "Navigation", AGENTS_AXE, ()),
    ("jump_to_entry", "Jump to entry", "Navigation", ALL_TABS, ("hint",)),
    (
        "jump_to_entry_fast",
        "Fast jump to entry",
        "Navigation",
        ALL_TABS,
        ("jump", "first", "back", "ctrl+o"),
    ),
    (
        "jump_to_entry_forward",
        "Jump forward through jump stack",
        "Navigation",
        CL_AXE,
        ("jump", "forward", "ctrl+k"),
    ),
    ("jump_to_all_entries", "Jump to any entry", "Navigation", ALL_TABS, ("hint",)),
    # Tab switching
    ("next_tab", "Next tab", "Tabs", ALL_TABS, ()),
    ("prev_tab", "Previous tab", "Tabs", ALL_TABS, ()),
    (
        "cycle_artifacts_subtab",
        "Next Artifacts sub-tab",
        "Tabs",
        CL_ONLY,
        ("next artifact", "commits", "bugs", "plans"),
    ),
    (
        "cycle_artifacts_subtab_reverse",
        "Previous Artifacts sub-tab",
        "Tabs",
        CL_ONLY,
        ("previous artifact",),
    ),
    (
        "pick_artifacts_project",
        "Pick Artifacts project scope",
        "Tabs",
        CL_ONLY,
        ("project scope", "filter project"),
    ),
    # Commits sub-tab
    ("commits_next", "Commits: next row", "Navigation", CL_ONLY, ("commit down",)),
    (
        "commits_prev",
        "Commits: previous row",
        "Navigation",
        CL_ONLY,
        ("commit up",),
    ),
    ("commits_view_selected", "Commits: view selected", "Display", CL_ONLY, ()),
    ("commits_copy_sha", "Commits: copy SHA", "Display", CL_ONLY, ()),
    ("commits_filters", "Commits: filter bar", "Display", CL_ONLY, ()),
    (
        "commits_toggle_sdd",
        "Commits: toggle SDD history",
        "Display",
        CL_ONLY,
        (),
    ),
    (
        "commits_toggle_all_projects",
        "Commits: toggle all projects",
        "Display",
        CL_ONLY,
        (),
    ),
    (
        "commits_fetch",
        "Commits: fetch remote refs",
        "Proposals & Sync",
        CL_ONLY,
        (),
    ),
    (
        "commits_refresh",
        "Commits: refresh local refs",
        "Proposals & Sync",
        CL_ONLY,
        ("reload commits",),
    ),
    # Plans sub-tab
    ("plans_next", "Plans: next row", "Navigation", CL_ONLY, ("plan down",)),
    ("plans_prev", "Plans: previous row", "Navigation", CL_ONLY, ("plan up",)),
    ("plans_view_selected", "Plans: view selected", "Display", CL_ONLY, ()),
    ("plans_filters", "Plans: filter bar", "Display", CL_ONLY, ()),
    ("plans_expand", "Plans: expand epic", "Folding", CL_ONLY, ()),
    ("plans_collapse", "Plans: collapse epic", "Folding", CL_ONLY, ()),
    (
        "plans_cycle_status",
        "Plans: cycle bead status",
        "Proposals & Sync",
        CL_ONLY,
        ("bead status",),
    ),
    (
        "plans_edit_bead",
        "Plans: edit bead",
        "Proposals & Sync",
        CL_ONLY,
        ("bead description",),
    ),
    (
        "plans_launch_epic",
        "Plans: launch epic work",
        "Agents",
        CL_ONLY,
        ("bead work", "run epic"),
    ),
    (
        "plans_approve",
        "Plans: approve proposal",
        "Proposals & Sync",
        CL_ONLY,
        ("approve plan",),
    ),
    (
        "plans_reject",
        "Plans: reject proposal",
        "Proposals & Sync",
        CL_ONLY,
        ("reject plan",),
    ),
    ("plans_open_bug", "Plans: open linked bug", "Display", CL_ONLY, ()),
    (
        "plans_refresh",
        "Plans: refresh",
        "Proposals & Sync",
        CL_ONLY,
        ("reload plans",),
    ),
    # Bugs sub-tab
    ("next_bug", "Next bug", "Bugs", CL_ONLY, ("next issue",)),
    ("prev_bug", "Previous bug", "Bugs", CL_ONLY, ("previous issue",)),
    ("cycle_bug_filter", "Cycle bug state filter", "Bugs", CL_ONLY, ()),
    ("create_bug", "Create bug", "Bugs", CL_ONLY, ("create issue",)),
    ("edit_bug", "Edit bug", "Bugs", CL_ONLY, ("edit issue",)),
    (
        "toggle_bug_state",
        "Close or reopen bug",
        "Bugs",
        CL_ONLY,
        ("close issue", "reopen issue"),
    ),
    ("open_bug", "Open bug in browser", "Bugs", CL_ONLY, ("issue url",)),
    ("copy_bug", "Copy bug URL and number", "Bugs", CL_ONLY, ()),
    (
        "start_agent_from_bug",
        "Run agent from bug",
        "Bugs",
        CL_ONLY,
        ("fix issue",),
    ),
    ("focus_bug_links", "Focus linked epics and PRs", "Bugs", CL_ONLY, ()),
    ("activate_bug_link", "Open focused bug link", "Bugs", CL_ONLY, ()),
    ("refresh_bugs", "Refresh bugs", "Bugs", CL_ONLY, ("reload issues",)),
    # PR Actions
    ("quit", "Quit ace", "Misc", ALL_TABS, ("exit",)),
    ("change_status", "Change PR status", "PR Actions", CL_ONLY, ()),
    (
        "run_workflow",
        "Run workflow / retry agent / re-run",
        "PR Actions",
        ALL_TABS,
        ("retry", "relaunch", "edit prompt"),
    ),
    ("mail", "Mail PR", "PR Actions", CL_ONLY, ("send",)),
    ("show_diff", "Show diff", "PR Actions", CL_ONLY, ()),
    ("reword", "Reword PR", "PR Actions", CL_ONLY, ()),
    ("add_tag", "Add tag", "PR Actions", CL_ONLY, ()),
    ("view_files", "View PR files", "PR Actions", CL_ONLY, ()),
    ("edit_spec", "Edit spec / chat / chop output", "PR Actions", ALL_TABS, ()),
    ("rename_cl", "Rename PR / agent", "PR Actions", CL_AGENTS, ()),
    # ChangeSpec edits
    (
        "edit_hooks",
        "Edit hooks / fork agent",
        "ChangeSpec Edits",
        CL_AGENTS,
        ("fork",),
    ),
    # Proposals & Sync
    ("accept_proposal", "Accept proposal", "Proposals & Sync", CL_AGENTS, ()),
    ("rebase", "Rebase PR", "Proposals & Sync", CL_ONLY, ()),
    (
        "start_rewind",
        "Rewind PR / Revive agent",
        "Proposals & Sync",
        CL_AGENTS,
        (),
    ),
    ("sync", "Sync repo", "Proposals & Sync", ALL_TABS, ()),
    ("refresh", "Refresh tab", "Proposals & Sync", ALL_TABS, ("reload",)),
    # Folding
    (
        "hooks_or_collapse",
        "Toggle hooks / collapse / less tools detail",
        "Folding",
        ALL_TABS,
        (),
    ),
    (
        "hooks_or_collapse_all",
        "Collapse focused agent panel / all folds / compact tools detail",
        "Folding",
        ALL_TABS,
        (),
    ),
    (
        "expand_or_layout",
        "Expand entry / change layout / more tools detail",
        "Folding",
        ALL_TABS,
        (),
    ),
    (
        "expand_all_folds",
        "Expand focused agent panel / all folds / full tools detail",
        "Folding",
        ALL_TABS,
        (),
    ),
    ("toggle_layout", "Toggle layout", "Folding", ALL_TABS, ()),
    # Marking
    ("toggle_mark", "Mark / unmark entry", "Marking", CL_AGENTS, ()),
    ("clear_marks", "Clear all marks", "Marking", CL_AGENTS, ("unmark",)),
    (
        "bulk_change_status",
        "Bulk status change",
        "Marking",
        CL_ONLY,
        ("marked cl", "bulk"),
    ),
    (
        "save_marked_agents",
        "Save/dismiss marked agents",
        "Marking",
        AGENTS_ONLY,
        (
            "save marked",
            "dismiss marked",
            "agent group",
            "name group",
            "saved group name",
        ),
    ),
    # Agents / Axe actions
    ("kill_agent", "Kill / dismiss / start-stop axe", "Agents", ALL_TABS, ()),
    (
        "open_agent_cleanup_panel",
        "Cleanup panel / clear output",
        "Agents",
        AGENTS_AXE,
        ("cleanup", "dismiss all", "clear output"),
    ),
    ("stop_axe_and_quit", "Quit / restart menu", "Axe", ALL_TABS, ()),
    ("start_custom_agent", "Run custom agent", "Agents", ALL_TABS, ("+",)),
    (
        "start_agent_home",
        "Run agent (home mode)",
        "Agents",
        ALL_TABS,
        ("home", "home mode", "~"),
    ),
    (
        "start_agent_from_changespec",
        "Run agent from PR",
        "Agents",
        CL_AGENTS,
        (),
    ),
    (
        "start_last_vcs_xprompt_in_editor",
        "Edit last VCS xprompt",
        "Agents",
        ALL_TABS,
        ("ctrl+g", "last vcs", "editor"),
    ),
    (
        "restore_prompt_stash",
        "Restore stashed prompt",
        "Agents",
        ALL_TABS,
        ("stash", "restore", "pop"),
    ),
    (
        "jump_to_agent_changespec",
        "Jump to agent's PR",
        "Agents",
        AGENTS_ONLY,
        ("go to pr",),
    ),
    ("zoom_panel", "Zoom largest panel", "Display", AGENTS_ONLY, ("zoom",)),
    ("edit_panel", "Edit panel file", "Agents", AGENTS_ONLY, ()),
    (
        "open_artifact_files",
        "Open agent artifact files",
        "Display",
        AGENTS_ONLY,
        ("artifact file", "image", "chat", "icat"),
    ),
    (
        "show_agent_run_log",
        "Show agent run log",
        "Agents",
        CL_ONLY,
        ("agent run log",),
    ),
    (
        "toggle_attempt_view",
        "Toggle attempt view",
        "Agents",
        AGENTS_ONLY,
        ("retry", "history"),
    ),
    (
        "toggle_agent_unread",
        "Toggle agent unread marker",
        "Agents",
        AGENTS_ONLY,
        ("unread", "read"),
    ),
    ("add_agent_tag", "Add / remove agent tag", "Agents", AGENTS_ONLY, ()),
    (
        "focus_next_agent_panel",
        "Focus next agent panel",
        "Agents",
        AGENTS_ONLY,
        (),
    ),
    (
        "focus_prev_agent_panel",
        "Focus previous agent panel",
        "Agents",
        AGENTS_ONLY,
        (),
    ),
    # Grouping (agents tab)
    ("cycle_grouping_mode", "Cycle grouping mode", "Grouping", AGENTS_ONLY, ()),
    (
        "cycle_grouping_mode_reverse",
        "Cycle grouping mode (reverse)",
        "Grouping",
        AGENTS_ONLY,
        (),
    ),
    # Tools panel
    ("toggle_thinking", "Toggle tools panel", "Display", AGENTS_ONLY, ()),
    (
        "toggle_thinking_reverse",
        "Toggle tools panel (reverse)",
        "Display",
        AGENTS_ONLY,
        (),
    ),
    # Queries
    ("edit_query", "Edit query", "Queries", ALL_TABS, ("/",)),
    (
        "open_saved_query_picker",
        "Choose saved PR query",
        "Saved Queries",
        CL_ONLY,
        ("saved query", "query slots", "star query"),
    ),
    ("prev_query", "Previous saved query", "Queries", ALL_TABS, ()),
    ("next_query", "Next saved query", "Queries", ALL_TABS, ()),
    # Display / misc
    ("toggle_hide_reverted", "Toggle hide reverted", "Display", CL_ONLY, ()),
    ("toggle_hide_submitted", "Toggle hide submitted", "Display", CL_ONLY, ()),
    ("show_notifications", "Show notifications", "Display", ALL_TABS, ()),
    ("show_help", "Show help", "Display", ALL_TABS, ("?",)),
    (
        "open_config_center",
        "Open SASE Admin Center",
        "Display",
        ALL_TABS,
        (
            "#",
            "admin",
            "admin center",
            "settings",
            "config",
            "configuration",
            "tasks",
            "task queue",
            "logs",
            "log panel",
            "updates",
            "plugins",
            "plugin catalog",
            "xprompts",
            "browse xprompts",
        ),
    ),
    (
        "dismiss_toasts",
        "Dismiss toasts",
        "Display",
        ALL_TABS,
        ("clear toasts", "clear notifications"),
    ),
    # Workspace prefixes
    ("checkout", "Checkout workspace (primary)", "Workspace", ALL_TABS, ()),
    ("start_checkout_mode", "Checkout workspace mode", "Modes", ALL_TABS, ()),
    ("open_tmux", "Open tmux (primary)", "Workspace", ALL_TABS, ()),
    ("start_tmux_mode", "Open tmux mode", "Modes", ALL_TABS, ()),
    # Tree navigation prefixes
    (
        "start_ancestor_mode",
        "Ancestor navigation",
        "Tree Navigation",
        CL_ONLY,
        (),
    ),
    ("start_child_mode", "Child navigation", "Tree Navigation", CL_ONLY, ()),
    ("start_sibling_mode", "Sibling navigation", "Tree Navigation", CL_AGENTS, ()),
    # Mode activation prefixes
    ("start_fold_mode", "Enter fold mode", "Modes", CL_AGENTS, ()),
    ("start_leader_mode", "Enter leader mode", "Modes", ALL_TABS, ()),
    ("start_bang_mode", "Enter bang mode", "Modes", ALL_TABS, ()),
    ("copy_tab_content", "Enter copy mode", "Modes", ALL_TABS, ()),
    # Palette itself
    (
        "open_command_palette",
        "Open command palette",
        "Misc",
        ALL_TABS,
        ("commands", ":"),
    ),
)


def ensure_metadata_covers_app_keymaps(
    meta: tuple[AppCommandMeta, ...] = APP_COMMAND_META,
) -> None:
    """Fail loudly if metadata drifts from :class:`AppKeymaps`."""
    meta_actions = {row[0] for row in meta}
    field_names = {f.name for f in fields(AppKeymaps)}
    missing = field_names - meta_actions
    extra = meta_actions - field_names
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"AppKeymaps fields missing metadata: {sorted(missing)}")
        if extra:
            parts.append(f"metadata for nonexistent fields: {sorted(extra)}")
        raise RuntimeError(
            "_APP_COMMAND_META / AppKeymaps mismatch - " + "; ".join(parts)
        )


ensure_metadata_covers_app_keymaps()
