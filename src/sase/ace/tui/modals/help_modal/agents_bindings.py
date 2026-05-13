"""Agents tab keybinding sections for the help modal."""

from ...keymaps import KeymapRegistry, key_display_name
from .binding_common import Sections, custom_mode_sections, sk


def agents_bindings(km: KeymapRegistry) -> Sections:
    """Build keybinding sections for the Agents tab."""
    d = key_display_name
    a = km.app
    lm = km.leader_mode
    bm = km.bang_mode
    cm = km.copy_mode

    ag_copy = cm.keys["agents"]
    assert isinstance(ag_copy, dict)

    sections: Sections = [
        (
            "Navigation",
            [
                (
                    f"{d(a.next_changespec)} / {d(a.prev_changespec)}",
                    "Move to next / previous agent",
                ),
                (
                    f"{d(a.focus_next_agent_panel)} / {d(a.focus_prev_agent_panel)}",
                    "Cycle focus across tag panels",
                ),
                (d(a.jump_to_entry), "Jump entry/head (' first/back)"),
                (d(a.jump_to_all_entries), "Jump to entry (all tabs, ` back)"),
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
                (d(a.rename_cl), "Name agent"),
                (d(a.run_workflow), "Resume chat as agent"),
                (d(a.start_rewind), "Revive dismissed agent"),
                (d(a.add_tag), "Wait for agent (or marked set)"),
                (d(a.reword), "Edit wait target / run now"),
                (d(a.kill_agent), "Kill/dismiss agent/group/marked"),
                (d(a.toggle_mark), "Mark/unmark current agent"),
                (d(a.toggle_agent_unread), "Toggle unread marker"),
                (d(a.clear_marks), "Clear all agent marks"),
                (d(a.open_agent_cleanup_panel), "Open cleanup panel"),
                (d(a.edit_spec), "Edit chat in editor"),
                (d(a.edit_panel), "Edit panel content in editor"),
                (
                    f"{d(a.toggle_thinking)} / {d(a.toggle_thinking_reverse)}",
                    "Cycle panels: file → thinking → metadata",
                ),
                (d(a.toggle_layout), "Toggle file/prompt layout"),
                (d(a.open_agent_artifacts), "Artifacts pane (or marked set)"),
                (d(a.toggle_attempt_view), "Toggle attempt history view"),
                (
                    f"{d(a.next_agent_file)} / {d(a.prev_agent_file)}",
                    "Next / prev file in panel",
                ),
                (d(a.reset_file_trim), "Reset file trim to default"),
                (d(a.show_all_file_lines), "Show all file lines"),
                (d(a.start_tmux_mode), "Tmux in agent workspace"),
                (d(a.add_agent_tag), "Tag/untag agent (or marked set)"),
                (d(a.open_tmux), "Tmux in primary workspace"),
            ],
        ),
        (
            "Group / Workflow Folding",
            [
                (
                    f"{d(a.expand_or_layout)} / {d(a.hooks_or_collapse)}",
                    "Expand / collapse focused group",
                ),
                (
                    f"{d(a.expand_all_folds)} / {d(a.hooks_or_collapse_all)}",
                    "Expand/collapse one level (all)",
                ),
            ],
        ),
        (
            f"Leader Mode ({d(lm.prefix)})",
            [
                (f"{d(lm.prefix)}{d(sk(lm.keys, 'agent_home'))}", "Run agent (home)"),
                (f"{d(lm.prefix)}{d(sk(lm.keys, 'runners'))}", "Show runners info"),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'toggle_agent_panel_grouping'))}",
                    "Toggle tag panels grouped/split",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'jump_to_next_unread_done_agent'))}",
                    "Jump to next unread done agent",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'jump_to_next_stopped_agent'))}",
                    "Jump to next stopped agent",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'mark_all_unread_done_agents_read'))}",
                    "Mark all unread done agents read",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'kill_and_edit'))}",
                    "Kill agent & edit prompt",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'retry_edit'))}",
                    "Retry: edit prompt & relaunch",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'prompt_history'))}",
                    "Prompt history (last CL)",
                ),
                (
                    f"{d(lm.prefix)} {d(sk(lm.keys, 'prompt_history_edit_first'))}",
                    "Edit first prompt history entry",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'prompt_history_cancelled'))}",
                    "Prompt history (+cancelled)",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'jump_to_notification'))}",
                    "Jump to agent notification",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'capture_agents_repro'))}",
                    "Capture repro bundle",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'toggle_agents_repro_checks'))}",
                    "Toggle repro auto-checks",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'activity_info'))}",
                    "Activity dashboard",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'temporary_llm_override'))}",
                    "Temporary model override",
                ),
            ],
        ),
        (
            f"Bang Mode ({d(bm.prefix)})",
            [
                (
                    f"{d(bm.prefix)}{d(sk(bm.keys, 'run_cmd'))}",
                    "Run background command",
                ),
                (
                    f"{d(bm.prefix)}{d(sk(bm.keys, 'toggle_axe'))}",
                    "Start / stop axe (or select process)",
                ),
            ],
        ),
        (
            f"Copy Mode ({d(cm.prefix)})",
            [
                (f"{d(cm.prefix)}{d(ag_copy['chat'])}", "Copy chat file path"),
                (f"{d(cm.prefix)}{d(ag_copy['name'])}", "Copy agent name"),
                (f"{d(cm.prefix)}{d(ag_copy['prompt'])}", "Copy agent prompt"),
                (f"{d(cm.prefix)}{d(ag_copy['snapshot'])}", "Copy sase ace snapshot"),
            ],
        ),
        (
            "Search",
            [
                (d(a.edit_query), "Filter agents by query"),
            ],
        ),
        (
            "Agent Query Syntax",
            [
                ("status:VAL", "Substring on status"),
                ("cl:VAL", "Substring on CL name"),
                ("project:VAL", "Substring on project basename"),
                ("name:VAL", "Substring on agent name"),
                ("model:VAL", "Substring on model"),
                ("provider:VAL", "Substring on llm provider"),
                ("type:VAL", "workflow | run | running"),
                ("source:VAL", "axe | manual"),
                ("needs:input", "Question / waiting input"),
                ("attention:BOOL", "true | false (needs attention)"),
                ("pinned:BOOL", "true | false (sugar tag:pinned)"),
                ("hidden:BOOL", "true | false (show hidden)"),
                ("tag:VAL  tag:", "Exact tag / any tagged"),
                ("age>=2h", "Op: > >= < <= = ; unit s|m|h|d"),
                ("age:2h", "Sugar for age>=2h"),
                ('text:"..."', "Quoted substring (whole hay)"),
                ('c"FAILED"', "Case-sensitive quoted"),
                ("AND OR NOT ( )", "Boolean ops; juxtapose = AND"),
            ],
        ),
        (
            "Grouping",
            [
                (
                    f"{d(a.cycle_grouping_mode)} / {d(a.cycle_grouping_mode_reverse)}",
                    "Cycle: project → date → status",
                ),
                ("by date", "Sub-grouped by hour, day, or week"),
                ("⏳ Waiting", "Timer or dependency wait"),
                ("▲ Stopped", "User must act"),
                ("▶ Running", "Actively executing"),
                ("✗ Failed", "Failed and retried"),
                ("✓ Done", "Completed"),
            ],
        ),
        (
            "Agent Row Glyphs",
            [
                ("×N", "N steps (collapsed)"),
                ("×N +M / −M", "M shown / hidden steps"),
                ("◆", "Bead-linked agent"),
                ("↻N", "N attempts / retry depth"),
                ("≡", "Workflow row"),
                ("❑", "ChangeSpec row"),
                ("⚡", "Auto-approve agent"),
                ("◌", "Hidden by default"),
                ("↳", "Retry chain attempt"),
            ],
        ),
    ]
    # Insert custom mode sections before "General".
    sections.extend(custom_mode_sections(km))
    sections.append(
        (
            "General",
            [
                (f"{d(a.next_tab)} / {d(a.prev_tab)}", "Switch tabs"),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'mark_inactive'))}",
                    "Toggle idle (any key clears)",
                ),
                (d(a.mark_inactive_pinned), "Toggle pinned idle (sticky)"),
                (d(a.start_agent_from_changespec), "Repeat last @/Space selection"),
                (d(a.toggle_hide_reverted), "Show/hide non-run agents"),
                (d(a.browse_xprompts), "Browse xprompts"),
                (d(a.show_notifications), "Show notifications"),
                (d(a.dismiss_toasts), "Dismiss toasts"),
                (d(a.stop_axe_and_quit), "Stop axe and quit"),
                (d(a.refresh), "Refresh"),
                (d(a.quit), "Quit"),
                (d(a.open_command_palette), "Open command palette"),
                (d(a.show_help), "Show this help"),
            ],
        ),
    )
    return sections
