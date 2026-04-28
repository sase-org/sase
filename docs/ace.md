# ACE TUI User Guide

## Overview

ACE (Agentic ChangeSpec Explorer) is the primary TUI for the SASE toolkit. It provides an interactive interface for
navigating, managing, and operating on ChangeSpecs, agents, and the Axe daemon.

## Launching

```bash
sase ace [QUERY] [options]
```

If no query is provided, the last used query is loaded (falling back to `!!!` for error suffixes).

### CLI Options

| Option                     | Description                                                                                                     |
| -------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `QUERY` (positional)       | Query string for filtering ChangeSpecs                                                                          |
| `-m`, `--model-tier`       | Override model tier for all LLM providers (`large` or `small`)                                                  |
| `-p`, `--profile [PATH]`   | Profile the TUI session with pyinstrument (writes text output to `PATH` or `$SASE_TMPDIR/ace_profile_<ts>.txt`) |
| `-r`, `--refresh-interval` | Auto-refresh interval in seconds (default: 10, 0 to disable)                                                    |
| `-x`, `--no-axe`           | Disable auto-starting the axe daemon on startup                                                                 |
| `-v`, `--vcs-provider`     | Override VCS provider (`git`, `hg`, or `auto`)                                                                  |
| `-R`, `--restart-axe`      | Restart the axe daemon on startup (shows RESTARTING indicator)                                                  |

### Examples

```bash
sase ace                              # Last query or "!!!"
sase ace '"feature" AND "Drafted"'    # Filter by name and status
sase ace '+myproject'                 # Filter by project
sase ace -m small -r 30 '!!! OR @@@' # Small model, 30s refresh
```

## Tab System

ACE has three tabs, cycled with `Tab` and `Shift+Tab`:

| Tab                   | Description                                                |
| --------------------- | ---------------------------------------------------------- |
| **CLs** (ChangeSpecs) | Browse and act on ChangeSpecs matching the current query   |
| **Agents**            | View running and completed agents, their files and prompts |
| **Axe**               | Monitor the Axe daemon and background commands             |

## Keybindings: CLs Tab

### Navigation

| Key                 | Action                                                                             |
| ------------------- | ---------------------------------------------------------------------------------- |
| `j` / `k`           | Move to next / previous visible row (banner at fold `< L2`, CL at the leaf level)  |
| `<` / `>` / `~`     | Navigate to ancestor / child / sibling CL                                          |
| `'`                 | Jump to entry by hint character (current tab); hints land on collapsed banners too |
| `` ` ``             | Jump to entry across all tabs (see [Jump All Modal](#jump-all-modal))              |
| `Ctrl+O` / `Ctrl+K` | Jump back / forward in CL history                                                  |
| `o`                 | Cycle CL grouping mode (`BY_PROJECT` → `BY_DATE` → `BY_STATUS`)                    |
| `g` / `G`           | Scroll detail panel to top / bottom                                                |
| `Ctrl+D` / `Ctrl+U` | Scroll detail panel down / up (half page)                                          |

> **Note:** `o` ("organize") cycles the L0 grouping bucket on the Agents and CLs tabs (each tab keeps its own persisted
> mode). On the AXE tab it is a silent no-op. See [CL Grouping and Folding](#cl-grouping-and-folding) and the Agents-tab
> [Grouping Modes](#grouping-modes) below.

### CL Actions

| Key             | Action                                                      |
| --------------- | ----------------------------------------------------------- |
| `a`             | Accept proposal (`!` = spec only, `@` = mark ready to mail) |
| `b`             | Rebase CL onto parent                                       |
| `C` / `c1`-`c9` | Checkout CL (primary / workspace 1-9)                       |
| `d`             | Show diff                                                   |
| `e`             | Edit spec file                                              |
| `M`             | Mail CL                                                     |
| `m`             | Mark / unmark current CL (auto-advances to next)            |
| `n`             | Rename CL (non-Sub/Rev CLs only)                            |
| `R`             | Rewind to previous commit (`!` suffix skips VCS operations) |
| `s`             | Change status (opens status modal)                          |
| `S`             | Bulk status change for all marked CLs                       |
| `T`             | Checkout + tmux (opens workspace input modal for number)    |
| `u`             | Clear all marks                                             |
| `v`             | View files (hint mode)                                      |
| `w`             | Reword CL description                                       |
| `W`             | Add tag to CL description                                   |
| `Y`             | Sync workspace                                              |

### CL Grouping and Folding

The CLs tab is always grouped — the renderer walks one of `BY_PROJECT`, `BY_DATE`, or `BY_STATUS` and emits a banner row
above each bucket. `BY_PROJECT` is the default; `o` cycles `BY_PROJECT → BY_DATE → BY_STATUS` and the active mode is
persisted to `~/.sase/changespec_grouping_mode.txt`.

| Mode         | L0 buckets                                                                   | Notes                                                                                                                              |
| ------------ | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `BY_PROJECT` | Project name                                                                 | Adds an L1 sibling-root sub-banner shared by `foobar_1` / `foobar_2` style suffixed siblings. Singletons suppress their L1 banner. |
| `BY_DATE`    | `Today` / `Yesterday` / `This Week` / `Earlier`                              | L0 only — bucket from the latest TIMESTAMPS entry.                                                                                 |
| `BY_STATUS`  | `WIP` / `Draft` / `Ready` / `Mailed` / `Submitted` / `Reverted` / `Archived` | L0 only — bucket from the literal `status` field, in lifecycle order.                                                              |

The active grouping mode is shown in the CLs-tab info-panel header as a `[group: <label>]` badge.

| Key | Action                                                                                                                                 |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `l` | Expand the focused banner one level (or peel one layer of the visible tree)                                                            |
| `h` | Collapse the focused banner; on a collapsed L1 banner, escalate to its parent. With agent focus, collapse the deepest enclosing group. |
| `L` | Snap to fully expanded — all banners and CL rows visible                                                                               |
| `H` | Snap to fully collapsed — collapse every visible banner                                                                                |

Collapsed banner rows are first-class navigation stops: `j`/`k` step through them just like CL rows, and `'` jump-hints
land on them too. After a fold change that hides the focused CL, focus snaps to the deepest collapsed ancestor banner so
the cursor always sits on a row the user can see.

