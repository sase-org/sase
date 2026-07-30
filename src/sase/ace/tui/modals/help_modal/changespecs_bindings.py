"""ChangeSpec tab keybinding sections for the help modal."""

from ...keymaps import KeymapRegistry, key_display_name, leader_key_display
from .binding_common import (
    ADMIN_CENTER_TASKS_SECTION,
    ADMIN_CENTER_UPDATES_SECTION,
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
    commits_copy = cm.keys["artifacts_commits"]
    plans_copy = cm.keys["artifacts_plans"]
    chats_copy = cm.keys["artifacts_chats"]
    files_copy = cm.keys["artifacts_files"]
    bugs_copy = cm.keys["artifacts_bugs"]
    assert isinstance(commits_copy, dict)
    assert isinstance(plans_copy, dict)
    assert isinstance(chats_copy, dict)
    assert isinstance(files_copy, dict)
    assert isinstance(bugs_copy, dict)
    pr_copy_key = cs_copy.get("pr_number", cs_copy.get("cl_number"))
    assert isinstance(pr_copy_key, str)
    artifact_list_navigation = [
        (
            f"{d(a.toggle_mark)} / {d(a.clear_marks)}",
            "Mark current / clear pane marks",
        ),
        (
            f"{d(a.scroll_to_top)} / {d(a.scroll_to_bottom)}",
            "Select first / last entry",
        ),
        (
            f"{d(a.scroll_detail_down)} / {d(a.scroll_detail_up)}",
            "Scroll right detail down / up",
        ),
        (
            f"{d(a.scroll_prompt_down)} / {d(a.scroll_prompt_up)}",
            "Move down / up 10 entries",
        ),
        (d(a.jump_to_entry), "Hint jump (' first / back)"),
    ]

    sections: Sections = [
        (
            "Artifact Sub-tabs",
            [
                (
                    "1 / 2 / 3 / 4 / 5 / 6",
                    "Jump all six artifact panes",
                ),
                (
                    f"{d(a.cycle_artifacts_subtab_reverse)} / {d(a.cycle_artifacts_subtab)}",
                    "Cycle all six artifact panes",
                ),
                (
                    d(a.pick_artifacts_project),
                    "Pick; Commits rewrites project:",
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
                ("p (commit view)", "Toggle attached local plan / commit"),
                (d(a.commits_copy_sha), "Copy full commit SHA"),
                (
                    f"{d(a.edit_query)} / {d(a.commits_filters)}",
                    "Focus persistent commit filter",
                ),
                ("project:NAME", "Single; omitted = all projects"),
                ("repo: / author:", "Filter repository / author substring"),
                ("since: / until:", "until:DAY includes the full day"),
                ("sidecar:true / false", "Include / exclude sidecars"),
                ("limit:N / limit:all", "N caps; omitted/all unlimited"),
                (
                    "[P/N] / [P/N+]",
                    "Selected position / matched total; + is a lower bound",
                ),
                ("bare text", "Match subject words"),
                ("Enter / Esc", "Commit / restore; row stays"),
                (
                    f"{d(a.commits_toggle_sdd)} / {d(a.commits_toggle_all_projects)}",
                    "Sidecars / project: off/on",
                ),
                (
                    f"{d(a.commits_fetch)} / {d(a.commits_refresh)}",
                    "Fetch remote refs / refresh from local refs",
                ),
                *artifact_list_navigation,
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
                *artifact_list_navigation,
            ],
        ),
        (
            "Plans Pane",
            [
                (f"{d(a.plans_next)} / {d(a.plans_prev)}", "Next / previous row"),
                (d(a.plans_view_selected), "Open selected plan or bead"),
                (
                    f"{d(a.edit_query)} / {d(a.plans_filters)}",
                    "Open inline plans filter bar",
                ),
                ("kind: / status: / tier:", "Filter kind, status, or tier"),
                ("kind:<sidecar role>", "Filter archived document kind"),
                ("project: / since: / until:", "Filter project or creation date"),
                ("bare text", "Title/body/id/metadata (AND)"),
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
                *artifact_list_navigation,
            ],
        ),
        (
            "Chats Pane",
            [
                (f"{d(a.chats_next)} / {d(a.chats_prev)}", "Next / previous row"),
                (d(a.chats_view_selected), "Open selected chat transcript"),
                (d(a.chats_filters), "Open chat filter bar"),
                (d(a.chats_cycle_provenance), "Cycle chat sync provenance"),
                (d(a.chats_open_agent), "Open associated agent"),
                (d(a.chats_open_external), "Open chat in editor"),
                (d(a.chats_copy_path), "Copy chat transcript path"),
                (d(a.chats_refresh), "Refresh chat transcripts"),
                *artifact_list_navigation,
            ],
        ),
        (
            "Files Pane",
            [
                (f"{d(a.files_next)} / {d(a.files_prev)}", "Next / previous row"),
                (d(a.files_view_selected), "View selected artifact file"),
                (d(a.files_open_viewer), "Open in rich viewer"),
                (d(a.files_open_external), "Open externally"),
                (d(a.files_open_agent), "Open producing agent"),
                (d(a.files_filters), "Open artifact-file filters"),
                (d(a.files_cycle_kind), "Cycle file kind"),
                (d(a.files_copy_reference), "Copy artifact-file reference"),
                (d(a.files_copy_path), "Copy stored path"),
                (d(a.files_refresh), "Refresh artifact files"),
                *artifact_list_navigation,
            ],
        ),
        (
            "Preview Reader",
            [
                ("j/k · Ctrl+D/U · g/G", "Line / page / edge scrolling"),
                ("y / Y", "Copy contents / source path"),
                ("%", "Open active pane Copy as… palette"),
                ("R", "Toggle Markdown rendered/source view"),
                ("/ · n/N", "Search source · next/previous match"),
                ("o / Z", "Open editor / rich viewer"),
                ("Esc / q", "Clear search then close / always close"),
            ],
        ),
        (
            "PR Navigation",
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
                    "Scroll PR detail down / up",
                ),
                (
                    f"{d(a.scroll_to_top)} / {d(a.scroll_to_bottom)}",
                    "Scroll PR detail top / bottom",
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
                (leader_key_display(km, "show_help"), "Show this help"),
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
                    "Update SASE + CLIs + hood cache",
                ),
            ],
        ),
        (
            "Queries",
            [
                (d(a.edit_query), "Edit search query"),
                (
                    f"{d(a.open_saved_query_picker)}1-9 / {d(a.open_saved_query_picker)}0",
                    "Choose saved PR query",
                ),
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
            f"Copy Mode · Commits ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, commits_copy["reference"]),
                    "Copy @commit reference",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["sha"]),
                    "Copy full SHA",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["message"]),
                    "Copy commit message",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["repo_sha"]),
                    "Copy repo@SHA",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["plan"]),
                    "Copy linked plan reference",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, commits_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Plans ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, plans_copy["reference"]),
                    "Copy @bead/document reference",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["design"]),
                    "Copy bead design reference",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["path"]),
                    "Copy plan path",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["title"]),
                    "Copy plan title",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["body"]),
                    "Copy plan body",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, plans_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Chats ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, chats_copy["reference"]),
                    "Copy @chat reference",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["path"]),
                    "Copy transcript path",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["agent"]),
                    "Copy agent name",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["transcript"]),
                    "Copy transcript contents",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, chats_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Files ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, files_copy["contents"]),
                    "Copy text contents",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["reference"]),
                    "Copy @file reference",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["path"]),
                    "Copy anchored stored path",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["source"]),
                    "Copy anchored source path",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["label"]),
                    "Copy artifact-file label",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, files_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode · Bugs ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (
                    key_sequence_display(cm.prefix, bugs_copy["reference"]),
                    "Copy @bug reference",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["link"]),
                    "Copy Markdown link",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["handoff"]),
                    "Reference in new agent prompt",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["number"]),
                    "Copy issue number",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["url"]),
                    "Copy issue URL",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["title"]),
                    "Copy issue title",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["prompt"]),
                    "Copy agent-ready prompt",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["json"]),
                    "Copy metadata JSON",
                ),
                (
                    key_sequence_display(cm.prefix, bugs_copy["snapshot"]),
                    "Copy sase ace snapshot",
                ),
            ],
        ),
        (
            f"Copy Mode ({d(cm.prefix)})",
            [
                (d(cm.prefix), "Open Copy as… palette"),
                (f"{d(cm.prefix)}{d(cs_copy['raw'])}", "Copy ChangeSpec"),
                (
                    f"{d(cm.prefix)}{d(cs_copy['with_snapshot'])}",
                    "Copy ChangeSpec + snapshot",
                ),
                (f"{d(cm.prefix)}{d(cs_copy['bug'])}", "Copy bug number"),
                (f"{d(cm.prefix)}{d(pr_copy_key)}", "Copy PR number"),
                (f"{d(cm.prefix)}{d(cs_copy['name'])}", "Copy ChangeSpec name"),
                (f"{d(cm.prefix)}{d(cs_copy['link'])}", "Copy Markdown link"),
                (f"{d(cm.prefix)}{d(cs_copy['spec'])}", "Copy project spec file"),
                (f"{d(cm.prefix)}{d(cs_copy['snapshot'])}", "Copy sase ace snapshot"),
            ],
        ),
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
                (d(a.toggle_hide_reverted), "Show/hide reverted PRs"),
                (
                    d(a.open_config_center),
                    "Admin Center: 1-7 jumps; Statistics [/] t/T/c/g/p/P/r/?",
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
