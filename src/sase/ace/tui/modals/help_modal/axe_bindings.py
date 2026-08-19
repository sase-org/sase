"""Axe tab keybinding sections for the help modal."""

from ...keymaps import KeymapRegistry, key_display_name
from .binding_common import (
    ADMIN_CENTER_TASKS_SECTION,
    ADMIN_CENTER_UPDATES_SECTION,
    PROMPT_INPUT_SECTION,
    Sections,
    custom_mode_sections,
    glossary_panel_section,
    key_sequence_display,
    memory_panel_section,
    sk,
)


def axe_bindings(km: KeymapRegistry) -> Sections:
    """Build keybinding sections for the AXE tab."""
    d = key_display_name
    a = km.app
    lm = km.leader_mode
    bm = km.bang_mode
    cm = km.copy_mode

    axe_copy = cm.keys["axe"]
    assert isinstance(axe_copy, dict)

    sections: Sections = [
        (
            "Navigation",
            [
                (
                    f"{d(a.next_patch)} / {d(a.prev_patch)}",
                    "Move to next / previous command",
                ),
                (d(a.jump_to_entry), "Jump to entry (' first/back stack)"),
                (
                    f"{d(a.jump_to_entry_fast)} / {d(a.jump_to_entry_forward)}",
                    "Jump stack back / forward",
                ),
                (d(a.jump_to_all_entries), "Jump to entry (all tabs, ` back)"),
                (
                    f"{d(a.next_agent_file)} / {d(a.prev_agent_file)}",
                    "Next / previous chop run",
                ),
                (d(a.scroll_to_top), "Scroll to top"),
                (d(a.scroll_to_bottom), "Scroll to bottom"),
                (d(a.edit_query), "Edit search query"),
            ],
        ),
        (
            "Background Commands",
            [
                (d(a.start_custom_agent), "Run agent"),
                (d(a.start_agent_home), "Run agent (home)"),
                (d(a.start_last_vcs_xprompt_in_editor), "Edit last VCS xprompt"),
                (d(a.restore_prompt_stash), "Restore stashed prompt"),
                (d(a.show_agent_run_log), "Agent run log"),
                (d(a.open_agent_cleanup_panel), "Clear output"),
                (d(a.add_axe_item), "Add lumberjack or chop"),
                (d(a.run_workflow), "Run chop, or re-run done bgcmd"),
                (d(a.edit_spec), "Edit lumberjack or chop config"),
                (d(a.toggle_axe_description), "Expand / collapse description"),
                (d(a.edit_panel), "Edit recorded chop output"),
            ],
        ),
        (
            f"Leader Mode ({d(lm.prefix)})",
            [
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'repeat_last'))}",
                    "Repeat last leader command",
                ),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "agent_home")),
                    "Run agent (home)",
                ),
                (f"{d(lm.prefix)}{d(sk(lm.keys, 'runners'))}", "Show runners info"),
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
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'models_panel'))}",
                    "Launch Control",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'update_sase'))}",
                    "Update SASE + CLIs + hood cache",
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
                (
                    f"{d(bm.prefix)}{d(sk(bm.keys, 'mark_pr_origin'))}",
                    "Mark PR origin",
                ),
            ],
        ),
        (
            f"Copy Mode ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (f"{d(cm.prefix)}{d(axe_copy['visible'])}", "Copy visible output"),
                (f"{d(cm.prefix)}{d(axe_copy['full'])}", "Copy full output"),
                (f"{d(cm.prefix)}{d(axe_copy['snapshot'])}", "Copy sase ace snapshot"),
            ],
        ),
        (
            "Axe Control",
            [
                (d(a.kill_agent), "Start / stop axe (or kill command)"),
                (d(a.open_agent_cleanup_panel), "Clear output"),
                (d(a.stop_axe_and_quit), "Quit / restart menu"),
            ],
        ),
    ]
    # Insert custom mode sections before "General".
    sections.extend(custom_mode_sections(km))
    sections.append(PROMPT_INPUT_SECTION)
    sections.append(glossary_panel_section(km))
    sections.append(memory_panel_section(km))
    sections.append(ADMIN_CENTER_TASKS_SECTION)
    sections.append(ADMIN_CENTER_UPDATES_SECTION)
    sections.append(
        (
            "General",
            [
                (f"{d(a.next_tab)} / {d(a.prev_tab)}", "Switch tabs"),
                ("[ / ]", "Switch Keymaps / Guide"),
                (
                    d(a.start_agent_from_patch),
                    "Repeat last launched VCS xprompt",
                ),
                (
                    d(a.open_config_center),
                    "Admin Center: 1-7 jump, # back",
                ),
                (d(a.show_help), "Show this help"),
                (d(a.show_notifications), "Notifications (d debugs row)"),
                (d(a.dismiss_toasts), "Dismiss toasts"),
                (d(a.refresh), "Refresh"),
                (d(a.quit), "Quit"),
                (d(a.open_command_palette), "Open command palette"),
            ],
        ),
    )
    return sections
