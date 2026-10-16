---
title: "ACE keymap configuration"
description: "Configuration behavior for SASE Admin Center and TUI keymaps."
---

# ACE keymap configuration

Configuration behavior for SASE Admin Center and TUI keymaps.

## `ace.keymaps`

All TUI keybindings are configurable. The `keymaps` section has focused modal and pane
scopes, app-wide bindings, and prefix-mode maps:

**`gate`** — Bindings active in the shared branch controls used by plan and custom gate
modals, plus the input panel those modals open when a selection needs typed input:

| Field                | Default     | Description                                                            |
| -------------------- | ----------- | ---------------------------------------------------------------------- |
| `next_control`       | `j`         | Focus the next branch control.                                         |
| `previous_control`   | `k`         | Focus the previous branch control.                                     |
| `toggle_option`      | `space`     | Toggle the focused option in an AND group.                             |
| `submit_primary`     | `enter`     | Submit the gate's declared primary branch.                             |
| `submit_branch`      | `ctrl+s`    | Submit the currently active branch and feedback.                       |
| `open_inputs`        | `i`         | Open the input panel for the focused option's note or declared fields. |
| `next_input`         | `tab`       | Focus the next field in the gate input panel.                          |
| `previous_input`     | `shift+tab` | Focus the previous field in the gate input panel.                      |
| `decision_next`      | `l,right`   | Next decision choice, or set yes.                                      |
| `decision_prev`      | `h,left`    | Previous decision choice, or set no.                                   |
| `decision_reset`     | `r`         | Reset the focused decision row to ★.                                   |
| `decision_reset_all` | `R`         | Reset every decision row to ★.                                         |
| `decision_zoom`      | `z`         | Toggle the full-width decision sheet (plans with decisions only).      |

Gate keys are scoped to the active modal and may overlap app-level bindings.
`open_inputs` is bound on the gate modal and opens the panel even when the selection
would otherwise submit immediately, unless the option takes no input. `next_input` and
`previous_input` dispatch only while that panel is open. `activate_control` remains
accepted as a deprecated alias for `submit_primary`.

**`config`** — Bindings active only while the Admin Center Config hub is focused. The
available actions are:

| Field           | Default | Description                                                                                      |
| --------------- | ------- | ------------------------------------------------------------------------------------------------ |
| `select_subtab` | `0`     | Arm numbered Config-child selection (`01`-`07` when Flags is visible, `01`-`06` when it is not). |

**`statistics`** — Bindings active only while the Admin Center Statistics pane is
focused. The available actions are:

| Field                          | Default                | Description                                                           |
| ------------------------------ | ---------------------- | --------------------------------------------------------------------- |
| `prev_view`                    | `left_square_bracket`  | Select the previous Statistics view.                                  |
| `next_view`                    | `right_square_bracket` | Select the next Statistics view.                                      |
| `select_view`                  | `0`                    | Arm `01`–`08` selection for a numbered Statistics view.               |
| `jump_to_entry`                | `apostrophe`           | Arm the same numbered-view selection used by `select_view`.           |
| `cycle_range`                  | `t`                    | Cycle to the next statistics time range.                              |
| `cycle_range_reverse`          | `T`                    | Cycle to the previous statistics time range.                          |
| `custom_range`                 | `c`                    | Enter a custom statistics time range.                                 |
| `cycle_group`                  | `g`                    | Cycle grouping in the Projects, Macros, or Perf view.                 |
| `cycle_project_filter`         | `p`                    | Cycle forward through All and the latest unfiltered project ranking.  |
| `cycle_project_filter_reverse` | `P`                    | Cycle backward through All and the latest unfiltered project ranking. |
| `focus_macro`                  | `x`                    | Focus one Macro in the Macros Statistics view.                        |
| `clear_macro_focus`            | `X`                    | Return the Macros Statistics view to all Macros.                      |
| `scroll_down`                  | `ctrl+d`               | Scroll the Statistics body down by half a page.                       |
| `scroll_up`                    | `ctrl+u`               | Scroll the Statistics body up by half a page.                         |
| `refresh`                      | `r`                    | Refresh the active view from its durable data sources.                |
| `help`                         | `question_mark`        | Open contextual Statistics help; the same key closes it.              |

