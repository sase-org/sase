"""ChangeSpec tab keybinding sections for the help modal."""

from ...keymaps import KeymapRegistry, key_display_name
from .binding_common import (
    PROMPT_INPUT_SECTION,
    Sections,
    custom_mode_sections,
    key_sequence_display,
    sk,
)


def cls_bindings(km: KeymapRegistry) -> Sections:
    """Build keybinding sections for the ChangeSpecs tab."""
    d = key_display_name
    a = km.app
    fm = km.fold_mode
    lm = km.leader_mode
    bm = km.bang_mode
    cm = km.copy_mode

    cs_copy = cm.keys["changespecs"]
    assert isinstance(cs_copy, dict)
    pr_copy_key = cs_copy.get("pr_number", cs_copy.get("cl_number"))
    assert isinstance(pr_copy_key, str)

    sections: Sections = [
        (
            "Artifact Sub-tabs",
            [
                (
                    f"{d(a.cycle_artifacts_subtab_reverse)} / {d(a.cycle_artifacts_subtab)}",
                    "Previous / next: PRs, Commits, Bugs, Plans",
                ),
                (
                    d(a.pick_artifacts_project),
                    "Pick scope for Commits, Bugs, or Plans",
                ),
                (
                    d(a.open_command_palette),
                    "Jump directly to any artifact pane",
                ),
            ],
        ),
        (
            "Commits Pane",
            [
                (
                    f"{d(a.commits_next)} / {d(a.commits_prev)}",
                    "Move to next / previous commit",
                ),
                (
                    d(a.commits_view_selected),
                    "Open full commit message and diff",
                ),
                (d(a.commits_copy_sha), "Copy full commit SHA"),
                (
                    d(a.commits_filters),
                    "Edit author, date, repo, and limit filters",
                ),
                (
                    f"{d(a.commits_toggle_sdd)} / {d(a.commits_toggle_all_projects)}",
                    "Toggle SDD history / all projects",
                ),
                (
                    f"{d(a.commits_fetch)} / {d(a.commits_refresh)}",
                    "Fetch remote refs / refresh from local refs",
                ),
            ],
        ),
        (
            "Bugs Pane",
            [
                (f"{d(a.next_bug)} / {d(a.prev_bug)}", "Next / previous issue"),
                (d(a.cycle_bug_filter), "Cycle open / closed / all issues"),
                (d(a.create_bug), "Create issue"),
                (d(a.edit_bug), "Edit selected issue"),
                (d(a.toggle_bug_state), "Close / reopen selected issue"),
                (d(a.open_bug), "Open issue in browser"),
                (d(a.copy_bug), "Copy issue number and URL"),
                (d(a.start_agent_from_bug), "Run an agent from issue context"),
                (d(a.focus_bug_links), "Focus linked epics and PRs"),
                (d(a.activate_bug_link), "Open focused epic or PR link"),
                (d(a.refresh_bugs), "Refresh tracker issues"),
            ],
        ),
        (
            "Plans Pane",
            [
                (f"{d(a.plans_next)} / {d(a.plans_prev)}", "Next / previous row"),
                (d(a.plans_view_selected), "Open selected plan or bead"),
                (
                    f"{d(a.plans_expand)} / {d(a.plans_collapse)}",
                    "Expand / collapse epic phases",
                ),
                (d(a.plans_cycle_status), "Cycle selected bead status"),
                (d(a.plans_edit_bead), "Edit selected bead"),
                (d(a.plans_launch_epic), "Launch ready epic work"),
                (d(a.plans_approve), "Approve selected proposal"),
                (d(a.plans_reject), "Reject selected proposal"),
                (d(a.plans_open_bug), "Open linked external bug"),
                (d(a.plans_refresh), "Refresh plans and beads"),
            ],
        ),
        (
            "Navigation",
            [
                (
                    f"{d(a.next_changespec)} / {d(a.prev_changespec)}",
                    "Move to next / previous ChangeSpec",
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
                    "Scroll detail panel down / up",
                ),
                (
                    f"{d(a.scroll_to_top)} / {d(a.scroll_to_bottom)}",
                    "Scroll detail panel to top / bottom",
                ),
            ],
        ),
        (
            "PR Actions",
            [
                (d(a.accept_proposal), "Accept (! = spec only, @ = mail)"),
                (d(a.rebase), "Rebase PR onto parent"),
                (
                    f"{d(a.checkout)} / {d(a.start_checkout_mode)}1-{d(a.start_checkout_mode)}9",
                    "Checkout PR (workspace 1-9)",
                ),
                (d(a.show_diff), "Show diff"),
                (d(a.edit_hooks), "Edit hooks"),
                (d(a.hooks_or_collapse_all), "Add hooks from failed targets"),
                (d(a.show_agent_run_log), "Agent run log"),
                (d(a.mail), "Mail PR"),
                (d(a.toggle_mark), "Mark/unmark current PR"),
                (d(a.rename_cl), "Rename PR (non-Sub/Rev)"),
                (d(a.start_rewind), "Rewind to prev commit (! skip VCS)"),
                (d(a.change_status), "Change status"),
                (d(a.bulk_change_status), "Bulk status change (marked PRs)"),
                (d(a.start_tmux_mode), "Checkout + tmux (prompts ws#)"),
                (d(a.clear_marks), "Clear all marks"),
                (d(a.view_files), "View files"),
                (d(a.reword), "Reword PR description"),
                (d(a.add_tag), "Add tag to PR description"),
                (d(a.sync), "Sync workspace"),
                (d(a.edit_spec), "Edit spec file"),
            ],
        ),
        (
            f"Fold Mode ({d(fm.prefix)})",
            [
                (
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'cycle_commits'))}",
                    "Cycle commits folding",
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
                    f"{d(fm.prefix)} {d(sk(fm.keys, 'toggle_commits'))}",
                    "Toggle commits collapsed/expanded",
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
            ],
        ),
        (
            "Workflows & Agents",
            [
                (d(a.run_workflow), "Run workflow"),
                (d(a.start_custom_agent), "Run an agent"),
                (d(a.start_agent_home), "Run agent (home)"),
                (
                    d(a.start_agent_from_changespec),
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
                    "Run command (use current PR)",
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
                    "Run agent from current PR",
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
                    "Models panel",
                ),
                (
                    f"{d(lm.prefix)}{d(sk(lm.keys, 'update_sase'))}",
                    "Update sase, core & plugins",
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
                    f"{d(a.expand_all_folds)} / {d(a.hooks_or_collapse_all)}",
                    "Expand/collapse all",
                ),
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
                (f"{d(cm.prefix)}{d(pr_copy_key)}", "Copy PR number"),
                (f"{d(cm.prefix)}{d(cs_copy['name'])}", "Copy ChangeSpec name"),
                (f"{d(cm.prefix)}{d(cs_copy['spec'])}", "Copy project spec file"),
                (f"{d(cm.prefix)}{d(cs_copy['snapshot'])}", "Copy sase ace snapshot"),
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
                ("[ / ]", "In help: switch Keymaps / Guide"),
                (d(a.toggle_hide_submitted), "Show/hide submitted PRs"),
                (d(a.toggle_hide_reverted), "Show/hide reverted PRs"),
                (
                    d(a.open_config_center),
                    "Admin Center: 1-6 jumps to tab",
                ),
                (d(a.show_notifications), "Show notifications"),
                (d(a.dismiss_toasts), "Dismiss toasts"),
                (d(a.stop_axe_and_quit), "Quit / restart menu"),
                (d(a.refresh), "Refresh"),
                (d(a.quit), "Quit"),
                (d(a.open_command_palette), "Open command palette"),
                (d(a.show_help), "Show this help"),
            ],
        ),
    )
    return sections
