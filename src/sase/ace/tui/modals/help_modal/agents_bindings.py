"""Agents tab keybinding sections for the help modal."""

from ...keymaps import KeymapRegistry, key_display_name, leader_key_display
from .binding_common import (
    PROMPT_INPUT_SECTION,
    Sections,
    custom_mode_sections,
    key_sequence_display,
    sk,
)


def agents_bindings(km: KeymapRegistry) -> Sections:
    """Build keybinding sections for the Agents tab."""
    d = key_display_name
    a = km.app
    lm = km.leader_mode
    bm = km.bang_mode
    cm = km.copy_mode
    fm = km.fold_mode

    ag_copy = cm.keys["agents"]
    assert isinstance(ag_copy, dict)
    ag_fold = fm.keys["agents"]
    assert isinstance(ag_fold, dict)

    sections: Sections = [
        (
            "Navigation",
            [
                (
                    f"{d(a.next_changespec)} / {d(a.prev_changespec)}",
                    "Move row / selected panel",
                ),
                (
                    f"{d(a.focus_next_agent_panel)} / {d(a.focus_prev_agent_panel)}",
                    "Jump into next / previous panel",
                ),
                (d(a.jump_to_entry), "Jump entry/head (' first/back stack)"),
                (
                    f"{d(a.jump_to_entry_fast)} / {d(a.jump_to_entry_forward)}",
                    "Jump stack back / forward",
                ),
                (d(a.jump_to_all_entries), "Jump to entry (all tabs, ` back)"),
                ("0-9", "Jump to numbered member"),
                ("Esc", "Enter selected panel / cancel member jump"),
                (d(a.start_sibling_mode), "Jump ancestor/neighbor/desc"),
                (
                    f"{d(a.next_agent_metadata_section)} / "
                    f"{d(a.prev_agent_metadata_section)}",
                    "Cycle metadata through top",
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
                (d(a.start_agent_home), "Run agent (home)"),
                (d(a.start_last_vcs_xprompt_in_editor), "Edit last VCS xprompt"),
                (d(a.restore_prompt_stash), "Restore stashed prompt"),
                (d(a.run_workflow), "Retry: edit prompt & relaunch"),
                (d(a.accept_proposal), "Open auto-approve menu / answer HITL"),
                (d(a.rename_cl), "Name agent"),
                (d(a.edit_hooks), "Fork chat as agent"),
                (d(a.start_rewind), "Revive dismissed (^k loads more)"),
                (d(a.add_tag), "Wait for agent (or marked set)"),
                (d(a.reword), "Edit wait deps/time / run now"),
                (d(a.save_marked_agents), "Save/dismiss marked agents"),
                (d(a.kill_agent), "Clean row/panel/group/clan/marks"),
                (d(a.toggle_mark), "Mark/unmark current agent or focused group"),
                (d(a.toggle_agent_unread), "Toggle unread marker"),
                (d(a.clear_marks), "Clear all agent marks"),
                (d(a.open_agent_cleanup_panel), "Open cleanup panel (C: clan)"),
                (d(a.edit_spec), "Edit chat(s) in editor"),
                (d(a.edit_panel), "Edit panel content in editor"),
                (d(a.view_files), "View file/tool-call hints"),
                (
                    f"{d(a.toggle_thinking)} / {d(a.toggle_thinking_reverse)}",
                    "Cycle panels: file → tools → metadata",
                ),
                (d(a.toggle_layout), "Toggle file/prompt layout"),
                (d(a.zoom_panel), "Zoom largest panel popup"),
                (d(a.open_artifact_files), "Artifact files (or marked set)"),
                (d(a.toggle_attempt_view), "Toggle attempt history view"),
                (
                    f"{d(a.next_agent_file)} / {d(a.prev_agent_file)}",
                    "Next / prev commit/link/file",
                ),
                (d(a.start_tmux_mode), "Tmux workspace chooser"),
                (d(a.add_agent_tag), "Tag/untag agent (or marked set)"),
                (d(a.open_tmux), "Tmux in primary workspace"),
            ],
        ),
        (
            "Panel / Group / Clan / Workflow Folding",
            [
                (
                    f"{d(a.expand_or_layout)} / {d(a.hooks_or_collapse)}",
                    "Expand/enter panel · collapse/select panel",
                ),
                (
                    d(a.expand_all_folds),
                    "Select visible folds by number",
                ),
                (
                    d(a.hooks_or_collapse_all),
                    "Only panel / collapse group / compact Tools",
                ),
            ],
        ),
        (
            f"Metadata Fold Mode ({d(fm.prefix)})",
            [
                (
                    " / ".join(
                        key_sequence_display(
                            fm.prefix,
                            ag_fold[f"set_level_{position}"],
                        )
                        for position in range(1, 3)
                    ),
                    "Set family level 1-2",
                ),
                (
                    " / ".join(
                        key_sequence_display(
                            fm.prefix,
                            ag_fold[f"set_level_{position}"],
                        )
                        for position in range(1, 4)
                    ),
                    "Set clan/session level 1-3",
                ),
                (
                    " / ".join(
                        key_sequence_display(
                            fm.prefix,
                            ag_fold[f"set_level_{position}"],
                        )
                        for position in range(1, 5)
                    ),
                    "Set selected tribe level 1-4",
                ),
                (
                    key_sequence_display(fm.prefix, ag_fold["cycle_level"]),
                    "Cycle panel fold level forward",
                ),
                (
                    key_sequence_display(fm.prefix, ag_fold["cycle_level_back"]),
                    "Cycle panel fold level backward",
                ),
                (
                    key_sequence_display(fm.prefix, ag_fold["cycle_section"]),
                    "Cycle section/member forward",
                ),
                (
                    key_sequence_display(fm.prefix, ag_fold["toggle_section"]),
                    "Toggle section/member full",
                ),
                ("Roster entry", "Inherit MEMBERS then panel"),
            ],
        ),
        (
            f"Leader Mode ({d(lm.prefix)})",
            [
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'repeat_last'))}",
                    "Repeat last leader command",
                ),
                (leader_key_display(km, "edit_query"), "Filter agents by query"),
                (leader_key_display(km, "show_help"), "Show this help"),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "agent_home")),
                    "Run agent (home)",
                ),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "agent_from_cl")),
                    "Run agent from selected agent",
                ),
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
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'full_history_refresh'))}",
                    "Refresh from full history",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'mark_all_unread_done_agents_read'))}",
                    "Mark all unread done agents read",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'kill_and_edit'))}",
                    "Kill & edit (marked or focused)",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'revert_agent'))}",
                    "Revert agent + opened repos",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'prompt_history'))}",
                    "Prompt history (^k older)",
                ),
                (
                    f"{d(lm.prefix)} {d(sk(lm.keys, 'prompt_history_edit_first'))}",
                    "Edit first prompt history entry",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'prompt_history_cancelled'))}",
                    "History +cancelled (^k older)",
                ),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "open_prompt_stash")),
                    "Open stashed prompts panel",
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
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'models_panel'))}",
                    "Models panel",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'update_sase'))}",
                    "Update sase, core & plugins",
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
            "Zoom Modal",
            [
                ("] / [", "Next / previous panel tab"),
                ("Ctrl-N / Ctrl-P", "Next / previous file, wraps"),
                ("/ / ?", "Search forward / backward"),
                ("n / N", "Next / previous match"),
                ("Esc", "Exit search before closing"),
                ("File rail", "Lists files frozen at open"),
            ],
        ),
        (
            "Agent Query Syntax",
            [
                ("status:VAL", "Substring on status"),
                ("cl:VAL", "Substring on ChangeSpec name"),
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
            "Waiting Badges",
            [
                ("▶ ◐ ⏳ ✓ ✗ ▲", "Dependency status (see Grouping)"),
                ("?", "Waited-for name not found"),
            ],
        ),
        (
            "Agent Row Glyphs",
            [
                ("×N", "N steps (collapsed)"),
                ("×N +M / −M", "M shown / hidden steps or family members"),
                ("◆", "Bead-linked agent"),
                ("↺", "Reverted (changes undone)"),
                ("↻N", "N attempts / retry depth"),
                ("≡", "Workflow row"),
                ("❑", "ChangeSpec row"),
                ("⚡", "Auto-approve (plan)"),
                ("⚡T", "Auto-approve as tale"),
                ("⚡E", "Auto-approve as epic"),
                ("◌", "Hidden by default"),
                ("↳", "Retry chain attempt"),
            ],
        ),
    ]
    # Insert custom mode sections before "General".
    sections.extend(custom_mode_sections(km))
    sections.append(PROMPT_INPUT_SECTION)
    sections.append(
        (
            "General",
            [
                (f"{d(a.next_tab)} / {d(a.prev_tab)}", "Switch tabs"),
                ("[ / ]", "Switch Keymaps / Guide"),
                (
                    d(a.start_agent_from_changespec),
                    "Repeat last +/Ctrl+Space selection",
                ),
                (d(a.toggle_hide_reverted), "Show/hide non-run agents"),
                (
                    d(a.open_config_center),
                    "Admin Center: 1-7 jumps; Statistics [/] t/c/g/p/r",
                ),
                (d(a.show_notifications), "Notifications (d debugs row)"),
                (d(a.dismiss_toasts), "Dismiss toasts"),
                (d(a.stop_axe_and_quit), "Quit / restart menu"),
                (d(a.refresh), "Refresh"),
                (d(a.quit), "Quit"),
                (d(a.open_command_palette), "Open command palette"),
            ],
        ),
    )
    return sections
