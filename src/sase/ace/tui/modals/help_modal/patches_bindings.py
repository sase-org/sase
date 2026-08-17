"""Patch tab keybinding sections for the help modal."""

from ...keymaps import KeymapRegistry, key_display_name
from .binding_common import (
    ADMIN_CENTER_TASKS_SECTION,
    ADMIN_CENTER_UPDATES_SECTION,
    PROMPT_INPUT_SECTION,
    Sections,
    custom_mode_sections,
    key_sequence_display,
    sk,
)
from .patches_artifact_bindings import artifact_sections
from .patches_copy_bindings import copy_mode_sections


def cls_bindings(km: KeymapRegistry) -> Sections:
    """Build keybinding sections for the Patches pane."""
    d = key_display_name
    a = km.app
    fm = km.fold_mode
    lm = km.leader_mode
    bm = km.bang_mode
    sections: Sections = [
        *artifact_sections(km),
        (
            "PR Navigation",
            [
                (
                    f"{d(a.next_patch)} / {d(a.prev_patch)}",
                    "Move to next / previous Patch",
                ),
                (
                    f"{d(a.start_ancestor_mode)} / {d(a.start_child_mode)} / {d(a.start_sibling_mode)}",
                    "Navigate to ancestor / child / sibling",
                ),
                (d(a.jump_to_entry), "Jump to entry (' first/back stack)"),
                (
                    f"{d(a.jump_to_entry_fast)} / {d(a.jump_to_entry_forward)}",
                    "Jump stack back / forward",
                ),
                (d(a.jump_to_all_entries), "Jump to entry (all tabs, ` back)"),
                (
                    f"{d(a.scroll_detail_down)} / {d(a.scroll_detail_up)}",
                    "Scroll Patch detail down / up",
                ),
                (
                    f"{d(a.scroll_to_top)} / {d(a.scroll_to_bottom)}",
                    "Scroll Patch detail top / bottom",
                ),
            ],
        ),
        (
            "Patch Actions",
            [
                (d(a.accept_proposal), "Accept (! = spec only, @ = mail)"),
                (d(a.rebase), "Rebase Patch onto parent"),
                (
                    f"{d(a.checkout)} / {d(a.start_checkout_mode)}1-{d(a.start_checkout_mode)}9",
                    "Checkout Patch (workspace 1-9)",
                ),
                (d(a.show_diff), "Show diff"),
                (d(a.edit_hooks), "Edit hooks"),
                (d(a.hooks_or_collapse_all), "Add hooks from failed targets"),
                (d(a.show_agent_run_log), "Agent run log"),
                (d(a.mail), "Mail Patch"),
                (d(a.toggle_mark), "Mark/unmark current Patch"),
                (d(a.rename_cl), "Rename Patch (non-Sub/Rev)"),
                (
                    key_sequence_display(bm.prefix, sk(bm.keys, "start_rewind")),
                    "Rewind to prev commit (! skip VCS)",
                ),
                (d(a.change_status), "Change status"),
                (
                    key_sequence_display(bm.prefix, sk(bm.keys, "mark_pr_origin")),
                    "Mark PR origin",
                ),
                (d(a.bulk_change_status), "Bulk status change (marked Patches)"),
                (d(a.start_tmux_mode), "Checkout + tmux (prompts ws#)"),
                (d(a.clear_marks), "Clear all marks"),
                (d(a.view_files), "View files"),
                (d(a.reword), "Reword Patch description"),
                (d(a.add_tag), "Add tag to Patch description"),
                (d(a.sync), "Sync workspace"),
                (d(a.edit_spec), "Edit spec file"),
            ],
        ),
        (
            f"Fold Mode ({d(fm.prefix)})",
            [
                (
                    " / ".join(
                        key_sequence_display(
                            fm.prefix,
                            sk(fm.keys, f"set_level_{position}"),
                        )
                        for position in range(1, 4)
                    ),
                    "Set all folds to level 1-3",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'cycle_stitches'))}",
                    "Cycle stitches folding",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'cycle_hooks'))}",
                    "Cycle hooks folding",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'cycle_mentors'))}",
                    "Cycle mentors folding",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'cycle_timestamps'))}",
                    "Cycle timestamps folding",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'cycle_deltas'))}",
                    "Cycle deltas summary/files/lines",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'toggle_stitches'))}",
                    "Toggle stitches collapsed/expanded",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'toggle_hooks'))}",
                    "Toggle hooks collapsed/expanded",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'toggle_mentors'))}",
                    "Toggle mentors collapsed/expanded",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'toggle_timestamps'))}",
                    "Toggle timestamps collapsed/expanded",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'toggle_deltas'))}",
                    "Toggle deltas folded/unfolded",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'cycle_all'))}",
                    "Cycle all sections",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'toggle_all'))}",
                    "Toggle all collapsed/expanded",
                ),
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'expand_all_groups'))}",
                    "Expand all grouping banners",
                ),
            ],
        ),
        (
            "Workflows & Agents",
            [
                (d(a.run_workflow), "Run workflow"),
                (d(a.start_custom_agent), "Run an agent"),
                (d(a.start_agent_home), "Run agent (home)"),
                (
                    d(a.start_agent_from_patch),
                    "Repeat last +/Ctrl+Space selection",
                ),
                (d(a.start_last_vcs_xprompt_in_editor), "Edit last VCS xprompt"),
                (d(a.restore_prompt_stash), "Restore stashed prompt"),
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
            f"Leader Mode ({d(lm.prefix)})",
            [
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'repeat_last'))}",
                    "Repeat last leader command",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'clear_comments'))}",
                    "Clear COMMENTS field",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'run_cmd'))}",
                    "Run command (use current Patch)",
                ),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "agent_home")),
                    "Run agent (home)",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'kill_mentors'))}",
                    "Kill running mentors",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'review_mentors'))}",
                    "Review mentor comments",
                ),
                (f"{d(lm.prefix)}{d(sk(lm.keys, 'runners'))}", "Show runners info"),
                (
                    key_sequence_display(lm.prefix, sk(lm.keys, "agent_from_cl")),
                    "Run agent from current Patch",
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
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'agent_run_log'))}",
                    "Agent run log",
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
            "Queries",
            [
                (d(a.edit_query), "Edit search query"),
                (
                    f"{d(a.start_saved_query_mode)}1-9 / {d(a.start_saved_query_mode)}0",
                    "Load saved Patch query slot",
                ),
                (d(a.open_saved_query_picker), "Choose saved Patch query"),
                (d(a.prev_query), "Previous query"),
                (d(a.next_query), "Next query"),
            ],
        ),
        (
            "Grouping",
            [
                (
                    f"{d(a.cycle_grouping_mode)} / {d(a.cycle_grouping_mode_reverse)}",
                    "Cycle: proj→date→status",
                ),
                ("PR by date", "Today/Yesterday by 4h then hour; week/older unchanged"),
                (
                    f"{d(a.expand_or_layout)} / {d(a.hooks_or_collapse)}",
                    "Expand/collapse group",
                ),
                (
                    f"{key_sequence_display(fm.prefix, sk(fm.keys, 'expand_all_groups'))}"
                    f" / {d(a.hooks_or_collapse_all)}",
                    "Expand/collapse all",
                ),
            ],
        ),
        *copy_mode_sections(km),
    ]
    # Insert custom mode sections before "General".
    sections.extend(custom_mode_sections(km))
    sections.append(PROMPT_INPUT_SECTION)
    sections.append(ADMIN_CENTER_TASKS_SECTION)
    sections.append(ADMIN_CENTER_UPDATES_SECTION)
    sections.append(
        (
            "General",
            [
                (f"{d(a.next_tab)} / {d(a.prev_tab)}", "Switch tabs"),
                ("[ / ]", "In help: switch Keymaps / Guide"),
                (d(a.toggle_hide_submitted), "Show/hide submitted PRs"),
                (d(a.patches_toggle_reverted), "Show/hide reverted PRs"),
                (
                    d(a.open_config_center),
                    "Admin Center: 1-7 jump, # back",
                ),
                (d(a.show_help), "Show this help"),
                (d(a.show_notifications), "Notifications (d debugs row)"),
                (d(a.dismiss_toasts), "Dismiss toasts"),
                (d(a.stop_axe_and_quit), "Quit / restart menu"),
                (d(a.refresh), "Refresh"),
                (d(a.artifacts_copy_reference), "Copy @patch: reference"),
                (d(a.quit), "Quit"),
                (d(a.open_command_palette), "Open command palette"),
            ],
        ),
    )
    return sections