Statistics keys may overlap app-level bindings because they are registered on the
focused pane, not globally.

**`glossary`** — Deprecated legacy bindings for the retired standalone Glossary panel,
accepted for one release for config-compatibility and always ignored: no defaults ship
for this scope and it builds no bindings. `sase doctor` warns when a loaded config layer
sets it explicitly. Move any customization to `ace.keymaps.memory` below — the Glossary
panel's browsing, relation-chip, and add/delete actions now live in the Memory panel,
opened the same way (`gG` / `Ctrl+G G`, seeded on the glossary term under the cursor).

**`memory`** — Bindings active only inside the
[Memory panel](../../ace.md#memory-panel), the browse-and-edit surface for notes, webs,
and strands opened from a prompt pane with `gm`, `Ctrl+G m`, `gG`, or `Ctrl+G G`. A
value may list more than one key, separated by commas:

| Field                   | Default             | Description                                                                                                    |
| ----------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------- |
| `next_note`             | `j`                 | Move the note rail cursor to the next note.                                                                    |
| `prev_note`             | `k`                 | Move the note rail cursor to the previous note.                                                                |
| `first_note`            | `g`                 | Jump to the first note.                                                                                        |
| `last_note`             | `G`                 | Jump to the last note.                                                                                         |
| `toggle_web`            | `space`             | Expand or collapse the selected memory web.                                                                    |
| `next_strand`           | `s`                 | Jump to the next strand in the selected memory web.                                                            |
| `prev_strand`           | `S`                 | Jump to the previous strand in the selected memory web.                                                        |
| `scroll_body_down`      | `ctrl+d`            | Scroll the note card down by half a page.                                                                      |
| `scroll_body_up`        | `ctrl+u`            | Scroll the note card up by half a page.                                                                        |
| `filter_notes`          | `slash`             | Filter notes by stem and description.                                                                          |
| `toggle_body_filter`    | `greater_than_sign` | Extend the active filter into note bodies.                                                                     |
| `next_link`             | `tab`               | Focus the next `PARENT`/`CHILDREN` (or `SEE ALSO`/`REFERENCED BY` on a mention strand) chip.                   |
| `prev_link`             | `shift+tab`         | Focus the previous link chip.                                                                                  |
| `follow_link`           | `enter,l`           | Travel to the focused chip's note or strand (or chip ① when none focused).                                     |
| `travel_back`           | `backspace,h`       | Walk back one step along the travel trail.                                                                     |
| `next_scope`            | `p`                 | Cycle forward through the memory scope ring.                                                                   |
| `prev_scope`            | `P`                 | Cycle backward through the memory scope ring.                                                                  |
| `pick_scope`            | `ctrl+p`            | Open the filterable scope picker.                                                                              |
| `add_note`              | `a`                 | Open the add-note form, or the add-strand form on a web row.                                                   |
| `edit_note`             | `e`                 | Open the edit form for the selected note's type/parent/description.                                            |
| `delete_note`           | `d`                 | Confirm and delete the selected note, or the selected strand.                                                  |
| `publish`               | `I`                 | Open the publish confirmation (`sase memory init`).                                                            |
| `open_source`           | `o`                 | Open the note or strand body in `$EDITOR`.                                                                     |
| `open_viewer`           | `Z`                 | Hand the source file to the artifact viewer.                                                                   |
| `open_history`          | `H`                 | Open the selection in the pager at the card's exact version and view (see `docs/reference/memory/history.md`). |
| `open_changes`          | `C`                 | Open or close the Changes lens (day-grouped changesets; see `docs/reference/memory/history.md`).               |
| `history_older`         | `(`                 | Step the memory card to the older version.                                                                     |
| `history_newer`         | `)`                 | Step the memory card to the newer version.                                                                     |
| `history_first`         | `{`                 | Step the memory card to the first version.                                                                     |
| `history_now`           | `}`                 | Return the memory card to now.                                                                                 |
| `history_toggle_diff`   | `=`                 | Toggle the memory card word-diff view (sticky for the pane session).                                           |
| `history_timeline`      | `@`                 | Open or close the Timeline lens (the rail becomes the subject's version timeline).                             |
| `history_compare_base`  | `b`                 | Set or clear the Timeline lens compare base (pager hand-off carries it).                                       |
| `history_toggle_hidden` | `.`                 | Reveal hidden versions in the Timeline lens (chip shortcuts are inert there).                                  |
| `toggle_deleted`        | `D`                 | Show or hide the DELETED group of tombstoned subjects (see `docs/reference/memory/history.md`).                |
| `mark_reviewed`         | `m`                 | Mark the Changes lens scope(s) reviewed through the newest changeset (see `docs/reference/memory/history.md`). |
| `copy_body`             | `y`                 | Copy the note or strand body to the clipboard.                                                                 |
| `copy_source_path`      | `Y`                 | Copy the source path to the clipboard.                                                                         |
| `refresh`               | `r`                 | Re-read the current scope.                                                                                     |
| `help`                  | `question_mark`     | Open the panel-scoped help overlay.                                                                            |

Like gate and statistics keys, memory keys are scoped to the panel and may overlap
app-level bindings. `.` then `1`–`9` follows a numbered link or relation chip in the
Notes lens; that prefix is a fixed pane key. `history_toggle_hidden` (default `.`)
re-routes the same physical key to the hidden-versions toggle inside the Timeline lens,
where chip shortcuts are inert — see the `on_key` ordering in the Memory pane. A user
override of `history_toggle_hidden` changes only the Timeline lens key, never the Notes
chip prefix. `greater_than_sign` (`>`) remains a valid configurable key. On the embedded
Admin Center Config sub-tab, bare digits remain top-level Admin Center tab selectors.

**`snippets`** — Bindings active only inside the
[Snippets panel](../../ace.md#snippets-panel), the browse-and-edit surface opened from a
prompt pane with `gT` or `Ctrl+G T`. A value may list more than one key, separated by
commas:

| Field                  | Default         | Description                                                         |
| ---------------------- | --------------- | ------------------------------------------------------------------- |
| `next_snippet`         | `j`             | Move the trigger-list cursor to the next snippet.                   |
| `prev_snippet`         | `k`             | Move the trigger-list cursor to the previous snippet.               |
| `first_snippet`        | `g`             | Jump to the first snippet.                                          |
| `last_snippet`         | `G`             | Jump to the last snippet.                                           |
| `scroll_template_down` | `ctrl+d`        | Scroll the template card down by half a page.                       |
| `scroll_template_up`   | `ctrl+u`        | Scroll the template card up by half a page.                         |
| `filter_snippets`      | `slash`         | Filter triggers and source labels.                                  |
| `toggle_body_filter`   | `full_stop`     | Extend the active filter into raw and composed bodies.              |
| `next_relation`        | `tab`           | Focus the next `CALLS` / `CALLED BY` chip.                          |
| `prev_relation`        | `shift+tab`     | Focus the previous relation chip.                                   |
| `follow_relation`      | `enter,l`       | Travel to the focused chip's trigger (or chip ① when none focused). |
| `travel_back`          | `backspace,h`   | Walk back one step along the travel trail.                          |
| `next_project`         | `p`             | Cycle forward through the enabled-project ring.                     |
| `prev_project`         | `P`             | Cycle backward through the enabled-project ring.                    |
| `add_snippet`          | `a`             | Open the add-snippet form.                                          |
| `edit_snippet`         | `e`             | Edit the selected config snippet, or open macro source.             |
| `delete_snippet`       | `d`             | Confirm and delete the selected writable snippet.                   |
| `open_source`          | `o`             | Open the source in `$EDITOR`.                                       |
| `open_viewer`          | `Z`             | Hand the source file to the artifact viewer.                        |
| `copy_template`        | `y`             | Copy the raw template to the clipboard.                             |
| `copy_source_path`     | `Y`             | Copy the source path to the clipboard.                              |
| `refresh`              | `r`             | Re-read the current project's snippets.                             |
| `help`                 | `question_mark` | Open the panel-scoped help overlay.                                 |

Like gate, statistics, and memory keys, snippets keys are scoped to the panel and may
overlap app-level bindings. Snippets still uses bare `1`–`9` for numbered chips and
keeps `.` (`full_stop`) as the default body-filter toggle.

**`projects`** — One keymap for the Admin Center
[Projects tab](../../ace.md#projects-tab). The Projects sub-tab uses every field except
`pick_project` and `clear_project_filter`. Repos and Workspaces use `next_option`,
`prev_option`, `focus_filter`, `jump_to_entry`, `pick_project`, `clear_project_filter`,
`reload`, `help`, and the sub-tab cycle; the other actions, including `new_project`, are
inactive there. `[` / `]` still cycle sub-tabs from a focused filter. A value may list
more than one key, separated by commas:

| Field                        | Default                | Description                                                           |
| ---------------------------- | ---------------------- | --------------------------------------------------------------------- |
| `next_option`                | `j,down,ctrl+n`        | Move selection to the next row.                                       |
| `prev_option`                | `k,up,ctrl+p`          | Move selection to the previous row.                                   |
| `new_project`                | `n`                    | Open the New Project wizard on the Projects sub-tab.                  |
| `focus_filter`               | `slash`                | Filter the active sub-tab.                                            |
| `cycle_subtab`               | `right_square_bracket` | Cycle to the next sub-tab (Projects, Repos, Workspaces).              |
| `cycle_subtab_reverse`       | `left_square_bracket`  | Cycle to the previous sub-tab.                                        |
| `toggle_project_mark`        | `m`                    | Toggle the mark on the highlighted project.                           |
| `clear_project_marks`        | `u`                    | Clear all marks.                                                      |
| `edit_project_spec`          | `e`                    | Edit the highlighted project's ProjectSpec in `$EDITOR`.              |
| `edit_project_aliases`       | `A`                    | Edit the highlighted project's aliases.                               |
| `enable_project`             | `a`                    | Enable the highlighted project or marked set.                         |
| `disable_project`            | `d`                    | Disable the highlighted project or marked set.                        |
| `delete_project`             | `ctrl+d`               | Delete the highlighted or marked SASE project directories.            |
| `force_current_state_change` | `F`                    | Force the last blocked disable after confirming live-work checks.     |
| `default_project_action`     | `enter`                | Run the highlighted project's default lifecycle action.               |
| `reload`                     | `R`                    | Reload records or the current inventory.                              |
| `show_project_repos`         | `r`                    | Show repos pre-filtered to the highlighted project.                   |
| `show_project_workspaces`    | `w`                    | Show workspaces pre-filtered to the highlighted project.              |
| `jump_to_entry`              | `apostrophe`           | Jump to a row via adaptive hints, within the active sub-tab only.     |
| `pick_project`               | `p`                    | Open the shared project picker on the Repos or Workspaces sub-tab.    |
| `clear_project_filter`       | `escape`               | Clear an inventory project filter.                                    |
| `set_current_project`        | `c`                    | Make the highlighted project [current](../../ace.md#current-project). |
| `initialize_project`         | `i`                    | Initialize the highlighted project or marked set.                     |
| `initialize_all_projects`    | `I`                    | Initialize every enabled project (`sase init --all`).                 |
| `help`                       | `question_mark`        | Open contextual Projects help.                                        |
| `show_new_project`           | `s`                    | Show a newly added project hidden by the current filter.              |

Like gate, statistics, and memory keys, Projects-tab keys are scoped to the pane and may
overlap app-level bindings. `new_project` is inactive while the project filter is
focused, so `n` stays available as text. `show_new_project` is inactive unless a newly
added project is hidden by the current filter, and while that filter is focused.
`pick_project` and `clear_project_filter` apply on Repos and Workspaces only.

**`machines`** — focused Admin Center Machines-tab keybindings. These bindings are
scoped to the Machines pane and do not become app-level sase's TUI shortcuts.

| Field                | Default         | Action                                                                                 |
| -------------------- | --------------- | -------------------------------------------------------------------------------------- |
| `next_option`        | `j,down,ctrl+n` | Select the next machine row.                                                           |
| `prev_option`        | `k,up,ctrl+p`   | Select the previous machine row.                                                       |
| `focus_filter`       | `slash`         | Focus the machine filter input.                                                        |
| `connect_machine`    | `c`             | Show the persistent Connect flow.                                                      |
| `check_status`       | `s`             | Run a bounded authenticated status check for the selection.                            |
| `repair_machine`     | `r`             | Show repair guidance for the selected remote machine.                                  |
| `rename_machine`     | `R`             | Show the rename command for the selected remote machine.                               |
| `remove_machine`     | `x`             | Show removal guidance for the selected remote machine.                                 |
| `show_agents`        | `enter`         | Open the selected machine's agent tab (or filter Agents when the tab strip is hidden). |
| `show_agents_filter` | `f`             | Open Agents filtered to the selected machine in all cases.                             |
| `copy_command`       | `y`             | Copy the current Machines action command.                                              |
| `reload`             | `U`             | Reload the machine inventory.                                                          |

**`tool_runs`** — focused Admin Center [Tools-tab](../../ace.md#tools-tab) keybindings
(Runs, Failures, and Catalog views). These bindings are scoped to the Tools pane and do
not become app-level sase's TUI shortcuts. A value may list more than one key, separated
by commas:

| Field                  | Default                | Action                                               |
| ---------------------- | ---------------------- | ---------------------------------------------------- |
| `next_option`          | `j,down,ctrl+n`        | Select the next run, group, or catalog row.          |
| `prev_option`          | `k,up,ctrl+p`          | Select the previous run, group, or catalog row.      |
| `focus_filter`         | `slash`                | Focus the Runs filter input.                         |
| `cycle_subtab`         | `right_square_bracket` | Cycle to the next sub-tab (Runs, Failures, Catalog). |
| `cycle_subtab_reverse` | `left_square_bracket`  | Cycle to the previous sub-tab.                       |
| `toggle_scope`         | `A`                    | Toggle between the current project and all projects. |
| `focus_detail`         | `enter`                | Focus the selected run's detail.                     |
| `jump_to_agent`        | `a`                    | Jump to the owning Agents-tab row.                   |
| `open_log`             | `v`                    | Open the retained run log in the pager.              |
| `copy_run_id`          | `y`                    | Copy the selected run id.                            |
| `stop_run`             | `s`                    | Stop the focused live run (with confirmation).       |
| `run_tool`             | `r`                    | Run the focused catalog tool (with confirmation).    |
| `reload`               | `R`                    | Reload the active view from the run ledger.          |

Like the Machines-tab keys, Tools-tab keys are scoped to the pane and may overlap
app-level bindings.

The Agents-tab copy mode (`%`) gains a `tool run id` target on nodes with tool runs,
configured as `ace.keymaps.modes.copy_mode.keys.agents.tool_run_id` (default `r`, so
`%r`).

On the Agents tab, `y` (`agents_copy_reference`) copies the selected agent's durable
`@agent:` reference in both Inbox and Archive. The same key remains
`artifacts_copy_reference` on the Artifacts tab. Agents copy-mode (`%`) also offers `%!`
(handoff prompt), `%l` (Markdown link; the link target is the durable `agent:` reference
itself), `%j` (Inbox metadata JSON, or the archive bundle JSON in Archive), and `%d`
(artifacts directory).

**`app`** — App-level keybindings. Each key is an action name mapped to a key string.
See `src/sase/default_config.yml` for the full list of configurable actions and their
defaults. Rebinding `open_config_center` also changes the Admin Center's home-page
resume key; it does not add a second keymap action or setting.

The Artifacts split actions are remappable as `cycle_artifacts_split` and
`cycle_artifacts_split_reverse`. Their defaults use `right_curly_bracket` (`}`) and
`left_curly_bracket` (`{`); both curly-bracket key names are accepted anywhere an sase's
TUI keybinding is configured.

The [Artifacts pane brief](../../ace.md#pane-description-brief) cycles with
`cycle_artifacts_description`, default `D`. It shares that key with the Agents-only
`toggle_attempt_view`; see the shared-key allowlist below.

The Agents header panel toggles with `toggle_agent_header`, default `d`. It shares that
key with the Artifacts `show_diff`, the Services `toggle_axe_description`, and the
Stitches `stitches_toggle_sdd` actions; see the shared-key allowlist below. The toggle
is available only on the Agents tab while the header panel is shown.

The Agents jump panel toggles with `toggle_agent_jump_panel`, default `.` (`full_stop`).
It shares that key with the Artifacts `toggle_relation_panel` and the Services
`toggle_hide_reverted` actions; see the shared-key allowlist below. The toggle is
available only on the Agents tab while the jump panel is shown.

The Agents show/hide non-run agents toggle is `toggle_hide_non_run_agents`, default `I`.
It moved off `.` (which now toggles the Agents jump panel); the Services
`toggle_hide_reverted` keeps `.` for axe commands.

Agents-tab [`Enter`](../../ace.md#enter-act-on-an-agent) is `act_on_agent`, default
`enter`: it opens the selected row's pending gate or jumps to its Patch, and offers a
chooser when more than one target applies. The older direct Patch jump remains as
`jump_to_agent_patch`, default `unbound`. A stale
`ace.keymaps.modes.leader_mode.keys.jump_to_notification` override (the retired `,n`
chord) is ignored with a warning pointing at `act_on_agent`.

`start_agent_from_patch`, default `space`, prefills the prompt with the most recently
launched VCS macro, or opens a blank home-workspace prompt when there is none. The
former `start_agent_home` action is removed; a leftover override for it is ignored as an
unknown action. The leader `,h` chord still opens a home-context prompt.

Remote Agents actions are also app-level fields. They intentionally ship as `unbound`:
the command palette exposes them contextually, and a configured key becomes active only
when the Agents tab and selected remote row support that action.

The top-level Agents query editor is available as the app-level `edit_query` binding,
default `/`, and the direct `agents_filters` binding, default `f`. The leader-mode
`search_forward` chord, default `,/`, starts inline deck search on Agents only.

| Field                           | Default   | Action                                                                                          |
| ------------------------------- | --------- | ----------------------------------------------------------------------------------------------- |
| `agents_filters`                | `f`       | Open the top-level Agents `agents-live` filter bar.                                             |
| `toggle_agents_archive`         | `,a`      | Toggle between the Agents Inbox and the Archive (leader-mode key).                              |
| `agents_refresh`                | `r`       | Open the Refresh panel for the Agents tab.                                                      |
| `agents_retry`                  | `R`       | Retry the selected local or remote agent.                                                       |
| `choose_agent_grouping`         | `o`       | Open the Agents grouping picker (`p`/`d`/`s`/`m` modes; local `o` toggles split/merged panels). |
| `view_agent_metadata`           | `V`       | Open the selected local agent's metadata panel in the SASE pager.                               |
| `connect_agent_machine`         | `unbound` | Open the Admin Center Machines tab.                                                             |
| `setup_agent_machine`           | `unbound` | Open the Admin Center Machines tab for enrollment guidance.                                     |
| `retry_remote_agent`            | `unbound` | Compatibility id: retry the selected row on its owning host.                                    |
| `view_remote_agent_content`     | `unbound` | Fetch bounded remote chat, output, or diff content.                                             |
| `answer_remote_attention`       | `unbound` | Answer a pending remote question or approve a pending gate.                                     |
| `check_dispatch_launch_outcome` | `unbound` | Reconcile the selected provisional remote dispatch-launch row with its operation outcome.       |

The former `toggle_layout`, `toggle_thinking`, `toggle_thinking_reverse`,
`choose_agent_view`, `next_agent_metadata_section`, and `prev_agent_metadata_section`
app-key settings are retired. Existing overrides for those names are ignored; the Agents
tab now uses deck keys instead (`next_deck_card` / `prev_deck_card` for cards,
`next_deck` / `prev_deck` for decks, `pick_deck` (`p`) for the deck picker,
`toggle_deck_split_below` / `toggle_deck_split_right` for splits).

On the Agents tab, `r` refreshes and `R` retries; every other tab keeps `r` for
`run_workflow` and `R` for `refresh`, which is why those pairs share keys (see the
allowlist below). Both refresh actions open the Refresh panel, and the leader
`full_history_refresh` chord (`,y`) opens it with the cursor on the Agents full-history
rescan. Likewise, `V` opens the Agent Run Log modal (`show_agent_run_log`) everywhere
except the Agents tab, where `view_agent_metadata` owns it.

Remote retry, stop, and fork reuse the ordinary `agents_retry`, `kill_agent`, and
`edit_hooks` actions when the row advertises those capabilities. See
[Machines](../../ace.md#machines).

**`modes`** — Prefix-key mode definitions. Built-in modes (`fold_mode`, `copy_mode`,
`leader_mode`, `bang_mode`) can be reconfigured, and custom modes can be added. Each
mode has:

[Generated reference for `ace.keymaps`](tui.md#ace-keymaps)

The built-in `fold_mode` direct actions are `set_level_1` through `set_level_3` for PR
details and the nested `agents.set_level_1` through `agents.set_level_4` for Agents
metadata. Their defaults produce `z1`-`z3` on PRs; Agents accepts levels 1-2 for a
session, 1-3 for a clan or single-agent scope, and 1-4 for a selected whole tribe panel.
The configured prefix and subkeys are used by dispatch, the command palette, footers,
and help.

Query editing is one app-level action. `ace.keymaps.app.edit_query` controls Patches,
Stitches, Plans, Files, Services, and the top-level Agents query editor, and defaults to
bare `/`. The top-level Agents filter bar also has `ace.keymaps.app.agents_filters` as a
direct alias, default `f`. Agents metadata search is
`ace.keymaps.modes.leader_mode.keys.search_forward`, default `,/`. Stale
`ace.keymaps.app.search_forward` and `ace.keymaps.modes.leader_mode.keys.edit_query`
overrides are ignored with a warning naming those replacements; they are not merged back
as runnable commands. Help is an app-level action controlled by
`ace.keymaps.app.show_help` and defaults to bare `?`; the retired
`leader_mode.keys.show_help` override is dropped at load time.

Agents panel layout is picker-local now. Configure
`ace.keymaps.app.choose_agent_grouping` to change the opener; with the default opener,
`oo` toggles between tribe-split panels and one merged panel, then closes the picker.
The second `o` is a literal key inside the picker, not a separate configurable app or
leader binding. Old `ace.keymaps.modes.leader_mode.keys.toggle_agent_panel_grouping`
overrides are ignored with a warning instead of being remapped onto the picker opener.

The Agents deck picker works the same way: configure `ace.keymaps.app.pick_deck`
(default `p`) to change the opener. Pressing that opener again inside the picker is the
return gesture (last deck, or cycle-previous when the panel has no history) and is not
its own binding. The in-picker deck letters (`m` / `f` / `t` / `n` for Main, Files,
Tools, and FINAL) and their capitals (`M` / `F` / `T` / `N`, which show the deck in the
most recently focused other panel with a position glyph hint) are fixed and not
configurable. When the opener is a single letter, its capital (`P` by default) sits next
to `M` / `F` / `T` / `N` and shows the same resolved return deck in the other panel. `p`
is shared with the Artifacts `pick_artifacts_project` action; the two are disambiguated
by tab (see the allowlist below).

The leader update keys are separate remappable actions. `update_sase` opens the cached
Update panel, while `update_everything` directly runs the same previewed Everything flow
as `,U` then capital `E`, including failed-preview and already-current no-op behavior.

A small allowlist of app actions intentionally shares a key because the two actions can
never be available on the same surface. Validation permits exactly these pairs and
rejects every other duplicate app binding:

| Shared key (default)      | Spelled in YAML as               | Pair                                                    | Disjoint because                                       |
| ------------------------- | -------------------------------- | ------------------------------------------------------- | ------------------------------------------------------ |
| `a`                       | `a`                              | `add_axe_item` / `open_artifact_files`                  | Services vs Artifacts                                  |
| `d`                       | `d`                              | `show_diff` / `toggle_axe_description`                  | Patches vs Services                                    |
| `d`                       | `d`                              | `toggle_agent_header` / `show_diff`                     | Agents vs Artifacts                                    |
| `d`                       | `d`                              | `toggle_agent_header` / `toggle_axe_description`        | Agents vs Services                                     |
| `d`                       | `d`                              | `toggle_agent_header` / `stitches_toggle_sdd`           | Agents vs Artifacts Stitches                           |
| `E`                       | `E`                              | `beads_open_bug` / `files_open_external`                | Beads vs Files panes (the shared open-externally verb) |
| `w`                       | `w`                              | `agents_revive` / `beads_launch_work`                   | Retired Agents pane (opt-out) vs Beads pane            |
| `w`                       | `w`                              | `agents_revive` / `reword`                              | Retired Agents pane (opt-out) vs Patches               |
| `.`                       | `full_stop`                      | `toggle_relation_panel` / `toggle_hide_reverted`        | Artifacts vs Services                                  |
| `.`                       | `full_stop`                      | `toggle_relation_panel` / `toggle_agent_jump_panel`     | Artifacts vs Agents                                    |
| `.`                       | `full_stop`                      | `toggle_hide_reverted` / `toggle_agent_jump_panel`      | Services vs Agents                                     |
| `X`                       | `X`                              | `open_agent_cleanup_panel` / `patches_toggle_reverted`  | Agents vs Patches                                      |
| `D`                       | `D`                              | `toggle_attempt_view` / `cycle_artifacts_description`   | Agents vs Artifacts                                    |
| `_`                       | `underscore` (or `_`)            | `next_query` / `collapse_all_panel_folds`               | Artifacts query history vs Agents fold sweep           |
| `r`                       | `r`                              | `agents_refresh` / `run_workflow`                       | Agents vs Patches/Services                             |
| `R`                       | `R`                              | `agents_retry` / `refresh`                              | Agents vs every other tab                              |
| `o`                       | `o`                              | `choose_agent_grouping` / `cycle_grouping_mode`         | Agents vs Artifacts                                    |
| `p`                       | `p`                              | `pick_deck` / `pick_artifacts_project`                  | Agents vs Artifacts                                    |
| `Ctrl+B`                  | `ctrl+b`                         | `toggle_deck_focus_reverse` / `scroll_prompt_up`        | Agents vs Services/Artifacts                           |
| `Ctrl+Shift+F` / `>`      | `ctrl+shift+f,greater_than_sign` | `swap_deck_panel_next` / `start_child_mode`             | Agents vs Artifacts                                    |
| `Ctrl+Shift+B` / `<`      | `ctrl+shift+b,less_than_sign`    | `swap_deck_panel_prev` / `start_ancestor_mode`          | Agents vs Artifacts                                    |
| `Ctrl+Shift+D` / `Ctrl+X` | `ctrl+shift+d,ctrl+x`            | `close_deck_panel` / `prev_chop_run`                    | Agents vs Services                                     |
| `Ctrl+T`                  | `ctrl+t`                         | `turn_deck_layout` / `beads_toggle_note_audience`       | Agents vs Artifacts Beads pane                         |
| configurable then `o`     | varies                           | `choose_agent_grouping` local panel-layout toggle       | Agents picker-local `o`; `oo` with defaults            |
| configurable              | varies                           | `choose_agent_grouping` / `cycle_grouping_mode_reverse` | Agents vs Artifacts                                    |

The first column is what the key looks like on your keyboard; the second is the name to
write in `sase.yml`, matching how `src/sase/default_config.yml` spells it. Punctuation
keys generally use their long name (`slash`, `full_stop`, `question_mark`, `backslash`,
`vertical_line`), the same convention as the curly-bracket names described above; the
raw `\` and `|` glyphs are also accepted for the last two.

The allowlist is keyed by action pair, not by key, so moving one of these actions onto a
different key keeps the exemption, and pointing a third action at a shared key does not
gain it. Only actions you overrode are checked: an override that collides with any
action outside its allowed pair is logged as a duplicate and reverted to that action's
default, leaving the rest of your keymap in place. The shipped `V` shared by
`show_agent_run_log` and `view_agent_metadata` is not on the list: it loads as shipped,
but moving both actions onto one new key is logged as a duplicate and both revert to
`V`.

`ace.keymaps.app.start_saved_query_mode` (default `0`) arms direct saved-PR-query slot
selection: press it, then a slot digit (`1`-`9`, then `0`) to load that slot. Its digit
sub-keys are not configurable -- they are the slot identifiers themselves, the same way
`start_checkout_mode`'s `1`-`9` workspace digits aren't. The prefix is scoped to the
Artifacts tab (any sub-tab); it does not arm on Agents or Services.

Custom mode key fields:

[Generated reference for `ace.keymaps`](tui.md#ace-keymaps)

\*Exactly one of `shell` or `action` must be provided.

The keymap loader validates configuration: invalid keys are reverted to defaults,
duplicate bindings within a scope are warned, and prefix conflicts between custom modes
and app bindings are detected.

Source: `src/sase/default_config.yml`, `src/sase/ace/tui/keymaps/`

## Related

- [TUI configuration](tui.md) — generated keymap keys and defaults.
- [TUI keymaps](../tui/keymaps.md) — generated key bindings.