### Fold Mode (`z` prefix)

| Key     | Action                                                 |
| ------- | ------------------------------------------------------ |
| `z` `c` | Cycle commits section (expand → collapse)              |
| `z` `h` | Cycle hooks section (expand → collapse)                |
| `z` `m` | Cycle mentors section (expand → collapse)              |
| `z` `t` | Cycle timestamps section (expand → collapse)           |
| `z` `C` | Toggle commits section (collapsed ↔ fully expanded)    |
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

### Workflows and Agents

| Key     | Action                                          |
| ------- | ----------------------------------------------- |
| `r`     | Run workflow on current CL                      |
| `@`     | Run a custom agent (opens project/CL selection) |
| `Space` | Run agent from current CL                       |

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

| Key        | Action                                                            |
| ---------- | ----------------------------------------------------------------- |
| `,!`       | Run command using current CL context                              |
| `,c`       | Clear COMMENTS field (kills CRS agents, deletes CRS proposals)    |
| `,h`       | Run agent (home directory)                                        |
| `,m`       | Review mentors (opens Mentor Review modal)                        |
| `,M`       | Kill running mentors                                              |
| `,r`       | Show runners info                                                 |
| `,t`       | Open task queue modal (see [Task Queue Modal](#task-queue-modal)) |
| `,<space>` | Run agent from current CL (skips project selection)               |
| `,.`       | Open prompt history modal for the last CL                         |
| `,>`       | Open prompt history modal with cancelled prompts visible          |

> **Note:** `,x` (kill & edit) is only available on the Agents tab — see
> [Agents Tab Leader Mode](#leader-mode--prefix-1).

### Mentor Review Modal

Press `,m` to open the Mentor Review modal, which lets you navigate mentor comments, accept or reject suggestions, and
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
| `%c` | Copy CL number             |
| `%n` | Copy CL name               |
| `%p` | Copy project spec file     |
| `%s` | Copy sase ace snapshot     |

## Keybindings: Agents Tab

### Navigation

| Key                 | Action                                                                                                |
| ------------------- | ----------------------------------------------------------------------------------------------------- |
| `j` / `k`           | Move to next / previous visible row (banner at fold `< L3`, agent at `L3`)                            |
| `J` / `K`           | Cycle focus across tag side panels (forward / reverse)                                                |
| `'`                 | Jump to entry by hint character (current tab); on the Agents tab, hints land on collapsed banners too |
| `` ` ``             | Jump to entry across all tabs (see [Jump All Modal](#jump-all-modal))                                 |
| `o`                 | Cycle grouping mode (`STANDARD` → `BY_DATE` → `BY_STATUS`)                                            |
| `g`                 | Scroll to top (file, thinking, or metadata panel)                                                     |
| `G`                 | Scroll to bottom (file, thinking, or metadata panel)                                                  |
| `Ctrl+D` / `Ctrl+U` | Scroll file panel down / up                                                                           |
| `Ctrl+F` / `Ctrl+B` | Scroll prompt panel down / up                                                                         |

> **Note:** `o` ("organize") cycles the grouping mode on the Agents and CLs tabs (each tab persists its own selection
> independently); on the AXE tab it is a silent no-op. `g`/`G` keep their conventional vim-style scroll-to-top/bottom
> meaning on every tab. See [Grouping Modes](#grouping-modes) below.

### Agent Actions

| Key                 | Action                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------- |
| `R`                 | Revive a previously dismissed agent                                                                           |
| `@`                 | Run custom agent                                                                                              |
| `a`                 | Toggle auto-approve / answer HITL                                                                             |
| `n`                 | Name agent                                                                                                    |
| `r`                 | Resume agent (by name if running, by chat file if completed)                                                  |
| `v`                 | View files (hint mode)                                                                                        |
| `V`                 | Toggle prior-attempt view (only shown when the agent has retried)                                             |
| `w`                 | Wait/unwait agent (opens WaitModal — see below)                                                               |
| `W`                 | Wait for agent (populate prompt with `%w`); with marks, fans out to `%w:a,b,c`                                |
| `m`                 | Mark / unmark current agent (auto-advances to next)                                                           |
| `u`                 | Clear all agent marks                                                                                         |
| `x`                 | Kill / dismiss agent, every marked agent, or every agent in the focused group                                 |
| `X`                 | Dismiss every completed agent in the focused tag panel (with confirmation)                                    |
| `Enter` / `L`       | Jump to CL (for agents with `meta_new_cl`/`meta_new_pr`)                                                      |
| `e`                 | Edit chat in editor                                                                                           |
| `E`                 | Edit panel content in editor                                                                                  |
| `t`                 | Open tmux window in the focused agent's claimed workspace                                                     |
| `T`                 | Open tmux window in the agent's primary (workspace 1) directory                                               |
| `N`                 | Open the agent tag/untag modal (input is pre-seeded with `pinned` for untagged agents; submit empty to clear) |
| `]` / `[`           | Cycle panels: file → thinking → metadata (forward / reverse)                                                  |
| `p`                 | Toggle file / prompt layout                                                                                   |
| `Ctrl+N` / `Ctrl+P` | Next / previous file in panel                                                                                 |
| `-`                 | Reset file trim to default                                                                                    |
| `=`                 | Show all file lines                                                                                           |

### Wait Modal

Press `w` on the Agents tab to open the WaitModal. Behavior depends on the agent's status:

- **WAITING agent**: Enter another agent's name to wait for, or leave empty and press Enter to run immediately (unwait).
- **RUNNING agent**: Enter an agent name to kill the current agent and restart it with a `%w` (wait) directive. This is
  useful for redirecting an agent to wait on a different dependency.

The modal supports readline-style keybindings (`Ctrl+F`/`Ctrl+B`/`Ctrl+A`/`Ctrl+E`) for cursor movement.

### VCS Tag Resolution in Resume/Wait

When resuming or waiting on an agent, VCS tags in the prompt (e.g., `#git(ref)`, `#gh:ref`) are automatically updated to
point to the correct branch. For non-project agents, the ref is replaced with the agent's CL name (branch). For project
agents using `#pr`, the ref is replaced with `@<name>` which resolves to the agent's branch. HITL suffixes (`!!`, `??`)
are stripped during replacement since resume scenarios should not carry over HITL overrides.

### Workflow Visibility

Workflows launched via `sase run` are visible in the Agents tab alongside ACE-launched workflows. The TUI scans
`artifacts/run/*` directories in addition to `workflow-*` and `ace-run` directories, and writes an initial
`workflow_state.json` before execution so that step data appears immediately rather than showing a bare RUNNING entry.

### Tag Side Panels

The Agents tab is laid out as a series of vertically-stacked side panels, one per agent **tag**. Untagged agents live in
their own `(untagged)` panel; each tagged group renders as `@<tag>` with an agent count in the panel title. Panel
heights are sized to their content (subject to a configurable floor and cap), and the last panel in a column expands to
fill any leftover vertical space so empty rows don't drift to the bottom.

Use `J` / `K` to move focus across panels (forward / reverse). Per-panel actions (kill, dismiss, expand, etc.) operate
on whichever panel currently holds focus.

Tags are set or cleared with `N` (see [Agent Actions](#agent-actions)). When opening the modal on an untagged agent the
input is pre-seeded with `pinned` so a single Enter promotes the agent into the standard "pinned" panel; that default
makes tag removal discoverable too — opening the modal on a tagged agent and submitting an empty string clears the tag.
The `%tag <name>` directive in a prompt assigns the tag at launch.

### Group Banners and Folding

Within each tag side panel, agents are grouped into either a 2-level or 3-level banner hierarchy depending on whether
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

Banners at fold levels `< 3` are selectable rows. When a banner is focused, `x` performs a bulk kill/dismiss on every
top-level agent in that group (single confirmation modal). Marks take priority over the group, so a non-empty mark set
always drives the bulk action regardless of banner focus. When a fold change hides the previously focused agent, focus
snaps to the nearest visible ancestor banner so navigation context is never lost.

Visual treatment: every row carries a fixed-width tier-guide gutter built from one `│  ` segment per ancestor L0/L1
banner (in the parent tier's dim accent — project blue or ChangeSpec cooler accent), so nesting reads as a tree at a
glance. L0 project / bucket banners use a sky-blue `▌` left bar and a heavy `━` rule; L1 ChangeSpec banners get a cooler
accent with a `▎` bar and a lighter `─` rule, so banner weight forms a three-tier gradient. Name-root banners use a `▸`
branch glyph (with the gutter doing the indentation work). Singleton name-root groups suppress their banner entirely to
reduce visual noise.

After a kill or dismiss, focus re-anchors on the visually-next row (rather than the next row in input order) so the
selection always lands somewhere meaningful in the rendered tree.

### Grouping Modes

Press `o` on the Agents tab to cycle the L0 grouping bucket through three modes. The Agents tab shows a brief toast
(`Grouping: by project` / `by date` / `by status`) on each cycle:

| Mode        | L0 buckets                                                    | Notes                                                                                       |
| ----------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `STANDARD`  | Project (with optional ChangeSpec sub-level)                  | The "by project" default. Uses the 2-/3-level layout described above.                       |
| `BY_DATE`   | `Today` / `Yesterday` / `This Week` / `Earlier`               | Two levels: date bucket at L0, hour-of-day (`HH:00`) sub-banner at L1. Sorted newest-first. |
| `BY_STATUS` | `Needs Attention` / `Running` / `Waiting` / `Failed` / `Done` | Bucketed by status (and retry-chain lineage); name-root sub-level inside each bucket.       |

In `BY_DATE` mode the L0 date bucket is sub-grouped by **hour-of-day** so long Today/Yesterday lists are easier to scan.
The hour anchor is `stop_time` for terminal agents and `start_time` otherwise; banners render as `HH:00` and sort
newest-first within their date bucket. Workflow children inherit the parent's anchor so they stay adjacent regardless of
their own start time, singleton hours suppress their sub-banner, and agents with no usable timestamp fall into a
`(no time)` bucket that sorts last. In `BY_STATUS` mode the L0 banner is the status bucket and L1 is the name-root, with
the same singleton-suppression rule as `STANDARD`. Each mode keeps its own per-group fold registry, so collapsing
buckets in `BY_STATUS` doesn't affect the project layout you had in `STANDARD`. `BY_STATUS` banners are prefixed with
semantic glyphs (`▲`, `▶`, `⏳`, `✗`, `✓`) so the bucket title still leads visually.

The active grouping strategy is also surfaced in the Agents tab header via a `[group: <label> (o)]` badge so the durable
mode is always visible after the cycle toast fades. The selected mode is persisted to `~/.sase/grouping_mode.txt` and
restored on the next TUI launch (mirroring the `last_selection.txt` precedent), so cycling once is durable. **Waiting**
holds agents that are blocked but progressing on their own — `WAITING` with a `wait_until` timer (`%wait:5m`,
`%wait:1430`) or a non-empty `waiting_for` dependency. **Needs Attention** keeps the strict "you need to act" semantics:
a `WAITING` agent with neither a timer nor a dependency stays there because it's parked waiting on the user.

### Agent Row Glyphs

To keep rows compact, agent statuses and types are rendered as one- or two-character badges instead of verbose text:

| Glyph | Meaning                                              |
| ----- | ---------------------------------------------------- |
| `▶`   | RUNNING                                              |
| `✓`   | DONE                                                 |
| `✓P`  | PLAN DONE                                            |
| `▶P`  | PLAN APPROVED                                        |
| `★E`  | EPIC CREATED                                         |
| `✎`   | PLANNING                                             |
| `✗`   | FAILED                                               |
| `⏳`  | WAITING                                              |
| `?`   | QUESTION                                             |
| `↻`   | RETRYING (followed by attempt count, e.g. `↻2`)      |
| `≡`   | Workflow row (top-level)                             |
| `❑`   | ChangeSpec / CL row (top-level)                      |
| `⚡`  | Autonomous (`%approve`) agent                        |
| `◌`   | Hidden agent (visible only when `.` toggles them in) |

The right-hand edge of each row carries a runtime suffix (`<start-timestamp> · <elapsed>`) right-aligned within the
panel. For finished agents, the start-timestamp half is rendered as a humanized `(date_prefix, time)` pair sized to fit
the existing 15-cell slot:

- **Same day**: `HH:MM:SS`
- **Prior day, same year**: `Mon DD HH:MM` (drops seconds — they're noise once a row finished hours ago)
- **Different year**: `Mon DD 'YY` (date only)

The date prefix uses a softer `dim #8787AF` while the time half keeps the standard `#8787AF`, giving the column internal
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

| Key        | Action                                                                      |
| ---------- | --------------------------------------------------------------------------- |
| `,h`       | Run agent (home directory)                                                  |
| `,I`       | Toggle manual idle (shows IDLE indicator; any keypress re-activates)        |
| `,n`       | Jump to agent notification (plan or question; auto-unhides if needed)       |
| `,r`       | Edit prompt and relaunch agent (retry without killing)                      |
| `,x`       | Kill agent & edit prompt                                                    |
| `,X`       | Kill & dismiss every agent (running and completed) in the focused tag panel |
| `,<space>` | Run agent from current agent's CL (skips selection)                         |
| `,.`       | Open prompt history modal for the last CL                                   |
| `,>`       | Open prompt history modal with cancelled prompts visible                    |

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

### Navigation

| Key                 | Action                              |
| ------------------- | ----------------------------------- |
| `j` / `k`           | Move to next / previous command     |
| `Ctrl+N` / `Ctrl+P` | Next / previous lumberjack output   |
| `g`                 | Scroll to top                       |
| `G`                 | Scroll to bottom (pins auto-scroll) |

### Commands

| Key | Action                                                                 |
| --- | ---------------------------------------------------------------------- |
| `@` | Run agent                                                              |
| `r` | Re-run the selected bgcmd (only when a completed bgcmd row is focused) |
| `x` | Start / stop axe (or kill bgcmd)                                       |
| `X` | Clear output                                                           |

### Leader Mode (`,` prefix)

| Key  | Action                     |
| ---- | -------------------------- |
| `,h` | Run agent (home directory) |
| `,r` | Show runners info          |

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

Press `1`-`9` or `0` to instantly load a saved query. These also work from within the help modal (`?`).

### Query History

| Key | Action                                |
| --- | ------------------------------------- |
| `^` | Navigate to previous query in history |
| `_` | Navigate to next query in history     |

Query history is available on the CLs tab and tracks queries as you switch between them.

See [`docs/query_language.md`](query_language.md) for the full query syntax reference, including boolean expressions,
status shorthands, property filters, and searchable fields.

## Global Keybindings

These work on all tabs:

| Key                 | Action                                                                            |
| ------------------- | --------------------------------------------------------------------------------- |
| `Tab` / `Shift+Tab` | Switch between CLs, Agents, and Axe tabs                                          |
| `#`                 | Open XPrompt Browser (see [XPrompt Browser](#xprompt-browser) below)              |
| `.`                 | Toggle visibility of hidden items (reverted CLs, non-run agents, or axe commands) |
| `,i`                | Open Activity Dashboard modal                                                     |
| `i`                 | Show notifications inbox                                                          |
| `I`                 | Pin idle mode (IDLE stays until `I` is pressed again; keypresses don't clear it)  |
| `Q`                 | Stop axe daemon and quit                                                          |
| `y`                 | Refresh current tab                                                               |
| `q`                 | Quit                                                                              |
| `?`                 | Show help modal                                                                   |

### Quit Confirmation

When quitting (`q` or `Q`) while background tasks are still running (task queue workers or background command slots), a
confirmation dialog appears showing the count of active tasks and asking whether to kill them and quit. Declining the
dialog cancels the quit and returns to the TUI.

## Notifications Modal

Press `i` (or the `,n` leader chord to jump straight to an agent's notification) to open the notifications modal. See
[`docs/notifications.md`](notifications.md) for the full keybinding reference, the priority/inbox/muted section
taxonomy, and the per-notification snooze and mute affordances.

The top-bar notification indicator color reflects the highest-priority unread bucket: orange for **PRIORITY**
notifications (plan approvals, user questions, mentor reviews, axe errors, CRS results, agent error reports), gold for
regular **INBOX** notifications, and cyan when only **MUTED** notifications remain.

## Notification Actions

Some notifications carry an `action` field that triggers a handler when the notification is selected. The following
notification action types are supported:

| Action            | Source     | Behavior                                                     |
| ----------------- | ---------- | ------------------------------------------------------------ |
| `ViewErrorReport` | Axe daemon | Opens the error digest file in `$EDITOR` for review          |
| `plan`            | Agent      | Jumps to the agent's plan notification in the Agents tab     |
| `question`        | Agent      | Jumps to the agent's question notification in the Agents tab |

The `ViewErrorReport` action is created by the axe `error_digest` chop when errors accumulate. The digest file
summarizing recent errors is stored at `~/.sase/axe/error_digests/digest_<timestamp>.txt`.

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

Press `#` on any tab to open the XPrompt Browser modal. It displays all discovered xprompts in a two-panel layout: a
filterable list on the left and a syntax-highlighted preview on the right.

Xprompts are grouped by source (CWD `.xprompts/`, CWD `xprompts/`, Home `~/.xprompts/`, Home `~/xprompts/`,
project-specific, config `sase.yml`, plugins, built-in). Workflow xprompts (multi-step YAML) are marked with a gear
icon. Project-local xprompts defined in each project's `sase.yml` file are also included, even though the TUI's normal
config loading does not read project-local config files.

### Keybindings

| Key      | Action                                |
| -------- | ------------------------------------- |
| `Ctrl+N` | Navigate to next xprompt              |
| `Ctrl+P` | Navigate to previous xprompt          |
| `Ctrl+D` | Scroll preview panel down             |
| `Ctrl+U` | Scroll preview panel up / clear input |
| `Enter`  | Edit highlighted xprompt in `$EDITOR` |
| `Ctrl+O` | Add a new xprompt                     |
| `Esc`    | Close browser                         |

Type in the filter input to narrow the list in real time.

### Editing XPrompts

Press `Enter` on any xprompt to edit it in `$EDITOR`. All xprompts are editable, including plugin and built-in sources —
these are copied to the highest-priority user directory (`~/.xprompts/`) before opening, so edits create an override
rather than modifying the original. After saving, the browser offers to commit and push changes to git if applicable.

### Creating XPrompts

Press `Ctrl+O` to start the guided creation flow:

1. **Location modal** — Choose where to save the new xprompt (CWD `.xprompts/`, CWD `xprompts/`, Home `~/.xprompts/`,
   Home `~/xprompts/`, or a config file). Press `Ctrl+G` to open the selected config file in `$EDITOR` instead of
   proceeding with creation.
2. **Filename modal** — Enter a filename (`.md` for prompt parts, `.yml` for workflows). Workflow files are pre-filled
   with a YAML template containing the workflow scaffold.
3. **Editor** — The file opens in `$EDITOR` for editing.
4. **Git commit** — After saving, the browser offers to commit and push changes.

## Idle Detection

ACE tracks user activity and displays an orange **IDLE** badge in the top bar when the user has been inactive for longer
than the configured threshold (`ace.inactive_seconds`, default: 600 seconds). The badge is also shown when the user
presses `,I` (leader chord) to manually mark themselves as inactive. Any keypress re-activates the user and hides the
badge.

Pressing `I` (capital) activates **pinned idle** mode, shown as a red **■ IDLE** badge. Pinned idle stays active
regardless of keypresses — only pressing `I` again clears it. This is useful when you want to remain marked as idle
while still interacting with the TUI. Pinned idle state is persisted to `~/.sase/tui_pinned_idle` and automatically
restored when the TUI restarts, so the user remains marked as idle across sessions.

External tools (e.g., chop scripts) can call `is_idle()` from `sase.ace.tui_activity` to check idle status
programmatically.

## Jump All Modal

Press `` ` `` (backtick) on any tab to open the Jump All Modal. It displays all entries across CLs, Agents, and Axe tabs
with single-keypress hint characters for instant navigation. Selecting an entry switches to the appropriate tab and
focuses it.

Hint characters are drawn from an extended alphabet — lowercase `a`–`z` first, then uppercase `A`–`Z` — so modals with
many entries can still fit a unique single-keypress hint per row without resorting to multi-character hints.

| Key         | Action                          |
| ----------- | ------------------------------- |
| Hint char   | Jump to the corresponding entry |
| `Esc` / `q` | Close modal                     |

The modal groups entries by tab (CLs, Agents, Axe) and shows contextual information for each: CL names and statuses,
agent names with running indicators, and Axe lumberjack/command labels.

### Jump Back

Both jump modals support a jump-back feature for toggling between two entries:

- **Backtick jump-back**: Pressing `` ` `` inside the Jump All Modal returns to the previous position, enabling quick
  toggling between two entries across tabs.
- **Apostrophe jump-back**: Pressing `'` twice (`''`) in the single-tab entry jump mode jumps back to the previously
  jumped-from entry. The footer shows a "JUMP" mode indicator with `' back` when a target exists.

The single-tab variant (`'` apostrophe) shows entries only from the current tab with the same hint-character navigation.

## Mentor Comment Stats in CL List

When a ChangeSpec has completed mentor reviews with comments, the CLs tab list entry shows inline stats:

- **checkmark + count** (e.g., `✓3`) — number of accepted comments
- **dot + count** (e.g., `●2`) — number of unread comments

These stats are computed from the latest commit entry's finished mentors. They update as you accept or read comments in
the Mentor Review modal.

## Tab Bar Display

The tab bar shows contextual counts alongside each tab label using the format `(MxD.H)`:

- **M** — main count (CLs, running agents, or running lumberjacks)
- **x*D*** — done/completed count (separated by `x`)
- **._H_** — hidden count, shown when hidden items are visible (separated by `.`)

Examples:

- **CLs tab**: `CLs (5)` for 5 CLs, or `CLs (5.2)` when 2 hidden (reverted) CLs are visible
- **Agents tab**: `Agents (2)` for 2 running agents, `Agents (2x1)` for 2 running + 1 done, `Agents (2x1.3)` with 3
  hidden also visible
- **AXE tab**: `AXE (3)` for 3 running lumberjacks, `AXE (3x2.1)` for 3 lumberjacks + 2 done bgcmds + 1 hidden command
  visible

### Background Task Indicator

A gear icon (⚙) with a count appears in the top bar when background tasks are running (e.g., sync, mail, accept
operations). The indicator automatically hides when all background tasks complete.

### Runners Modal

Press `,r` (leader + `r`) to open the runners modal. It shows concurrency information including hook runners, agent
runners, and a **Background Tasks** section listing active and recently completed background tasks (sync, rebase,
accept, mail, add-tag). Each task entry shows its type, CL name, status, and timestamps.

## File Panel Trimming

When viewing agent files on the Agents tab, large files are automatically trimmed to fit the visible viewport. A blue
indicator shows "N more lines below" when content is trimmed. Trim controls (`-`, `=`) are listed in the
[Agent Actions](#agent-actions) keybindings above. Trim state is preserved when switching between agents or refreshing
data.

Pressing `G` on a trimmed file auto-expands it first, then scrolls to the bottom — so jumping to the end of a large file
never leaves you staring at a trimmed page.

## Agent Auto-Naming

All agents are automatically assigned a short alphabetic name (`a`, `b`, ..., `z`, `aa`, `ab`, ...) when launched
without an explicit `%name` directive. Names are allocated sequentially, reusing names from dismissed agents. This
enables the resume-by-name workflow: press `r` on a running named agent to queue a follow-up that waits for it to finish
and then loads its conversation history.

### Per-Step Naming for Multi-Agent Workflows

When a workflow spawns follow-up agents (e.g., plan approval followed by a coder step), the agents receive dotted names
derived from the base name. For example, if the initial agent is named `a`:

1. When the first follow-up is created, the initial agent is renamed from `a` to `a.1`
2. The follow-up agent becomes `a.2`
3. Subsequent follow-ups become `a.3`, `a.4`, etc.

The base name (`a`) is reserved for the workflow as a whole, so `%wait:a` or `@a` references resolve correctly. Single-
agent workflows (no follow-ups) keep their original name unchanged.

## Agent Statuses

Each agent in the Agents tab displays a status label indicating its current state. Statuses fall into two categories:
active (the agent is still running or awaiting input) and completed (the agent has finished).

### Active Statuses

| Status             | Color        | Description                                                        |
| ------------------ | ------------ | ------------------------------------------------------------------ |
| **RUNNING**        | Gold         | Agent subprocess is executing                                      |
| **WAITING**        | Light blue   | Agent is queued, waiting for another agent to complete (`%wait`)   |
| **WAITING INPUT**  | Amber/orange | Workflow is paused at a human-in-the-loop (HITL) step              |
| **PLANNING**       | Pink/magenta | Agent has produced a plan and is waiting for user approval         |
| **PLAN APPROVED**  | Cyan         | Plan was approved; follow-up agent has been spawned                |
| **EPIC APPROVED**  | Cyan         | Plan was approved as an epic; `.epic` follow-up is running         |
| **PLAN COMMITTED** | Cyan         | Plan was approved with auto-commit; `.commit` follow-up is running |
| **QUESTION**       | Amber        | Agent is asking the user a question (via `/sase_questions`)        |
| **RETRYING**       | Orange       | Agent hit a retryable error and is in a countdown before retrying  |

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
| **EPIC CREATED** | Green | Plan workflow completed and its latest `.epic` follow-up finished successfully |
| **FAILED**       | Red   | Agent exited with an error                                                     |

Completed agents can be dismissed with `x` (single) or `X` (all completed).

### Agent Revival

Press `R` on the Agents tab to revive a previously dismissed agent. All dismissed agent chats are saved as individual
files under `~/.sase/dismissed_bundles/` and can be restored at any time. There is no limit on the number of dismissed
agents that can be stored.

Dismiss operations are O(1) per agent — each agent is saved to its own file rather than a monolithic store.

#### Dismissed-Name Prefix

When an agent is dismissed it is renamed in place to `YYmmdd.<base>` — a six-digit completion-date prefix on top of the
agent's live base name. The prefix is persisted into the dismissed bundle's `agent_name` and `cl_name`, and any visible
agent that referenced the dismissed name (`%wait:foo`, `#resume:foo`) has those references rewritten to the prefixed
form so cross-agent dependencies keep resolving after dismissal.

If the same base name was already used by a previous dismissed agent on the same date, the new dismissal allocates a
collision suffix (`YYmmdd.<base>.2`, `.3`, …) so historical names stay unique.

On revive the prefix is stripped and any visible references to the prefixed name are rewritten back to the base name, so
a revived agent rejoins its old peers transparently. Bare `%wait` (no target) intentionally skips dismissal-prefixed
candidates so it always anchors on a live, visible agent.

## Agents Tab Metadata Panel

The Agents tab metadata panel (cycled to via `]`/`[`) shows structured information about the selected agent:

- **Agent details**: Name, status, model, provider, CL association, and chronologically sorted timestamps:
  - `WAIT` — when the agent was spawned (waiting for a slot)
  - `BEGIN` — when execution started
  - `PLAN` — each plan proposal round (multiple entries when re-planning occurs)
  - `FBACK` — each time the agent requested feedback from the user
  - `QUEST` — each time the agent asked the user a question
  - `RETRY` — each time the agent entered retry state (retryable error)
  - `CODE` — when the agent began writing code
  - `END` — when execution completed
- **AGENT REPLY**: The agent's live or completed reply content, streamed from `live_reply.md` during execution and read
  from the artifacts directory after completion. When per-turn reply timestamps are available (recorded in
  `live_reply_timestamps.jsonl`), the reply is displayed with timestamp dividers between each agent turn. For agents
  with follow-up phases (planner, feedback rounds, coder), the AGENT REPLY section consolidates replies from all phases
  into a single view with purple phase dividers showing each phase's label and start time

When the file or thinking panel is empty, the `g`/`G` keys automatically fall back to scrolling the metadata panel.

## Plan Workflows

When a workflow uses the `%plan` directive, the agent enters a planning phase before executing:

- **PLANNING** — The agent has produced a plan and is waiting for user approval. Shown in pink/magenta in the prompt
  panel.
- **PLAN APPROVED** — The plan has been approved and the follow-up agent has been spawned. Shown in cyan/turquoise.

Plan files generated by the agent are displayed in the file panel alongside other agent artifacts. Plan approval
notifications include the LLM provider and model name, so users can see which model proposed the plan (visible in both
the TUI notification modal and Telegram delivery).

The Plan Review modal title shows a provider-themed `PROVIDER(model)` badge between the "Plan Review" label and the plan
filename — orange for Claude, lime for Codex, Google blue for Gemini, neutral muted for other providers. The badge is
omitted when provider/model metadata is absent, leaving the legacy title shape unchanged.

### Plan Approval Keybindings

| Key          | Action                                                           |
| ------------ | ---------------------------------------------------------------- |
| `a`          | Approve the plan                                                 |
| `A`          | Approve with options (opens [Approve Options](#approve-options)) |
| `r`          | Reject the plan                                                  |
| `f`          | Request feedback (send follow-up questions to the agent)         |
| `e`          | Edit the plan file in `$EDITOR`                                  |
| `E`          | Mark the plan as an epic (creates bead)                          |
| `y`          | Copy plan content to clipboard                                   |
| `Y`          | Copy plan file path to clipboard                                 |
| `Ctrl+D`/`U` | Scroll plan content down / up                                    |
| `g` / `G`    | Scroll to top / bottom                                           |
| `q` / `Esc`  | Cancel                                                           |

The question modal also supports `y` to copy questions and selected answers.

### Approve Options

Pressing `A` in the plan approval modal opens an options dialog with fine-grained control over what happens after
approval:

| Key         | Action                  |
| ----------- | ----------------------- |
| `Enter`     | Approve with selections |
| `Space`     | Toggle focused switch   |
| `Ctrl+N`    | Next field              |
| `Ctrl+P`    | Previous field          |
| `q` / `Esc` | Cancel                  |

The dialog presents toggle switches, an optional text input, and a model picker:

- **Commit plan** (default: ON) — Whether to commit the plan file
- **Run coder agent** (default: ON) — Whether to launch a coder agent after approval
- **Additional prompt** — Optional extra instructions for the coder agent (only editable when coder is ON)
- **Coder model** — Select an LLM model for the coder agent instead of inheriting the planner's model. Shows all
  registered models grouped by provider (Claude, Codex, Gemini) with a "Custom..." option for freeform input.

At least one of commit/coder must be enabled — disabling one locks the other ON.

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

Every time the axe retry loop retries an agent — context-overflow restart, user-configured retry, or fallback-model
switch — the failed attempt's partial reply, error text, timestamps, and model are snapshotted under
`<artifacts_dir>/attempts/<N>/`. The AGENT REPLY area in the Agents tab renders these prior attempts inline with styled
dividers before the current/final attempt, so the full arc of the agent's work stays visible in one scroll.

Press `V` to collapse the view to the current attempt only; press `V` again to re-expand. The binding only appears in
the keybinding footer when the selected agent has one or more prior attempts.

## Custom Keymaps

All TUI keybindings are configurable via the `ace.keymaps` section in `sase.yml`. You can remap any built-in key and
define entirely new prefix-key modes.

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
- **Duplicate keys** (two actions bound to the same key) are detected and the conflicting override is reverted
- **Prefix conflicts** between custom mode prefixes and existing app bindings are warned

See [`docs/configuration.md`](configuration.md) for the full `ace.keymaps` configuration reference.

## Prompt Input Widget

The prompt input is a multiline TextArea widget that supports two editing modes: INSERT and NORMAL. The widget provides
markdown syntax highlighting for prompt content (headings, bold, italic, code blocks, lists, etc.).

### INSERT Mode (Default)

| Key      | Action                                                                   |
| -------- | ------------------------------------------------------------------------ |
| `Enter`  | Submit the prompt                                                        |
| `Ctrl+J` | Insert a newline                                                         |
| `Ctrl+A` | Move to start of line (jumps to previous line start if already at col 0) |
| `Ctrl+E` | Move to end of line (jumps to next line end if already at end)           |
| `Ctrl+G` | Open full prompt in `$EDITOR`                                            |
| `Ctrl+I` | Load a prompt from history                                               |
| `Ctrl+T` | Completion (file paths or xprompt names; see [Completion](#completion))  |
| `Tab`    | Snippet expansion (see below)                                            |
| `#@`     | Open XPrompt snippet picker (type `#` then `@`)                          |
| `Escape` | Switch to vim NORMAL mode                                                |

Text automatically wraps at the terminal width, breaking at spaces (never mid-word). Line numbers appear in cyan when
the text exceeds one line.

### Completion

Press `Ctrl+T` to activate completion. The completion kind is determined by the token under the cursor:

- **XPrompt completion**: When the cursor is on a `#`-prefixed token (e.g., `#my_pro`), completion shows matching
  xprompt names from all discovery sources.
- **File path completion**: When the cursor is on a path-like token (starting with `/`, `./`, `../`, `~/`, or containing
  `/`), completion shows matching filesystem entries. Tokens starting with `@` are also recognized — the `@` prefix is
  preserved in the completed path (useful for file-reference arguments).
- **File-history completion**: When the cursor is in whitespace (or at an empty prompt prefix), `Ctrl+T` opens a list of
  recently referenced files drawn from prompt history, ranked by recency. Project-local `.sase/` paths are filtered out
  so internal bead/plan artifacts don't pollute the suggestions. Press `Ctrl+D` in the completion panel to delete the
  highlighted entry from the on-disk history.

| Key                | Action                                   |
| ------------------ | ---------------------------------------- |
| `Ctrl+T`           | Start completion or insert shared prefix |
| `Ctrl+N` / `Down`  | Next candidate                           |
| `Ctrl+P` / `Up`    | Previous candidate                       |
| `Enter` / `Ctrl+L` | Accept highlighted candidate             |
| `Escape`           | Cancel completion                        |

For file completion, directories appear before files in the candidate list. Dotfiles are hidden unless the partial
prefix starts with `.`. Accepting a directory automatically re-opens completion for the next level (drill-down). The
completion panel shows up to 10 candidates at a time and scrolls to keep the highlight visible.

### Special Prompt Shortcuts

| Input | Action                                                            |
| ----- | ----------------------------------------------------------------- |
| `.`   | Open prompt history modal for the current CL                      |
| `.x`  | Open prompt history modal with cancelled prompts shown by default |

### NORMAL Mode

Press `Escape` in INSERT mode to enter vim-style NORMAL mode. The border title shows `[NORMAL]` and line numbers switch
to relative numbering (current line shows absolute, others show offset).

#### Motions

| Key               | Action                        |
| ----------------- | ----------------------------- |
| `h` / `l`         | Move left / right             |
| `j` / `k`         | Move down / up (actual lines) |
| `w` / `W`         | Next word / WORD start        |
| `e` / `E`         | Next word / WORD end          |
| `b` / `B`         | Previous word / WORD start    |
| `f{c}` / `F{c}`   | Find char forward / backward  |
| `t{c}` / `T{c}`   | Till char forward / backward  |
| `;` / `,`         | Repeat / reverse last f/F/t/T |
| `0` / `$`         | Line start / end              |
| `^`               | First non-blank character     |
| `gg` / `G`        | Top / bottom of document      |
| `Ctrl+D`/`Ctrl+U` | Half-page down / up           |

All motions accept a numeric count prefix (e.g., `3j` moves down 3 lines).

#### Operators

| Key   | Action                                                  |
| ----- | ------------------------------------------------------- |
| `d`   | Delete (takes a motion, e.g. `dw`); copies to clipboard |
| `c`   | Change (takes a motion, e.g. `cw`); copies to clipboard |
| `D`   | Delete to end of line                                   |
| `C`   | Change to end of line                                   |
| `dd`  | Delete entire line                                      |
| `cc`  | Change entire line                                      |
| `dae` | Delete entire buffer (copies to clipboard)              |
| `cae` | Change entire buffer (copies to clipboard)              |

#### Other Commands

| Key | Action                                                       |
| --- | ------------------------------------------------------------ |
| `i` | Enter INSERT mode                                            |
| `a` | Append after cursor                                          |
| `A` | Append at end of line                                        |
| `I` | Insert at line start                                         |
| `o` | Open line below                                              |
| `O` | Open line above                                              |
| `u` | Undo                                                         |
| `x` | Delete character                                             |
| `p` | Paste                                                        |
| `~` | Toggle case of character(s) at cursor (supports count: `5~`) |
| `.` | Repeat last mutation (supports count: `3.`)                  |
| `J` | Join current line with next (supports count: `5J`)           |

The border subtitle shows pending operators and counts (e.g., `2d` when a delete with count 2 is pending).

## Prompt History Modal

Press `,.` (leader + `.`) on the CLs or Agents tab to open the prompt history modal. It displays prompts previously run
in ACE, sorted by relevance to the current CL/agent context. Prompts shorter than two words are skipped when writing to
history, so trivial one-word inputs (e.g. `y`, `ok`) don't clutter the list.

### Keybindings

| Key      | Action                                        |
| -------- | --------------------------------------------- |
| `Enter`  | Submit the highlighted prompt directly        |
| `Ctrl+G` | Edit first — load prompt into editor          |
| `Ctrl+I` | Load prompt into the input widget for editing |
| `Ctrl+X` | Toggle visibility of cancelled prompts        |
| `Ctrl+Y` | Copy prompt to clipboard                      |
| `Ctrl+D` | Delete highlighted entry from history         |
| `Esc`    | Close modal                                   |

### Filtering

Type in the search box to filter prompts by text or branch/workspace name. Press `Ctrl+X` to toggle cancelled prompts on
or off — when enabled, cancelled prompts appear in the results with a `✗` marker.

### Visual Markers

| Marker | Color   | Meaning                          |
| ------ | ------- | -------------------------------- |
| `*`    | Green   | Prompt matches current branch    |
| `~`    | Yellow  | Prompt matches current workspace |
| `✗`    | Magenta | Prompt was cancelled             |

## Task Queue Modal

Press `,t` (leader + `t`) to open the task queue modal. It shows background tasks (hook runs, mentor executions, etc.)
with live output for running tasks and completed output for finished ones.

### Layout

The modal uses a two-panel layout: a task list on the left and an output pane on the right. Running tasks refresh their
output every second.

### Task Status Icons

| Icon | Color | Meaning |
| ---- | ----- | ------- |
| `●`  | Green | Running |
| `✓`  | Cyan  | Success |
| `✗`  | Red   | Error   |
| `?`  | Dim   | Unknown |

### Keybindings

| Key            | Action                          |
| -------------- | ------------------------------- |
| `j` / `k`      | Navigate task list              |
| `K`            | Kill selected running task      |
| `d`            | Dismiss selected completed task |
| `D`            | Dismiss all completed tasks     |
| `e`            | Open task output in `$EDITOR`   |
| `y`            | Copy task output to clipboard   |
| `Ctrl+D` / `U` | Scroll output pane down / up    |
| `q` / `Esc`    | Close modal                     |

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

### XPrompt Picker (`#@`)

Typing `#@` (the `#` character followed by `@`) opens the XPrompt snippet picker modal. This lists all available
xprompts (including project-local xprompts from `sase.yml` files) and inserts the selected xprompt name at the cursor
position after the `#`. This is separate from the `ace.snippets` mechanism — it provides quick access to xprompt
references rather than expanding static templates.

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
