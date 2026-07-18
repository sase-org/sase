# ACE TUI User Guide

## Overview

ACE (Agentic ChangeSpec Explorer) is the primary TUI for the SASE toolkit. It provides an interactive interface for
navigating, managing, and operating on ChangeSpecs, agents, and the Axe daemon.

## Launching

```bash
sase ace [QUERY] [options]
```

If no query is provided, ACE loads the last used query, then the first saved query, then falls back to `!!!` for error
suffixes.

### CLI Options

| Option                     | Description                                                                             |
| -------------------------- | --------------------------------------------------------------------------------------- |
| `QUERY` (positional)       | Query string for filtering ChangeSpecs                                                  |
| `-m`, `--model-tier`       | Override model tier for all LLM providers (`large` or `small`)                          |
| `-M`, `--model-size`       | Deprecated alias for `--model-tier` (`big` or `little`)                                 |
| `-p`, `--profile [PATH]`   | Profile the TUI session with pyinstrument; optional output path                         |
| `-r`, `--refresh-interval` | Auto-refresh interval in seconds (default: 10, 0 to disable)                            |
| `-x`, `--no-axe`           | Disable auto-starting the axe daemon on startup                                         |
| `-v`, `--vcs-provider`     | Override VCS provider (`git`, `hg`, or `auto`)                                          |
| `-R`, `--restart-axe`      | Restart the axe daemon on startup (shows RESTARTING indicator)                          |
| `-t`, `--tab`              | Tab to focus on startup (`artifacts`, `agents`, `axe`; `changespecs` is a legacy alias) |
| `-T`, `--tmux`             | Launch ACE in a new tmux window and print the target for external control               |

When profiling is enabled, ACE writes text output to `PATH` or `$SASE_TMPDIR/ace_profile_<ts>.txt`, prints the shortened
path on exit, and copies that path when a clipboard tool is available.

### Examples

```bash
sase ace                              # Last query, first saved query, or "!!!"
sase ace '"feature" AND "Drafted"'    # Filter by name and status
sase ace '+myproject'                 # Filter by project
sase ace -m small -r 30 '!!! OR @@@' # Small model, 30s refresh
```

When `--profile` is enabled, ACE prints a shortened profile-output path after the TUI exits and tries to copy that
shortened path to the system clipboard (`pbcopy`, `wl-copy`, `xclip`, or `xsel` when available).

## Tab System

ACE has three tabs, cycled with `Tab` and `Shift+Tab`:

| Tab           | Description                                                   |
| ------------- | ------------------------------------------------------------- |
| **Agents**    | View running and completed agents, their files and prompts    |
| **Artifacts** | Browse PRs, commits, bugs, and plans in four focused sub-tabs |
| **Axe**       | Monitor the Axe daemon and background commands                |

Agents is the first tab and the startup default. Each tab has a contextual guide: press `,?` (leader mode) to open the
current tab's guide modal, which summarizes what the tab shows and its most useful keybindings. While the guide or the
`?` help modal is open, the configured tab-switch keys still switch ACE tabs and refresh the modal content in place. By
default those keys are `Tab` and `Shift+Tab`; if you remap them, the modals follow the configured keys.

On first use, empty tabs render onboarding states instead of blank panels: the PRs sub-tab shows a getting-started card
when no ChangeSpecs or saved queries exist yet, and the Agents tab walks through launching a first agent — the
project/ChangeSpec launch hint appears only when a launchable target exists — and can recommend installing plugins from
the Admin Center when no third-party plugins are installed. Onboarding cards carry "learn more" links into the published
docs.

Within Artifacts, the strip is numbered **1 PRs · 2 Commits · 3 Bugs · 4 Plans**. Press `1`–`4` to jump directly to a
sub-tab, or use `[` / `]` to cycle. These digits act only while Artifacts is visible. Press `p` in Commits, Bugs, or
Plans to change the shared project scope, or use the command palette to jump directly to any sub-tab. PRs remains
query-scoped and retains the existing ChangeSpec workflow.

### Navigation in Commits, Bugs, and Plans

The three non-PR panes share fast navigation over their selectable left-panel entries. Commits skip day headings, Plans
skip section and empty-state rows, and Bugs always targets the issue list rather than its separately focusable Linked
work list. Movement clamps at the first or last entry and silently does nothing when a list is empty.

| Key                 | Action                                                                                |
| ------------------- | ------------------------------------------------------------------------------------- |
| `g` / `G`           | Select the first / last commit, issue, proposal, bead, phase, or archived plan        |
| `Ctrl+F` / `Ctrl+B` | Move down / up 10 selectable entries                                                  |
| `Ctrl+D` / `Ctrl+U` | Scroll the active right-hand detail pane down / up (half page)                        |
| `'`                 | Show one-key entry hints; press `'` again for the first entry or the last jump origin |

Hint keys select an entry without activating it. Jump-back history is kept separately for Commits, Bugs, and Plans, and
stale origins disappear automatically after filtering, changing project scope, refreshing data, or collapsing an
expanded plan tree. Escape or an invalid hint exits jump mode. These actions use the configured keymap values; the keys
above are the defaults.

### Filtering Commits and Plans

Press `/` in Commits or Plans to open its live filter bar. Tokens from different facets combine with AND semantics;
comma-separated and repeated values within one facet combine with OR semantics. Free-text terms must all match. Press
`Tab` to accept the highlighted key or value completion, `Enter` to keep the query, or `Escape` to restore the last
committed query.

Commits accepts `repo:`, `author:`, `since:`, `until:`, and `limit:` plus free text matched against the commit subject.
For example, `repo:sase author:Ada since:7d fix` shows recent SASE commits by Ada whose subjects contain `fix`, while
`limit:all` removes the final row cap.

Plans accepts `kind:`, `status:`, `tier:`, `project:`, `since:`, and `until:` plus free text matched across plan and
bead metadata. Kinds are `proposal`, `epic`, `phase`, and `archive`. For example,
`kind:epic,phase status:open project:sase filter` shows open SASE epics or phases containing `filter`.

A leading unquoted `-` excludes a match. Commits can exclude repositories, authors, and subject text; Plans can exclude
kinds, statuses, tiers, projects, and text. Exclusion wins when positive and negative constraints overlap:
`repo:sase,plans -repo:plans`, `author:Ada -author:bot`, and `status:open -status:blocked` are all valid. A comma list
negates the whole token, so `-repo:plans,research` excludes either repository. Date bounds and `limit:` cannot be
negated. Quote the whole token to search for a literal leading minus (`"-repo:plans"`); quote only the excluded value to
keep negation active (`-"generated rollout"`). Matching remains case-insensitive, and repository/project aliases work
for both inclusion and exclusion.

## Keybindings: Artifacts / PRs

### Navigation

| Key                 | Action                                                                             |
| ------------------- | ---------------------------------------------------------------------------------- |
| `j` / `k`           | Move to next / previous visible row (banner at fold `< L2`, PR at the leaf level)  |
| `<` / `>` / `~`     | Navigate to ancestor / child / sibling PR                                          |
| `'`                 | Jump to entry by hint character (current tab); hints land on collapsed banners too |
| `Ctrl+O`            | Fast jump: jump back if possible, otherwise jump to the first current-tab hint     |
| `` ` ``             | Jump to entry across all tabs (see [Jump All Modal](#jump-all-modal))              |
| `Ctrl+R` / `Ctrl+K` | Jump back / forward in PR history                                                  |
| `o` / `O`           | Cycle PR grouping mode forward / reverse (`BY_PROJECT` ↔ `BY_DATE` ↔ `BY_STATUS`)  |
| `g` / `G`           | Scroll detail panel to top / bottom                                                |
| `Ctrl+D` / `Ctrl+U` | Scroll detail panel down / up (half page)                                          |

> **Note:** `o`/`O` ("organize") cycles the L0 grouping bucket forward / reverse on the Agents tab and the PRs sub-tab
> (each surface keeps its own in-session mode). On the AXE tab it is a silent no-op. See
> [PR Grouping and Folding](#pr-grouping-and-folding) and the Agents-tab [Grouping Modes](#grouping-modes) below.

### PR Actions

| Key             | Action                                                      |
| --------------- | ----------------------------------------------------------- |
| `A`             | Accept proposal (`!` = spec only, `@` = mark ready to mail) |
| `b`             | Rebase PR onto parent                                       |
| `C` / `c1`-`c9` | Checkout PR (primary / workspace 1-9)                       |
| `d`             | Show diff                                                   |
| `e`             | Edit spec file                                              |
| `f`             | Edit hooks (re-run / delete via hint input)                 |
| `M`             | Mail PR                                                     |
| `m`             | Mark / unmark current PR (auto-advances to next)            |
| `n`             | Rename PR (non-Sub/Rev PRs only)                            |
| `R`             | Rewind to previous commit (`!` suffix skips VCS operations) |
| `s`             | Change status (opens status modal)                          |
| `S`             | Bulk status change for all marked PRs                       |
| `T`             | Checkout + tmux (opens workspace input modal for number)    |
| `u`             | Clear all marks                                             |
| `v`             | View files (hint mode)                                      |
| `w`             | Reword PR description                                       |
| `W`             | Add tag to PR description                                   |
| `Y`             | Sync workspace                                              |

### PR Grouping and Folding

The PRs sub-tab is always grouped — the renderer walks one of `BY_PROJECT`, `BY_DATE`, or `BY_STATUS` and emits a banner
row above each bucket. `BY_PROJECT` is the startup default; `o` cycles `BY_PROJECT → BY_DATE → BY_STATUS` for the
current session.

| Mode         | L0 buckets                                                                   | Notes                                                                                                                                                                                                                                                                                                       |
| ------------ | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BY_PROJECT` | Project name                                                                 | Adds an L1 sibling-root sub-banner shared by `foobar_1` / `foobar_2` style suffixed siblings. Singletons suppress their L1 banner.                                                                                                                                                                          |
| `BY_DATE`    | `Today` / `Yesterday` / `This Week` / `Earlier`                              | Bucket from the latest TIMESTAMPS entry. Today/Yesterday add 4-hour L1 windows; hourly L2 headings appear only inside 4-hour windows with 2+ PRs. This Week adds day headings; Earlier adds week headings plus `(no timestamp)`.                                                                            |
| `BY_STATUS`  | `Mailed` / `Ready` / `WIP` / `Draft` / `Submitted` / `Reverted` / `Archived` | Bucket from the literal `status` field; actionable buckets first (`Mailed` = awaiting response, `Ready` = next to mail), terminal states last. Adds an L1 sibling-root sub-banner shared by `foobar_1` / `foobar_2` style suffixed siblings inside each status bucket. Singletons suppress their L1 banner. |

In `BY_DATE` mode, PRs sort newest-first within each date bucket. `Today` and `Yesterday` are grouped first by compact
4-hour windows (`8AM-12PM`); one-hour headings (`09:00`) appear only when that 4-hour window contains at least two PRs.
`This Week` uses calendar-day subgroups; `Earlier` uses Monday-start week ranges. PRs without a parseable TIMESTAMPS
entry fall into `(no timestamp)` under `Earlier`.

The active grouping mode is shown in the PRs sub-tab's info-panel header as a `[group: <label>]` badge.

| Key | Action                                                                                                                                 |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `l` | Expand the focused banner one level (or peel one layer of the visible tree)                                                            |
| `h` | Collapse the focused banner; on a collapsed L1 banner, escalate to its parent. With agent focus, collapse the deepest enclosing group. |
| `L` | Snap to fully expanded — all banners and ChangeSpec rows visible                                                                       |
| `H` | Snap to fully collapsed — collapse every visible banner                                                                                |

Collapsed banner rows are first-class navigation stops: `j`/`k` step through them just like ChangeSpec rows, and `'`
jump-hints land on them too. After a fold change that hides the focused PR, focus snaps to the deepest collapsed
ancestor banner so the cursor always sits on a row the user can see.

### Fold Mode (`z` prefix)

| Key     | Action                                                 |
| ------- | ------------------------------------------------------ |
| `z` `c` | Cycle commits section (expand → collapse)              |
| `z` `d` | Cycle deltas section (folded ↔ unfolded)               |
| `z` `h` | Cycle hooks section (expand → collapse)                |
| `z` `m` | Cycle mentors section (expand → collapse)              |
| `z` `t` | Cycle timestamps section (expand → collapse)           |
| `z` `C` | Toggle commits section (collapsed ↔ fully expanded)    |
| `z` `D` | Toggle deltas section (folded ↔ unfolded)              |
| `z` `H` | Toggle hooks section (collapsed ↔ fully expanded)      |
| `z` `M` | Toggle mentors section (collapsed ↔ fully expanded)    |
| `z` `T` | Toggle timestamps section (collapsed ↔ fully expanded) |
| `z` `z` | Cycle all sections                                     |
| `z` `Z` | Toggle all sections (expand ↔ collapse)                |

COMMITS, HOOKS, MENTORS, and TIMESTAMPS sections each cycle through three fold levels:

| Level              | Behavior                                                                           |
| ------------------ | ---------------------------------------------------------------------------------- |
| **Collapsed**      | Notes truncated to fit; multi-line body shown as `[+N lines]`; only latest drawers |
| **Expanded**       | Full notes; body shown in dimmed text; all CHAT/DIFF/PLAN drawers visible          |
| **Fully Expanded** | Everything visible including rejected proposals                                    |

The lowercase cycle keys (`z` `c`, `z` `h`, `z` `m`, `z` `t`) step through all three levels in order. The uppercase
toggle keys (`z` `C`, `z` `H`, `z` `M`, `z` `T`) skip the intermediate **Expanded** state, jumping directly between
**Collapsed** and **Fully Expanded**.

When collapsed, a `[folded: CHAT + DIFF + PLAN + N proposals]` indicator appears on COMMITS entries with hidden content.
The indicator width is pre-calculated so that note truncation accounts for it. TIMESTAMPS shows a `[folded: N]`
indicator inline with the header and displays the most recent timestamp entry when collapsed, giving a quick view of the
last lifecycle event.

The DELTAS section uses two semantic states. When **folded**, the section renders a one-line file and line-count summary
such as `DELTAS:  +3 (+428) ~6 (+91 ~37 -14) -1 (-22) (10 files)`. When **unfolded**, the alphabetical entry list is
shown with colored glyphs (green `+`, gold `~`, red `-`) and inline line-count tokens. Binary files display `binary`;
zero-count entries display `0 lines`. The section is omitted entirely when the ChangeSpec has no deltas.

### Workflows and Agents

| Key     | Action                                                  |
| ------- | ------------------------------------------------------- |
| `r`     | Run workflow on current PR                              |
| `+`     | Run a custom agent (opens project/ChangeSpec selection) |
| `Space` | Run agent from current PR                               |

If ACE cannot detect a workspace provider for the selected ChangeSpec or agent, the quick-launch actions show an error
toast instead of opening a prompt with a broken VCS prefix.

### Bang Mode (`!` prefix)

| Key  | Action                                            |
| ---- | ------------------------------------------------- |
| `!!` | Run background command (opens hook history modal) |
| `!x` | Start / stop axe (or select process)              |

### Hook History Modal

Pressing `!!` opens the hook history modal showing previously run background commands:

| Key         | Action                                     |
| ----------- | ------------------------------------------ |
| `j` / `k`   | Navigate through hook history              |
| `Enter`     | Select and execute highlighted hook        |
| `Ctrl+D`    | Delete highlighted hook from history       |
| `Ctrl+G`    | Edit first — select hook and open in input |
| `Esc` / `q` | Cancel and close modal                     |

The modal supports live filtering as you type in the search box and displays last-used timestamps for each hook.

### Leader Mode (`,` prefix)

