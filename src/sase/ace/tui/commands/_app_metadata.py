"""App action metadata for the ace TUI command catalog."""

from __future__ import annotations

from dataclasses import fields

from sase.ace.tui.commands._tabs import (
    AGENTS_AXE,
    AGENTS_ONLY,
    ALL_TABS,
    AXE_ONLY,
    CL_AGENTS,
    CL_AXE,
    CL_ONLY,
)
from sase.ace.tui.commands.types import CommandCategory, CommandTab
from sase.ace.tui.keymaps.app_keymaps import AppKeymaps

type AppCommandMeta = tuple[
    str, str, CommandCategory, tuple[CommandTab, ...], tuple[str, ...]
]


# (action, label, category, tabs, aliases).  Action name MUST match an
# AppKeymaps field. Labels are tuned for the palette; categories mirror
# the help modal sections; tabs encode where the binding can ever fire
# (entry-level applicability is layered on by ``availability.py``).
APP_COMMAND_META: tuple[AppCommandMeta, ...] = (
    # Navigation
    ("next_patch", "Next entry", "Navigation", ALL_TABS, ("down", "j")),
    ("prev_patch", "Previous entry", "Navigation", ALL_TABS, ("up", "k")),
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
        ALL_TABS,
        ("jump", "forward", "ctrl+shift+o"),
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
        ("next artifact", "stitches", "commits", "beads", "files"),
    ),
    (
        "cycle_artifacts_subtab_reverse",
        "Previous Artifacts sub-tab",
        "Tabs",
        CL_ONLY,
        ("previous artifact",),
    ),
    (
        "cycle_artifacts_split",
        "Widen Artifacts list panel",
        "Display",
        CL_ONLY,
        ("split", "pane width", "wider list"),
    ),
    (
        "cycle_artifacts_split_reverse",
        "Narrow Artifacts list panel",
        "Display",
        CL_ONLY,
        ("split", "pane width", "narrower list"),
    ),
    ("files_next_version", "Files: next version", "Navigation", CL_ONLY, ()),
    ("files_prev_version", "Files: previous version", "Navigation", CL_ONLY, ()),
    (
        "pick_artifacts_project",
        "Pick Artifacts project scope (seeds current)",
        "Tabs",
        CL_ONLY,
        ("project scope", "filter project", "current project", "seeded"),
    ),
    (
        "artifacts_load_more",
        "Artifacts: load more rows",
        "Navigation",
        CL_ONLY,
        ("load more", "page size", "limit", "ctrl+j"),
    ),
    (
        "artifacts_unload",
        "Artifacts: unload a page of rows",
        "Navigation",
        CL_ONLY,
        ("unload", "page size", "limit", "ctrl+k"),
    ),
    # Stitches sub-tab
    (
        "stitches_next",
        "Stitches: next row",
        "Navigation",
        CL_ONLY,
        ("commit down", "stitches down"),
    ),
    (
        "stitches_prev",
        "Stitches: previous row",
        "Navigation",
        CL_ONLY,
        ("commit up", "stitches up"),
    ),
    ("stitches_view_selected", "Stitches: view selected", "Display", CL_ONLY, ()),
    ("stitches_filters", "Stitches: filter bar", "Display", CL_ONLY, ()),
    (
        "stitches_toggle_sdd",
        "Stitches: toggle sidecar history",
        "Display",
        CL_ONLY,
        (),
    ),
    (
        "stitches_cycle_merges",
        "Stitches: cycle merge visibility",
        "Display",
        CL_ONLY,
        (),
    ),
    (
        "stitches_toggle_all_projects",
        "Stitches: toggle all projects",
        "Display",
        CL_ONLY,
        (),
    ),
    (
        "stitches_fetch",
        "Stitches: fetch remote refs",
        "Proposals & Sync",
        CL_ONLY,
        (),
    ),
    # Plans sub-tab
    ("plans_next", "Plans: next row", "Navigation", CL_ONLY, ("plan down",)),
    ("plans_prev", "Plans: previous row", "Navigation", CL_ONLY, ("plan up",)),
    ("plans_view_selected", "Plans: view selected", "Display", CL_ONLY, ()),
    ("plans_filters", "Plans: filter bar", "Display", CL_ONLY, ()),
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
    ("plans_open_bead", "Plans: go to linked bead", "Navigation", CL_ONLY, ()),
    # Beads sub-tab
    ("beads_next", "Beads: next row", "Navigation", CL_ONLY, ()),
    ("beads_prev", "Beads: previous row", "Navigation", CL_ONLY, ()),
    ("beads_view_selected", "Beads: view selected", "Display", CL_ONLY, ()),
    ("beads_filters", "Beads: filter bar", "Display", CL_ONLY, ()),
    ("beads_expand", "Beads: expand epic", "Folding", CL_ONLY, ()),
    ("beads_collapse", "Beads: collapse epic", "Folding", CL_ONLY, ()),
    ("beads_cycle_status", "Beads: cycle status", "Proposals & Sync", CL_ONLY, ()),
    ("beads_edit", "Beads: edit", "Proposals & Sync", CL_ONLY, ()),
    ("beads_add_note", "Beads: add note", "Proposals & Sync", CL_ONLY, ()),
    ("beads_create", "Beads: create task", "Proposals & Sync", CL_ONLY, ()),
    ("beads_close", "Beads: close or reopen", "Proposals & Sync", CL_ONLY, ()),
    ("beads_snooze", "Beads: snooze task", "Proposals & Sync", CL_ONLY, ()),
    ("beads_launch_work", "Beads: launch work", "Agents", CL_ONLY, ()),
    ("beads_open_bug", "Beads: open linked issue", "Display", CL_ONLY, ()),
    ("start_bead_issue_mode", "Beads: issue actions", "Bugs", CL_ONLY, ()),
    ("beads_open_plan", "Beads: go to linked plan", "Navigation", CL_ONLY, ()),
    # Files sub-tab
    ("files_next", "Files: next row", "Navigation", CL_ONLY, ("file down",)),
    ("files_prev", "Files: previous row", "Navigation", CL_ONLY, ("file up",)),
    ("files_view_selected", "Files: view selected", "Display", CL_ONLY, ()),
    ("files_open_viewer", "Files: open in rich viewer", "Display", CL_ONLY, ()),
    ("files_open_external", "Files: open externally", "Display", CL_ONLY, ()),
    ("files_open_agent", "Files: open producing agent", "Agents", CL_ONLY, ()),
    ("files_filters", "Files: filter bar", "Display", CL_ONLY, ()),
    (
        "files_cycle_kind",
        "Files: cycle kind filter",
        "Proposals & Sync",
        CL_ONLY,
        (),
    ),
    ("files_copy_path", "Files: copy stored path", "Display", CL_ONLY, ()),
    # Patch actions
    ("quit", "Quit ace", "Misc", ALL_TABS, ("exit",)),
    ("change_status", "Change Patch status", "Patch Actions", CL_ONLY, ()),
    (
        "run_workflow",
        "Run workflow / retry agent / re-run",
        "Patch Actions",
        ALL_TABS,
        ("retry", "relaunch", "edit prompt"),
    ),
    ("mail", "Mail Patch", "Patch Actions", CL_ONLY, ("send",)),
    ("show_diff", "Show diff", "Patch Actions", CL_ONLY, ()),
    ("reword", "Reword Patch", "Patch Actions", CL_ONLY, ()),
    (
        "add_tag",
        "Add tag / wait for agent, clan, or tribe",
        "Patch Actions",
        CL_AGENTS,
        (
            "wait",
            "wait for agent",
            "wait for clan",
            "wait for tribe",
            "new prompt with wait",
        ),
    ),
    ("view_files", "View Patch files", "Patch Actions", CL_ONLY, ()),
    (
        "edit_spec",
        "Edit spec / chat / AXE config",
        "Patch Actions",
        ALL_TABS,
        ("edit lumberjack", "edit chop config"),
    ),
    (
        "add_axe_item",
        "Add AXE lumberjack or chop",
        "Axe",
        AXE_ONLY,
        ("new lumberjack", "new chop", "add chop"),
    ),
    (
        "toggle_axe_description",
        "Toggle AXE description",
        "Axe",
        AXE_ONLY,
        ("description", "expand description", "collapse description"),
    ),
    ("rename_cl", "Rename Patch / agent", "Patch Actions", CL_AGENTS, ()),
    ("patches_filters", "Patches: filter bar", "Display", CL_ONLY, ()),
    # Patch edits
    (
        "edit_hooks",
        "Edit hooks / fork agent, clan, or tribe",
        "Patch Edits",
        CL_AGENTS,
        ("fork",),
    ),
    (
        "mark_pr_origin",
        "Mark PR origin (sase / external / unknown)",
        "Patch Edits",
        CL_ONLY,
        ("origin", "adopt"),
    ),
    # Proposals & Sync
    ("accept_proposal", "Accept proposal", "Proposals & Sync", CL_AGENTS, ()),
    ("rebase", "Rebase Patch", "Proposals & Sync", CL_ONLY, ()),
    (
        "start_rewind",
        "Rewind Patch / Revive agent",
        "Proposals & Sync",
        CL_AGENTS,
        (),
    ),
    ("sync", "Sync repo", "Proposals & Sync", ALL_TABS, ()),
    ("refresh", "Refresh tab", "Proposals & Sync", ALL_TABS, ("reload",)),
    (
        "artifacts_copy_reference",
        "Artifacts: copy row reference",
        "Display",
        CL_ONLY,
        ("copy reference", "copy sha", "copy bug ref"),
    ),
    # Folding
    (
        "hooks_or_collapse",
        "Navigate to parent container or tribe / collapse selected panel, "
        "jump to last expanded panel, or collapse fold",
        "Folding",
        ALL_TABS,
        ("last expanded panel",),
    ),
    (
        "hooks_or_collapse_all",
        "Collapse selected workflow/family, then group sase agents, selected "
        "clan, remaining clans/groups; panel sase agents/clans/groups/panel / "
        "compact tools detail / collapse all folds on other tabs",
        "Folding",
        ALL_TABS,
        (
            "collapse workflow",
            "collapse family",
            "collapse sase agents",
            "collapse clan",
            "collapse selected clan",
            "collapse clans",
            "collapse remaining clans",
            "collapse group",
            "collapse selected panel",
        ),
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
        "Toggle a fold in the selected tribe / expand all folds on other tabs",
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
        "start_agent_from_patch",
        "Run agent from Patch",
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
        "jump_to_agent_patch",
        "Jump to agent's Patch",
        "Agents",
        AGENTS_ONLY,
        ("go to patch",),
    ),
    (
        "zoom_panel",
        "Zoom agent or tribe detail panel",
        "Display",
        AGENTS_ONLY,
        ("zoom", "tribe"),
    ),
    (
        "isolate_panels",
        "Isolate or restore tribe panels",
        "Display",
        AGENTS_ONLY,
        ("only panel", "restore panels", "isolate"),
    ),
    (
        "collapse_panel_folds",
        "Collapse or restore tribe panel folds",
        "Display",
        AGENTS_ONLY,
        ("collapse folds", "restore folds", "fold panel"),
    ),
    (
        "edit_panel",
        "Edit panel file / chop output",
        "Display",
        AGENTS_AXE,
        ("recorded chop output", "open chop log"),
    ),
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
    ("edit_agent_tribe", "Set, edit, or clear agent tribe", "Agents", AGENTS_ONLY, ()),
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
    # Grouping (grouping-capable Artifacts panes + Agents)
    ("cycle_grouping_mode", "Cycle grouping mode", "Grouping", CL_AGENTS, ()),
    (
        "cycle_grouping_mode_reverse",
        "Cycle grouping mode (reverse)",
        "Grouping",
        CL_AGENTS,
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
    (
        "edit_query",
        "Edit query or filter",
        "Queries",
        CL_AXE,
        ("filter", "query", "/"),
    ),
    (
        "search_forward",
        "Search metadata forward",
        "Queries",
        AGENTS_ONLY,
        ("find", "forward", "/"),
    ),
    (
        "search_reverse",
        "Reverse metadata search order",
        "Queries",
        AGENTS_ONLY,
        ("find", "reverse", "search direction", "ctrl+r"),
    ),
    (
        "open_saved_query_picker",
        "Choose saved Patch query",
        "Saved Queries",
        CL_ONLY,
        ("saved query", "query slots", "star query"),
    ),
    (
        "start_saved_query_mode",
        "Load saved Patch query by slot",
        "Saved Queries",
        CL_ONLY,
        ("saved query slot", "query slot"),
    ),
    ("prev_query", "Previous saved query", "Queries", ALL_TABS, ()),
    ("next_query", "Next saved query", "Queries", ALL_TABS, ()),
    # Display / misc
    ("toggle_hide_reverted", "Toggle hide reverted", "Display", AGENTS_AXE, ()),
    (
        "patches_toggle_reverted",
        "Toggle hide reverted",
        "Display",
        CL_ONLY,
        (),
    ),
    (
        "toggle_relation_panel",
        "Collapse relations panel",
        "Display",
        CL_ONLY,
        ("relations", "ancestors", "children", "relation panel"),
    ),
    ("toggle_hide_submitted", "Toggle hide submitted", "Display", CL_ONLY, ()),
    ("show_notifications", "Show notifications", "Display", ALL_TABS, ()),
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
            "procs",
            "proc queue",
            "tasks",
            "task queue",
            "logs",
            "log panel",
            "updates",
            "plugins",
            "plugin catalog",
            "xprompts",
            "browse xprompts",
            "glossary",
            "memory",
            "snippets",
        ),
    ),
    (
        "show_help",
        "Show help",
        "Display",
        ALL_TABS,
        ("help", "keybindings", "?", "guide"),
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
