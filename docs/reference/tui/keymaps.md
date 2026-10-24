---
title: TUI keymaps
description: Default configurable key bindings for SASE's terminal interface.
---

<!-- generated, do not edit; source: src/sase/default_config.yml and src/sase/ace/tui/keymaps/metadata.py (tools/render_keymap_macro_reference; run just fix to regenerate) -->

# TUI keymaps

These are the bundled defaults for configurable TUI actions. The key and action labels come from the keymap configuration and the metadata used by the live help surfaces. Fixed widget and text-editor keys are documented with their behavior in the [TUI reference](index.md).

## Application

| Default key | Action | Configuration |
| --- | --- | --- |
| `j` | Next | `ace.keymaps.app.next_patch` |
| `k` | Previous | `ace.keymaps.app.prev_patch` |
| `q` | Quit | `ace.keymaps.app.quit` |
| `s` | Status | `ace.keymaps.app.change_status` |
| `r` | Run / Re-run | `ace.keymaps.app.run_workflow` |
| `r` | Refresh | `ace.keymaps.app.agents_refresh` |
| `M` | Mail | `ace.keymaps.app.mail` |
| `d` | Diff | `ace.keymaps.app.show_diff` |
| `w` | Reword | `ace.keymaps.app.reword` |
| `W` | Add Tag | `ace.keymaps.app.add_tag` |
| `v` | View | `ace.keymaps.app.view_files` |
| `'` | Jump to Entry | `ace.keymaps.app.jump_to_entry` |
| `Ctrl+O` | Fast Jump | `ace.keymaps.app.jump_to_entry_fast` |
| `Ctrl+Shift+O` | Forward Jump | `ace.keymaps.app.jump_to_entry_forward` |
| `` ` `` | Jump All | `ace.keymaps.app.jump_to_all_entries` |
| `"` | Jump to Node | `ace.keymaps.app.jump_to_node` |
| `h` | Parent / Collapse or Jump Panel/Fold | `ace.keymaps.app.hooks_or_collapse` |
| `H` | Collapse Selected Workflow/Session / Scoped Agent Nodes/Clans/Groups / Hint Panel Fold / Compact LLM Calls / All | `ace.keymaps.app.hooks_or_collapse_all` |
| `F` | Edit Hooks / Fork | `ace.keymaps.app.edit_hooks` |
| `Unbound` | Mark PR Origin | `ace.keymaps.app.mark_pr_origin` |
| `z` | Fold | `ace.keymaps.app.start_fold_mode` |
| `Z` | Zoom Detail | `ace.keymaps.app.zoom_panel` |
| `=` | Only/Restore Panels | `ace.keymaps.app.isolate_panels` |
| `-` | Collapse/Restore Panel Folds | `ace.keymaps.app.collapse_panel_folds` |
| `_` | Collapse/Restore All Panel Folds | `ace.keymaps.app.collapse_all_panel_folds` |
| `A` | Approve Plan | `ace.keymaps.app.plans_approve` |
| `A` | Accept / Answer | `ace.keymaps.app.accept_proposal` |
| `b` | Rebase | `ace.keymaps.app.rebase` |
| `Unbound` | Rewind | `ace.keymaps.app.start_rewind` |
| `T` | Tmux | `ace.keymaps.app.open_tmux` |
| `t` | Tmux Mode | `ace.keymaps.app.start_tmux_mode` |
| `C` | Checkout | `ace.keymaps.app.checkout` |
| `c` | Checkout Mode | `ace.keymaps.app.start_checkout_mode` |
| `R` | Refresh | `ace.keymaps.app.refresh` |
| `R` | Retry | `ace.keymaps.app.agents_retry` |
| `y` | Copy Reference | `ace.keymaps.app.artifacts_copy_reference` |
| `y` | Copy Agent Reference | `ace.keymaps.app.agents_copy_reference` |
| `Unbound` | Link Marked Artifact | `ace.keymaps.app.artifacts_link_marked` |
| `Y` | Sync | `ace.keymaps.app.sync` |
| `/` | Edit Query | `ace.keymaps.app.edit_query` |
| `Ctrl+R` | Reverse Search Order | `ace.keymaps.app.search_reverse` |
| `*` | Saved Queries | `ace.keymaps.app.open_saved_query_picker` |
| `0` | Saved Query Slots | `ace.keymaps.app.start_saved_query_mode` |
| `e` | Edit Spec / Content | `ace.keymaps.app.edit_spec` |
| `a` | Add AXE Item | `ace.keymaps.app.add_axe_item` |
| `d` | Toggle AXE Description | `ace.keymaps.app.toggle_axe_description` |
| `Ctrl+D` | Scroll Down | `ace.keymaps.app.scroll_detail_down` |
| `Ctrl+U` | Scroll Up | `ace.keymaps.app.scroll_detail_up` |
| `Ctrl+F` | Scroll Prompt Down | `ace.keymaps.app.scroll_prompt_down` |
| `Ctrl+B` | Scroll Prompt Up | `ace.keymaps.app.scroll_prompt_up` |
| `Tab` | Next Tab | `ace.keymaps.app.next_tab` |
| `Shift+Tab` | Prev Tab | `ace.keymaps.app.prev_tab` |
| `]` | Next Agent Tab | `ace.keymaps.app.next_agents_tab` |
| `[` | Previous Agent Tab | `ace.keymaps.app.prev_agents_tab` |
| `Unbound` | Go to Agent Tab | `ace.keymaps.app.pick_agents_tab` |
| `]` | Next Artifact | `ace.keymaps.app.cycle_artifacts_subtab` |
| `[` | Previous Artifact | `ace.keymaps.app.cycle_artifacts_subtab_reverse` |
| `}` | Wider Artifact List | `ace.keymaps.app.cycle_artifacts_split` |
| `{` | Narrower Artifact List | `ace.keymaps.app.cycle_artifacts_split_reverse` |
| `D` | Pane Description | `ace.keymaps.app.cycle_artifacts_description` |
| `)` | Next File Version | `ace.keymaps.app.files_next_version` |
| `(` | Previous File Version | `ace.keymaps.app.files_prev_version` |
| `p` | Project Scope | `ace.keymaps.app.pick_artifacts_project` |
| `Ctrl+J` | Load More | `ace.keymaps.app.artifacts_load_more` |
| `Ctrl+K` | Unload | `ace.keymaps.app.artifacts_unload` |
| `j` | Next Commit | `ace.keymaps.app.stitches_next` |
| `k` | Previous Commit | `ace.keymaps.app.stitches_prev` |
| `Enter` | View Commit | `ace.keymaps.app.stitches_view_selected` |
| `f` | Commit Filters | `ace.keymaps.app.stitches_filters` |
| `d` | Toggle Commit Sidecars | `ace.keymaps.app.stitches_toggle_sdd` |
| `z` | Cycle Merge Visibility | `ace.keymaps.app.stitches_cycle_merges` |
| `a` | Toggle All Projects | `ace.keymaps.app.stitches_toggle_all_projects` |
| `F` | Fetch Commits | `ace.keymaps.app.stitches_fetch` |
| `j` | Next Plan | `ace.keymaps.app.plans_next` |
| `k` | Previous Plan | `ace.keymaps.app.plans_prev` |
| `Enter` | View Plan | `ace.keymaps.app.plans_view_selected` |
| `f` | Plan Filters | `ace.keymaps.app.plans_filters` |
| `X` | Reject Plan | `ace.keymaps.app.plans_reject` |
| `j` | Next Bead | `ace.keymaps.app.beads_next` |
| `k` | Previous Bead | `ace.keymaps.app.beads_prev` |
| `Enter` | View Bead | `ace.keymaps.app.beads_view_selected` |
| `f` | Bead Filters | `ace.keymaps.app.beads_filters` |
| `l` | Expand Epic | `ace.keymaps.app.beads_expand` |
| `h` | Collapse Epic | `ace.keymaps.app.beads_collapse` |
| `s` | Cycle Bead Status | `ace.keymaps.app.beads_cycle_status` |
| `e` | Edit Bead | `ace.keymaps.app.beads_edit` |
| `N` | Add Bead Note | `ace.keymaps.app.beads_add_note` |
| `Ctrl+T` | Toggle Note Audience | `ace.keymaps.app.beads_toggle_note_audience` |
| `n` | Create Task Bead | `ace.keymaps.app.beads_create` |
| `c` | Close / Reopen Bead | `ace.keymaps.app.beads_close` |
| `z` | Snooze Bead | `ace.keymaps.app.beads_snooze` |
| `w` | Launch / Resolve Stranded | `ace.keymaps.app.beads_launch_work` |
| `E` | Open Linked Issue | `ace.keymaps.app.beads_open_bug` |
| `O` | Open Attachments | `ace.keymaps.app.beads_open_attachments` |
| `b` | Bead Issue Mode | `ace.keymaps.app.start_bead_issue_mode` |
| `j` | Next Artifact File | `ace.keymaps.app.files_next` |
| `k` | Previous Artifact File | `ace.keymaps.app.files_prev` |
| `Enter` | View Artifact File | `ace.keymaps.app.files_view_selected` |
| `Z` | Open in Rich Viewer | `ace.keymaps.app.files_open_viewer` |
| `E` | Open Externally | `ace.keymaps.app.files_open_external` |
| `a` | Open Producing Agent | `ace.keymaps.app.files_open_agent` |
| `f` | Artifact File Filters | `ace.keymaps.app.files_filters` |
| `z` | Cycle Kind Filter | `ace.keymaps.app.files_cycle_kind` |
| `Y` | Copy Stored Path | `ace.keymaps.app.files_copy_path` |
| `j` | Next Agent | `ace.keymaps.app.agents_next` |
| `k` | Previous Agent | `ace.keymaps.app.agents_prev` |
| `w` | Revive Agent | `ace.keymaps.app.agents_revive` |
| `f` | Agent Filters | `ace.keymaps.app.agents_filters` |
| `Unbound` | Machine | `ace.keymaps.app.connect_agent_machine` |
| `Unbound` | Connect Machine | `ace.keymaps.app.setup_agent_machine` |
| `Unbound` | Retry Remote Agent | `ace.keymaps.app.retry_remote_agent` |
| `Unbound` | View Remote Content | `ace.keymaps.app.view_remote_agent_content` |
| `Unbound` | Answer/Approve Remote Attention | `ace.keymaps.app.answer_remote_attention` |
| `Unbound` | Check Dispatch Launch Outcome | `ace.keymaps.app.check_dispatch_launch_outcome` |
| `f` | Patch Filters | `ace.keymaps.app.patches_filters` |
| `X` | Agent Cleanup | `ace.keymaps.app.open_agent_cleanup_panel` |
| `Q` | Quit / Restart | `ace.keymaps.app.stop_axe_and_quit` |
| `+` | Run Agent | `ace.keymaps.app.start_custom_agent` |
| `Space` | Run Agent (Last VCS Macro) | `ace.keymaps.app.start_agent_from_patch` |
| `Ctrl+G` | Edit Last VCS Macro | `ace.keymaps.app.start_last_vcs_macro_in_editor` |
| `@` | Restore Prompt Stash | `ace.keymaps.app.restore_prompt_stash` |
| `!` | Bang Mode | `ace.keymaps.app.start_bang_mode` |
| `m` | Mark | `ace.keymaps.app.toggle_mark` |
| `n` | Rename | `ace.keymaps.app.rename_cl` |
| `u` | Unmark All | `ace.keymaps.app.clear_marks` |
| `S` | Bulk Status | `ace.keymaps.app.bulk_change_status` |
| `s` | Save Marked Agents | `ace.keymaps.app.save_marked_agents` |
| `i` | Notifications | `ace.keymaps.app.show_notifications` |
| `x` | Kill | `ace.keymaps.app.kill_agent` |
| `l` | Expand / Enter Panel | `ace.keymaps.app.expand_or_layout` |
| `L` | Tribe Folds / Expand All | `ace.keymaps.app.expand_all_folds` |
| `%` | Copy | `ace.keymaps.app.copy_tab_content` |
| `g` | Top | `ace.keymaps.app.scroll_to_top` |
| `G` | Bottom | `ace.keymaps.app.scroll_to_bottom` |
| `#` | SASE Admin Center | `ace.keymaps.app.open_config_center` |
| `?` | Help | `ace.keymaps.app.show_help` |
| `^` | Prev Query | `ace.keymaps.app.prev_query` |
| `_` | Next Query | `ace.keymaps.app.next_query` |
| `<` | Ancestor | `ace.keymaps.app.start_ancestor_mode` |
| `>` | Child | `ace.keymaps.app.start_child_mode` |
| `~` | Sibling | `ace.keymaps.app.start_sibling_mode` |
| `.` | Relations Panel | `ace.keymaps.app.toggle_relation_panel` |
| `$` | Follow Link | `ace.keymaps.app.follow_artifact_link` |
| `.` | Toggle Reverted | `ace.keymaps.app.toggle_hide_reverted` |
| `X` | Toggle Reverted | `ace.keymaps.app.patches_toggle_reverted` |
| `x` | Toggle Submitted | `ace.keymaps.app.toggle_hide_submitted` |
| `,` | Leader | `ace.keymaps.app.start_leader_mode` |
| `Ctrl+N` | Next Job Run | `ace.keymaps.app.next_chop_run` |
| `Ctrl+P` | Previous Job Run | `ace.keymaps.app.prev_chop_run` |
| `Ctrl+J` | Next Deck Card | `ace.keymaps.app.next_deck_card` |
| `Ctrl+K` | Previous Deck Card | `ace.keymaps.app.prev_deck_card` |
| `)` | Newer Card Block | `ace.keymaps.app.next_card_block` |
| `(` | Older Card Block | `ace.keymaps.app.prev_card_block` |
| `Ctrl+N` | Next Deck | `ace.keymaps.app.next_deck` |
| `Ctrl+P` | Previous Deck | `ace.keymaps.app.prev_deck` |
| `p` | Pick Deck | `ace.keymaps.app.pick_deck` |
| `P` | Cycle Deck View | `ace.keymaps.app.cycle_deck_view` |
| `B` | Toggle Deck View Lock | `ace.keymaps.app.toggle_deck_view_lock` |
| `\` | Split Deck Below | `ace.keymaps.app.toggle_deck_split_below` |
| <code>&#124;</code> | Split Deck Right | `ace.keymaps.app.toggle_deck_split_right` |
| `Ctrl+F` | Focus Next Deck Panel | `ace.keymaps.app.toggle_deck_focus` |
| `Ctrl+B` | Focus Previous Deck Panel | `ace.keymaps.app.toggle_deck_focus_reverse` |
| `Ctrl+Shift+F / >` | Swap Deck Panel Next | `ace.keymaps.app.swap_deck_panel_next` |
| `Ctrl+Shift+B / <` | Swap Deck Panel Previous | `ace.keymaps.app.swap_deck_panel_prev` |
| `Ctrl+Shift+D / Ctrl+X` | Close Deck Panel | `ace.keymaps.app.close_deck_panel` |
| `Ctrl+T` | Turn Deck Layout | `ace.keymaps.app.turn_deck_layout` |
| `}` | Grow Deck Panel | `ace.keymaps.app.grow_deck_panel` |
| `{` | Shrink Deck Panel | `ace.keymaps.app.shrink_deck_panel` |
| `Ctrl+S` | Toggle node rail | `ace.keymaps.app.toggle_node_panel` |
| `E` | Edit Panel | `ace.keymaps.app.edit_panel` |
| `Enter` | Act on agent | `ace.keymaps.app.act_on_agent` |
| `Unbound` | Go to Patch | `ace.keymaps.app.jump_to_agent_patch` |
| `a` | Artifact Files | `ace.keymaps.app.open_artifact_files` |
| `D` | Toggle Attempt View | `ace.keymaps.app.toggle_attempt_view` |
| `d` | Toggle Agent Header | `ace.keymaps.app.toggle_agent_header` |
| `.` | Toggle Jump Panel | `ace.keymaps.app.toggle_agent_jump_panel` |
| `I` | Show/Hide Non-Run Agents | `ace.keymaps.app.toggle_hide_non_run_agents` |
| `U` | Toggle Agent Unread | `ace.keymaps.app.toggle_agent_unread` |
| `N` | Edit Agent Tribe | `ace.keymaps.app.edit_agent_tribe` |
| `J` | Next Panel | `ace.keymaps.app.focus_next_agent_panel` |
| `K` | Prev Panel | `ace.keymaps.app.focus_prev_agent_panel` |
| `J` | Next Panel | `ace.keymaps.app.focus_next_service_panel` |
| `K` | Prev Panel | `ace.keymaps.app.focus_prev_service_panel` |
| `o` | Choose Grouping | `ace.keymaps.app.choose_agent_grouping` |
| `o` | Cycle Grouping | `ace.keymaps.app.cycle_grouping_mode` |
| `O` | Cycle Grouping Rev | `ace.keymaps.app.cycle_grouping_mode_reverse` |
| `V` | Agent Run Log | `ace.keymaps.app.show_agent_run_log` |
| `V` | Agent Metadata | `ace.keymaps.app.view_agent_metadata` |
| `;` | Command Palette | `ace.keymaps.app.open_command_palette` |
| `:` | Command Line | `ace.keymaps.app.open_command_line` |
| `Ctrl+L` | Dismiss Toasts | `ace.keymaps.app.dismiss_toasts` |
## Command Line panel

| Default key | Action | Configuration |
| --- | --- | --- |
| `Ctrl+T` | Full Height | `ace.keymaps.command_line.toggle_full_height` |
| `Ctrl+L` | Clear Transcript | `ace.keymaps.command_line.clear_transcript` |
| `Ctrl+D` | Scroll Output Down | `ace.keymaps.command_line.scroll_transcript_down` |
| `Ctrl+U` | Scroll Output Up | `ace.keymaps.command_line.scroll_transcript_up` |
| `escape` | Hide Panel | `ace.keymaps.command_line.hide_panel` |
| `j / down` | Next Block | `ace.keymaps.command_line.block_next` |
| `k / up` | Previous Block | `ace.keymaps.command_line.block_prev` |
| `g` | First Block | `ace.keymaps.command_line.block_first` |
| `G / Shift+G` | Last Block | `ace.keymaps.command_line.block_last` |
| `o / Enter` | Expand Block | `ace.keymaps.command_line.block_toggle_expand` |
| `v` | Block Pager | `ace.keymaps.command_line.block_pager` |
| `K / Shift+K` | Kill Block | `ace.keymaps.command_line.block_kill` |
| `r` | Rerun Block | `ace.keymaps.command_line.block_rerun` |
| `R / Shift+R` | Rerun Block with -y | `ace.keymaps.command_line.block_rerun_confirm` |
| `e` | Edit Block | `ace.keymaps.command_line.block_edit` |
| `y` | Copy Block Output | `ace.keymaps.command_line.block_copy_output` |
| `Y / Shift+Y` | Copy Block Command | `ace.keymaps.command_line.block_copy_command` |
| `p` | Block in Procs | `ace.keymaps.command_line.block_procs` |
| `x` | Remove Block | `ace.keymaps.command_line.block_remove` |
| `i / a / :` | Focus Input | `ace.keymaps.command_line.block_focus_input` |
## Config hub

| Default key | Action | Configuration |
| --- | --- | --- |
| `0` | Select Sub-tab by Number | `ace.keymaps.config.select_subtab` |
## Gate modal

| Default key | Action | Configuration |
| --- | --- | --- |
| `j` | Next control | `ace.keymaps.gate.next_control` |
| `k` | Previous control | `ace.keymaps.gate.previous_control` |
| `Space` | Toggle option | `ace.keymaps.gate.toggle_option` |
| `Enter` | Submit primary | `ace.keymaps.gate.submit_primary` |
| `Ctrl+S` | Submit | `ace.keymaps.gate.submit_branch` |
| `i` | Open inputs | `ace.keymaps.gate.open_inputs` |
| `l / right` | Next decision choice | `ace.keymaps.gate.decision_next` |
| `h / left` | Previous decision choice | `ace.keymaps.gate.decision_prev` |
| `r` | Reset decision row | `ace.keymaps.gate.decision_reset` |
| `R` | Reset all decisions | `ace.keymaps.gate.decision_reset_all` |
| `z` | Decision sheet | `ace.keymaps.gate.decision_zoom` |
## Gate input panel

| Default key | Action | Configuration |
| --- | --- | --- |
| `Tab` | Next input | `ace.keymaps.gate.next_input` |
| `Shift+Tab` | Previous input | `ace.keymaps.gate.previous_input` |
## Machines pane

| Default key | Action | Configuration |
| --- | --- | --- |
| `j / down / Ctrl+N` | Next | `ace.keymaps.machines.next_option` |
| `k / up / Ctrl+P` | Previous | `ace.keymaps.machines.prev_option` |
| `/` | Filter | `ace.keymaps.machines.focus_filter` |
| `c` | Connect | `ace.keymaps.machines.connect_machine` |
| `s` | Check Status | `ace.keymaps.machines.check_status` |
| `r` | Repair | `ace.keymaps.machines.repair_machine` |
| `R` | Rename | `ace.keymaps.machines.rename_machine` |
| `x` | Remove | `ace.keymaps.machines.remove_machine` |
| `Enter` | Show Agents | `ace.keymaps.machines.show_agents` |
| `f` | Filter Agents | `ace.keymaps.machines.show_agents_filter` |
| `y` | Copy Command | `ace.keymaps.machines.copy_command` |
| `U` | Reload | `ace.keymaps.machines.reload` |
## Memory panel

| Default key | Action | Configuration |
| --- | --- | --- |
| `j` | Next Note | `ace.keymaps.memory.next_note` |
| `k` | Previous Note | `ace.keymaps.memory.prev_note` |
| `g` | First Note | `ace.keymaps.memory.first_note` |
| `G` | Last Note | `ace.keymaps.memory.last_note` |
| `Space` | Expand/Collapse Web | `ace.keymaps.memory.toggle_web` |
| `s` | Next Strand | `ace.keymaps.memory.next_strand` |
| `S` | Previous Strand | `ace.keymaps.memory.prev_strand` |
| `Ctrl+D` | Scroll Body Down | `ace.keymaps.memory.scroll_body_down` |
| `Ctrl+U` | Scroll Body Up | `ace.keymaps.memory.scroll_body_up` |
| `/` | Filter | `ace.keymaps.memory.filter_notes` |
| `>` | Toggle Body Match | `ace.keymaps.memory.toggle_body_filter` |
| `Tab` | Next Link Chip | `ace.keymaps.memory.next_link` |
| `Shift+Tab` | Previous Link Chip | `ace.keymaps.memory.prev_link` |
| `Enter / l` | Follow Link | `ace.keymaps.memory.follow_link` |
| `backspace / h` | Travel Back | `ace.keymaps.memory.travel_back` |
| `p` | Next Scope | `ace.keymaps.memory.next_scope` |
| `P` | Previous Scope | `ace.keymaps.memory.prev_scope` |
| `Ctrl+P` | Pick Scope | `ace.keymaps.memory.pick_scope` |
| `a` | Add Note | `ace.keymaps.memory.add_note` |
| `e` | Edit Note | `ace.keymaps.memory.edit_note` |
| `d` | Delete Note | `ace.keymaps.memory.delete_note` |
| `I` | Publish | `ace.keymaps.memory.publish` |
| `o` | Open in Editor | `ace.keymaps.memory.open_source` |
| `Z` | Open in Viewer | `ace.keymaps.memory.open_viewer` |
| `H` | History | `ace.keymaps.memory.open_history` |
| `C` | Changes | `ace.keymaps.memory.open_changes` |
| `(` | Older Version | `ace.keymaps.memory.history_older` |
| `)` | Newer Version | `ace.keymaps.memory.history_newer` |
| `{` | First Version | `ace.keymaps.memory.history_first` |
| `}` | Now | `ace.keymaps.memory.history_now` |
| `=` | Toggle Diff | `ace.keymaps.memory.history_toggle_diff` |
| `@` | Timeline Lens | `ace.keymaps.memory.history_timeline` |
| `b` | Set Compare Base | `ace.keymaps.memory.history_compare_base` |
| `.` | Reveal Hidden Versions | `ace.keymaps.memory.history_toggle_hidden` |
| `D` | Deleted Subjects | `ace.keymaps.memory.toggle_deleted` |
| `m` | Mark Reviewed | `ace.keymaps.memory.mark_reviewed` |
| `y` | Copy Body | `ace.keymaps.memory.copy_body` |
| `Y` | Copy Source Path | `ace.keymaps.memory.copy_source_path` |
| `r` | Refresh | `ace.keymaps.memory.refresh` |
| `?` | Help | `ace.keymaps.memory.help` |
## Projects pane

| Default key | Action | Configuration |
| --- | --- | --- |
| `j / down / Ctrl+N` | Next | `ace.keymaps.projects.next_option` |
| `k / up / Ctrl+P` | Previous | `ace.keymaps.projects.prev_option` |
| `n` | New Project | `ace.keymaps.projects.new_project` |
| `/` | Filter | `ace.keymaps.projects.focus_filter` |
| `]` | Next Sub-tab | `ace.keymaps.projects.cycle_subtab` |
| `[` | Previous Sub-tab | `ace.keymaps.projects.cycle_subtab_reverse` |
| `m` | Mark | `ace.keymaps.projects.toggle_project_mark` |
| `u` | Unmark All | `ace.keymaps.projects.clear_project_marks` |
| `e` | Edit | `ace.keymaps.projects.edit_project_spec` |
| `A` | Aliases | `ace.keymaps.projects.edit_project_aliases` |
| `a` | Enable | `ace.keymaps.projects.enable_project` |
| `d` | Disable | `ace.keymaps.projects.disable_project` |
| `Ctrl+D` | Delete | `ace.keymaps.projects.delete_project` |
| `F` | Force | `ace.keymaps.projects.force_current_state_change` |
| `Enter` | Default | `ace.keymaps.projects.default_project_action` |
| `R` | Reload | `ace.keymaps.projects.reload` |
| `r` | Project Repos | `ace.keymaps.projects.show_project_repos` |
| `w` | Project Workspaces | `ace.keymaps.projects.show_project_workspaces` |
| `'` | Jump | `ace.keymaps.projects.jump_to_entry` |
| `c` | Set Current | `ace.keymaps.projects.set_current_project` |
| `i` | Initialize | `ace.keymaps.projects.initialize_project` |
| `I` | Initialize All | `ace.keymaps.projects.initialize_all_projects` |
| `?` | Help | `ace.keymaps.projects.help` |
| `s` | Show New Project | `ace.keymaps.projects.show_new_project` |
## Projects inventory

| Default key | Action | Configuration |
| --- | --- | --- |
| `j / down / Ctrl+N` | Next | `ace.keymaps.projects.next_option` |
| `k / up / Ctrl+P` | Previous | `ace.keymaps.projects.prev_option` |
| `/` | Filter | `ace.keymaps.projects.focus_filter` |
| `p` | Pick Project | `ace.keymaps.projects.pick_project` |
| `R` | Reload | `ace.keymaps.projects.reload` |
| `'` | Jump | `ace.keymaps.projects.jump_to_entry` |
| `escape` | Clear Project | `ace.keymaps.projects.clear_project_filter` |
| `?` | Help | `ace.keymaps.projects.help` |
## Snippets panel

| Default key | Action | Configuration |
| --- | --- | --- |
| `j` | Next Snippet | `ace.keymaps.snippets.next_snippet` |
| `k` | Previous Snippet | `ace.keymaps.snippets.prev_snippet` |
| `g` | First Snippet | `ace.keymaps.snippets.first_snippet` |
| `G` | Last Snippet | `ace.keymaps.snippets.last_snippet` |
| `Ctrl+D` | Scroll Template Down | `ace.keymaps.snippets.scroll_template_down` |
| `Ctrl+U` | Scroll Template Up | `ace.keymaps.snippets.scroll_template_up` |
| `/` | Filter | `ace.keymaps.snippets.filter_snippets` |
| `.` | Toggle Body Match | `ace.keymaps.snippets.toggle_body_filter` |
| `Tab` | Next Relation Chip | `ace.keymaps.snippets.next_relation` |
| `Shift+Tab` | Previous Relation Chip | `ace.keymaps.snippets.prev_relation` |
| `Enter / l` | Follow Relation | `ace.keymaps.snippets.follow_relation` |
| `backspace / h` | Travel Back | `ace.keymaps.snippets.travel_back` |
| `p` | Next Project | `ace.keymaps.snippets.next_project` |
| `P` | Previous Project | `ace.keymaps.snippets.prev_project` |
| `a` | Add Snippet | `ace.keymaps.snippets.add_snippet` |
| `e` | Edit Snippet | `ace.keymaps.snippets.edit_snippet` |
| `d` | Delete Snippet | `ace.keymaps.snippets.delete_snippet` |
| `o` | Open in Editor | `ace.keymaps.snippets.open_source` |
| `Z` | Open in Viewer | `ace.keymaps.snippets.open_viewer` |
| `y` | Copy Template | `ace.keymaps.snippets.copy_template` |
| `Y` | Copy Source Path | `ace.keymaps.snippets.copy_source_path` |
| `r` | Refresh | `ace.keymaps.snippets.refresh` |
| `?` | Help | `ace.keymaps.snippets.help` |
## Statistics pane

| Default key | Action | Configuration |
| --- | --- | --- |
| `[` | Previous View | `ace.keymaps.statistics.prev_view` |
| `]` | Next View | `ace.keymaps.statistics.next_view` |
| `0` | Select View by Number | `ace.keymaps.statistics.select_view` |
| `'` | Jump | `ace.keymaps.statistics.jump_to_entry` |
| `t` | Time Range | `ace.keymaps.statistics.cycle_range` |
| `T` | Previous Time Range | `ace.keymaps.statistics.cycle_range_reverse` |
| `c` | Custom Range | `ace.keymaps.statistics.custom_range` |
| `g` | Group By | `ace.keymaps.statistics.cycle_group` |
| `p` | Project Filter | `ace.keymaps.statistics.cycle_project_filter` |
| `P` | Previous Project Filter | `ace.keymaps.statistics.cycle_project_filter_reverse` |
| `x` | Focus Macro | `ace.keymaps.statistics.focus_macro` |
| `X` | Clear Macro Focus | `ace.keymaps.statistics.clear_macro_focus` |
| `Ctrl+D` | Scroll Down | `ace.keymaps.statistics.scroll_down` |
| `Ctrl+U` | Scroll Up | `ace.keymaps.statistics.scroll_up` |
| `r` | Refresh | `ace.keymaps.statistics.refresh` |
| `?` | Help | `ace.keymaps.statistics.help` |
## Tools pane

| Default key | Action | Configuration |
| --- | --- | --- |
| `j / down / Ctrl+N` | Next | `ace.keymaps.tool_runs.next_option` |
| `k / up / Ctrl+P` | Previous | `ace.keymaps.tool_runs.prev_option` |
| `/` | Filter | `ace.keymaps.tool_runs.focus_filter` |
| `]` | Next View | `ace.keymaps.tool_runs.cycle_subtab` |
| `[` | Previous View | `ace.keymaps.tool_runs.cycle_subtab_reverse` |
| `A` | All Projects | `ace.keymaps.tool_runs.toggle_scope` |
| `Enter` | Detail | `ace.keymaps.tool_runs.focus_detail` |
| `a` | Open Agent | `ace.keymaps.tool_runs.jump_to_agent` |
| `v` | Open Log | `ace.keymaps.tool_runs.open_log` |
| `y` | Copy Run ID | `ace.keymaps.tool_runs.copy_run_id` |
| `s` | Stop | `ace.keymaps.tool_runs.stop_run` |
| `r` | Run | `ace.keymaps.tool_runs.run_tool` |
| `R` | Reload | `ace.keymaps.tool_runs.reload` |
## Fold mode

| Default key | Action | Configuration |
| --- | --- | --- |
| `zc` | Cycle stitches | `ace.keymaps.modes.fold_mode.keys.cycle_stitches` |
| `zh` | Cycle hooks | `ace.keymaps.modes.fold_mode.keys.cycle_hooks` |
| `zm` | Cycle mentors | `ace.keymaps.modes.fold_mode.keys.cycle_mentors` |
| `zt` | Cycle timestamps | `ace.keymaps.modes.fold_mode.keys.cycle_timestamps` |
| `zd` | Cycle deltas | `ace.keymaps.modes.fold_mode.keys.cycle_deltas` |
| `zC` | Toggle stitches | `ace.keymaps.modes.fold_mode.keys.toggle_stitches` |
| `zH` | Toggle hooks | `ace.keymaps.modes.fold_mode.keys.toggle_hooks` |
| `zM` | Toggle mentors | `ace.keymaps.modes.fold_mode.keys.toggle_mentors` |
| `zT` | Toggle timestamps | `ace.keymaps.modes.fold_mode.keys.toggle_timestamps` |
| `zD` | Toggle deltas | `ace.keymaps.modes.fold_mode.keys.toggle_deltas` |
| `zz` | Cycle all | `ace.keymaps.modes.fold_mode.keys.cycle_all` |
| `zZ` | Toggle all | `ace.keymaps.modes.fold_mode.keys.toggle_all` |
| `zL` | Expand all groups | `ace.keymaps.modes.fold_mode.keys.expand_all_groups` |
| `z1` | Set level 1 | `ace.keymaps.modes.fold_mode.keys.set_level_1` |
| `z2` | Set level 2 | `ace.keymaps.modes.fold_mode.keys.set_level_2` |
| `z3` | Set level 3 | `ace.keymaps.modes.fold_mode.keys.set_level_3` |
| `zz` | Cycle level | `ace.keymaps.modes.fold_mode.keys.agents.cycle_level` |
| `zZ` | Toggle all | `ace.keymaps.modes.fold_mode.keys.agents.toggle_all` |
| `za` | Cycle section | `ace.keymaps.modes.fold_mode.keys.agents.cycle_section` |
| `zA` | Toggle section | `ace.keymaps.modes.fold_mode.keys.agents.toggle_section` |
| `z1` | Set level 1 | `ace.keymaps.modes.fold_mode.keys.agents.set_level_1` |
| `z2` | Set level 2 | `ace.keymaps.modes.fold_mode.keys.agents.set_level_2` |
| `z3` | Set level 3 | `ace.keymaps.modes.fold_mode.keys.agents.set_level_3` |
| `z4` | Set level 4 | `ace.keymaps.modes.fold_mode.keys.agents.set_level_4` |
## Copy mode

| Default key | Action | Configuration |
| --- | --- | --- |
| `%%` | Raw | `ace.keymaps.modes.copy_mode.keys.patches.raw` |
| `%!` | With snapshot | `ace.keymaps.modes.copy_mode.keys.patches.with_snapshot` |
| `%b` | Bug | `ace.keymaps.modes.copy_mode.keys.patches.bug` |
| `%c` | Pr number | `ace.keymaps.modes.copy_mode.keys.patches.pr_number` |
| `%n` | Name | `ace.keymaps.modes.copy_mode.keys.patches.name` |
| `%l` | Link | `ace.keymaps.modes.copy_mode.keys.patches.link` |
| `%p` | Spec | `ace.keymaps.modes.copy_mode.keys.patches.spec` |
| `%@` | Reference | `ace.keymaps.modes.copy_mode.keys.patches.reference` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.patches.snapshot` |
| `%%` | Sha | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.sha` |
| `%@` | Reference | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.reference` |
| `%!` | Handoff | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.handoff` |
| `%m` | Message | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.message` |
| `%r` | Repo sha | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.repo_sha` |
| `%p` | Plan | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.plan` |
| `%l` | Link | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.link` |
| `%J` | Json | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.json` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.artifacts_stitches.snapshot` |
| `%%` | Bead id | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.bead_id` |
| `%@` | Reference | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.reference` |
| `%!` | Handoff | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.handoff` |
| `%d` | Design | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.design` |
| `%p` | Path | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.path` |
| `%t` | Title | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.title` |
| `%b` | Body | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.body` |
| `%l` | Link | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.link` |
| `%J` | Json | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.json` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.artifacts_plans.snapshot` |
| `%@` | Reference | `ace.keymaps.modes.copy_mode.keys.artifacts_documents.reference` |
| `%!` | Handoff | `ace.keymaps.modes.copy_mode.keys.artifacts_documents.handoff` |
| `%p` | Path | `ace.keymaps.modes.copy_mode.keys.artifacts_documents.path` |
| `%t` | Title | `ace.keymaps.modes.copy_mode.keys.artifacts_documents.title` |
| `%b` | Body | `ace.keymaps.modes.copy_mode.keys.artifacts_documents.body` |
| `%l` | Link | `ace.keymaps.modes.copy_mode.keys.artifacts_documents.link` |
| `%J` | Json | `ace.keymaps.modes.copy_mode.keys.artifacts_documents.json` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.artifacts_documents.snapshot` |
| `%%` | Id | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.id` |
| `%@` | Reference | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.reference` |
| `%!` | Handoff | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.handoff` |
| `%t` | Title | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.title` |
| `%b` | Body | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.body` |
| `%d` | Design | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.design` |
| `%l` | Link | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.link` |
| `%J` | Json | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.json` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.snapshot` |
| `%u` | Bug | `ace.keymaps.modes.copy_mode.keys.artifacts_beads.bug` |
| `%%` | Contents | `ace.keymaps.modes.copy_mode.keys.artifacts_other.contents` |
| `%@` | Reference | `ace.keymaps.modes.copy_mode.keys.artifacts_other.reference` |
| `%L` | Link | `ace.keymaps.modes.copy_mode.keys.artifacts_other.link` |
| `%!` | Handoff | `ace.keymaps.modes.copy_mode.keys.artifacts_other.handoff` |
| `%p` | Path | `ace.keymaps.modes.copy_mode.keys.artifacts_other.path` |
| `%o` | Source | `ace.keymaps.modes.copy_mode.keys.artifacts_other.source` |
| `%l` | Label | `ace.keymaps.modes.copy_mode.keys.artifacts_other.label` |
| `%j` | Json | `ace.keymaps.modes.copy_mode.keys.artifacts_other.json` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.artifacts_other.snapshot` |
| `%c` | Chat | `ace.keymaps.modes.copy_mode.keys.agents.chat` |
| `%E` | File path | `ace.keymaps.modes.copy_mode.keys.agents.file_path` |
| `%n` | Name | `ace.keymaps.modes.copy_mode.keys.agents.name` |
| `%p` | Prompt | `ace.keymaps.modes.copy_mode.keys.agents.prompt` |
| `%@` | Reference | `ace.keymaps.modes.copy_mode.keys.agents.reference` |
| `%!` | Handoff | `ace.keymaps.modes.copy_mode.keys.agents.handoff` |
| `%l` | Link | `ace.keymaps.modes.copy_mode.keys.agents.link` |
| `%j` | Json | `ace.keymaps.modes.copy_mode.keys.agents.json` |
| `%d` | Artifacts dir | `ace.keymaps.modes.copy_mode.keys.agents.artifacts_dir` |
| `%r` | Tool run id | `ace.keymaps.modes.copy_mode.keys.agents.tool_run_id` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.agents.snapshot` |
| `%@` | Reference | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.reference` |
| `%!` | Handoff | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.handoff` |
| `%n` | Name | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.name` |
| `%l` | Link | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.link` |
| `%p` | Path | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.path` |
| `%c` | Chat | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.chat` |
| `%P` | Prompt | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.prompt` |
| `%j` | Json | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.json` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.artifacts_agents.snapshot` |
| `%o` | Visible | `ace.keymaps.modes.copy_mode.keys.axe.visible` |
| `%O` | Full | `ace.keymaps.modes.copy_mode.keys.axe.full` |
| `%s` | Snapshot | `ace.keymaps.modes.copy_mode.keys.axe.snapshot` |
## Leader mode

| Default key | Action | Configuration |
| --- | --- | --- |
| `,,` | Repeat last | `ace.keymaps.modes.leader_mode.keys.repeat_last` |
| `,/` | Search forward | `ace.keymaps.modes.leader_mode.keys.search_forward` |
| `,!` | Run cmd | `ace.keymaps.modes.leader_mode.keys.run_cmd` |
| `,R` | Runners | `ace.keymaps.modes.leader_mode.keys.runners` |
| `,r` | Revert agent | `ace.keymaps.modes.leader_mode.keys.revert_agent` |
| `,M` | Kill mentors | `ace.keymaps.modes.leader_mode.keys.kill_mentors` |
| `,C` | Review mentors | `ace.keymaps.modes.leader_mode.keys.review_mentors` |
| `,h` | Agent home | `ace.keymaps.modes.leader_mode.keys.agent_home` |
| `, Space` | Agent from cl | `ace.keymaps.modes.leader_mode.keys.agent_from_cl` |
| `,H` | Collapse fold by hint | `ace.keymaps.modes.leader_mode.keys.collapse_fold_by_hint` |
| `,j` | Jump to next unread done agent | `ace.keymaps.modes.leader_mode.keys.jump_to_next_unread_done_agent` |
| `,J` | Jump to next stopped agent | `ace.keymaps.modes.leader_mode.keys.jump_to_next_stopped_agent` |
| `,y` | Full history refresh | `ace.keymaps.modes.leader_mode.keys.full_history_refresh` |
| `,u` | Mark all unread done agents read | `ace.keymaps.modes.leader_mode.keys.mark_all_unread_done_agents_read` |
| `,x` | Kill and edit | `ace.keymaps.modes.leader_mode.keys.kill_and_edit` |
| `,X` | Kill and edit last | `ace.keymaps.modes.leader_mode.keys.kill_and_edit_last` |
| `,c` | Clear comments | `ace.keymaps.modes.leader_mode.keys.clear_comments` |
| `,@` | Open prompt stash | `ace.keymaps.modes.leader_mode.keys.open_prompt_stash` |
| `,.` | Prompt history | `ace.keymaps.modes.leader_mode.keys.prompt_history` |
| `, Ctrl+G` | Prompt history edit first | `ace.keymaps.modes.leader_mode.keys.prompt_history_edit_first` |
| `,>` | Prompt history cancelled | `ace.keymaps.modes.leader_mode.keys.prompt_history_cancelled` |
| `,A` | Agent run log | `ace.keymaps.modes.leader_mode.keys.agent_run_log` |
| `,m` | Models panel | `ace.keymaps.modes.leader_mode.keys.models_panel` |
| `,U` | Update sase | `ace.keymaps.modes.leader_mode.keys.update_sase` |
| `,E` | Update everything | `ace.keymaps.modes.leader_mode.keys.update_everything` |
| `,B` | Capture agents repro | `ace.keymaps.modes.leader_mode.keys.capture_agents_repro` |
| `,T` | Toggle agents repro checks | `ace.keymaps.modes.leader_mode.keys.toggle_agents_repro_checks` |
| `,L` | Jump to last error | `ace.keymaps.modes.leader_mode.keys.jump_to_last_error` |
| `,a` | Toggle agents archive | `ace.keymaps.modes.leader_mode.keys.toggle_agents_archive` |
## Bang mode

| Default key | Action | Configuration |
| --- | --- | --- |
| `!!` | Run cmd | `ace.keymaps.modes.bang_mode.keys.run_cmd` |
| `!x` | Toggle axe | `ace.keymaps.modes.bang_mode.keys.toggle_axe` |
| `!e` | Toggle service enablement | `ace.keymaps.modes.bang_mode.keys.toggle_service_enablement` |
| `!o` | Mark pr origin | `ace.keymaps.modes.bang_mode.keys.mark_pr_origin` |
| `!R` | Start rewind | `ace.keymaps.modes.bang_mode.keys.start_rewind` |
## Bead issue mode

| Default key | Action | Configuration |
| --- | --- | --- |
| `bv` | View | `ace.keymaps.modes.bead_issue_mode.keys.view` |
| `be` | Edit | `ace.keymaps.modes.bead_issue_mode.keys.edit` |
| `bs` | Toggle state | `ace.keymaps.modes.bead_issue_mode.keys.toggle_state` |
| `bu` | Copy url | `ace.keymaps.modes.bead_issue_mode.keys.copy_url` |
| `ba` | Attach | `ace.keymaps.modes.bead_issue_mode.keys.attach` |
| `bc` | Create | `ace.keymaps.modes.bead_issue_mode.keys.create` |
