"""Default keybindings for the ace TUI app."""

from textual.binding import Binding, BindingType

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
    Binding("h", "hooks_or_collapse", "Hooks / Collapse", show=False),
    Binding("H", "hooks_or_collapse_all", "Hooks / Collapse All", show=False),
    Binding("z", "start_fold_mode", "Fold", show=False),
    Binding("a", "accept_proposal", "Accept", show=False),
    Binding("b", "rebase", "Rebase", show=False),
    Binding("R", "start_rewind", "Rewind", show=False),
    Binding("T", "open_tmux", "Tmux", show=False),
    Binding("t", "start_tmux_mode", "Tmux Mode", show=False),
    Binding("C", "checkout", "Checkout", show=False),
    Binding("c", "start_checkout_mode", "Checkout Mode", show=False),
    # Note: "!" binding removed - use "a" then "@" to mark ready to mail
    Binding("y", "refresh", "Refresh", show=False),
    Binding("Y", "sync", "Sync", show=False),
    Binding("slash", "edit_query", "Edit Query", show=False),
    Binding("e", "edit_spec", "Edit Spec", show=False),
    Binding("ctrl+d", "scroll_detail_down", "Scroll Down", show=False),
    Binding("ctrl+u", "scroll_detail_up", "Scroll Up", show=False),
    Binding("ctrl+f", "scroll_prompt_down", "Scroll Prompt Down", show=False),
    Binding("ctrl+b", "scroll_prompt_up", "Scroll Prompt Up", show=False),
    # Saved query keybindings (1-9, 0)
    Binding("1", "load_saved_query_1", "Load Q1", show=False),
    Binding("2", "load_saved_query_2", "Load Q2", show=False),
    Binding("3", "load_saved_query_3", "Load Q3", show=False),
    Binding("4", "load_saved_query_4", "Load Q4", show=False),
    Binding("5", "load_saved_query_5", "Load Q5", show=False),
    Binding("6", "load_saved_query_6", "Load Q6", show=False),
    Binding("7", "load_saved_query_7", "Load Q7", show=False),
    Binding("8", "load_saved_query_8", "Load Q8", show=False),
    Binding("9", "load_saved_query_9", "Load Q9", show=False),
    Binding("0", "load_saved_query_0", "Load Q0", show=False),
    # Tab switching
    Binding("tab", "next_tab", "Next Tab", show=False, priority=True),
    Binding("shift+tab", "prev_tab", "Prev Tab", show=False, priority=True),
    # Axe control (AXE tab only - global access via !x)
    Binding("X", "toggle_axe", "Start/Stop Axe", show=False),
    Binding("Q", "stop_axe_and_quit", "Stop & Quit", show=False),
    # Agent workflow (all tabs) - shows project/CL selection modals
    Binding("at", "start_custom_agent", "Run Agent", show=False),
    # Run agent from ChangeSpec (CLs tab only)
    Binding("space", "start_agent_from_changespec", "Run Agent (CL)", show=False),
    # Bang mode prefix (all tabs) - !x = toggle axe, !! = run bgcmd
    Binding("exclamation_mark", "start_bang_mode", "Bang Mode", show=False),
    # Marking (CLs tab only)
    Binding("m", "toggle_mark", "Mark", show=False),
    Binding("n", "rename_cl", "Rename", show=False),
    Binding("u", "clear_marks", "Unmark All", show=False),
    Binding("S", "bulk_change_status", "Bulk Status", show=False),
    Binding("N", "show_notifications", "Notifications", show=False),
    Binding("x", "kill_agent", "Kill", show=False),
    Binding("l", "expand_or_layout", "Expand / Layout", show=False),
    Binding("L", "expand_all_folds", "Expand All", show=False),
    Binding("p", "toggle_layout", "Layout", show=False),
    Binding("right_square_bracket", "toggle_thinking", "Thinking", show=False),
    Binding(
        "left_square_bracket", "toggle_thinking_reverse", "Thinking Rev", show=False
    ),
    Binding("i", "mark_inactive", "Mark Inactive", show=False),
    # Copy to clipboard (changespecs tab - % followed by key)
    Binding("percent_sign", "copy_tab_content", "Copy", show=False),
    # Scroll to top/bottom (Axe tab)
    Binding("g", "scroll_to_top", "Top", show=False),
    Binding("G", "scroll_to_bottom", "Bottom", show=False),
    # Help
    Binding("question_mark", "show_help", "Help", show=False),
    # XPrompt browser
    Binding("number_sign", "browse_xprompts", "XPrompts", show=False),
    # Query history navigation
    Binding("circumflex_accent", "prev_query", "Prev Query", show=False),
    Binding("underscore", "next_query", "Next Query", show=False),
    # ChangeSpec history navigation (vim-style jumplist)
    Binding("ctrl+o", "prev_changespec_history", "Prev CL History", show=False),
    Binding("ctrl+k", "next_changespec_history", "Next CL History", show=False),
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
    Binding("E", "edit_panel", "Edit Panel", show=False),
    Binding("minus", "reset_file_trim", "Reset Trim", show=False),
    Binding("equals_sign", "show_all_file_lines", "Show All", show=False),
    # Jump to CL from agent (agents tab)
    Binding("enter", "jump_to_agent_changespec", "Go to CL", show=False),
    Binding("J", "focus_pinned_panel", "Focus Pinned", show=False),
]
