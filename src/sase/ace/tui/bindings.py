"""Default keybindings for the ace TUI app."""

import os

from textual.binding import Binding, BindingType

from .artifact_tabs import ARTIFACTS_SUBTAB_ORDER

# Default bindings for AceApp. These are overridden at runtime by the keymap
# registry (see keymaps/ module), but serve as the fallback definition.
DEFAULT_BINDINGS: list[BindingType] = [
    Binding("j", "next_changespec", "Next", show=False),
    Binding("k", "prev_changespec", "Previous", show=False),
    Binding("q", "quit", "Quit", show=False),
    Binding("s", "change_status", "Status", show=False),
    Binding("r", "run_workflow", "Run", show=False),
    Binding("M", "mail", "Mail", show=False),
    Binding("d", "show_diff", "Diff", show=False),
    Binding("w", "reword", "Reword", show=False),
    Binding("W", "add_tag", "Add Tag", show=False),
    Binding("v", "view_files", "View", show=False),
    Binding("apostrophe", "jump_to_entry", "Jump to Entry", show=False),
    Binding("ctrl+o", "jump_to_entry_fast", "Fast Jump", show=False),
    Binding("ctrl+shift+o", "jump_to_entry_forward", "Forward Jump", show=False),
    Binding("grave_accent", "jump_to_all_entries", "Jump All", show=False),
    Binding(
        "h",
        "hooks_or_collapse",
        "Parent / Collapse or Jump Panel/Fold",
        show=False,
    ),
    Binding(
        "H",
        "hooks_or_collapse_all",
        "Collapse Scoped Lanes/Selected Clan/Clans/Groups/Panel / Compact Tools / All",
        show=False,
    ),
    Binding("f", "edit_hooks", "Edit Hooks", show=False),
    Binding("z", "start_fold_mode", "Fold", show=False),
    Binding("Z", "zoom_panel", "Zoom Detail / Only/Restore Panels", show=False),
    Binding("A", "plans_approve", "Approve Plan", show=False),
    Binding("A", "accept_proposal", "Accept", show=False),
    Binding("b", "rebase", "Rebase", show=False),
    Binding("R", "start_rewind", "Rewind", show=False),
    Binding("T", "open_tmux", "Tmux", show=False),
    Binding("t", "start_tmux_mode", "Tmux Mode", show=False),
    Binding("C", "checkout", "Checkout", show=False),
    Binding("c", "start_checkout_mode", "Checkout Mode", show=False),
    # Note: "!" binding removed - use "A" then "@" to mark ready to mail
    Binding("y", "refresh", "Refresh", show=False),
    Binding("Y", "sync", "Sync", show=False),
    Binding("slash", "search_forward", "Search Forward", show=False),
    Binding("slash", "edit_query", "Edit Query", show=False),
    Binding("question_mark", "search_reverse", "Search Reverse", show=False),
    Binding("e", "edit_spec", "Edit Spec", show=False),
    Binding("a", "add_axe_item", "Add AXE Item", show=False),
    Binding("d", "toggle_axe_description", "Toggle AXE Description", show=False),
    Binding("ctrl+d", "scroll_detail_down", "Scroll Down", show=False),
    Binding("ctrl+u", "scroll_detail_up", "Scroll Up", show=False),
    Binding("ctrl+f", "scroll_prompt_down", "Scroll Prompt Down", show=False),
    Binding("ctrl+b", "scroll_prompt_up", "Scroll Prompt Up", show=False),
    Binding(
        "ctrl+j",
        "next_agent_metadata_section",
        "Next Metadata Section",
        show=False,
    ),
    Binding(
        "ctrl+k",
        "prev_agent_metadata_section",
        "Previous Metadata Section",
        show=False,
    ),
    # Tab switching
    Binding("tab", "next_tab", "Next Tab", show=False, priority=True),
    Binding("shift+tab", "prev_tab", "Prev Tab", show=False, priority=True),
    Binding(
        "right_square_bracket",
        "cycle_artifacts_subtab",
        "Next Artifact",
        show=False,
    ),
    Binding(
        "left_square_bracket",
        "cycle_artifacts_subtab_reverse",
        "Previous Artifact",
        show=False,
    ),
    Binding("p", "pick_artifacts_project", "Project Scope", show=False),
    *[
        Binding(
            str(index),
            f"show_artifacts_{subtab}",
            f"Show {subtab.title()}",
            show=False,
        )
        for index, subtab in enumerate(ARTIFACTS_SUBTAB_ORDER, start=1)
    ],
    # Commits sub-tab actions.
    Binding("j", "commits_next", "Next Commit", show=False),
    Binding("k", "commits_prev", "Previous Commit", show=False),
    Binding("enter", "commits_view_selected", "View Commit", show=False),
    Binding("y", "commits_copy_sha", "Copy Commit SHA", show=False),
    Binding("f", "commits_filters", "Commit Filters", show=False),
    Binding("d", "commits_toggle_sdd", "Toggle Commit Sidecars", show=False),
    Binding(
        "a",
        "commits_toggle_all_projects",
        "Toggle All Projects",
        show=False,
    ),
    Binding("F", "commits_fetch", "Fetch Commits", show=False),
    Binding("R", "commits_refresh", "Refresh Commits", show=False),
    # Plans sub-tab actions.
    Binding("j", "plans_next", "Next Plan", show=False),
    Binding("k", "plans_prev", "Previous Plan", show=False),
    Binding("enter", "plans_view_selected", "View Plan", show=False),
    Binding("f", "plans_filters", "Plan Filters", show=False),
    Binding("l", "plans_expand", "Expand Epic", show=False),
    Binding("h", "plans_collapse", "Collapse Epic", show=False),
    Binding("s", "plans_cycle_status", "Bead Status", show=False),
    Binding("e", "plans_edit_bead", "Edit Bead", show=False),
    Binding("w", "plans_launch_epic", "Launch Epic", show=False),
    Binding("X", "plans_reject", "Reject Plan", show=False),
    Binding("o", "plans_open_bug", "Open Bug", show=False),
    Binding("R", "plans_refresh", "Refresh Plans", show=False),
    # Chats sub-tab actions.
    Binding("j", "chats_next", "Next Chat", show=False),
    Binding("k", "chats_prev", "Previous Chat", show=False),
    Binding("enter", "chats_view_selected", "View Chat", show=False),
    Binding("f", "chats_filters", "Chat Filters", show=False),
    Binding("s", "chats_cycle_provenance", "Cycle Sync State", show=False),
    Binding("a", "chats_open_agent", "Open Chat Agent", show=False),
    Binding("o", "chats_open_external", "Open Chat in Editor", show=False),
    Binding("y", "chats_copy_path", "Copy Chat Path", show=False),
    Binding("R", "chats_refresh", "Refresh Chats", show=False),
    # Bugs sub-tab actions (context-gated; keys intentionally overlap PRs).
    Binding("j", "next_bug", "Next Bug", show=False),
    Binding("k", "prev_bug", "Previous Bug", show=False),
    Binding("f", "cycle_bug_filter", "Bug State Filter", show=False),
    Binding("c", "create_bug", "Create Bug", show=False),
    Binding("e", "edit_bug", "Edit Bug", show=False),
    Binding("s", "toggle_bug_state", "Close / Reopen Bug", show=False),
    Binding("o", "open_bug", "Open Bug", show=False),
    Binding("y", "copy_bug", "Copy Bug", show=False),
    Binding("a", "start_agent_from_bug", "Run Agent (Bug)", show=False),
    Binding("l", "focus_bug_links", "Bug Links", show=False),
    Binding("enter", "activate_bug_link", "Open Bug Link", show=False, priority=True),
    Binding("R", "refresh_bugs", "Refresh Bugs", show=False),
    # Agent cleanup on Agents; clear output on AXE.
    Binding("X", "open_agent_cleanup_panel", "Agent Cleanup", show=False),
    Binding("Q", "stop_axe_and_quit", "Quit / Restart", show=False),
    # Agent workflow (all tabs) - shows project/PR selection modals
    Binding("plus", "start_custom_agent", "Run Agent", show=False),
    Binding("space", "start_agent_home", "Run Agent (Home)", show=False),
    # Run agent from ChangeSpec (PRs tab only)
    Binding("ctrl+@", "start_agent_from_changespec", "Run Agent (PR)", show=False),
    Binding(
        "ctrl+g",
        "start_last_vcs_xprompt_in_editor",
        "Edit Last VCS XPrompt",
        show=False,
    ),
    # Global prompt-stash restore (pop-and-load), reachable from every tab.
    Binding("at", "restore_prompt_stash", "Restore Prompt Stash", show=False),
    # Bang mode prefix (all tabs) - !x = toggle axe, !! = run bgcmd
    Binding("exclamation_mark", "start_bang_mode", "Bang Mode", show=False),
    # Marking (PRs tab only)
    Binding("m", "toggle_mark", "Mark", show=False),
    Binding("n", "rename_cl", "Rename", show=False),
    Binding("u", "clear_marks", "Unmark All", show=False),
    Binding("S", "bulk_change_status", "Bulk Status", show=False),
    Binding("s", "save_marked_agents", "Save Marked Agents", show=False),
    Binding("i", "show_notifications", "Notifications", show=False),
    Binding("x", "kill_agent", "Kill", show=False),
    Binding("l", "expand_or_layout", "Expand / Enter Panel", show=False),
    Binding("L", "expand_all_folds", "Toggle Tribe Fold / Expand All", show=False),
    Binding("p", "toggle_layout", "Layout", show=False),
    Binding("right_square_bracket", "toggle_thinking", "Tools", show=False),
    Binding("left_square_bracket", "toggle_thinking_reverse", "Tools Rev", show=False),
    Binding("a", "open_artifact_files", "Artifact Files", show=False),
    Binding("D", "toggle_attempt_view", "Attempt View", show=False),
    Binding("U", "toggle_agent_unread", "Toggle Agent Unread", show=False),
    Binding("N", "edit_agent_tribe", "Edit Agent Tribe", show=False),
    # Tribe-driven side-panel focus cycling (agents tab)
    Binding("J", "focus_next_agent_panel", "Next Panel", show=False),
    Binding("K", "focus_prev_agent_panel", "Prev Panel", show=False),
    # Copy to clipboard (changespecs tab - % followed by key)
    Binding("percent_sign", "copy_tab_content", "Copy", show=False),
    # Scroll to top/bottom (Axe tab)
    Binding("g", "scroll_to_top", "Top", show=False),
    Binding("G", "scroll_to_bottom", "Bottom", show=False),
    # SASE Admin Center (config editor + xprompt browser)
    Binding("number_sign", "open_config_center", "SASE Admin Center", show=False),
    # Query history navigation
    Binding("circumflex_accent", "prev_query", "Prev Query", show=False),
    Binding("underscore", "next_query", "Next Query", show=False),
    Binding(
        "asterisk",
        "open_saved_query_picker",
        "Saved Queries",
        show=False,
    ),
    # Ancestor/child/sibling navigation
    Binding("<", "start_ancestor_mode", "Ancestor", show=False),
    Binding(">", "start_child_mode", "Child", show=False),
    Binding("~", "start_sibling_mode", "Sibling", show=False),
    # Hide/show reverted/submitted
    Binding("full_stop", "toggle_hide_reverted", "Toggle Reverted", show=False),
    Binding("x", "toggle_hide_submitted", "Toggle Submitted", show=False),
    # Leader mode (for quick shortcuts)
    Binding("comma", "start_leader_mode", "Leader", show=False),
    # File cycling (agents tab)
    Binding("ctrl+n", "next_agent_file", "Next File", show=False),
    Binding("ctrl+p", "prev_agent_file", "Prev File", show=False),
    Binding("E", "edit_panel", "Edit Panel / Chop Output", show=False),
    # Jump to PR from agent (agents tab)
    Binding("enter", "jump_to_agent_changespec", "Go to PR", show=False),
    Binding("V", "show_agent_run_log", "Agent Run Log", show=False),
    Binding("ctrl+l", "dismiss_toasts", "Dismiss Toasts", show=False),
]


# Opt-in developer keybind for the leak-snapshot probe. Only attached
# when ``SASE_ACE_DEBUG_LEAKS=1`` is set so production users don't see
# the binding in help output. Wired to ``action_debug_leak_snapshot``
# defined on ``EventRefreshMixin``.
if os.environ.get("SASE_ACE_DEBUG_LEAKS") == "1":
    DEFAULT_BINDINGS.append(
        Binding("ctrl+shift+d", "debug_leak_snapshot", "Leak Snapshot", show=False)
    )