| Key        | Action                                                                               |
| ---------- | ------------------------------------------------------------------------------------ |
| `,,`       | Repeat the last leader command                                                       |
| `,!`       | Run command using current PR context                                                 |
| `,A`       | Open the Agent Run Log modal for the current PR                                      |
| `,c`       | Clear COMMENTS field (kills CRS agents, deletes CRS proposals)                       |
| `,C`       | Review mentors (opens Mentor Review modal)                                           |
| `,h`       | Run agent from home prompt context; bare prompts default to `#git:home`              |
| `,m`       | Open the Models panel (view/manage model aliases; see [Models Panel](#models-panel)) |
| `,U`       | Update sase, core, and plugins (opens Updates confirmation prompt)                   |
| `,M`       | Kill running mentors                                                                 |
| `,R`       | Show runners info                                                                    |
| `,<space>` | Run agent from current PR (skips project selection)                                  |
| `,.`       | Open prompt history modal                                                            |
| `,>`       | Open prompt history modal with cancelled prompts visible                             |
| `,?`       | Open the current tab's guide modal                                                   |

The `,h` shortcut opens a home-context prompt directly. Project and PR launch pickers use lifecycle-aware discovery:
project entries, including `home` when it appears in picker lists, must have enabled and launchable ProjectSpecs; PR
choices come from enabled ProjectSpecs. Disabled projects do not appear in normal launch pickers until they are enabled
with `sase project enable <project>`. You can also type a known-project VCS ref explicitly; launch preparation treats
that as intent to resume work and re-enables the project before claiming a workspace.

Project launch pickers also support `Ctrl+D` for cleanup of empty project entries. This deletes only the highlighted
project's active/archive ProjectSpec files, refuses entries whose ProjectSpec files still contain ChangeSpecs, and does
not delete workspace checkouts or other SASE state. For lifecycle changes, bulk operations, ProjectSpec editing, or
deleting the whole SASE project directory, use the **Projects** tab of the SASE Admin Center (press `#`).

The repeat binding is the leader prefix followed by the configured `repeat_last` key. With the defaults both are comma,
so the sequence is `,,`; if the leader prefix is changed but `repeat_last` is not, the second key remains comma. Repeat
re-dispatches the last recognized leader subkey against the current tab and selection. If no leader command has been run
yet, ACE shows a toast and does nothing.

> **Note:** `,x` (kill & edit) is only available on the Agents tab — see
> [Agents Tab Leader Mode](#leader-mode-prefix_1).

### Mentor Review Modal

Press `,C` to open the Mentor Review modal, which lets you navigate mentor comments, accept or reject suggestions, and
apply accepted changes. See [docs/mentors.md](mentors.md) for the full mentor system reference.

| Key                 | Action                                                   |
| ------------------- | -------------------------------------------------------- |
| `j` / `k`           | Navigate between mentors                                 |
| `n` / `p`           | Navigate between comments within a mentor                |
| `N` / `P`           | Navigate between accepted comments only                  |
| `Ctrl+D` / `Ctrl+U` | Scroll comment details down / up                         |
| `Space`             | Toggle acceptance of the current comment                 |
| `Enter`             | Apply all accepted comments (launches agent)             |
| `a`                 | Apply accepted comments and propose (amend with propose) |
| `A`                 | Apply accepted comments and commit                       |
| `r`                 | Run a mentor profile (opens profile picker)              |
| `y`                 | Copy the current comment to the clipboard                |
| `Shift+K`           | Kill a running mentor                                    |
| `Esc` / `q`         | Close modal                                              |

### Copy Mode (`%` prefix)

| Key  | Action                     |
| ---- | -------------------------- |
| `%%` | Copy ChangeSpec            |
| `%!` | Copy ChangeSpec + snapshot |
| `%b` | Copy bug number            |
| `%c` | Copy PR number             |
| `%n` | Copy PR name               |
| `%p` | Copy project spec file     |
| `%s` | Copy sase ace snapshot     |

## Keybindings: Agents Tab

### Navigation

| Key                 | Action                                                                                                |
| ------------------- | ----------------------------------------------------------------------------------------------------- |
| `j` / `k`           | Move to next / previous visible row (banner at fold `< L3`, agent at `L3`)                            |
| `J` / `K`           | Cycle focus across tribe side panels (forward / reverse)                                              |
| `'`                 | Jump to entry by hint character (current tab); on the Agents tab, hints land on collapsed banners too |
| `Ctrl+O`            | Fast jump: jump back if possible, otherwise jump to the first current-tab hint                        |
| `Ctrl+J` / `Ctrl+K` | Cycle metadata sections forward / backward through the document top                                   |
| `` ` ``             | Jump to entry across all tabs (see [Jump All Modal](#jump-all-modal))                                 |
| `o` / `O`           | Cycle grouping mode forward / reverse (`STANDARD` ↔ `BY_DATE` ↔ `BY_STATUS`)                          |
| `~`                 | Jump among related agent rows: dotted-name ancestors, descendants, and same-namespace neighbors       |
| `g`                 | Scroll to top (file, tools, or metadata panel)                                                        |
| `G`                 | Scroll to bottom (file, tools, or metadata panel)                                                     |
| `Ctrl+D` / `Ctrl+U` | Scroll file panel down / up                                                                           |
| `Ctrl+F` / `Ctrl+B` | Scroll prompt panel down / up                                                                         |

> **Note:** `o`/`O` ("organize") cycles the grouping mode forward / reverse on the Agents tab and the PRs sub-tab (each
> surface keeps its own in-session selection independently); on the AXE tab it is a silent no-op. `g`/`G` keep their
> conventional vim-style scroll-to-top/bottom meaning on every tab. See [Grouping Modes](#grouping-modes) below.

On the Agents tab, `~` uses dotted agent-name relationships rather than ChangeSpec sibling families. It can jump among
visible ancestors, descendants, and neighbors in the same immediate namespace, such as `foo.bar` and `foo.baz`. Dotless
names can still have descendants (`foo.child`) but do not have same-namespace peer neighbors. If there is only one
related visible row ACE jumps directly; otherwise it opens a chooser that can also revive same-session dismissed
descendants.

### Agent Actions

| Key                 | Action                                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------------------------- |
| `R`                 | Revive a previously dismissed agent                                                                        |
| `a`                 | Open completion artifacts for the focused agent; in tmux, press again to close the viewer pane             |
| `+`                 | Run custom agent                                                                                           |
| `A`                 | Open auto-approve menu / answer HITL                                                                       |
| `f`                 | Fork agent (by name if running, by chat file if completed)                                                 |
| `n`                 | Name agent                                                                                                 |
| `r`                 | Edit prompt and relaunch agent (retry without killing)                                                     |
| `v`                 | View files (hint mode)                                                                                     |
| `D`                 | Toggle prior-attempt view (only shown when the agent has retried)                                          |
| `V`                 | Open the Agent Run Log modal for the focused agent                                                         |
| `w`                 | Wait/unwait agent (opens WaitModal — see below)                                                            |
| `W`                 | Wait for agent (populate prompt with `%w`); with marks, fans out to `%w:a,b,c`                             |
| `m`                 | Mark / unmark current agent, or all top-level agents in focused collapsed group (auto-advances to next)    |
| `s`                 | Save and dismiss marked agents as a revivable group (opens optional group-name modal)                      |
| `U`                 | Toggle the focused agent's unread marker                                                                   |
| `u`                 | Clear all agent marks                                                                                      |
| `x`                 | Kill / dismiss agent, every marked agent, or every agent in the focused group                              |
| `X`                 | Open the cleanup panel for panel, global, tribe, marked, group, or custom cleanup                          |
| `Enter` / `L`       | Jump to PR (for agents with `meta_new_cl`/`meta_new_pr`)                                                   |
| `e`                 | Edit chat in editor; with marks, open all editable marked transcripts in one editor invocation             |
| `E`                 | Edit panel content in editor                                                                               |
| `t`                 | Open the focused agent's tmux target; agents with opened linked-workspace context show a workspace chooser |
| `T`                 | Open tmux window in the agent's primary project workspace                                                  |
| `N`                 | Open the agent tribe modal (input is pre-seeded with `pinned` for agents without a tribe; empty clears it) |
| `]` / `[`           | Cycle panels: file → tools → metadata (forward / reverse)                                                  |
| `p`                 | Toggle file / prompt layout                                                                                |
| `z`                 | Open the zoom modal for the active detail panel                                                            |
| `Ctrl+N` / `Ctrl+P` | Next / previous file in panel                                                                              |

When ACE knows a planner/author or epic lander's associated plan, the metadata panel adds `PLAN` as the leading lane in
`SASE CONTEXT`. The section ranks intent and inputs before outputs: `PLAN`, the audited `MEMORY`, `SKILLS`, and
`WORKSPACES` event lanes, then the output-focused `ARTIFACTS` lane. A plan or any recorded output is enough to show the
context section. An epic phase worker never shows the `PLAN` lane. Instead, its launch metadata identifies the epic plan
and exact phase bead, and ACE derives a single `Bead: <phase bead id> - <phase description>` row from that phase's
validated, frontmatter-ordered entry. Authored descriptions are normalized to one line; a missing description uses the
same stable plan-and-phase pointer generated during deterministic bead creation. This modern path does not read the bead
store, and missing, damaged, or out-of-range metadata falls back to the bare phase bead ID without exposing the epic
roadmap.

For planner/author and lander rows, the lane body contains the complete normalized `Title`, `Goal`, and canonical
`Path`. Its header shows the effective user-facing tier (`plan`, `tale`, or `epic`) and, for epics, the phase count. The
tier records how the user approved the plan: `approve` means a plan approved without an SDD commit, `tale` (and the
legacy commit-only action) means a committed tale, and `epic` means a committed or launched epic. That displayed choice
survives a later commit or launch failure. When action metadata is absent, ACE falls back to a valid authored
`tier: tale` or `tier: epic`; a legacy committed record without a readable authored tier falls back to `tale`, while a
genuinely unresolved tier renders `tier unavailable`. Path selection is independent: committed paths are relative to the
agent workspace (including SDD sidecars such as `sase/repos/plans/...`), while pending and explicitly uncommitted
archives use `~/.sase/plans/...`.

Validated authored epics add a phase roadmap beneath those three rows. Each entry shows its one-based authored order,
title, canonical ID, `no dependencies` or `after <id>, ...`, plus an authored phase model when present. Optional
descriptions get their own hanging-indented line. The order and diamond glyph describe static plan structure, not
execution state or live bead progress. Tales retain the compact three-row form. Long goals, titles, IDs, dependency
lists, models, and descriptions use hanging indentation and responsive Unicode-aware folding without ellipses; the lane
caps content at 80 terminal cells on wide panels and reflows to the normal metadata panel or metadata zoom width. In
hint mode only `Path` receives a numbered file hint, allocated in the plan's visual reading order. Missing or damaged
plans keep their known lane and path visible; when epic context is known, strict validation failure renders one quiet
`phases unavailable` header state rather than partial phase data.

ACE separates fast visible-inbox loads from full-history scans. The visible inbox is the normal Agents-tab working set:
active rows plus recent completed, non-hidden rows. Startup, manual refresh (`y`), and active agent search use that path
through the persistent artifact index when it is available.

If the index is missing or unhealthy, ACE falls back to a bounded source-artifact scan for the first paint and shows a
repair warning with the reason. That repair state can arm a deferred full-history reconcile after input has been quiet,
but normal `y` refreshes still stay on the visible-inbox path. Use `sase agent index status --json` for a lightweight
check that does not scan source artifacts, `sase agent index verify` to compare the index with source artifacts, and
`sase agent index gc` to rebuild the index and dismissed projection. Use the Agents-tab leader command `,y` when you
want an immediate full-history refresh from source artifacts.

The dismissed projection that hides agents from the visible inbox is rebuilt from the in-memory dismissed set _unioned
with every dismissed-bundle summary_. Reviving an agent now purges its dismissed bundle, so a revived agent stays
visible. For archives that accumulated stale bundles before that fix, plain `sase agent index gc` is **not** a repair on
its own -- it rebuilds the projection _from_ those lingering bundles and re-hides the revived agents. Run
`sase agent index gc --purge-revived-bundles` (`-r`) to first delete dismissed-bundle files and summary rows for
suffixes that are no longer present in `dismissed_agents.json`, then rebuild the corrected projection.

When one or more agents are marked, `e` edits the marked set instead of only the focused row. ACE opens editable
completed transcripts in visible row order, deduplicates repeated paths, skips live marked rows that are still running
or have no chat file, and reports that live skip count. Stale marks are ignored for this action, and marks remain in
place after the editor exits.

### Opened Repository Context

Configured `linked_repos` are recorded in agent metadata at launch time, while linked and external repos opened during a
run are recorded in opened-repository markers. For non-terminal agents, ACE can include dirty opened repos in the agent
detail `SASE CONTEXT` `ARTIFACTS` lane under `Deltas`. The field counts primary and opened-repo changes together, groups
linked and external entries under distinct glyphs and canonical repo names, and resolves file hints relative to the
opened repo directory. Missing workspace directories, clean repos, and completed/failed agents are not part of this live
delta display.

When a SASE-launched agent uses `/sase_repo`, the run records an opened-repository marker. The underlying command infers
the host project and workspace from cwd; configured linked repos remain backed by hidden `PROJECT_STATE: sibling`
project records, while external repos remain workspace-local and create no project record. ACE shows the markers in the
prompt/detail `SASE CONTEXT` section with the repo name, kind, resolved path, open time, and reason. Live deltas, commit
diffs, and revert all retain the canonical external name (for example, `gh:pallets/click`); reverting an external repo
discards local clone changes without re-cloning from the network.

### Wait Modal

Press `w` on the Agents tab to open the WaitModal. Behavior depends on the agent's status:

- **WAITING agent**: Edit dependency names, a time floor, or the `runners` threshold. A runner-slot-parked agent applies
  a runners-only edit live on its next poll; changing earlier wait stages restarts the agent. Clearing an explicit
  runner threshold returns it to the global `max_running_agents` cap rather than bypassing that cap.
- **RUNNING agent**: Enter a dependency, time floor, or runners threshold to kill and restart the current agent with a
  canonical `%wait(...)` directive.

The modal supports readline-style keybindings (`Ctrl+F`/`Ctrl+B`/`Ctrl+A`/`Ctrl+E`) for cursor movement.

### VCS Tag Resolution in Fork/Wait

When forking or waiting on an agent, VCS tags in the prompt (e.g., `#git(ref)`, `#gh:ref`) are automatically updated to
point to the correct branch. For non-project agents, the ref is replaced with the agent's PR name (branch). For project
agents using `#pr`, the ref is replaced with `@<name>` which resolves to the agent's branch. HITL suffixes (`!!`, `??`)
are stripped during replacement since fork scenarios should not carry over HITL overrides.

### Workflow Visibility

Workflows launched via `sase run` are visible in the Agents tab alongside ACE-launched workflows. The TUI scans
`artifacts/run/*` directories in addition to `workflow-*` and `ace-run` directories, and writes an initial
`workflow_state.json` before execution so that step data appears immediately rather than showing a bare RUNNING entry.
Anonymous `tmp_*` workflows are included in the normal visible-inbox index when their workflow state has
`appears_as_agent: true` and does not set `hidden: true`; explicitly hidden workflow rows are omitted from the default
view. Specialized review runners launched by axe (mentor, CRS, fix-hook, and summarize-hook review agents) are also
visible and are automatically grouped into tribe `@review`, matching the behavior of a `%tribe:review` prompt launch.

### Agent Artifacts

Press `a` on a focused agent to open the artifact panel whenever artifacts are associated with that agent. The list can
include chat transcripts, plan files, generated Markdown PDFs, generated images, generated videos, prompt-referenced
media from saved prompt artifacts, and explicit files saved with
`sase artifact create -p <path> [-n <label>] [-k <kind>]`. ACE always opens the panel, even for a single artifact, so
the label, kind, and path are visible before launching the terminal viewer.

The prompt/detail header includes those non-chat entries in the plan-adjacent `SASE CONTEXT` `ARTIFACTS` lane. Within
that lane, `Commits`, `Deltas`, and `Artifacts` stay in that order when present. Paths are made workspace-relative when
possible, and hint mode assigns numbers to those paths so they can be opened with the normal file-hint flow.

Artifact panel controls:

| Key         | Action                                                                  |
| ----------- | ----------------------------------------------------------------------- |
| selector    | Open the artifact with that one-key selector (`1`-`0`, then letters)    |
| `j` / `k`   | Move through artifact rows                                              |
| `m`         | Mark / unmark the highlighted artifact and advance to the next row      |
| `y`         | Copy highlighted Markdown artifact contents                             |
| `Y`         | Copy the highlighted artifact path, workspace-relative when possible    |
| `Enter`     | Open marked artifacts in list order, or the highlighted row if unmarked |
| `A`         | Open all artifacts in list order, ignoring marks                        |
| `q` / `Esc` | Close the panel                                                         |

When ACE is running inside tmux, artifact viewing opens in a right-side tmux pane so the TUI remains visible. The Agents
list collapses while the tracked pane is live, row-changing navigation shows a warning instead of moving to a different
agent, `l` focuses the tracked pane, and lowercase `a` closes it. If the pane was already closed, lowercase `a` opens
the artifact panel normally. Outside tmux, ACE suspends while the terminal viewer runs in the current pane. The viewer
supports image, video, Markdown, PDF, and text artifacts: images are displayed directly with `kitten icat`, videos play
with `mpv`, Markdown is first rendered to PDF, PDFs are converted to PNG pages for paging, and unknown file artifacts
fall back to a text viewer. The viewer needs `kitten` for image/PDF/Markdown display, `mpv` for videos, `pdftoppm` for
PDF/Markdown paging, and `pandoc` plus a supported PDF engine for Markdown rendering. Missing tools produce a warning
instead of failing the TUI.

Viewer controls:

| Key   | Action                                                       |
| ----- | ------------------------------------------------------------ |
| `j`   | Next page when the artifact has multiple pages; wraps around |
| `k`   | Previous page when the artifact has multiple pages           |
| `n`   | Next artifact when viewing an artifact sequence              |
| `p`   | Previous artifact when viewing an artifact sequence          |
| `r`   | Refresh the current page                                     |
| `z`   | Toggle tmux zoom when available for the viewer pane          |
| `Tab` | Focus the SASE TUI from a tmux artifact pane                 |
| `q`   | Close the viewer                                             |

Only one plan artifact is shown for an agent. When both an archived plan and an SDD tale path are present, ACE prefers
the committed SDD plan; otherwise it keeps the path that best matches the run metadata.

During successful-agent finalization, Markdown-to-PDF rendering updates `workflow_state.json.pdf_status` and a compact
activity label. ACE renders that label on the agent row and in the prompt/detail header, so long conversions show
progress such as `PDF 2/4 <path>` or `PDFs done 3/4 (1 skipped)` instead of looking idle.

### Tribe Side Panels

The Agents tab is laid out as a series of vertically-stacked side panels, one per agent **tribe**. Agents without a
tribe live in the `(untagged)` panel; each tribe renders as `@<tribe>` with an agent count in the panel title. Each
panel title can also show compact scoped metrics in the form `[H1 R2 W1 F1 U1 D3]`: `H` is human-in-the-loop, `R` is
running, `W` is waiting, `F` is failed, `U` is unread terminal work, and `D` is done/read terminal work. Zero-count
metrics are omitted. Panel heights are sized to their content and separated by a one-row gap. When the panels fit, the
first panel grows to absorb leftover vertical space while later panels stay pinned to their natural height; when the
panels overflow, space is weighted by each panel's rendered row count.

Use `J` / `K` to move focus across panels (forward / reverse). `J` lands on the first selectable row in the new panel;
`K` lands on the last selectable row, including collapsed group banners when those are visible. Per-panel actions (kill,
dismiss, expand, etc.) operate on whichever panel currently holds focus. Press `X` to open the cleanup panel: `d`
dismisses completed agents in the focused panel, `D` dismisses completed agents across loaded panels, `k` cleans the
focused panel, `K` cleans all loaded panels, `m` cleans marked agents, `g` cleans the focused group, `t` chooses a
tribe, and `c` opens the custom selector.

Tribes are set or cleared with `N` (see [Agent Actions](#agent-actions)). When opening the modal on an agent without a
tribe the input is pre-seeded with `pinned` so a single Enter promotes the agent into the standard "pinned" panel; that
default makes tribe removal discoverable too — opening the modal on an assigned agent and submitting an empty string
clears the tribe. The `%tribe:<name>` directive (alias `%t`) assigns the tribe at launch; `sase agent tribe` manages it
from the CLI.

### Group Banners and Folding

Within each tribe side panel, agents are grouped into either a 2-level or 3-level banner hierarchy depending on whether
any agent in the panel targets a ChangeSpec:

- **3-level layout** (panel contains at least one ChangeSpec-scoped agent): **project → ChangeSpec → name-root**.
  Project-scoped agents and agents with no `cl_name` fall into a synthetic `(no ChangeSpec)` bucket that sorts last.
- **2-level layout** (no ChangeSpec anywhere in the panel): **project → name-root**.

Banners are rendered between agent rows and carry a summary chip (`N agents · K running · M failed`). Workflow children
inherit grouping identity from their parent agent so banners never appear between a parent and its workflow steps.

A single global fold level controls how much of the hierarchy is visible:

| Level | What's visible (3-level layout)                           | What's visible (2-level layout) |
| ----- | --------------------------------------------------------- | ------------------------------- |
| `L0`  | Project banners only                                      | Project banners only            |
| `L1`  | Project + ChangeSpec banners                              | Project + name-root banners     |
| `L2`  | Project + ChangeSpec + name-root banners                  | All banners and agent rows      |
| `L3`  | All banners and agent rows (and per-workflow folds apply) | (same as `L2`)                  |

| Key | Action                                                                                                             |
| --- | ------------------------------------------------------------------------------------------------------------------ |
| `l` | Step the focused group's fold one level up (`L0` → `L1` → `L2` → `L3`); at `L3`, expand the focused workflow       |
| `h` | Collapse the focused workflow; once it's collapsed (or no workflow is focused), step the group fold one level down |
| `L` | Snap to fully expanded — every banner, every agent row, every workflow step visible                                |
| `H` | Snap to fully collapsed — every per-workflow fold collapsed, then group fold to `L0` (only top-level banners)      |

Banners at fold levels `< 3` are selectable rows. When a banner is focused, `m` toggles marks for all top-level agents
in that group; workflow child rows are not marked independently by the banner shortcut. `x` performs a bulk kill/dismiss
on every top-level agent in that group (single confirmation modal). Marked collapsed banners show `[✓]` when all covered
top-level agents are marked and `[~]` when only some are marked. Marks take priority over the group for bulk actions, so
a non-empty mark set always drives the bulk action regardless of banner focus. When a fold change hides the previously
focused agent, focus snaps to the nearest visible ancestor banner so navigation context is never lost.

Clan and family rows add an agent-tree hierarchy inside those grouping banners. Their trailing names are color-coded by
kind without an additional icon. A clan is a selectable synthetic container, never an agent, and ends in an orchid
`<name>` after its rolled-up status and member counts. A real multi-member family root remains a teal agent row and ends
in an azure `<name>`; ordinary agent annotations and lone plan proposers with only their display-only planner child
remain gold. Clan `@tribe` tags follow the orchid name. From a collapsed clan row, press `l` once to reveal direct
members (agents, family rows, and visible workflow steps), then press `l` again to reveal hidden steps and family
members at a third indentation level. `h` walks those levels in reverse. Sequential family members use `--<suffix>`
names and run one after another. Killing or dismissing a clan row cascades to the clan's live members; acting on one
member leaves its siblings alone. Direct clan members always sort by the clan-local status priority Failed, Stopped,
Running, Waiting, Done in every grouping mode; Starting shares Running's rank. Launch recency orders only members in the
same status bucket. A family row moves as one unit with its follow-ups and workflow steps, preserving their adjacency
and internal order.

Visual treatment: every row carries a fixed-width tier-guide gutter built from one `│  ` segment per ancestor L0/L1
banner (in the parent tier's dim accent — project blue or ChangeSpec cooler accent), so nesting reads as a tree at a
glance. L0 project / bucket banners use a sky-blue `▌` left bar and a heavy `━` rule; level-2 visual headings
(ChangeSpec banners and `BY_DATE` 4-hour windows) get a cooler accent with a `▎` bar and a lighter `─` rule. Level-3
visual headings (name-root banners and conditional `BY_DATE` hourly windows) use a `▸` branch glyph with a teal label.
Singleton name-root groups suppress their banner entirely to reduce visual noise.

The currently-focused side-panel row is marked with a thick accent-colored left bar, **bold** text, and a translucent
accent tint applied to the row background. The tint is intentionally light so per-token status colors (running cyan,
failed red, waiting yellow, etc.) remain readable through the highlight — the bar and bold weight do most of the work of
marking the selection.

After a kill or dismiss, focus re-anchors on the visually-next row (rather than the next row in input order) so the
selection always lands somewhere meaningful in the rendered tree.

### Grouping Modes

Press `o` on the Agents tab to cycle the L0 grouping bucket through three modes. The Agents tab shows a brief toast
(`Grouping: by project` / `by date` / `by status`) on each cycle:

| Mode        | L0 buckets                                                         | Notes                                                                                                                                                             |
| ----------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `STANDARD`  | Project (with optional ChangeSpec sub-level)                       | The "by project" default. Uses the 2-/3-level layout described above.                                                                                             |
| `BY_DATE`   | `Today` / `Yesterday` / `This Week` / `Earlier`                    | Date bucket at L0, then a date-aware L1 subgroup. Sorted newest-first within each bucket.                                                                         |
| `BY_STATUS` | `Stopped` / `Failed` / `Running` / `Waiting` / `Done` / `Starting` | Bucketed by shared status semantics; status priority fixes bucket position, while launch recency sorts display units only within a bucket. Name subgroups remain. |

In `BY_DATE` mode, ACE chooses one L1 subgroup style from the L0 date bucket: one-hour windows (`09:00`) for `Today` and
`Yesterday`, calendar-day labels for `This Week`, and Monday-start week ranges for `Earlier`. The time anchor is
`stop_time` for terminal agents and `start_time` otherwise; both buckets and their subgroups sort newest-first. Workflow
children inherit the parent's anchor so they stay adjacent regardless of their own start time, and agents with no usable
timestamp fall into a `(no time)` subgroup that sorts last.

In `BY_STATUS` mode the L0 banner is the status bucket and L1 is the name-root, with the same singleton-suppression rule
as `STANDARD`. Status priority fixes the bucket order: Stopped, Failed, Running, Waiting, Done, Starting. Launch time
never moves a display unit across those buckets; within a bucket, top-level display units sort by `start_time`, newest
first. Units with no launch timestamp sort after timestamped units, with structural names and input order providing
deterministic tie-breakers. A family, clan, or workflow subtree uses its outer/root agent's launch time and remains
contiguous. Inside a clan, direct members still use the clan-local Failed, Stopped, Running/Starting, Waiting, Done
priority described above, with launch recency breaking same-status ties; that order intentionally differs from this L0
bucket order. Family follow-ups and workflow steps remain adjacent to their direct-member anchor in their established
internal preorder, including any name-prefix banners. The `Starting` bucket remains last and its transient rows remain
hidden, so startup-only work does not displace active rows during daemon or launch refreshes. Each mode keeps its own
per-group fold registry, so collapsing buckets in `BY_STATUS` doesn't affect the project layout you had in `STANDARD`.
`BY_STATUS` banners are prefixed with semantic glyphs (`▲`, `✗`, `▶`, `⏳`, `✓`, `◐`) so the bucket title still leads
visually.

The active grouping strategy is also surfaced in the Agents tab header via a `[group: <label> (o)]` badge so the current
session mode is always visible after the cycle toast fades. The same header starts with a visible top-level agent metric
strip in the form `N [S stopped · T starting · R running · W waiting · F failed · U unread · D done]`, with numeric
counts in place of the letters and zero-count metrics omitted. The leading `N` is the top-level agent total, including
agents still in the `STARTING` bucket. `stopped` counts agents paused for plan approval, questions, or workflow
human-input steps; `starting` counts just-launched agents that have not yet surfaced as visible rows; `running` excludes
waiting, failed, and stopped rows; `waiting` is the blocked/queued subset; `failed` is terminal failed work; `unread`
counts terminal rows that still need acknowledgement; and `done` is completed visible work that has already been
acknowledged. During startup the metric strip renders `Agents: …` until the first agent scan has loaded, avoiding a
misleading zero-agent count. Each TUI launch starts in by-project grouping; cycling only changes the current session.
**Waiting** holds agents that are blocked but progressing on their own — `WAITING` with a time wait (`%wait(time=5m)`,
`%wait(time=1430)`), a non-empty `waiting_for` dependency, or a runner-slot gate. Runner-slot rows add a dim Running
glyph suffix: config-gated waits use live-count/cap form (`WAITING ▶10/10`), while an explicit threshold uses an arrow
(`WAITING ▶7→0`) so a drain barrier cannot be mistaken for a fraction. **Stopped** keeps the strict "you need to act"
semantics for plan approval, questions, and workflow input.

### Agent Row Glyphs

To keep rows compact, agent statuses and types are rendered as one- or two-character badges instead of verbose text:

| Glyph | Meaning                                              |
| ----- | ---------------------------------------------------- |
| `▶`   | RUNNING                                              |
| `✓`   | DONE                                                 |
| `✓P`  | PLAN DONE                                            |
| `▶P`  | PLAN APPROVED                                        |
| `★E`  | EPIC CREATED                                         |
| `✎`   | PLAN                                                 |
| `✗`   | FAILED                                               |
| `⏳`  | WAITING                                              |
| `?`   | QUESTION                                             |
| `↻`   | RETRYING (followed by attempt count, e.g. `↻2`)      |
| `≡`   | Workflow row (top-level)                             |
| `❑`   | ChangeSpec / ChangeSpec row (top-level)              |
| `⚡`  | Autonomous (`%auto`) agent                           |
| `◌`   | Hidden agent (visible only when `.` toggles them in) |

Agents launched by `sase bead work` also show a gold `◆ <bead_id>` badge between the status glyph and the tribe/name. A
phase agent named `<epic_id>.<N>` displays that phase bead ID; the final `<epic_id>.land` agent displays the parent epic
bead ID. Legacy plain `<epic_id>` land agents keep the same badge. Dismissed agents keep the badge by stripping only the
date-prefix used for dismissal. Modern phase rows use their explicit launch metadata immediately; legacy bead-shaped
names retain the deferred bead-store confirmation fallback.

Each agent row also carries a per-provider emoji badge before the display name so the LLM provider behind a row is
readable at a glance without scanning the right-hand model suffix:

| Badge | Provider          |
| ----- | ----------------- |
| 🎭    | Claude            |
| 🪐    | Antigravity (agy) |
| 🤖    | Codex             |
| 🐼    | Qwen              |
| 🐙    | OpenCode          |

The same provider palette also colors the `<PROVIDER>(<model>)` suffix on the right edge of the row — the provider name,
the parentheses, and the model name each render in a distinct shade from that provider's palette so multi-model fan-outs
are easy to scan. Providers without a dedicated palette (anything outside the table above) fall back to a neutral purple
palette and render no emoji badge.

Workflow child rows for `python` and `bash` steps render a leading 🐍 / 🐚 glyph after the `N/M` step number, styled
with the matching step-type accent. The glyph is a stronger signal than the step-type color alone for colorblind users
and for rapid scanning. Agent, parallel, and `prompt_part` step rows are left unchanged — agent rows already carry a
meaningful display name, parallel rows fan out into structural children, and `prompt_part` rows are invisible by
default.

The right-hand edge of each row carries a runtime suffix (`<start-timestamp> · <elapsed>`) right-aligned within the
panel. Active rows that have actually started include a `🏃‍♂️` marker before the ticking elapsed duration; unread
completed rows use a `✅` marker in the same suffix slot, or `❌` when the agent finished in a `FAILED` state; and
user-paused rows (`PLAN`, `QUESTION`, `WAITING INPUT`) use a `✋` marker while waiting for a human response. Pre-run
`WAITING` rows with no `BEGIN` time hide the suffix so queued waits do not look like live runtime. For finished agents,
the start-timestamp half is rendered as a humanized `(date_prefix, time)` pair sized to fit the existing 15-cell slot:

- **Same day**: `HH:MM:SS`
- **Prior day, same year**: `Mon DD HH:MM` (drops seconds — they're noise once a row finished hours ago)
- **Different year**: `Mon DD 'YY` (date only)

The elapsed duration starts at `BEGIN` when a row recorded wait-before-run metadata, otherwise at the row start time.
For root agents, `BEGIN` is runner admission and includes primary and linked-workspace preparation in the active
runtime. Completed `DONE` / `PLAN DONE` / `TALE DONE` workflow rows use the terminal agent stop time when one exists;
plan-step rows that finish without a subprocess stop time anchor to the latest recorded plan submission time so
completed planning rows do not keep ticking. `PLAN APPROVED` rows with a running follow-up show active elapsed time for
the planner segment plus the coder segment, excluding the idle approval gap between plan submission and code launch. The
date prefix uses a softer `dim #8787AF` while the time half keeps the standard `#8787AF`, giving the column internal
hierarchy without inflating the palette. Statuses not in the table fall back to `(STATUS)` text for forwards
compatibility.

### Agent Search

Press `/` on the Agents tab to open the query editor. The query language is a **structured Boolean expression** —
parallel to the ChangeSpec query language but with a property-key allowlist tailored to agents. Bare words are
substring-matched against an agent's `cl_name`, `display_name`, `agent_name`, and `status`, plus its **xprompt, live
reply/response, chat transcript, and prior attempt replies**.

Property keys (closed allowlist):

| Key                                                                                     | Form                                | Notes                                             |
| --------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------------------- |
| `status`, `cl`, `project`, `name`, `model`, `provider`, `tag`, `text`, `type`, `source` | `key:value` (substring match)       | `source` is `axe` (workflow / step) or `manual`.  |
| `pinned`, `hidden`, `attention`, `needs`                                                | `key:true` / `key:false`            | Boolean keys.                                     |
| `age`                                                                                   | `age<5m`, `age>=2h`, `age:1d`, etc. | `:` is sugar for `>=`. Suffixes: `s`/`m`/`h`/`d`. |

Boolean operators: juxtaposition is implicit `AND`; explicit `AND`, `OR`, and `NOT` (with parentheses) are honored.
Precedence is `NOT > AND > OR`. The help modal carries an **Agent Query Syntax** section listing the same grammar.

Parse failures are non-fatal: the loader falls back to "no filter" for that render and surfaces a transient toast; the
query-edit modal re-validates on Apply, keeping itself open and rendering the error inline (in red) on failure.

Transcript files are read lazily (only while a query is active) and cached by `(path, mtime_ns)` so auto-refresh stays
cheap. Per-file reads are capped at 512 KB; missing or unreadable files are skipped silently. Parsed ASTs are also
cached by raw query string so re-renders skip the parse.

### Leader Mode (`,` prefix)

Leader mode is available on every tab. In the Agents tab it also exposes layout and notification shortcuts for the
currently loaded agent list; global entries such as `,m` and `,U` behave the same from other tabs. Unread-completed
actions operate on terminal rows that are loaded in the Agents tab; `,j` can reveal a direct member hidden by a
collapsed clan.

| Key        | Action                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------- |
| `,,`       | Repeat the last leader command                                                                    |
| `,h`       | Run agent from home prompt context; bare prompts default to `#git:home`                           |
| `,g`       | Toggle between tag-split panels and one merged agent panel                                        |
| `,j`       | Jump to the next unread completed agent, revealing a collapsed clan when needed, and mark it read |
| `,J`       | Jump to the next visible stopped/terminal agent, newest first, without changing unread state      |
| `,y`       | Refresh the Agents tab from full artifact history                                                 |
| `,u`       | Mark all loaded unread completed agents as read                                                   |
| `,n`       | Jump to agent notification (plan or question; auto-unhides if needed)                             |
| `,m`       | Open the Models panel (view/manage model aliases; see [Models Panel](#models-panel))              |
| `,U`       | Update sase, core, and plugins (opens Updates confirmation prompt)                                |
| `,B`       | Capture an Agents-tab reproduction bundle for debugging row disappearance or duplication          |
| `,T`       | Toggle continuous Agents-tab repro invariant checks and auto-capture on violation                 |
| `,r`       | Revert focused or marked agent commits, including recorded linked repos                           |
| `,x`       | Kill focused or marked agent(s) and edit their prompt(s)                                          |
| `,<space>` | Run agent from current agent's PR (skips selection)                                               |
| `,.`       | Open prompt history modal                                                                         |
| `,>`       | Open prompt history modal with cancelled prompts visible                                          |
| `,?`       | Open the current tab's guide modal                                                                |

Here, "stopped" means a dismissable terminal row such as `DONE`, `FAILED`, `PLAN DONE`, `TALE DONE`, `PLAN REJECTED`,
`PLAN COMMITTED`, or `EPIC CREATED`; it is separate from the Agents header's "stopped" attention bucket for rows paused
on user action.

If any agents are marked, `,x` acts on that marked set instead of the focused row. Stale marks are ignored; if any
remaining marked agent has no recoverable prompt, ACE warns and leaves the set untouched. After confirmation, ACE kills
or dismisses the marked agents and opens a prompt stack with one editable pane per original prompt in mark order.
Embedded `---` inside an individual agent prompt stays inside that agent's pane.

Press `,r` on a `DONE` or `FAILED` agent to preview commits attributed to that agent before creating git revert commits.
For plan/follow-up families, ACE reverts the family scope when the row carries family metadata; otherwise it reverts the
focused agent name. The preview includes the primary workspace plus recorded `linked_repos` metadata entries that still
point at an existing workspace directory; never-opened linked workspaces are not part of this action. Each repository is
checked before execution, and a dirty or non-git linked repo is reported and skipped while clean repositories can still
be reverted. Successful execution creates one revert commit per repository, pushes when a remote tracking branch is
available, and writes `revert_result.json` beside the agent artifacts.

When agents are marked, `,r` previews the combined commit set for the marked `DONE` / `FAILED` rows. Marked agents must
come from the same primary workspace. The bulk path still groups work by repository, deduplicates overlapping family
matches, skips marked rows with no matching commits, and reports partial linked-repo failures instead of hiding them.

### Agents Tab Reproduction Bundles

Agents-tab reproduction bundles capture the loader/apply sequence that determines which rows are visible. Use them when
the Agents tab briefly drops historical rows, re-adds them, or shows duplicate workflow parents.

When you see one of these bugs in a live ACE session, switch to the Agents tab and press `,B` before refreshing again.
ACE writes a commit-safe bundle to `~/.sase/repros/<timestamp>-manual-.../agents_tab_repro.json` and shows a toast with
the path. "Commit-safe" means local names and paths are redacted, and prompt, response, chat, and diff bodies are
omitted. The bundle keeps the row identities, loader state, app projection state, screen text, and an SVG screenshot
needed to replay the row-list behavior.

Replay a bundle from a checkout of this repository:

```bash
sase repro replay tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json --assert-stable --json
```

The current expected verdict for the checked-in fixture is:

```json
{
  "result": "passed",
  "failed_invariants": [],
  "verdict": "current code fixed for the captured Agents-tab bug class"
}
```

Add `--write-artifacts /tmp/sase-agents-tab-repro-artifacts` to write one `.txt` screen dump and one `.svg` screenshot
per replay step. The replay JSON lists those paths in `screen_paths` and `screenshot_paths`.

Use out-of-band capture only when you need a filesystem baseline and did not have the live TUI capture running:

```bash
sase repro capture agents-tab --output /tmp/sase-agents-tab-capture --commit-safe --json
```

Out-of-band capture is labeled `capture_mode=out_of_band` because it loads the current filesystem state and cannot
reconstruct transient refreshes that already passed through the running TUI. The replay harness is scoped to the known
Agents-tab disappearance/reappearance and duplicate-parent bug class; it is not a general proof for arbitrary rendering
races.

For continuous diagnosis, press `,T` on the Agents tab to enable invariant checks after each load/apply cycle. On the
first violation in a burst, ACE auto-captures one bundle under `~/.sase/repros/<timestamp>-auto-.../` and shows a
warning toast. It does not write a new bundle every refresh while the same violation remains active.

### Bang Mode (`!` prefix)

| Key  | Action                               |
| ---- | ------------------------------------ |
| `!!` | Run background command               |
| `!x` | Start / stop axe (or select process) |

### Copy Mode (`%` prefix)

| Key  | Action                                                                                      |
| ---- | ------------------------------------------------------------------------------------------- |
| `%c` | Copy chat file path                                                                         |
| `%E` | Copy file path                                                                              |
| `%n` | Copy the focused agent's `agent_name` (falls back to `display_name`; toast indicates which) |
| `%p` | Copy agent prompt                                                                           |
| `%s` | Copy sase ace snapshot                                                                      |

## Keybindings: Axe Tab

### Sidebar Row Taxonomy

The Axe sidebar renders three row types so the operational tree reads at a glance:

- **Lumberjack** rows are top-level sections with a solid left accent bar (`▌`) in the lumberjack hue, a `[*]` / `[!]` /
  `[·]` running/error/idle marker, the lumberjack name, and an optional compact `Nc / Ne` cycles/errors chip at the end.
- **Chop** rows are child rows indented under their parent with a `  └─` tree connector, a per-run status icon (`✓`
  success, `!` failure/timeout, `?` missing script, `●` running, `*` agent-launched, `·` no runs), and the chop name in
  a dim-gold child hue.
- **Background command** rows (run via `!!`) live below the lumberjack tree, separated by a dim divider line when both
  groups are present, and use a distinct command/slot badge so they cannot be mistaken for scheduled AXE work.

### Dynamic Sidebar Width and No-Wrap Rows

Every sidebar row is rendered as single-line Rich `Text` with `no_wrap=True` and `overflow="ellipsis"`. After each
refresh the widget computes the widest formatted row and emits a `WidthChanged` message; the AXE container resizes
between a 35-cell minimum and an 80-cell maximum, clamped further so the right-hand dashboard always keeps at least 40
cells. On terminals too narrow to fit a label even at the clamped width, the row ellipsizes rather than wrapping onto a
second line.

### Controlled-Output Highlighting and ANSI Fallback

Output in the dashboard right panel uses a semantic highlighter for sources whose shape is controlled by sase, and falls
back to ANSI rendering for everything else:

- **Lumberjack aggregate logs** (`[YYYY-MM-DD HH:MM:SS] [lumberjack] message`) get timestamp, lumberjack name, status
  words (`success`, `failure`, `timeout`, `running`, `error`, …), PIDs, durations, exit codes, and counts colored by
  severity and consistent with the sidebar taxonomy.
- **Controlled chop output** — runner lifecycle lines such as `Launched proposal 1 as <name> (PID <pid>)` use the same
  status-word, PID, duration, and count highlighting as other lumberjack messages.
- **External chop scripts** and **background command output** are arbitrary text and stay on the ANSI fallback
  (`Text.from_ansi`) with the existing capping and tail-biased caching behavior.

Render cache slots are keyed on `(source_id, source_type)` so the semantic and ANSI paths cannot collide for the same
numerical identity.

### Navigation

| Key                 | Action                                                                        |
| ------------------- | ----------------------------------------------------------------------------- |
| `j` / `k`           | Move to next / previous sidebar row (lumberjack, chop, or background command) |
| `Ctrl+N` / `Ctrl+P` | Page through the focused chop's run history (newer / older)                   |
| `g`                 | Scroll to top                                                                 |
| `G`                 | Scroll to bottom (pins auto-scroll)                                           |

### Commands

| Key | Action                                                                                    |
| --- | ----------------------------------------------------------------------------------------- |
| `+` | Run agent                                                                                 |
| `r` | Run selected chop manually, or re-run the focused completed background command (`!!`) row |
| `x` | Start / stop axe (or kill the focused background command)                                 |
| `X` | Clear output                                                                              |

### Leader Mode (`,` prefix)

| Key  | Action                                                                               |
| ---- | ------------------------------------------------------------------------------------ |
| `,,` | Repeat the last leader command                                                       |
| `,h` | Run agent from home prompt context; bare prompts default to `#git:home`              |
| `,m` | Open the Models panel (view/manage model aliases; see [Models Panel](#models-panel)) |
| `,U` | Update sase, core, and plugins (opens Updates confirmation prompt)                   |
| `,R` | Show runners info                                                                    |
| `,?` | Open the current tab's guide modal                                                   |

### Bang Mode (`!` prefix)

| Key  | Action                               |
| ---- | ------------------------------------ |
| `!!` | Run background command               |
| `!x` | Start / stop axe (or select process) |

### Copy Mode (`%` prefix)

| Key  | Action                 |
| ---- | ---------------------- |
| `%o` | Copy visible output    |
| `%O` | Copy full output       |
| `%s` | Copy sase ace snapshot |

### Axe Control

| Key | Action            |
| --- | ----------------- |
| `Q` | Stop axe and quit |

## Query System

### Editing Queries

Press `/` to open the query editor. The current canonical query is pre-filled.

To save a query, prefix with `#`:

- `#3 "myproject"` -- save to slot 3
- `# "myproject"` -- save to next available slot
- `#3` (no query) -- delete slot 3

### Saved Queries

On the PRs sub-tab, press `*` to open the saved-query chooser. Press a populated slot (`1`–`9`, then `0`), move with
`j`/`k` or the arrow keys and press `Enter`, or click a row. `q`/`Esc` closes the chooser without changing the query.
The chooser shows the saved query text and marks the active query; an empty chooser also repeats the save syntax. Bare
digits no longer load saved queries, and the chooser is unavailable from Agents, Axe, Commits, Bugs, and Plans.

### Query History

| Key | Action                                |
| --- | ------------------------------------- |
| `^` | Navigate to previous query in history |
| `_` | Navigate to next query in history     |

Query history is available on the PRs sub-tab and tracks queries as you switch between them.

See [`docs/query_language.md`](query_language.md) for the full query syntax reference, including boolean expressions,
status shorthands, property filters, and searchable fields.

## Global Keybindings

These work on all tabs:

| Key                 | Action                                                                                           |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| `Tab` / `Shift+Tab` | Switch between Agents, Artifacts, and Axe tabs                                                   |
| `#`                 | Open SASE Admin Center (Config, Logs, Projects, Tasks, Updates, XPrompts; `1`–`6` jump to a tab) |
| `.`                 | Toggle visibility of hidden items (reverted PRs, non-run agents, or axe commands)                |
| `:` / `;`           | Open the context-aware [Command Palette](#command-palette)                                       |
| `i`                 | Show notifications inbox                                                                         |
| `Ctrl+G`            | Open the agent editor pre-filled with the most recent VCS xprompt prefix                         |
| `Ctrl+L`            | Dismiss all currently-visible toast notifications                                                |
| `@`                 | Open the stashed-prompt restore picker                                                           |
| `Q`                 | Open the quit / restart menu                                                                     |
| `y`                 | Refresh current tab                                                                              |
| `q`                 | Quit                                                                                             |
| `?`                 | Show help modal                                                                                  |

### Quit / Restart Menu

Pressing `Q` opens the **quit / restart menu**. When background tasks are still running, the menu warns inline with the
count that leaving will stop (`N background tasks will be stopped`), and it offers three actions:

- `1` / `s` — quit ACE and stop the axe daemon
- `2` / `r` — restart the TUI, leaving axe running
- `3` / `a` — restart the TUI and restart axe

Press `esc` (or `q`) to cancel and return to the TUI.

A plain `q` quits ACE directly. When background tasks are still running, `q` first shows a confirmation dialog listing
the active tasks and asks whether to kill them and quit; declining returns to the TUI.

## Command Palette

Press `:` or `;` from any tab to open the **Command Palette** — a context-aware modal listing every keymapped action
that is currently runnable. The palette is the discovery surface for the TUI: rather than memorizing every chord, you
can search by command label, key sequence (e.g. `%n`, `,A`, `zc`), category, or alias.

**Behavior:**

- Only commands applicable to the current tab and selected entry are shown by default. For example, PR diff appears only
  when a PR is selected; AXE start/stop appears only on the AXE tab; agent-specific actions appear only when an agent
  row (not a group banner) is focused.
- Each row shows the keybinding, the command label, and a category badge such as `Navigation`, `PR Actions`,
  `Agent Actions`, `Copy`, or `Leader`.
- A title-bar badge (`Agents`, `Artifacts`, or `AXE`) reflects the current tab.

**Keybindings inside the palette:**

| Key                 | Action                                       |
| ------------------- | -------------------------------------------- |
| `Type`              | Filter commands (case-insensitive substring) |
| `↑` / `↓`           | Move highlight                               |
| `Ctrl+P` / `Ctrl+N` | Move highlight                               |
| `Enter`             | Run the highlighted command                  |
| `Esc`               | Close without running anything               |

The palette delegates execution to the same handlers that the keybindings use, so behavior matches pressing the chord
directly. Selecting a built-in mode subcommand (e.g. `%n` to copy an agent name) runs the action without forcing you
through the transient prefix mode. Custom modes defined in `sase.yml` are also represented per-command.

The `:` / `;` binding follows your configured keymap. To rebind it, set `ace.keymaps.app.open_command_palette` in
`~/.config/sase/sase.yml`; comma-separated keys in that setting are treated as alternate bindings for the same action.

## Projects Tab

Open the SASE Admin Center with `#` and switch to the **Projects** tab with `3`, `[` / `]`, or the main tab strip. The
tab contains a second clickable strip: **Projects · Repos · Workspaces**. `[` / `]` cycle these sub-tabs while `Tab` /
`Shift+Tab` continue switching the main Admin Center tabs.

The **Projects** sub-tab lists true, non-system projects only, with enabled projects first and disabled projects still
visible. Here, "true project" means a project backed by its own main ProjectSpec, rather than an internal linked-repo
backing record; a true project can be enabled or disabled. Rows show the display/canonical name, VCS kind (`git` or
`gh`), lifecycle state, active claims, workspace/repo counts, and warnings. Telemetry-only directories and linked-repo
backing records cannot appear.

| Key       | Action                                                              |
| --------- | ------------------------------------------------------------------- |
| `j` / `k` | Move selection                                                      |
| `/`       | Filter the current sub-tab                                          |
| `[` / `]` | Cycle Projects, Repos, and Workspaces sub-tabs                      |
| `r` / `w` | Show repos or workspaces pre-filtered to the highlighted project    |
| `Enter`   | Run the highlighted project's default lifecycle action              |
| `m` / `u` | Toggle one mark / clear all marks                                   |
| `e` / `A` | Edit the ProjectSpec / aliases                                      |
| `a` / `d` | Enable / disable the highlighted project or marked set              |
| `Ctrl+D`  | Delete the highlighted SASE project directory or marked directories |
| `F`       | Force the last blocked disable after confirming live-work checks    |
| `R`       | Reload records or the current inventory                             |
| `p`       | Open the shared project picker on the Repos or Workspaces sub-tab   |
| `Esc`     | Clear an inventory project filter; otherwise close the Admin Center |
| `q`       | Close the SASE Admin Center                                         |

When one or more projects are marked, `a`, `d`, and `Ctrl+D` target the marked set instead of only the highlighted row.
Successful lifecycle changes clear the affected marks; blocked or failed rows stay marked so you can inspect or retry
them. Disabling uses the same locked mutation path as `sase project disable`; live `RUNNING` claims or artifact markers
block it unless the `F` force retry is intentional.

The **Repos** sub-tab inventories every known primary, sidecar, linked, and opened external repo for enabled projects by
default. Rows show owning project, checkout presence, and path; details include source, description, `auto_clone`,
environment name, and SDD storage mode. The **Workspaces** sub-tab joins every registry entry with its claim, PID
liveness, pin, last-used time, TTL staleness, and checkout presence. Missing checkouts point to `sase workspace repair`,
and dead claims are warning-styled. Both sub-tabs load off-thread and show cached rows during refresh.

Press `p` on either inventory to choose all projects, an enabled project (`●`), or a disabled project (`○`). Explicitly
selecting a disabled project is how its repos/workspaces become visible. `/` then filters within that project scope;
`Esc` clears the scope. The picker is filterable by display name, canonical key, or state and shows repo/workspace
counts for each project.

`e` suspends ACE, opens the selected ProjectSpec in `$EDITOR` (falling back to `nvim`), holds the ProjectSpec edit lock
for the editor session, then reloads project records. In this panel, `Ctrl+D` asks for confirmation before deleting the
entire SASE project directory: ProjectSpecs, project-local config, artifacts, and related state under
`~/.sase/projects/<project>/`. Deletion is refused while the project still has `RUNNING` claims or live artifact
markers. It does not delete workspace checkouts, and system-managed projects such as `home` are excluded from the panel.

## Models Panel

Press `,m` from any tab to open the **Models** panel — one keyboard-driven surface for viewing and managing every model
alias: the implicit role aliases (`default`, `coder`, `<provider>_coder`, `epic_lander`, `big_epic_lander`,
`phase_worker`) and any user-defined `llm_provider.model_aliases.custom` entry.

Each row shows the alias name with a small kind badge (`default` / `role` / `<provider> coder` / `user`), its effective
provider/model as a provider-themed badge, and a state tag — `configured`, `implicit` / `implicit → @<fallback>`, or an
`override · <time> left` / `override · until cleared` chip when a temporary override is active. The top level is sorted
deterministically: `default`, the built-in `coders` bucket, `epic_lander`, `big_epic_lander`, `phase_worker`, then
custom buckets and ungrouped user aliases in alphabetical order.

The always-present `coders` bucket groups `coder` first and every registered `<provider>_coder` alias alphabetically.
Its collapsed row reports the member count and active overrides, while the description strip summarizes the distinct
effective models. Open any bucket with `l`, Right, or Enter; return with `h` or Left. Inside `coders`, each alias keeps
its own configured/implicit state and can be edited, reset, overridden, or cleared independently.

The two-line strip below the list explains the highlighted alias. Builtin aliases use fixed descriptions. User aliases
use `llm_provider.model_aliases.custom.<name>.description`; a malformed user alias without one shows that config path as
the fix.

Navigate with `j`/`k` (or arrows / `Ctrl+N` / `Ctrl+P`) and act on the highlighted alias:

| Key                   | Action                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------ |
| `l` / Right / `Enter` | **Open** the highlighted bucket                                                            |
| `h` / Left            | **Back** to the top level from an open bucket                                              |
| `o`                   | **Override** — set/change a time-bound temporary override (model picker → duration picker) |
| `x`                   | **Clear** — remove the temporary override on this alias                                    |
| `e`                   | **Edit** — change the persistent configured value (model picker / custom input → preview)  |
| `r`                   | **Reset** — unset the configured value back to its implicit fallback                       |
| `Esc` / `q`           | Close the panel                                                                            |

### Temporary overrides

`Edit` and `Override` open the shared model picker with an `ALIASES` group before the provider-grouped concrete models.
Alias rows show the exact `@name` token and its current effective provider/model; filter by either `@coder` or `coder`,
an alias kind or description, or the displayed target. For persistent edits, the current alias and any alias that would
introduce a direct or transitive cycle remain visible but unavailable with a concise reason. `Custom...` remains
available for concrete model strings and applies the same safety check to free-form `@alias` values.

`Override` continues from the picker to the duration picker (`15m`, `30m`, `1h`, `2h`, `4h`, `Until cleared`, or a
custom duration like `45m`, `1h30m`, `90m`). Press `t` in the duration picker to choose **Until a specific time**. The
focused time popup accepts local forms such as `5pm`, `5:30 PM`, `17:30`, `1730`, `today 5pm`, `tomorrow 9am`, and
`2026-07-12 09:00`. An undated clock means its next occurrence (later today or tomorrow); an explicit day/date must
still be in the future.

The popup previews the resolved weekday/date, local time and abbreviation, configured IANA timezone, and remaining
duration before Enter writes anything. Daylight-saving gaps are rejected; repeated fall-back times require an
offset-qualified ISO value such as `2026-11-01T01:30-04:00`. Invalid input stays focused with an inline explanation.
`Esc` goes back to the duration picker, where a second `Esc` cancels the override flow. Overrides are per-alias and
independent:

- An override on **`default`** drives the no-`%model` launch default and renders in the existing gold top-bar pill — its
  behavior is unchanged.
- An override on **any other alias** takes effect wherever that alias is resolved (e.g. `@coder`, `@phase_worker`), and
  is surfaced by a distinct, concise violet top-bar pill: a single active override renders as
  `Override @<alias> <time-left>`, and several render as an `Overrides ×N` count.

Overrides apply only to default selection: explicit prompt directives (`%model:codex/o3`,
`%model:opencode/anthropic/claude-sonnet-4-5`) and an explicit `provider_name` argument always win, already-running
agents keep their current provider/model, and an explicit `@default` reference always resolves to the configured default
(ignoring the `default` override). Override state is persisted to `~/.sase/llm_override.json` — shared across all sase
processes on the machine — and is best-effort self-cleaning: expired or malformed entries are pruned on next read.
`Until cleared` is a no-expiry mode — convenient, but still a _temporary_ state, not a permanent config edit. The
temporary override is independent of `SASE_MODEL_TIER_OVERRIDE`; a concrete override takes the full provider/model path,
while the tier override only applies when no concrete override is active.

Delegated launches (plan coder follow-ups and `sase bead work` phase/land agents) resolve through
[role aliases](llms.md#role-aliases-for-delegated-work) configured under `llm_provider.model_aliases.builtin`, all of
which fall back to `@default`, so a `default` override also moves delegated work unless a role alias pins it elsewhere.

### Persistent edits

`Edit` and `Reset` change the alias's value in `sase.yml` itself, written through the Rust-backed, source-preserving
config-edit path (comments and key order are preserved). The change is shown in a preview/confirm step before it is
written, and after a successful write the panel offers to **commit and push** it (`y`/`n`). With `use_chezmoi: true` the
edit targets the chezmoi source and the commit/push runs against the chezmoi repo followed by `chezmoi apply`; when the
target file is not in a git repo the commit offer is skipped and the file is simply written. An active temporary
override visually "wins" the effective-target column even after a persistent edit; the state tag distinguishes the
_configured_ value from the _currently effective (overridden)_ one.

Selecting an alias during `Edit` stores the raw reference (for example, `@big_epic_lander` → `@coder`), so it remains a
dynamic link and follows future changes to `@coder`. Selecting an alias during `Override` instead resolves it when the
override is written and stores that concrete provider/model snapshot together with the raw token; later changes to the
referenced alias do not change the active override.

Builtin aliases edit under `llm_provider.model_aliases.builtin.<name>`. User aliases under
`llm_provider.model_aliases.custom.<name>` edit their `model` field and reset by deleting the whole custom alias entry.

### Examples

- Highlight `default`, `o`, pick `codex/o3`, duration `1h` — default launches use Codex `o3` for the next hour, then
  revert to the configured default.
- Highlight `coder`, `o`, pick a model, then `t`, enter `5pm` — the preview resolves the next 5:00 PM in the configured
  timezone and the override expires at that exact instant.
- Highlight `phase_worker`, `o`, pick `claude/opus`, `Until cleared` — `@phase_worker` resolves to CLAUDE(opus) until
  you clear it; the violet non-default pill appears in the top bar.
- Highlight `big_epic_lander`, `e`, pick a model, and confirm — only threshold-selected epic landers use that persistent
  target; leaving it implicit preserves the `@epic_lander` target.
- Highlight `big_epic_lander`, `e`, filter for `@coder`, select it, and confirm — the persistent value is the dynamic
  `@coder` reference, not a copied concrete model.
- Highlight `phase_worker`, `o`, select `@coder`, then choose `1h` — the override records the concrete provider/model to
  which `@coder` resolves at write time while retaining `@coder` as its raw input.
- Highlight `coder`, `e`, pick a model, confirm the preview, then `y` — the configured
  `llm_provider.model_aliases.builtin.coder` value is updated and committed (and pushed / `chezmoi apply`-ed when
  `use_chezmoi` is set).
- Highlight an alias, `x` — clear its temporary override; `r` — unset its configured value back to its implicit
  fallback.

See [docs/llms.md](llms.md#temporary-model-overrides) for the resolution order and state-file format.

## Notifications Modal

Press `i` (or the `,n` leader chord to jump straight to an agent's notification) to open the notifications modal. See
[`docs/notifications.md`](notifications.md) for the full keybinding reference, modal tabs, priority/error/muted
classification, and the per-notification snooze and mute affordances.

Rows and the detail header begin with the notification's single-glyph icon when one is present, with a per-action
fallback icon otherwise. The text action badge remains visible as the secondary label.

Press `d` on the highlighted inbox row to open Gate Debug, even when the row is not gate-backed or its gate modal can no
longer load. The same `d` binding is available inside plan/epic approval, user-question, launch-approval, custom-gate,
and workflow HITL panels. Gate Debug presents Overview, Request, Response, Errors, and raw Row tabs; `[` / `]` switch
tabs, `y` copies the current tab, `Y` copies the bundle path, `e` opens the backing file, and `d`, `q`, or `Esc` closes
the overlay without losing state in the underlying panel.

The top-bar notification indicator color reflects the highest-priority unread bucket: orange for unmuted priority or
error notifications (plan approvals, launch approvals, user questions, mentor reviews, axe errors, CRS results, agent
error reports), gold for regular unmuted notifications, and cyan when only muted or snoozed notifications remain. A
trailing dot means muted unread rows also exist while the badge is showing the actionable count.

## Notification Actions

Some notifications carry an `action` field that triggers a handler when the notification is selected. The following
notification action types are supported:

| Action               | Source          | Behavior                                                                        |
| -------------------- | --------------- | ------------------------------------------------------------------------------- |
| `CustomGate`         | Agent/tool      | Opens the generic choices, add-ons, and feedback modal                          |
| `HITL`               | Workflow        | Opens the workflow human-in-the-loop response modal                             |
| `JumpToAgent`        | Agent/workflow  | Jumps to the matching Agents-tab row                                            |
| `JumpToChangeSpec`   | Sync/workflow   | Jumps to the referenced ChangeSpec on the PRs sub-tab                           |
| `JumpToMentorReview` | Mentors         | Jumps to the ChangeSpec and opens mentor review output when available           |
| `LaunchApproval`     | Agent           | Opens the launch approval modal for an agent-requested launch                   |
| `PlanApproval`       | Agent           | Opens the plan approval modal                                                   |
| `Tmux`               | External bridge | Runs `tm <workspace-name>` for the notification's `action_data.workspace_dir`   |
| `UserQuestion`       | Agent           | Opens the structured user-question response modal                               |
| `ViewErrorReport`    | Axe/agent       | Opens `action_data.error_report_path`, or the first attached file, in `$EDITOR` |
| `memory_review`      | Memory          | Suspends ACE and opens the memory proposal review TUI at that proposal          |

The axe `error_digest` chop creates `ViewErrorReport` notifications whose digest files live under
`~/.sase/axe/error_digests/digest_<timestamp>.txt`; user-agent failures can use the same action for their own attached
error reports. Memory proposal notifications created by `sase memory write --notify` use `memory_review` with
`action_data.proposal_id`. Selecting one opens the same review UI as `sase memory review`, preselected on that proposal;
approval or rejection still happens inside the review UI.

The custom-gate modal shows the sender and notes or verified preview, one icon-led button per terminal choice,
checkboxes for that choice's independently selectable add-on commands, and a feedback input. Required feedback blocks
submission until non-empty text is present; optional and disabled modes adjust the affordance accordingly. Unsupported
future actions produce a warning instead of silently doing nothing.

Custom gates and neutral HITL gates execute through the shared hash-verifying gate executor. ACE schedules the terminal
command and each selected add-on through the tracked background-task queue, streams live stdout/stderr to the task,
shows each command as a reporter phase, and refreshes the inbox when the task completes. Legacy HITL bundles retain the
direct response-file fallback.

### Toast Notifications

Each newly-arrived notification produces a short toast in the TUI. The toast text is derived per-action type (plan,
question, HITL, axe error, ChangeSpec sync, agent update) so the message previews the actual event rather than a generic
"N new notification(s)" line. Severity is also picked per type: plans, questions, and HITL render as warnings; axe
errors (and sync failures) render as errors; everything else renders as information.

When more than 3 notifications arrive in the same poll tick, per-notification toasts are consolidated into one grouped
toast per severity bucket (e.g., `2 warnings: 1 plan, 1 question`). Ordering is urgency-first: errors, then warnings,
then information. Silent notifications are excluded from this pipeline entirely.

Agent completion and failure toasts include the `%name`-set agent name with an `@` prefix when present (e.g.,
`CLAUDE(opus) @sase-q.land completed: ace(run)-...`); anonymous agents (no `agent_name`) keep the prior format.

## XPrompt Browser

Press `#` on any tab to open **SASE Admin Center**, then switch to the **XPrompts** tab with `[` / `]` or the tab strip.
The XPrompts tab displays all discovered xprompts in a two-panel layout: a filterable list on the left and a
syntax-highlighted preview on the right.

Xprompts are grouped by source (project `sase/xprompts/`, home `~/sase/xprompts/`, project-specific home, config
`sase.yml`, plugins, built-in, plus labeled legacy compatibility sources). Workflow xprompts (multi-step YAML) are
marked with a gear icon; standalone workflows are displayed with the `#!name` insertion syntax. Project-local xprompts
defined in each project's `sase.yml` file are also included, even though the TUI's normal config loading does not read
project-local config files.

The list rows and preview metadata show the same insertion form and visible input metadata used by `Ctrl+T` completion.
Step-only inputs are hidden from this user-facing surface because they are supplied by workflow execution rather than
typed by the user.

### Keybindings

| Key       | Action                                                |
| --------- | ----------------------------------------------------- |
| `j` / `↓` | Navigate to next xprompt                              |
| `k` / `↑` | Navigate to previous xprompt                          |
| `Ctrl+N`  | Navigate to next xprompt                              |
| `Ctrl+P`  | Navigate to previous xprompt                          |
| `Ctrl+D`  | Scroll preview panel down                             |
| `Ctrl+U`  | Scroll preview panel up / clear input                 |
| `Enter`   | Edit highlighted xprompt in `$EDITOR`                 |
| `Ctrl+O`  | Add a new xprompt                                     |
| `Ctrl+I`  | Load the highlighted xprompt into the home prompt bar |
| `Esc`     | Close SASE Admin Center                               |

Type in the filter input to narrow the list in real time.

### Editing XPrompts

Press `Enter` on any xprompt to edit it in `$EDITOR`. All xprompts are editable, including legacy, plugin, and built-in
sources — read-only sources are copied to the canonical user directory (`~/sase/xprompts/`) before opening, so edits
create an override rather than modifying the original. After saving, the browser offers to commit and push changes to
git if applicable.

### Creating XPrompts

Press `Ctrl+O` to start the guided creation flow:

1. **Location modal** — Choose where to save the new xprompt (project `sase/xprompts/`, home `~/sase/xprompts/`, project
   `sase/sase.yml`, or a global config file). Legacy sources remain browseable but are never new-write destinations.
   Press `Ctrl+G` to open the selected config file in `$EDITOR` instead of proceeding with creation.
2. **Filename modal** — Enter a filename (`.md` for prompt parts, `.yml` for workflows). Workflow files are pre-filled
   with a YAML template containing the workflow scaffold.
3. **Editor** — The file opens in `$EDITOR` for editing.
4. **Git commit** — After saving, the browser offers to commit and push changes.

## Jump All Modal

Press `` ` `` (backtick) on any tab to open the Jump All Modal. It displays all entries across Agents, Artifacts, and
Axe tabs with single-keypress hint characters for instant navigation. Selecting an entry switches to the appropriate tab
and focuses it.

Hint characters are drawn from an extended alphabet — lowercase `a`–`z` first, then uppercase `A`–`Z` — so modals with
many entries can still fit a unique single-keypress hint per row without resorting to multi-character hints.

| Key         | Action                          |
| ----------- | ------------------------------- |
| Hint char   | Jump to the corresponding entry |
| `Esc` / `q` | Close modal                     |

The modal groups entries by tab (Agents, Artifacts, Axe) and shows contextual information for each: PR names and
statuses, agent names with running indicators, and Axe lumberjack/command labels.

### Jump Back

Both jump modals support a jump-back feature for toggling between two entries:

- **Backtick jump-back**: Pressing `` ` `` inside the Jump All Modal returns to the previous position, enabling quick
  toggling between two entries across tabs.
- **Apostrophe jump-back**: Pressing `'` twice (`''`) in the single-tab entry jump mode jumps back to the previously
  jumped-from entry. The footer shows a "JUMP" mode indicator with `' back` when a target exists.
- **Fast jump**: `Ctrl+O` runs the same current-tab jump-back path without painting hints first; when no jump-back
  target exists, it selects the first current-tab hint.

The single-tab variant (`'` apostrophe) shows entries only from the current tab with the same hint-character navigation.

## Mentor Comment Stats in PR List

When a ChangeSpec has completed mentor reviews with comments, its PRs sub-tab list entry shows inline stats:

- **checkmark + count** (e.g., `✓3`) — number of accepted comments
- **dot + count** (e.g., `●2`) — number of unread comments

These stats are computed from the latest commit entry's finished mentors. They update as you accept or read comments in
the Mentor Review modal.

## Tab Bar Display

The tab bar renders plain tab labels (`Agents`, `Artifacts`, `AXE`). Per-bucket counts live inside each tab's body — for
example the per-panel count summaries on the Agents tab — rather than as suffixes on the tab title itself.

### Background Task Indicator

A gear icon (⚙) with a count appears in the top bar when background tasks are running (e.g., sync, mail, accept, and
notification-gate operations). The indicator automatically hides when all background tasks complete.

### Runners Modal

Press `,R` (leader + `R`) to open the runners modal. It shows concurrency information including hook runners, agent
runners, and a **Background Tasks** section listing active and recently completed background tasks (sync, rebase,
accept, mail, add-tag, notification gates). Each task entry shows its type, target, status, timestamps, and live output
when the task reports it.

## File Panel Rendering

Agent files render in full and scroll natively in the file panel. Syntax highlighting falls back to plain text for large
content. Pathological outputs above the file-panel safety limit show the first 5,000 lines and an explicit editor
notice; press `E` to open the complete content.

## Agents Zoom Panel

Press `z` on the Agents tab to open a near-fullscreen view of the active detail panel. The header shows the available
panel tabs (`METADATA`, `FILE`, `TOOLS`) with the active panel highlighted; use `]` / `[` to cycle those panels with
wrap-around.

When the zoom modal shows files, the file list is fixed for the life of that modal so refreshes cannot add, remove,
reorder, or jump the selected file. Use `Ctrl+N` / `Ctrl+P` to cycle files with first-to-last wrap-around. Multi-file
views show a left rail listing every frozen file entry and marking the active one; single-file views use the full width
for content.

Inside the zoom modal, `/` starts forward search, `?` starts backward search, and typed queries jump to the first match
as you type. Press `Enter` to keep the highlighted matches, then use `n` / `N` to move to the next / previous match with
wrap-around feedback.

Search covers the complete text behind the zoomed panel, including content beyond the pathological render cap. `Esc` or
`Ctrl+C` cancels an in-progress search; after a search is committed, `Esc` leaves search and returns to the normal
zoomed panel.

## Image Preview Foundation

ACE renders PNG, JPEG, WebP, and GIF attachments with a Pillow-backed Rich cell preview. The renderer decodes the first
image frame, preserves aspect ratio within the visible panel bounds, composites transparency, and paints colored
half-block cells using truecolor when the terminal advertises it and 256-color approximations otherwise.

Generated images are already attached to successful agent completion notifications and recorded in `done.json` as
`image_paths`. The Agents tab file panel and notification modal route supported raster image attachments through this
preview layer before attempting text decoding. See [`agent_images.md`](agent_images.md) for supported image extensions,
guardrails, and current preview behavior.

## Agent Auto-Naming

Prompts with no `%name` directive, or with a bare `%name`, use the plain auto-name template `@`. SASE reserves the
lowest available token from the sequence `0`, `1`, ..., `9`, `a`, ..., `z`, `00`, `01`, ...; with no reserved names,
plain auto-naming yields concrete names such as `0`, then `1`.

An explicit `%name` value containing exactly one `@` marker is an agent-name template. SASE substitutes the same token
sequence into the marker, so the first allocation for `%name:@.cld` becomes `0.cld`, `%name:build-@` becomes `build-0`,
and `%name:research.@.final` becomes `research.0.final`. Later `%wait`, `#fork`, and `#resume` references can use the
same template text; within a multi-agent launch, SASE rewrites those references to the concrete name already planned for
that template.

Names are permanent IDs: a name used by any existing agent state remains reserved until that agent is explicitly wiped
or deleted. This enables the fork-by-name workflow: press `f` on a running named agent to queue a follow-up that waits
for it to finish and then loads its conversation history.

### Provider/Model Suffixes

When the same base name is shared by multiple co-launched agents (e.g. multi-model fan-out via the `%model:` directive),
the rendered display name carries a short `.<provider>` or `.<provider>(<model>)` suffix so each row is distinguishable.
Provider suffixes are supplied by the LLM provider plugins via the `llm_provider_short_name` hook (built-in defaults:
`cld` for Claude, `cdx` for Codex, `agy` for Antigravity). Additional provider plugins can contribute their own short
names. Model-name shorthands come from the `llm_model_short_aliases` hook (e.g. `fable` for `claude-fable-5`, `gpt56sol`
for `gpt-5.6-sol`; see [Model Short Aliases](llms.md#model-short-aliases)) and are resolved against the configured model
so the suffix stays compact regardless of how the model was spelled in the prompt or config. Single-runtime spawns omit
the suffix.

An explicit `%name:<name>` launch fails before spawning if `<name>` is already reserved. The prompt is saved as a
cancelled history entry and the error suggests the lowest free numeric suffix, such as `<name>1`. To deliberately reuse
a reserved name from the TUI, launch with `%name:!<name>`; the `!` form confirms that SASE should wipe the previous
owner and then claim the name for the new agent. Reviving and dismissing agents preserve their stored names.

The durable registry lives at `~/.sase/agent_name_registry.json` and is rebuilt from visible artifacts plus dismissed
bundles when missing or stale. Use `sase agent names migrate-auto` to run the historical auto-name migration that moves
older generated names into the permanent namespace; pass `--force` to rerun after the migration marker is present or
`--json` for machine-readable output.

### Per-Step Naming for Multi-Agent Workflows

Sequential plan-family workflows have a stable family container plus member suffixes. When the first follow-up attaches,
the original agent is renamed and the bare family name becomes a pure container. Generated follow-up rows and phase
metadata use canonical double-dash suffixes. For example, if the initial agent was named `a`:

1. The first attachment creates family container `a` and gives the original its persisted role suffix (`a--plan` for a
   plan proposer or `a--0` for a generic agent).
2. The planner phase uses a canonical `--plan` role suffix.
3. Feedback and question-continuation rounds become `a--2`, `a--3`, etc.
4. Terminal follow-ups use the phase suffix, such as `a--code`, `a--epic`, or `a--commit`.

The base name (`a`) is reserved for the family as a whole, so `%wait:a` or `@a` references resolve through the family
container. New plan-family metadata stores double-dash `role_suffix` values (`--plan`, `--2`, `--code`, ...). ACE still
canonicalizes older dotted suffixes (`.plan`, `.2`, `.code`, etc.) and legacy single-dash suffixes (`-plan`, `-2`,
`-code`, etc.) when reading legacy artifacts.

## Agent Statuses

Each agent in the Agents tab displays a status label indicating its current state. Statuses fall into two categories:
active (the agent is still running or awaiting input) and completed (the agent has finished).

### Active Statuses

| Status             | Color        | Description                                                         |
| ------------------ | ------------ | ------------------------------------------------------------------- |
| **RUNNING**        | Gold         | Agent subprocess is executing                                       |
| **WAITING**        | Light blue   | Agent is queued, waiting for another agent to succeed (`%wait`)     |
| **WAITING INPUT**  | Amber/orange | Workflow is paused at a human-in-the-loop (HITL) step               |
| **PLAN**           | Pink/magenta | Agent has produced a plan and is waiting for user approval          |
| **PLAN APPROVED**  | Cyan         | Plan was approved; follow-up agent has been spawned                 |
| **EPIC APPROVED**  | Cyan         | Plan was approved as an epic; `--epic` follow-up is running         |
| **PLAN COMMITTED** | Cyan         | Plan was approved with auto-commit; `--commit` follow-up is running |
| **QUESTION**       | Amber        | Agent is asking the user a question (via `/sase_questions`)         |
| **RETRYING**       | Orange       | Agent hit a retryable error and is in a countdown before retrying   |

`QUESTION` status survives notification dismissal. While an agent is waiting for an answer it writes a
`pending_question.json` marker into its run directory and temporarily yields its root runner slot. The marker remains
until the agent reacquires capacity after an answer, or until the agent is killed or crashes. If capacity is full after
the answer, the row becomes a normal runner-slot `WAITING` row before follow-up work resumes. Any otherwise-active row
whose own run directory contains an unanswered marker is shown as `QUESTION`, so the "waiting on you" status keeps
appearing even after you dismiss the matching question notification from the inbox. The `,n` shortcut (jump to the open
question) reads the marker directly when no unread notification is left, so it can still reopen the question modal.

`QUESTION` also propagates up agent families. When a completed row recorded a question (`questions_times` is non-empty)
but has neither a persisted `question_response_path` nor a later follow-up child, the parent workflow row inherits
`QUESTION` so the family still shows as waiting on you. Once the user response is persisted, the continued work usually
appears as the next numeric phase (`--2`, `--3`, ...); `--q` identifies the question phase in metadata and phase labels.
On the next status pass, the parent is re-evaluated without the stale question override. If the parent has several
active children, the most recently started one wins, so a newer `RUNNING` child can overtake the `QUESTION` override on
the parent.

The keybinding footer renders available conditional actions as non-breaking key/label chips. When the chips do not fit
on one line, the footer switches to a deterministic grid so narrow terminals and leader-mode action sets do not wrap in
the middle of a binding. Mode labels such as `LEADER` are pinned on the left, and the axe/status indicator remains
pinned on the right. The status is a segmented badge with a neutral `AXE` label chip before the colored state chip, so
the indicator always identifies the daemon it describes.

The footer also shows axe daemon status indicators:

| Status         | Color         | Description                                                  |
| -------------- | ------------- | ------------------------------------------------------------ |
| **RUNNING**    | Green         | Axe daemon is running normally                               |
| **STOPPED**    | Red           | Axe daemon is not running                                    |
| **STARTING**   | Yellow        | Axe daemon is starting up                                    |
| **STOPPING**   | Yellow        | Axe daemon is shutting down                                  |
| **RESTARTING** | Deep sky blue | Axe daemon is restarting (triggered by `--restart-axe` flag) |

During TUI startup the footer slot shows a live **starting** stopwatch with a rotating glyph in place of the daemon
status, ticking at ~10 Hz until the TUI finishes mounting and the real axe status resolves. The background color turns
from its normal tone to a slow-startup tone once the elapsed time crosses the slow threshold, giving immediate visual
feedback on cold-start latency. A safety timeout forcibly retires the stopwatch if the mount signal never fires.

### Completed Statuses

| Status           | Color | Description                                                                    |
| ---------------- | ----- | ------------------------------------------------------------------------------ |
| **DONE**         | Green | Agent completed successfully                                                   |
| **PLAN DONE**    | Green | Plan workflow fully completed (all steps)                                      |
| **TALE DONE**    | Green | Tale plan workflow fully completed (all follow-ups)                            |
| **EPIC CREATED** | Green | Plan workflow completed and its latest `-epic` follow-up finished successfully |
| **FAILED**       | Red   | Agent exited with an error                                                     |

Completed agents can be dismissed with `x` on a single row, or through the `X` cleanup panel for focused-panel, global,
tag, marked, group, and custom selections. `DONE`, `PLAN DONE`, and `TALE DONE` rows with a saved response path are
resumable from the Agents tab.

When a terminal agent becomes unread, ACE marks it with the completed-agent indicator and includes it in the Agents
header unread count. Selecting that row, jumping to it with `,j`, or toggling it back to read with `U` acknowledges the
row and dismisses the matching user-agent completion notification. Manually marking a row unread with `U` arms it for
normal acknowledgement after you move away and return, so the marker can be used as a short-lived reminder without
leaving stale inbox entries.

If the currently focused row finishes while you are already on the Agents tab, ACE still marks it unread and keeps the
completion notification active until a real navigation or selection event acknowledges it. A refresh that merely
preserves focus does not silently consume the unread marker.

The `unread` count in the Agents header is drawn as black text on a gold pill so the "you still have unseen completed
work" signal stands out from the rest of the colored metrics. It uses the same gold tone as the top-bar notification
indicator, giving you a single color to scan for.

Switching to the Agents tab does not bulk-dismiss completion notifications. ACE projects active completion notifications
onto unread rows, then acknowledges rows one at a time when you select or navigate into a terminal unread row. Bulk
acknowledgement is explicit through `,u`, which marks loaded unread completed agents read. Plan approvals and user
questions are never auto-dismissed by this flow; they always require explicit `y` / `n` confirmation from their
respective modals.

### Agent Revival

Press `R` on the Agents tab to revive previously dismissed work. ACE opens the saved-group revival modal first, showing
newest saved groups with a right-hand preview of included agents, projects, PRs, statuses, provider/model labels, and
revival count. Select a group and press Enter to revive it, choose **Load more saved groups...** to page older groups,
or choose **Custom revival search...** to open the older dismissed-agent search where you choose all, home, project, or
PR scope manually.

Use `m` to mark related Agents-tab rows and then `s` to save and dismiss them as a group. The save modal accepts an
optional human name. Leaving it blank keeps the generated display title, such as "3 agents from @review" or "2 agents in
auth_retry". Saving a marked group hides the selected rows from the normal Agents tab without killing running processes.
When a marked top-level workflow row has child rows, ACE also includes the children in the saved group so revival can
restore the original tree.

Dismissed agents are saved as individual bundle files under month shards in `~/.sase/dismissed_bundles/YYYYMM/` and can
be restored later. Saved group metadata lives under `~/.sase/dismissed_agent_groups/` and stores stable references to
those bundle files plus the optional group name, status counts, projects, PRs, model/provider metadata, and tribes.
There is no limit on the number of dismissed agents or saved groups that can be stored.

Dismiss operations are O(1) per agent: each agent is saved to its own JSON file rather than a monolithic store. Parent
workflow rows use `<raw_suffix>.json`; workflow children use `<raw_suffix>__c<step_index>.json`. ACE keeps a SQLite
summary index in the dismissed-bundle directory so the revive modal and internal lookups can list dismissed agents
without opening every bundle. Use `sase agent archive verify` to check that maintenance index, or
`sase agent archive rebuild-index` to rebuild it from bundle files. The index stores metadata such as status, name,
project, model, provider, workflow, and ChangeSpec metadata; it is not a full-text copy of agent chat contents.

Revival removes the agent identity from the dismissed set, restores enough artifact files for ACE to rediscover the
agent, and preserves the dismissed bundle as historical recovery data. Saved-group revival skips missing bundle
references with a warning and restores the remaining agents. Group metadata is not deleted after revival; ACE marks the
group with `revived_at` and increments `times_revived` so the modal can show previous use. The reload path forces a
full-history scan and can hydrate the just-revived row directly from the bundle, so agents still appear after revive
even if the persistent artifact index was empty or stale.

Every revival also writes structured events to `~/.sase/logs/events.jsonl` (start, per-agent success, per-agent
failure). Read them back with `sase revive-log` — see [Agent revival audit log](troubleshooting/agent-revival.md) for
the record schema and CLI flags.

#### Legacy Dismissed-Name Prefix

Current dismiss and revive operations preserve stored agent names, per-agent tribes, and top-level/workflow-child
identity. Older dismissed bundles may still contain `YYmmdd.<base>` names from the previous dismissal model, and ACE
keeps compatibility helpers for reading those bundles. Bare `%wait` (no target) intentionally skips legacy
dismissal-prefixed candidates so it anchors on a live, visible agent.

## Agents Tab Metadata Panel

The Agents tab metadata panel (cycled to via `]`/`[`) shows structured information about the selected agent:

`Ctrl+J` and `Ctrl+K` cycle forward and backward through the rendered titled sections in this pane, with the true top of
the metadata document as a waypoint before the first title. On a fresh agent document, the first forward jump selects
the first title and the first reverse jump selects the final title. From the final title, `Ctrl+J` jumps to the document
top and another press selects the first title; from the first title, `Ctrl+K` jumps to the document top and another
press selects the final title. Both directions share one cursor. Each selected title is aligned with the first visible
metadata row, including a short final section, while the top waypoint reveals any ordinary header fields before the
first title. Only rendered section titles participate; matching text inside prompts or replies does not. The shortcuts
continue to target the metadata pane when a file or tools pane is also visible, and changing agents or entering/leaving
a pinned attempt view resets the cursor.

- **Agent details**: Name, status, model, provider, ChangeSpec association, and chronologically sorted timestamps:
  - `Bead` — shown for agents launched by `sase bead work`; modern phase rows use explicit epic/phase/plan launch
    metadata and validated plan frontmatter, while exact epic and legacy phase/`.land` rows retain compatibility
    inference
  - `WAIT` — when the agent was spawned (waiting for a slot)
  - `BEGIN` — when runner admission completed, before workspace preparation for root agents
  - `PLAN` — each plan proposal round (multiple entries when re-planning occurs)
  - `FBACK` — each time the agent requested feedback from the user
  - `QUEST` — each time the agent asked the user a question
  - `RETRY` — each time the agent entered retry state (retryable error)
  - `CODE` — when the agent began writing code
  - `EPIC` — when an epic follow-up agent was launched after plan approval
  - `DONE` — when execution completed
- **CLAN / MEMBERS**: Shown when a synthetic clan row is selected. The orchid heading and orchid `Name:` value match the
  clan row's identity block; the header also shows `@tribes`, rolled-up status counts, wall-clock runtime, and
  agent/family totals. Member rows are sorted by launch time and show the hood-relative suffix, kind, status, model, and
  duration; members of a nested sequential family are indented under its aggregate row. The section participates in `g}`
  / `g{` metadata-section navigation like the other titled sections.
- **SASE CONTEXT / PLAN**: Shown as the leading context lane for the epic-authoring planner and epic lander when direct
  metadata or a confirmed legacy epic association resolves a plan. Phase workers deliberately omit the lane and show
  only their one phase's `Bead` value; no goal, path, or other roadmap phases are rendered. For plan-bearing roles, the
  body rows are `Title`, `Goal`, and canonical `Path`, in that order. The lane header carries the effective tier
  (`plan`, `tale`, or `epic`) and an epic's phase count. An `approve` action displays `plan`, `tale` and legacy
  commit-only actions display `tale`, and an `epic` action displays `epic`, even when the corresponding commit or launch
  later fails. Without action metadata, a valid authored tale or epic supplies the tier; legacy committed plans without
  a readable authored tier display `tale`, and unresolved values display `tier unavailable`. Canonical path selection
  remains separate: committed paths are workspace-relative, while pending or explicitly uncommitted paths use the
  home-shortened machine-local archive. Valid authored epics then show every phase in authored order with its title, ID,
  dependency IDs, optional model, and optional description; these are static roadmap ordinals, not progress indicators.
  Every value wraps without truncation in the normal panel and metadata zoom view, and only the path participates in
  file hint mode. Invalid known epics show `phases unavailable` in the lane header without leaking partial entries;
  tales do not show a phase roadmap. A plan alone renders `SASE CONTEXT`; across every combination of present lanes, the
  full order is `PLAN`, `ARTIFACTS`, `MEMORY`, `SKILLS`, then `WORKSPACES`. `PLAN` is always first when present, and
  `ARTIFACTS` follows it directly; when `PLAN` is absent, `ARTIFACTS` is the leading present lane.
- **SASE CONTEXT / ARTIFACTS**: The plan-adjacent output lane groups `Commits`, `Deltas`, and `Artifacts` as compact
  fields, preserves that internal order, and summarizes only the present fields in its header. Commits persisted by the
  selected agent's post-run steps are grouped by repository; primary workspace, linked-repo, sidecar, and external-repo
  commits retain their repository identity. Deltas preserve their green `+`, gold `~`, and red `-` change glyphs and
  group linked or external files by repository. Artifact type remains visible through its icon shape, while every
  artifact icon and path uses the shared blue output-lane/file-path palette. The lane is rendered atomically with full
  header enrichment, so it is omitted from the immediate cheap navigation frame rather than appearing first with partial
  content.
- **Slow tool calls**: The metadata header lists tool calls that took 20 seconds or longer, ordered by start time and
  capped at 8 rows (an overflow line points to the full [Tools panel](#agents-tab-tools-panel) timeline via `]`). For a
  root agent the list aggregates calls across its children while attributing each call to the child that made it.
- **Wait state**: For an agent gated by `%wait`, a duration wait, or an absolute-time wait, the detail view shows a
  `Wait:` line. It lists the dependency names recorded on the waiting agent, adds per-name status badges for currently
  known agents, clan containers, or family containers, and marks unknown names with `?` so typos and stale references
  are obvious. Timed waits add compact duration, target time, and countdown text when available. The final runner-slot
  stage shows the live running count and cap or explicit threshold, plus position among waiters currently eligible at
  that count. Ineligible waits are labeled directly, and `runners=0` is labeled as a drain barrier.
- **OUTPUT VARIABLES**: Small string values written by the selected agent family with `sase var set KEY=VALUE`. A single
  contributing agent renders as a flat sorted key/value list; multiple family members render with compact role labels so
  root, planner, coder, tester, and follow-up values stay attributable. Multi-line values are indented, and the section
  is omitted when the family has not published variables. These values are stored in `agent_meta.json`, so they are
  visible metadata rather than secret storage.
- **AGENT REPLY**: The agent's live or completed reply content, streamed from `live_reply.md` during execution and read
  from the artifacts directory after completion. When per-turn reply timestamps are available (recorded in
  `live_reply_timestamps.jsonl`), the reply is displayed with timestamp dividers between each agent turn. For agents
  with follow-up phases (planner, feedback rounds, coder), the AGENT REPLY section consolidates replies from all phases
  into a single view with purple phase dividers showing each phase's label and start time. Phase labels are derived from
  canonical plan-family `role_suffix` values: `--plan` renders as `PLANNER`, `--code` as `CODER`, `--q` as `QUESTIONS`,
  `--epic` as `EPIC`, `--commit` as `COMMIT`, and numeric feedback suffixes such as `--2` as `PLANNER (round 2)`. Legacy
  dotted and single-dash suffixes render the same way.
- **WORKFLOW VARIABLES**: xprompt workflow output variables from step outputs with additional `meta_*` keys are grouped
  under a dedicated header. The special routing keys `meta_project`, `meta_changespec`, and `meta_workspace` are still
  promoted into the normal header fields; other metadata keys are title-cased and shown in this section.
- **PROMPT**: For agents launched from a multi-agent (`---`-separated) prompt, the final, planner, and question
  transcripts include a `PROMPT:` row linking the saved original launch prompt (stored under
  `~/.sase/.../multi_prompts/`), so the exact text that fanned out into every segment stays recoverable.

When the file or tools panel is empty, the `g`/`G` keys automatically fall back to scrolling the metadata panel.

## Agents Tab Tools Panel

The tools panel sits between the file panel and the metadata panel in the Agents-tab cycle (`]` advances forward, `[`
goes back). It shows a chronological timeline of the LLM tool calls the selected agent has made — file reads, edits,
bash invocations, web fetches, sub-agent launches, and so on.

Entries are read from the `tool_calls.jsonl` artifact in the agent's run directory. Each call renders as one timeline
row:

- A status label colored by outcome — `ok` (success), `fail` (error), `stop` (interrupted), `agent` (sub-agent launch),
  or `wait` (the post-call record has not arrived yet).
- The tool name, optionally followed by a compact target (such as the file path the tool acted on) and the call's
  duration.
- A short preview of the call result on the next line, when the collector captured one. Command-output previews keep a
  marked suffix with at least the final 50 logical lines; the character budget is soft so unusually wide trailing lines
  remain complete. Other preview types remain head-oriented.

The panel header shows the total call count, the failure count, the interrupted count, and a timestamp for the most
recent reload. While a background reload is in flight (because the artifact changed on disk), `(refreshing...)` appears
next to that timestamp. The body shows `No tools artifact available` when the file does not yet exist for this agent and
`No tool calls recorded` when the file exists but contains zero records.

For retry chains and planner-to-coder follow-up families, the panel aggregates `tool_calls.jsonl` from related artifact
directories so the selected logical agent shows one ordered tool timeline. Discovery uses the persistent artifact index
when it is available; if the index is missing or stale, ACE falls back to direct lineage pointers plus a bounded scan of
nearby legacy sibling artifacts.

Records are produced by writers that share one normalized on-disk format. Claude uses the SASE tool-call hook collector
as the preferred source and keeps its stream-derived parser as a fallback when hooks are unavailable. Codex writes
equivalent rows from its `codex exec --json` stream with `runtime: "codex"` and `source: "stream"`; current Codex
start/completion events can show pending rows, result previews, failures, interruptions, and durations, while older
completed-only `function_call` rows remain readable with more limited detail. Qwen writes stream-derived rows from its
`--output-format stream-json` output with `runtime: "qwen"` and `source: "stream"`; start/completion (and Qwen's
`tool_use` / `tool_result`) pairs collapse into single rows the same way Codex pairs do. Antigravity (`agy`) runs in
plain-stdout mode; SASE never scrapes display prose, but supported Antigravity versions may contribute guarded
`source: "trajectory"` rows from the local trajectory DB. When that extractor is unavailable, the panel simply shows
nothing for `agy` runs. See [LLM Providers — Claude tool-call hooks](llms.md#claude-tool-call-hooks),
[LLM Providers — Codex tool-call capture](llms.md#codex-tool-call-capture),
[LLM Providers — Qwen tool-call capture](llms.md#qwen-tool-call-capture), and
[LLM Providers — Antigravity (`agy`) Integration](llms.md#antigravity-agy-integration) for provider integration details.

## Plan Workflows

When an agent submits a plan via `/sase_plan` (or `sase plan propose`, including the `%auto:epic` path), it enters a
planning phase before executing:

- **PLAN** — The agent has produced a plan and is waiting for user approval. Shown in pink/magenta in the prompt panel.
- **PLAN APPROVED** — The plan has been approved and the follow-up agent has been spawned. Shown in cyan/turquoise.
- **PLAN REJECTED** — The plan was rejected. A no-feedback rejection from ACE or `sase plan reject` writes the rejection
  response first, then attempts to dismiss the notification, user-kill the matching planner, and persist dismissed-agent
  state so the row is hidden on refresh. If the matching row is already gone, the plan is still rejected. Rejected
  archived plans can still appear in history-oriented views, and redundant completion notifications are suppressed.

Plan files generated by the agent are displayed in the file panel alongside other agent artifacts. Plan approval
notifications include the LLM provider and model name, so users can see which model proposed the plan (visible in both
the TUI notification modal and Telegram delivery).

When `sase plan propose` writes the plan, it also touches `~/.sase/.ace_refresh_pulse` to wake any running TUI
immediately — PLAN status appears without waiting for the next auto-refresh tick. The pulse file is consumed by the
inotify artifact watcher (see [Auto-Refresh](#auto-refresh)) and is harmless if no TUI is open.

Root plan workflows also surface PLAN when a re-proposed plan is still awaiting review. Plan and feedback timestamps
from feedback-round children (`--2`, `--3`, ...; legacy `-2`, `.2`, etc.) propagate onto the root entry, and whenever
the root's latest plan timestamp is newer than its latest feedback timestamp the override engine restores `PLAN` over a
`RUNNING` or `DONE` label. This applies only to root plan workflows that have not yet spawned a terminal follow-up
(`--code`, `--epic`, ...); once a terminal follow-up is launched, the parent moves on to `PLAN APPROVED` (or the
matching follow-up status) instead.

The Plan Review modal title shows a provider-themed `PROVIDER(model)` badge between the "Plan Review" label and the plan
filename — orange for Claude, lime for Codex, Antigravity indigo (`#6E5DE7`) for agy, neutral muted for other providers.
The badge is omitted when provider/model metadata is absent, leaving the legacy title shape unchanged.

For tale plans, the modal's primary **Approve** decision includes two independently selectable add-ons: **Commit plan
file to the plans sidecar** and **Run coder follow-up**. Both are selected by default. Press `enter` to approve with the
current checkbox selection; the existing `a`, `t`, `c`, `r`, `f`, and `E` bindings remain as compatibility shortcuts for
their common presets and alternate flows.

The same pending approvals are available from the CLI. Run `sase plan` to see pending proposals, recent approvals, and
inferred rejected archived plans; run `sase plan approve <id-prefix> --kind approve|commit|epic|tale` or
`sase plan reject <id-prefix>` to write the same response protocol used by the TUI modal. Use the `id_prefix` from a
Proposed row; if the selector is omitted, the CLI acts only when exactly one proposal is pending. Omitting `--kind` uses
the plan's authored tier. In the Plan Review modal, `enter` uses that same authored-tier default; `a`, `t`, and `E`
remain explicit overrides. `approve` starts the coder without committing an SDD plan, `tale` commits the plan as an SDD
tale and starts the coder, `epic` commits the matching SDD tier and launches the bead follow-up, and `commit` records
the approved plan in SDD without launching a coder. `-m/--model` picks the follow-up agent's model, while `-p/--prompt`
adds extra coder instructions for the `approve` and `tale` paths. Tale and epic choices validate the plan against the
target schema before consuming the approval; failures surface an error and keep the notification actionable. CLI
rejection also attempts the durable planner cleanup used by no-feedback TUI rejection.

For active Agents-tab rows, `A` opens the **Auto-Approve menu**, a single-key modal that configures how the agent's
_next_ submitted plan is auto-approved. The agent's current state is marked with `▸`; pressing `p` (Plan — approve the
plan as-is), `t` (Tale — approve and commit as a tale), `e` (Epic — approve and commit as an epic), or `d` (Disable —
turn off auto-approval) applies the change immediately, while `esc`/`q` cancels. The selected state shows on the agent
row as a `⚡` (plan), `⚡T` (tale), or `⚡E` (epic) icon. For plan submissions, these choices correspond to the
plan-adapter behavior of `%auto`, `%auto:tale`, and `%auto:epic` respectively — for example, epic auto-approve accepts
the next submitted plan as an epic, writes SDD epic artifacts, initializes beads, and launches the epic follow-up agent.
The menu only configures plan auto-approval; unlike bare `%auto`, it does not automatically answer questions or
unrelated HITL prompts.

### Plan Approval Keybindings

| Key          | Action                                                   |
| ------------ | -------------------------------------------------------- |
| `a`          | Approve and run coder without committing an SDD tale     |
| `t`          | Save as tale and run coder                               |
| `c`          | Open [Custom Approval](#custom-approval)                 |
| `r`          | Reject the plan                                          |
| `f`          | Request feedback (send follow-up questions to the agent) |
| `e`          | Edit the plan file in `$EDITOR`                          |
| `E`          | Mark the plan as an epic (creates bead)                  |
| `y`          | Copy plan content to clipboard                           |
| `Y`          | Copy plan file path to clipboard                         |
| `Ctrl+D`/`U` | Scroll plan content down / up                            |
| `g` / `G`    | Scroll to top / bottom                                   |
| `q` / `Esc`  | Cancel                                                   |

The question modal also supports `y` to copy questions and selected answers.

### Custom Approval

Pressing `c` in the plan approval modal opens a custom approval dialog. Choose the approval outcome directly: Approve,
Tale, or Epic. These choices map to the same response protocol used by external approval transports: Approve runs the
coder without asking the runner to commit an SDD plan, while Tale and Epic commit the plan under the matching tier in
the resolved SDD plans root's `<YYYYMM>/` directory. The root may be in-tree, a legacy `.sase/sdd/` clone, or the split
`--plans` sidecar; `sase repo path plans` prints it.

| Key          | Action                        |
| ------------ | ----------------------------- |
| `Enter`      | Choose the highlighted action |
| `a`          | Highlight Approve             |
| `t`          | Highlight Tale                |
| `e`          | Highlight Epic                |
| `m`          | Select coder model            |
| `p`          | Edit additional coder prompt  |
| `Ctrl+N`/`P` | Next / previous action        |
| `q` / `Esc`  | Cancel                        |

The dialog keeps the custom coder prompt and follow-up model controls for Approve and Tale. Epic approval reads its land
and phase models from structured plan frontmatter and launches bead work directly, so those controls are hidden for
Epic:

- **Additional prompt** — Optional extra instructions for the coder follow-up. It is used by Approve and Tale.
- **Coder model** — Select an LLM model for the next follow-up agent instead of using the role default. For Approve and
  Tale that agent is the coder. Shows all registered models grouped by provider (Claude, Codex, Antigravity, Qwen,
  OpenCode) with a "Custom..." option for freeform input. Type to filter by provider, model id, label, or short alias;
  use `j`/`k` or arrows to navigate, `Enter` to select, `Esc` to clear the filter or cancel, and `'` for jump hints over
  the visible selectable rows. The displayed default resolves to the model the handoff will actually use: the planner
  provider's coder alias (`@<planner_provider>_coder`, e.g. `@claude_coder`, falling back to `@coder` when planner
  provider metadata is missing). Selecting a specific model and then re-opening the picker and choosing "Follow-up
  default" resets the follow-up back to that role default (distinct from pressing `Esc`, which keeps the current
  selection).

The custom approval dialog no longer exposes separate commit/run switches because the selected outcome determines the
commit location and follow-up behavior. Additional family members are launched explicitly with `%n(parent, suffix)`;
they are not selected at the plan gate.

## Launch Approval

Launches requested by a running agent (see
[Agent-initiated launches](agent_families.md#agent-initiated-family-launches)) arrive as priority notifications with a
`LaunchApproval` action. Selecting one opens the launch approval modal, which renders the request's human-readable
preview (`launch_preview.md`). Clan slots identify their rootless clan alongside the model, kind, and planned member
name. Press `a` to approve, `r` to reject, and `q` or `Esc` to cancel. ACE resolves the same hash-verified command
bundle used by mobile and remote callbacks, while retaining legacy launch-request fallback. The CLI equivalents are
`sase launch approve <selector>` and `sase launch reject <selector>`.

## Linked Chats in Multi-Step Workflows

When a workflow spawns multiple agents (e.g., a planner step followed by a coder step), the chat history files for each
step are cross-linked via a `## Linked Chats` markdown section. This section is inserted near the top of each chat file
and lists all related agents with their roles and file paths, making it easy to trace the full workflow from any
individual agent's chat history.

For example, a plan-then-code workflow produces chat files with:

```markdown
## Linked Chats

- **1. planner** — `/path/to/planner_chat.md`
- 2. coder — `/path/to/coder_chat.md`
```

The current agent's entry is bolded for quick identification.

## Retry/Fallback Display

When an agent encounters a retryable error (configured via `llm_provider.retry`), the Agents tab shows retry state:

- **RETRYING** — Shown in bold orange when waiting before the next retry attempt. Includes a countdown timer:
  `RETRYING (45s)`.
- **↻N** — Shown after the status for running agents that have retried. The number indicates how many retries have
  occurred (e.g., `↻2` means two retries so far).
- **▸Model** — Appended to the retry annotation when the agent has fallen back to an alternate model (e.g., `↻3▸flash`).

### Prior Agent Attempts

Every time the axe retry loop retries an agent — context-limit retry, provider/API-error retry, user-configured retry,
or fallback-model switch — the failed attempt's partial reply, error text, timestamps, and model are snapshotted under
`<artifacts_dir>/attempts/<N>/`. The AGENT REPLY area in the Agents tab renders these prior attempts inline with styled
dividers before the current/final attempt, so the full arc of the agent's work stays visible in one scroll.

ACE hydrates prior-attempt history lazily. Normal Agents-tab refreshes do not enumerate every `attempts/<N>/` directory;
the selected detail panel, `D` attempt-view toggle, and content search hydrate the needed attempt records on demand.

Press `D` to collapse the view to the current attempt only; press `D` again to re-expand. The binding only appears in
the keybinding footer when the selected agent has one or more prior attempts.

## Custom Keymaps

All TUI keybindings are configurable via the `ace.keymaps` section in `sase.yml`. You can remap app-level, gate-modal,
and focused Telemetry-pane keys and define entirely new prefix-key modes.

### Remapping Built-in Keys

Override any app-level keybinding under `ace.keymaps.app`:

```yaml
ace:
  keymaps:
    app:
      next_changespec: "n" # Remap j → n
      prev_changespec: "p" # Remap k → p
      show_notifications: "N" # Remap i → N
```

### Remapping Telemetry Pane Keys

Override focused Telemetry bindings under `ace.keymaps.telemetry`:

```yaml
ace:
  keymaps:
    telemetry:
      cycle_subsystem: "f12"
      cycle_range: "f11"
      refresh: "f10"
```

These keys dispatch only while the Admin Center Telemetry pane is focused. They may overlap app-level bindings without
creating a global conflict, and the pane's hint bar always shows the effective keys.

### Remapping Gate Modal Keys

Override the shared plan/custom gate controls under `ace.keymaps.gate`:

```yaml
ace:
  keymaps:
    gate:
      next_control: "down"
      previous_control: "up"
      toggle_option: "space"
      submit_primary: "enter"
      submit_branch: "ctrl+enter"
```

These bindings dispatch only while a branch-driven gate modal is open, and its footer shows the effective keys. The
retired `activate_control` setting is accepted as a deprecated alias for `submit_primary`.

### Custom Modes

Define user-defined prefix-key modes under `ace.keymaps.modes`. Each custom mode has a `prefix` key and a `keys` dict
where each sub-key specifies either a `shell` command or a built-in `action`:

```yaml
ace:
  keymaps:
    modes:
      my_mode:
        prefix: ";"
        keys:
          run_tests:
            key: "t"
            shell: "just test"
          show_log:
            key: "l"
            shell: "git log --oneline -20"
          refresh:
            key: "r"
            action: "refresh"
```

Pressing `;` activates the mode, then pressing `t` runs `just test`, `l` shows the git log, etc.

### Validation

The keymap loader validates all configuration:

- **Invalid keys** are reverted to their defaults with a warning
- **Duplicate keys within one binding scope** are detected and the conflicting override is reverted
- **Prefix conflicts** between custom mode prefixes and existing app bindings are warned

See [`docs/configuration.md`](configuration.md) for the full `ace.keymaps` configuration reference.

## Prompt Input Widget

The prompt input is a multiline TextArea widget that supports two editing modes: INSERT and NORMAL. The widget provides
markdown syntax highlighting for prompt content (headings, bold, italic, code blocks, lists, etc.).

When loaded prompt text contains literal top-level `---` multi-agent separators, ACE renders the text as a prompt stack:
one pane per agent segment. YAML frontmatter at the start stays prompt-level metadata, and `---` lines inside fenced
code blocks are left alone. A `#name` xprompt swarm invocation stays a single pane and expands only when it is launched.
During live editing, typed `---` lines stay literal text; add prompt panes with `g-` in prompt NORMAL mode. The detailed
multi-agent parsing rules live in the [XPrompt reference](xprompt.md#multi-agent-prompts).

### INSERT Mode (Default)

| Key                          | Action                                                                                                     |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `Enter`                      | Submit; in a prompt stack, open the submit chooser                                                         |
| `Ctrl+S`                     | Stash the active pane; from an empty prompt, open the stashed-prompt picker                                |
| `Ctrl+G Enter`               | Submit only the selected pane                                                                              |
| `Ctrl+C`                     | Cancel the prompt; in a prompt stack, cancel only the selected pane                                        |
| `Ctrl+J`                     | Insert a newline                                                                                           |
| `Ctrl+A`                     | Move to start of line (jumps to previous line start if already at col 0)                                   |
| `Ctrl+E`                     | Move to end of line (jumps to next line end if already at end)                                             |
| `Ctrl+G`                     | Start the prompt-local prefix; press `g` or `Ctrl+G` again to open `$EDITOR`                               |
| `Ctrl+G Enter`               | Submit only the selected pane                                                                              |
| `Ctrl+G j/k`                 | Focus the next / previous pane and leave the target pane in INSERT mode                                    |
| `Ctrl+G J/K`                 | Move the active pane down / up and leave it in INSERT mode                                                 |
| `Ctrl+G -`                   | Add an empty bottom pane                                                                                   |
| `Ctrl+G =`                   | Show/focus the xprompt frontmatter panel                                                                   |
| `Ctrl+G s`                   | Bundle every non-empty pane into one stash row                                                             |
| `Ctrl+G S`                   | Overwrite a pinned stashed prompt with the current stack                                                   |
| `Ctrl+G x` / `Ctrl+G Ctrl+X` | Save the current stack as a reusable xprompt or snippet                                                    |
| `Ctrl+G X`                   | Convert the active pane into a frontmatter-local xprompt                                                   |
| `Ctrl+G Ctrl+C`              | Cancel every pane in the prompt stack at once                                                              |
| `Ctrl+G p`                   | Open the stashed-prompt picker                                                                             |
| `Ctrl+Y`                     | Open the workflow YAML editor                                                                              |
| `Ctrl+K`                     | Open prompt history from a single-line prompt, pre-filtered by that text                                   |
| `Ctrl+P`                     | Cycle toward older workspace MRU prefixes, including a no-prefix stop before wrapping                      |
| `Ctrl+N`                     | Cycle toward newer workspace MRU prefixes, including a no-prefix stop before wrapping                      |
| `Ctrl+T`                     | Completion (structured tokens, paths, prompt-local words, or history words; see [Completion](#completion)) |
| `Ctrl+R`                     | Recursive fuzzy file finder using the same prompt-aware path root as file completion                       |
| `Tab`                        | Snippet expansion (see below)                                                                              |
| `#@`                         | Open XPrompt snippet picker (type `#` then `@`)                                                            |
| `Escape`                     | Switch to vim NORMAL mode                                                                                  |

In prompt INSERT mode, ACE auto-pairs safe openers for `()`, `[]`, `{}`, `<>`, single quotes, double quotes, and
backticks. Typing the matching closer over an auto-inserted closer moves the cursor across it instead of duplicating it,
and backspace or delete removes both sides of an empty pair. Pairing is conservative: it is suppressed before token
characters, when text is selected (the typed character replaces the selection literally), for contractions or
possessives, and for repeated quotes/backticks needed to type Markdown fences or code spans.

Text automatically wraps at the terminal width, breaking at spaces (never mid-word). Line numbers appear in cyan when
the text exceeds one line. The native cursor cell is color-coded by prompt Vim mode: INSERT uses cyan, NORMAL uses gold,
and VISUAL or V-LINE uses magenta.

### Prompt Stacks

Prompt stacks are the ACE editing surface for literal `---` multi-agent prompts. Loading multi-agent prompt text from
history, a whole-bar editor session, or an editor buffer that returned with a ` @` review marker splits top-level `---`
segment separators into panes labeled `agent 1`, `agent 2`, and so on; the border title shows `Prompt · N agents`.
Restoring stashed prompts and using marked-agent `,x` can also open a stack, but those paths load one pane per selected
draft or agent instead of re-parsing each pane's text. Panes are ordered top-to-bottom for whole-stack submission. The
bottom pane is active by default so you can keep drafting the newest segment; it is not a priority marker, and pressing
`Enter` immediately opens the submit chooser.

Inactive panes stay compact, and the active pane takes the available height. A `---` line typed while INSERT mode is
active stays literal prompt text; use `Ctrl+G -` while drafting, or `g-` from prompt NORMAL mode, to add a new bottom
pane. `Ctrl+G g` and `Ctrl+G Ctrl+G` open the whole stack in `$EDITOR` when the bar already has multiple panes (a
single-pane bar opens just the current prompt). Returning from a whole-bar editor session, or from a single-pane editor
buffer with a ` @` review marker, reloads xprompt-style Markdown and parses `---` separators into fresh panes. History
loads parse only real multi-agent prompts; a single history item with leading YAML frontmatter stays one verbatim pane
instead of auto-opening the Frontmatter Panel.

A single-pane editor session normally launches the moment you close `$EDITOR`. To review it in the prompt bar first, end
any line of the buffer with the exact suffix ` @` (a space followed by `@`). On return, that marker is stripped from
every matching line and the cleaned text reloads with editor-file semantics: leading xprompt frontmatter is lifted into
the Frontmatter Panel and real `---` separators split into one pane per agent, so a marked multi-agent buffer comes back
as a reviewable stack instead of launching. The marker is editor-return-only — typing ` @` in the prompt bar and
submitting carries no special meaning. (This replaces the removed `%edit` directive.)

In prompt INSERT mode, pressing `Ctrl+G` opens the same context-aware hint row as prompt NORMAL mode's `g` prefix, plus
the editor continuation. Press `Esc` while the prefix is pending to cancel it and stay in INSERT mode.

In prompt NORMAL mode, pressing `g` opens a small hint row for the prompt-local `g` prefix actions currently available.

| Key         | Action                                                                                                 |
| ----------- | ------------------------------------------------------------------------------------------------------ |
| `Enter`     | Open the submit chooser; when one pane remains, `Enter` submits it normally                            |
| `Ctrl+S`    | Stash the active pane; from an empty prompt, open the stashed-prompt picker                            |
| `g<enter>`  | Launch the selected pane and remove it from the stack                                                  |
| `Ctrl+C`    | Record the selected pane as cancelled history and remove it; the final remaining pane cancels normally |
| `Escape`    | Enter NORMAL mode for stack navigation                                                                 |
| `gj` / `gk` | Focus the next / previous pane in NORMAL mode; focus cycles at the stack edges                         |
| `gJ` / `gK` | Move the active pane down / up in NORMAL mode; reorder cycles at the stack edges                       |
| `g-`        | Add an empty bottom pane in NORMAL mode and switch it to INSERT mode                                   |
| `g=`        | Show/focus the xprompt frontmatter panel; in the focused panel, run its deactivate/apply path          |
| `gs`        | Bundle every non-empty pane into one stash row and dismiss the prompt bar                              |
| `gS`        | Overwrite a pinned stashed prompt with the current stack, leaving the bar open                         |
| `gw`        | Write a bound xprompt definition; unbound drafts fall through to save-as                               |
| `gd`        | Edit the xprompt definition under the cursor in the prompt bar                                         |
| `gx`        | Save the current stack as a reusable xprompt or snippet, leaving the bar open                          |
| `gX`        | Convert the active pane into a frontmatter-local xprompt, leaving the bar open                         |

Submitting one pane at a time re-attaches prompt-level frontmatter to the launched pane so local xprompts and metadata
continue to resolve. Empty selected panes are dropped without launching. Whole-stack submission joins panes in
top-to-bottom order and then uses the usual multi-agent launch path, including `%wait`, `%name`, `%model`, and other
segment-local directives. Segment order alone does not make later agents wait; add `%wait` to the later pane when it
must start after an earlier agent succeeds.

The `Enter` submit chooser accepts `a` or `Ctrl+S` for all panes, `c` for the current pane, and `Esc`/`q` to cancel
without changing the stack. Outside that chooser, `Ctrl+S` is always an active-pane stash shortcut.

Prompt stashes are a per-user draft pile stored outside prompt history. `Ctrl+S` captures the selected non-empty pane
plus the shared prompt frontmatter; when other panes remain the bar stays open, and when the last pane is stashed the
bar closes without also recording the draft as cancelled history. If the active pane is empty, `Ctrl+S` opens the
stashed-prompt picker instead. `gs` captures all non-empty panes in their current order as one bundled stash row and
dismisses the bar. `gS` opens an update flow for an existing pinned stash and overwrites the chosen row with the current
non-empty panes. `gx`, `Ctrl+G x`, and `Ctrl+G Ctrl+X` open one save screen containing the name, storage location,
resolved path, and a live preview when the name collides. Inside that screen, `Ctrl+X` switches between xprompt and
snippet mode, so `Ctrl+G Ctrl+X Ctrl+X` goes directly from a prompt draft to snippet mode. `Ctrl+T` remains manual
completion in the prompt input and does not toggle this save screen. A successful save binds the prompt stack to that
source. `gw` then performs atomic write-back, and if the source changed since load it offers overwrite, reload, or
save-as instead of clobbering it. `gd` loads the simple xprompt under the cursor for the same bound editing loop. `gX`
instead converts the active pane through a prefilled frontmatter ghost row and rewrites the pane to invoke the committed
helper.

`Ctrl+G p` opens the unified stashed-prompt picker from the prompt bar, and `@` opens the same picker from the main ACE
tabs even when the prompt bar is not active. In the picker, `space` toggles a row's persistent pin, `Tab` marks a
single-prompt row to restore and remove from the stash, `d` marks any row for deletion, `a` toggles all selectable
single-prompt rows for restore-and-remove, and `Enter` confirms the marked set. With no explicit marks, `Enter` restores
the highlighted row; pinned rows stay stashed when restored, while unpinned rows are popped. Number keys `1`-`9` and `0`
restore rows 1-10 directly with the same pin-aware behavior. A small top-bar badge shows how many restorable drafts are
currently stashed.

### Completion

Press `Ctrl+T` to activate token completion. The completion kind is determined by the token under the cursor:

- **XPrompt completion**: When the cursor is on a `#`-prefixed token (e.g., `#my_pro`), completion shows matching
  xprompt names from all discovery sources, including registered workspace workflow xprompts. Completion rows include
  the xprompt kind and visible typed inputs, with required arguments shown as `name: type` and optional arguments shown
  as `name?: type` plus a default when the default is a simple scalar. Standalone workflow references use the `#!name`
  insertion form; typing `#!` filters completion to entries whose canonical insertion starts with `#!`.
- **Project/ChangeSpec completion**: When the cursor is on a `#+` token, or on a `+` token that is the first character
  in the prompt, completion opens a project/ChangeSpec picker. The picker contains enabled launchable projects plus
  active PR-sized ChangeSpecs in `WIP`, `Draft`, `Ready`, or `Mailed` status; system-managed `home`, disabled projects,
  internal sibling backing records, and non-launchable projects are excluded. Typing after the trigger filters by
  project name, project alias, or ChangeSpec name prefix. Accepting a row inserts the canonical workspace tag such as
  `#gh:sase` or `#gh:my_change`, replacing existing line-start VCS tags when present or placing the tag after leading
  frontmatter/directives when no tag exists.
- **VCS ref completion**: When the cursor is inside the root segment of a registered VCS workflow ref, such as `#gh:`,
  `#gh:sa`, or `#git(`, completion lists that provider's projects and active PR-sized ChangeSpecs. Providers can add
  namespace rows, such as GitHub organization rows, from local project/config data. Accepting a project or ChangeSpec
  completes only the current ref token, producing `#gh:sase ` in colon form or `#gh(sase)` in parenthesized form.
  Accepting a namespace inserts a trailing slash such as `#gh:sase-org/` and immediately hands off to repository
  completion.
- **VCS repository completion**: When the cursor is inside a registered VCS workflow ref that already contains an owner
  or namespace plus `/`, completion lists repositories for that namespace through the owning workspace plugin. For
  example, `#gh:bbugyi200/` opens GitHub repositories for `bbugyi200`, and `#gh:bbugyi200/sa` narrows locally or through
  the LSP client's filtering. Accepting a row replaces only the current ref value, producing `#gh:bbugyi200/sase ` in
  colon form or `#gh(bbugyi200/sase)` in parenthesized form. Failed or empty lookups show a placeholder row in ACE;
  stale cached results are reused when a refresh fails.
- **Slash-skill completion**: When the cursor is on a slash-skill token such as `/` or `/sase_`, completion filters the
  same catalog to xprompts marked as `skill: true` and inserts `/skill_name`. Packaged built-in skills are included, so
  `/sase_plan`, `/sase_questions`, and other bundled SASE skills are available without a project-local xprompt file.
- **XPrompt argument completion**: When the cursor is inside a known xprompt argument position, `Ctrl+T` completes the
  active argument instead of the xprompt name. For `path` inputs it delegates to file path completion, for `bool` inputs
  it offers `true` and `false`, and inside parenthesized syntax it completes missing `name=` arguments without repeating
  names already present in the argument list. Numeric inputs keep the type hint visible but do not invent values.
- **Directive completion**: When the cursor is on a `%`-prefixed directive token (e.g., `%m`), completion lists
  user-facing prompt directives and accepts aliases into their canonical forms. For example, `%m` completes to `%model`
  and `%w` completes to `%wait`. The panel shows each directive's aliases and whether it takes an argument or is a flag.
- **File path completion**: When the cursor is on a path-like token (starting with `/`, `./`, `../`, `~/`, or containing
  `/`), completion shows matching filesystem entries. Tokens starting with `@` are also recognized — the `@` prefix is
  preserved in the completed path (useful for file-reference arguments). Relative paths use the prompt-selected base
  directory: registered workspace-provider refs and known-project refs such as `#git:<project>` or `#gh:<owner>/<repo>`
  can root completion in that project checkout. If no prompt workspace ref resolves, ACE uses the TUI process directory.
- **File-history completion**: When the cursor is in whitespace (or at an empty prompt prefix), `Ctrl+T` opens a list of
  recently referenced files drawn from prompt history, ranked by recency. Project-local `.sase/` paths are filtered out
  so internal bead/plan artifacts don't pollute the suggestions. Press `Ctrl+D` in the completion panel to delete the
  highlighted entry from the on-disk history.
- **Prompt-local word completion**: As the first fallback for a plain prose token, `Ctrl+T` filters words already in the
  active prompt by the word prefix immediately left of the cursor. Matching is case-insensitive, but each candidate
  keeps its original spelling. Accepting a candidate replaces the complete word under the cursor, including any suffix
  to the right, so completion also works safely in the middle of a word. This provider scans only the current prompt
  pane and always takes precedence over history words.
- **History-word completion**: When prompt-local words have no match, `Ctrl+T` filters recently used words derived from
  recorded prompt history. Matching remains case-insensitive and keeps exact spelling, while rows are ordered by most
  recent use. ACE retains up to `ace.prompt_completion.history_word_count` unique words of at least
  `history_word_min_length` characters (defaults: `1000` and `5`); set `history_word_count: 0` to disable this final
  fallback. History is loaded off-thread, so a cold cache briefly shows `loading history words…` without blocking input.

| Key                | Action                                   |
| ------------------ | ---------------------------------------- |
| `Ctrl+T`           | Start completion or insert shared prefix |
| `Ctrl+N` / `Down`  | Next candidate                           |
| `Ctrl+P` / `Up`    | Previous candidate                       |
| `Enter` / `Ctrl+L` | Accept highlighted candidate             |
| `Escape`           | Cancel completion                        |

Press `Ctrl+R` to open the recursive fuzzy file finder. With a token such as `src/alp`, `src/` becomes the search root
and `alp` pre-seeds the fuzzy query; with no token, the finder starts at the prompt-selected base directory described
above. If a `Ctrl+T` file, recent-file, or path-argument candidate is highlighted, that highlighted path seeds the
recursive root instead. The finder uses `git ls-files --cached --others --exclude-standard` from the search root when
possible, falls back to a bounded filesystem walk, and inserts the selected path into the prompt position captured when
the finder opened. Inside the finder, type to filter, use `Ctrl+N` / `Ctrl+P` or arrows to move, `Ctrl+U` to clear the
query, `Enter` to insert, and `Esc` to cancel.

In prompt NORMAL mode, `K` previews the xprompt, slash skill, or file under the cursor, and `Ctrl+]` jumps to its
definition or opens an action picker when several jump targets are available.

ACE also computes a non-disruptive live suggestion after a short debounce while the prompt input is in INSERT mode. The
suggestion appears in the prompt bar subtitle as `[^L] accept ...`; press `Ctrl+L` to accept it. `Enter` still submits
the prompt as typed, so live suggestions cannot accidentally replace text on send.

Live soft completion covers directives, xprompt names, xprompt argument names, and bool argument values. File-path soft
completion is disabled by default because it can scan the filesystem while typing; enable it with
`ace.prompt_completion.auto_file_paths: true`. The xprompt/skill menu also opens automatically while typing matching
`#name`, `#!name`, or `/skill` tokens; disable that xprompt auto-open behavior with
`ace.prompt_completion.auto_xprompt_menu: false`. The directive menu likewise opens automatically while typing matching
`%name` tokens; disable it with `ace.prompt_completion.auto_directive_menu: false`. Both auto-menus open only once at
least one identifier character follows the marker (bare `#`, `/`, and `%` stay quiet) and never auto-accept a single
match. The `#+` / offset-zero `+` project/ChangeSpec picker opens when `+` completes a valid trigger and is also
available through manual `Ctrl+T`. The VCS ref-root menu opens when `:` or `(` completes a known workflow ref trigger
such as `#gh:` and local candidates exist. The VCS repository menu opens when `/` completes a known workflow ref trigger
such as `#gh:owner/`; cached rows appear immediately and uncached namespaces fetch in a background worker. Manual
`Ctrl+T` completion still supports file paths, xprompt names, directives, skills, project/ChangeSpec tags, VCS ref
roots, VCS repository refs, prompt-local prose words, and enabled history words regardless of the automatic settings.
Live suggestions pause while the manual completion panel is open, while snippet tabstops are active, in NORMAL mode, and
during feedback prompts.

For file completion, directories appear before files in the candidate list. Dotfiles are hidden unless the partial
prefix starts with `.`. Accepting a directory automatically re-opens completion for the next level (drill-down). The
completion panel shows up to 10 candidates at a time and scrolls to keep the highlight visible. When exactly one xprompt
or file candidate matches, accepting completion inserts the canonical reference immediately.

Accepting an xprompt completion, or selecting an xprompt from the `#@` picker, opens an `xprompt args` hint panel when
the xprompt has required user-facing inputs. The panel shows the supported arguments and highlights the active one.
Press `:` while the accepted reference is still current to switch to colon syntax, or press `(` to insert a
required-argument named snippet and use `Tab` to advance through the snippet fields.

The same smart insertion rules apply to `#@` selections and `Ctrl+T` completions. A selected xprompt with no required
inputs inserts a trailing space, a single required non-text input inserts colon syntax, a single required text input
inserts double-colon shorthand, and multiple required inputs insert a parenthesized named-argument snippet.

The same hint panel appears while typing narrow, known argument forms such as `#name:`, `#!name:`, `#ns/name:`,
`#ns__name:`, `#name!!:`, `#name??:`, `#name(`, and `#name(arg=`. The hint is advisory; the backend xprompt parser still
owns expansion semantics when the prompt is submitted. Detection intentionally stays conservative, so prose shorthand,
URLs, unknown xprompt names, `#name+`, and completed colon text such as `#name: value` do not keep the prompt-bar hint
open.

### Alt Brace Syntax (`%{...}`)

The prompt input has dedicated highlighting and editing help for the `%{A | B}` alt fan-out shorthand (see the
[Alt Directive reference](xprompt.md#alt-directive)). It distinguishes the alt delimiters from the branch separators so
a fan-out is easy to read at a glance:

- The `%{` opener and `}` closer are styled as **delimiters** (bold accent).
- Top-level `|` branch **separators** use a dimmed accent so they read differently from the delimiters.
- A branch name before a top-level `=` (e.g. `sec=` in `%{sec=... | perf=...}`) is highlighted as a **branch name**.
- An unmatched `%{` (or stray closer) is flagged as an **error** span.

The alt overlay layers on top of the existing Jinja and search highlighting rather than replacing it, and it uses the
same size guards, so highlighting stays responsive on large prompts.

Editing help in the ACE prompt input mirrors the Jinja auto-pair behavior and only fires for the `%{...}` shorthand:

- **Auto-pair** — typing `{` immediately after a directive-valid `%` inserts the matching `}` and leaves the cursor
  between the braces (`%{|}`).
- **Paired delete** — backspacing the `{` in `%{|}` also removes the auto-inserted `}`; a forward delete on `%|{}`
  removes both braces.
- **`|` separator normalization** — typing `|` inside a live `%{...}` span inserts a padded `|` separator, keeps the
  cursor after the trailing space and before the closing `}`, and normalizes comma spacing in the current branch. For
  example, typing `|` at the end of `%{foo ,bar, and baz` yields `%{foo, bar, and baz | }` with the cursor before `}`.

These edits are suppressed when there is an active selection or when the cursor is not inside a directive-valid `%{...}`
context, so ordinary `{` and `|` typing elsewhere is unaffected. External editor integrations do not own `%{}`
auto-pairing or paired delete; editor-local brace-pair plugins own that lifecycle there. The
[Neovim plugin](https://github.com/sase-org/sase-nvim) still provides the same separator-normalization behavior for
prompt buffers.

### NORMAL Mode

Press `Escape` in INSERT mode to enter vim-style NORMAL mode. The border title shows `[NORMAL]` and line numbers switch
to relative numbering (current line shows absolute, others show offset).

#### Motions

| Key               | Action                             |
| ----------------- | ---------------------------------- |
| `h` / `l`         | Move left / right                  |
| `j` / `k`         | Move down / up (actual lines)      |
| `w` / `W`         | Next word / WORD start             |
| `e` / `E`         | Next word / WORD end               |
| `b` / `B`         | Previous word / WORD start         |
| `ge` / `gE`       | Previous word / WORD end           |
| `f{c}` / `F{c}`   | Find char forward / backward       |
| `t{c}` / `T{c}`   | Till char forward / backward       |
| `;` / `,`         | Repeat / reverse last f/F/t/T      |
| `%`               | Matching bracket                   |
| `0` / `$`         | Line start / end                   |
| `^`               | First non-blank character          |
| `{` / `}`         | Previous / next paragraph boundary |
| `gg` / `G`        | Top / bottom of document           |
| `Ctrl+D`/`Ctrl+U` | Half-page down / up                |

All motions accept a numeric count prefix (e.g., `3j` moves down 3 lines).

#### Operators

| Key   | Action                                                                                       |
| ----- | -------------------------------------------------------------------------------------------- |
| `d`   | Delete (takes a motion, e.g. `dw`); copies to clipboard                                      |
| `c`   | Change (takes a motion, e.g. `cw`); `cw`/`cW` stop at the word/WORD end; copies to clipboard |
| `y`   | Yank (takes a motion, e.g. `yw`); copies to clipboard                                        |
| `>`   | Indent lines covered by a motion by two spaces                                               |
| `<`   | Dedent lines covered by a motion by up to two spaces                                         |
| `gu`  | Lowercase text covered by a motion or text object                                            |
| `gU`  | Uppercase text covered by a motion or text object                                            |
| `g~`  | Toggle case for text covered by a motion or text object                                      |
| `D`   | Delete to end of line                                                                        |
| `C`   | Change to end of line                                                                        |
| `S`   | Change entire line                                                                           |
| `Y`   | Yank entire line                                                                             |
| `dd`  | Delete entire line                                                                           |
| `cc`  | Change entire line                                                                           |
| `yy`  | Yank entire line                                                                             |
| `>>`  | Indent current line; count indents multiple lines                                            |
| `<<`  | Dedent current line; count dedents multiple lines                                            |
| `guu` | Lowercase current line; count lowercases multiple lines                                      |
| `gUU` | Uppercase current line; count uppercases multiple lines                                      |
| `g~~` | Toggle case on current line; count toggles multiple lines                                    |
| `dae` | Delete entire buffer (copies to clipboard)                                                   |
| `cae` | Change entire buffer (copies to clipboard)                                                   |
| `yae` | Yank entire buffer (copies to clipboard)                                                     |

#### Text Objects

Text objects compose with `d`, `c`, and `y`.

| Key                  | Action                                                  |
| -------------------- | ------------------------------------------------------- |
| `iw` / `aw`          | Inner / a word                                          |
| `iW` / `aW`          | Inner / a WORD                                          |
| `i"` / `a"`          | Inner / a double-quoted string                          |
| `i'` / `a'`          | Inner / a single-quoted string                          |
| `` i` `` / `` a` ``  | Inner / a backtick-quoted string                        |
| `i(`/`a(`, `ib`/`ab` | Inner / a parenthesized block                           |
| `i[` / `a[`          | Inner / a square-bracket block                          |
| `i{`/`a{`, `iB`/`aB` | Inner / a brace block                                   |
| `i<` / `a<`          | Inner / an angle-bracket block                          |
| `ip` / `ap`          | Inner / a paragraph; `ap` includes adjacent blank lines |
| `ae`                 | Entire buffer                                           |

#### Other Commands

| Key        | Action                                                                                    |
| ---------- | ----------------------------------------------------------------------------------------- |
| `i`        | Enter INSERT mode; inserted text is repeatable with `.`                                   |
| `v`        | Enter charwise VISUAL mode                                                                |
| `V`        | Enter linewise V-LINE mode                                                                |
| `a`        | Append after cursor; inserted text is repeatable with `.`                                 |
| `A`        | Append at end of line; inserted text is repeatable with `.`                               |
| `I`        | Insert at line start; inserted text is repeatable with `.`                                |
| `o`        | Open line below; inserted text is repeatable with `.`                                     |
| `O`        | Open line above; inserted text is repeatable with `.`                                     |
| `[<Space>` | Insert blank line(s) above current line without leaving NORMAL mode                       |
| `]<Space>` | Insert blank line(s) below current line without leaving NORMAL mode                       |
| `u`        | Undo                                                                                      |
| `Ctrl+R`   | Redo                                                                                      |
| `Ctrl+A`   | Increment the number at/after cursor, wrapping to the prompt top (supports count and `.`) |
| `Ctrl+X`   | Decrement the number at/after cursor, wrapping to the prompt top (supports count and `.`) |
| `x`        | Delete character                                                                          |
| `X`        | Delete character before cursor                                                            |
| `r{c}`     | Replace character(s) at cursor (supports count: `3rx`)                                    |
| `p`        | Paste after cursor / below line from the internal register                                |
| `P`        | Paste before cursor / above line from the internal register                               |
| `~`        | Toggle case of character(s) at cursor (supports count: `5~`)                              |
| `.`        | Repeat last mutation, including inserted text; a count replaces the recorded count        |
| `J`        | Join current line with next (supports count: `5J`)                                        |
| `K`        | Preview the xprompt, workflow, skill, or file under the cursor in a scrollable modal      |
| `Ctrl+]`   | Jump to the xprompt/workflow/skill definition or file under the cursor                    |

For `Ctrl+]`, ACE opens the target directly in `$EDITOR` when there is only one available action. Inside tmux, or for
loadable Markdown xprompt definitions, it can show a small chooser for editor, tmux-pane, or load-into-prompt actions.

The border subtitle shows pending operators and counts (e.g., `2d` when a delete with count 2 is pending).

### Visual Mode

Press `v` in NORMAL mode for charwise VISUAL mode, or `V` for linewise V-LINE mode. The border title shows `[VISUAL]` or
`[V-LINE]`. `Escape` returns to NORMAL mode, and `o` swaps the active selection end.

Visual mode supports the NORMAL-mode motions and counts listed above, including word motions, paragraph motions, line
motions, `f`/`F`/`t`/`T` with `;`/`,` repeats, `%`, `gg`/`G`, `Ctrl+D`/`Ctrl+U`, and the NORMAL-mode text objects. `v`
exits charwise VISUAL mode; `V` exits V-LINE mode; pressing the other visual key switches selection kind.

Visual changes (`d`, `c`, `>`/`<`, `u`/`U`, `~`) are dot-repeatable over a same-sized range from the current cursor;
visual `c` repeats the replacement text typed before `Escape`.

| Key       | Action                                                       |
| --------- | ------------------------------------------------------------ |
| `d` / `x` | Delete selection and copy it to the internal register        |
| `c` / `s` | Change selection and enter INSERT mode                       |
| `y`       | Yank selection to the internal register and system clipboard |
| `p`       | Replace selection with the internal register                 |
| `>` / `<` | Indent / dedent selected lines by two spaces                 |
| `u` / `U` | Lowercase / uppercase the selection                          |
| `~`       | Toggle case in the selection                                 |

V-LINE operators always apply to whole selected lines regardless of the cursor column.

## Prompt History Modal

Press `Ctrl+K` from the prompt input to open the prompt history modal. That shortcut is available when the current
prompt is a single logical line; that line pre-fills the modal filter. Press `,.` (leader + `.`) to open the same modal
from the main ACE UI. The modal loads prompts previously launched from ACE or `sase run` in 250-row recency pages.
Normal launch writes skip trivial one-token prompts (e.g. `y`, `ok`) so they do not clutter the list, while
failed-launch recovery can still preserve a short submitted prompt.

Bare prompts are stored after launch normalization, so a prompt without an explicit workspace reference appears with the
default `#git:home` prefix. Explicit workspace prefixes also feed the prompt-input MRU controls. In the prompt input,
the MRU ring is ordered from most recent to oldest: `Ctrl+P` moves toward older launchable workspace prefixes, while
`Ctrl+N` moves toward newer prefixes. Each edge has a no-prefix stop that removes the first launchable workspace tag
from the prompt without touching the remaining prompt text, then wraps. When no workspace tag is present, `Ctrl+P`
starts at the most recent entry and `Ctrl+N` starts at the oldest one.

### Keybindings

| Key              | Action                                        |
| ---------------- | --------------------------------------------- |
| `Enter`          | Submit the highlighted prompt directly        |
| `Ctrl+G`         | Open the highlighted prompt in `$EDITOR`      |
| `Tab` / `Ctrl+I` | Load prompt into the input widget for editing |
| `Ctrl+K`         | Load older prompts (+250)                     |
| `Ctrl+X`         | Toggle visibility of cancelled prompts        |
| `Ctrl+Y`         | Copy prompt to clipboard                      |
| `Esc`            | Close modal                                   |

### Filtering

Type in the search box to filter the prompts that have already been loaded by text. Press `Ctrl+K` to load older pages,
and press `Ctrl+X` to toggle cancelled prompts on or off — when enabled, cancelled prompts appear in the results with an
`x` marker.

Prompt-history rows are compact single-line entries: cancelled marker, last-used timestamp (`MM-DD HH:MM` when
parseable), and a first-line prompt preview. The preview panel still shows the full prompt and timestamp metadata.
History writes use a sidecar lock plus atomic tempfile replacement of monthly shard files under
`~/.sase/prompt_history/`, so concurrent agent launches do not truncate prompt history. A legacy
`~/.sase/prompt_history.json` store is migrated into shards before normal reads and writes when the shard directory has
not already been created.

## Tasks Tab

Open the SASE Admin Center with `#`, then press `4` (or `]` until you reach **Tasks**). You can also run the keyless
**Open tasks panel** command from the command palette. The tab shows background tasks (hook runs, mentor executions,
agent launches, plugin operations, etc.) with live output for running tasks and completed output for finished ones.

### Layout

The tab uses a two-panel layout: a task list on the left and an output pane on the right. Running tasks refresh their
output every second while the Tasks tab is visible.

### Task Status Icons

| Icon | Color | Meaning |
| ---- | ----- | ------- |
| `●`  | Green | Running |
| `✓`  | Cyan  | Success |
| `✗`  | Red   | Error   |
| `?`  | Dim   | Unknown |

### Keybindings

| Key                 | Action                          |
| ------------------- | ------------------------------- |
| `j` / `k`           | Navigate task list              |
| `K`                 | Kill selected running task      |
| `d`                 | Dismiss selected completed task |
| `D`                 | Dismiss all completed tasks     |
| `e`                 | Open task output in `$EDITOR`   |
| `y`                 | Copy task output to clipboard   |
| `Ctrl+D` / `Ctrl+U` | Scroll output pane down / up    |
| `g` / `G`           | Jump output pane to top/bottom  |
| `[` / `]`           | Switch Admin Center tabs        |
| `q` / `Esc`         | Close SASE Admin Center         |

## Updates Tab

Open the SASE Admin Center with `#`, then press `5` (or `]` until you reach **Updates**). The Updates tab keeps SASE
itself and its installed plugins current without leaving the TUI: a **SASE Core** panel shows the installed and latest
versions of the `sase` and `sase-core` packages, and below it the full plugin catalog lets you browse, inspect, install,
update, or uninstall plugins. Press `I` or `Space` to mark installable rows, `i` to install the marked set in one
combined operation (or the highlighted plugin when nothing is marked), `u` to run the full SASE update for core plus
installed plugins, `U` to update the highlighted installed plugin when that row has an update available, `x` to
uninstall, and `r` to refresh the catalog and latest versions. Editable / dev installs are labeled with a lowercase
`dev` source marker and compared against their git upstream rather than PyPI, so a local checkout can surface an
`↑ dev update available` hint. The SASE Core panel and plugin details can show incoming commit subjects when update
metadata is available. The top-bar update badge is purple for routine updates; it turns amber and adds `*` when the
available set includes `sase-core-rs`, warning that the update will rebuild Rust code and take longer. A single-plugin
install preview can offer both index and git sources; press `g` inside that confirmation modal to switch variants before
confirming. Every mutation previews the underlying `uv` command or editable-checkout plan first and then runs as a
tracked background task. See the [Updates tab reference](configuration.md#updates-tab) for the full keymap and behavior,
and [Plugins](plugins.md) for the equivalent `sase plugin` CLI.

## Snippets

The prompt input supports expandable text snippets triggered by pressing `Tab`. Snippets are configured in the
`ace.snippets` section of `sase.yml` as a mapping of trigger words to template strings:

```yaml
ace:
  snippets:
    fix: "Please fix the following issue:\n$0"
    review: "Review this code for correctness, performance, and style."
    bug: "Bug in $1:\n\nExpected: $2\nActual: $3\n\nPlease fix.$0"
```

### Usage

1. Type a trigger word (e.g., `fix`) in the prompt input.
2. Press `Tab`. If the word before the cursor matches a snippet, it is replaced with the template text.
3. If the template contains tabstop markers (`$1`, `$2`, ...), the cursor jumps to `$1` first. Press `Tab` again to
   advance to `$2`, then `$3`, and so on. `$0` marks the final cursor position after all tabstops are visited. If there
   are no tabstop markers, the cursor moves to the end of the expanded text.

**Tab priority:** Snippet expansion always takes priority over tabstop advancement. If you type a trigger word at an
active tabstop and press `Tab`, the snippet expands rather than jumping to the next tabstop.

**Multi-line indentation:** When a multi-line snippet is expanded on an indented line, continuation lines automatically
inherit the leading whitespace of the trigger line. Tabstop positions are adjusted accordingly.

Trigger words are matched against the alphanumeric/underscore word immediately before the cursor. If no snippet matches,
`Tab` advances to the next tabstop (if any are remaining from a previous expansion), or behaves normally.

XPrompt-derived snippets compose normal xprompt references before they enter the snippet registry. After xprompt-derived
snippets and `ace.snippets` are merged, any snippet can splice another snippet by trigger with `#[trigger]`.
`#[trigger(value)]` and `#[trigger:value]` fill the referenced snippet's `$1`, `$2`, ... tabstops before splicing. The
final template is renumbered so tabstops from the caller and referenced snippets do not collide.

You can also create a snippet on the fly from the prompt save panel, opened with `gx`, `Ctrl+G x`, or `Ctrl+G Ctrl+X`.
Press `Ctrl+X` in that panel to switch to snippet mode and choose which config file should store the new `ace.snippets`
entry; `Ctrl+G Ctrl+X Ctrl+X` performs that sequence directly from the draft. In snippet mode, rows are grouped by
source and sorted alphabetically by trigger; snippet completions elsewhere are listed in trigger order, too, for stable
display. As soon as ACE reports the snippet as created or saved, it is available to every prompt input already open in
the current TUI; no prompt remount or restart is needed.

When `use_chezmoi` is enabled, the save panel writes the chezmoi source file first. ACE keeps that successfully written
snippet live as session state even before deployment. Skipping or failing the optional commit/push/apply step does not
remove it from the running TUI, but another SASE process will not see the source-only change until chezmoi is applied.
SASE applies chezmoi from this flow only after the user confirms the optional commit-and-push action.

Editors using `sase lsp` can receive the same registry as LSP snippet completions after bare trigger words when the
client advertises `completionItem.snippetSupport`. The server uses the editor helper operation
`sase editor helper-bridge snippet-catalog` as the authoritative source and falls back to native Rust loading only for
simple snippets if the helper is unavailable. Clients without snippet support do not receive these entries, because raw
`$1` / `$0` markers would not behave like ACE tabstops.

### XPrompt Picker (`#@`)

Typing `#@` (the `#` character followed by `@`) opens the XPrompt snippet picker modal. This lists all available
xprompts (including project-local xprompts from `sase/sase.yml` files) and inserts the selected reference at the cursor
position. Inline-capable xprompts and workflows insert as `#name`; standalone workflows insert as `#!name`. The picker
uses the same argument-aware skeletons as xprompt completion, so typed inputs can be filled immediately after selection.
Markdown xprompt swarms are inline-capable and insert as `#name`. This is separate from the `ace.snippets` mechanism —
it provides quick access to xprompt references rather than expanding static templates.

## Auto-Refresh

ACE auto-refreshes data at a configurable interval (default: 10 seconds). The remaining time until the next refresh is
shown in the info panel. Set `--refresh-interval 0` to disable.

Tab switches are instant: cached data is shown immediately while a background refresh runs asynchronously, so moving
between tabs never blocks on disk I/O.

When the inotify-based artifact watcher is active, the periodic tick is **event-driven**: it consults per-surface dirty
flags (`_dirty_changespecs`, `_dirty_agents`, `_dirty_axe`) and short-circuits the whole tick when nothing has changed.
A 60-second `FULL_SANITY_REFRESH_SECONDS` floor still triggers a full reconcile to recover from missed inotify events,
so a quiet TUI does ~zero work between real changes without going stale.

### Performance Tracing

For diagnosing TUI latency, set `SASE_TUI_TRACE=1` before launching `sase ace`. Tracing is near-zero-cost when the env
var is unset; with it enabled, each instrumented hot path emits one JSONL line per span to
`~/.sase/perf/tui_trace.jsonl` (override via `SASE_TUI_TRACE_PATH=…`). See [`docs/perf_runbook.md`](perf_runbook.md) for
the full span catalog, benchmark harness, and per-phase performance targets.
