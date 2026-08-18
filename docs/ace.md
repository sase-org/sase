# ACE TUI User Guide

## Overview

ACE (Agentic Change Explorer) is the primary TUI for the SASE toolkit. It provides an
interactive interface for navigating, managing, and operating on Patches, agents, and
the Axe daemon.

## Launching

```bash
sase ace [QUERY] [options]
```

If no query is provided, ACE loads the last used query, then the first saved query, then
falls back to `!!!` for error suffixes.

### CLI Options

| Option                     | Description                                                                                            |
| -------------------------- | ------------------------------------------------------------------------------------------------------ |
| `QUERY` (positional)       | Query string for filtering Patches                                                                     |
| `-m`, `--model-tier`       | Override model tier for all LLM providers (`large` or `small`)                                         |
| `-M`, `--model-size`       | Deprecated alias for `--model-tier` (`big` or `little`)                                                |
| `-p`, `--profile [PATH]`   | Profile the TUI session with pyinstrument; optional output path                                        |
| `-r`, `--refresh-interval` | Auto-refresh interval in seconds (default: 10, 0 to disable)                                           |
| `-x`, `--no-axe`           | Disable auto-starting the axe daemon on startup                                                        |
| `-v`, `--vcs-provider`     | Override VCS provider (`git`, `hg`, or `auto`)                                                         |
| `-R`, `--restart-axe`      | Restart the axe daemon on startup (shows RESTARTING indicator)                                         |
| `-t`, `--tab`              | Tab to focus on startup (`artifacts`, `agents`, `axe`; `changespecs` and `patches` are legacy aliases) |
| `-T`, `--tmux`             | Launch ACE in a new tmux window and print the target for external control                              |

When profiling is enabled, ACE writes text output to `PATH`. If `PATH` is omitted, it
uses the managed temp tree: `$SASE_TMPDIR/ace-profiles/ace_profile_<timestamp>.txt` when
`SASE_TMPDIR` is set, or `$SASE_HOME/tmp/ace-profiles/ace_profile_<timestamp>.txt`
otherwise (`SASE_HOME` defaults to `~/.sase`). On exit, ACE prints the shortened path
and copies it when a clipboard tool is available.

### Examples

```bash
sase ace                              # Last query, first saved query, or "!!!"
sase ace '"feature" AND "Drafted"'    # Filter by name and status
sase ace '+myproject'                 # Filter by project
sase ace -m small -r 30 '!!! OR @@@' # Small model, 30s refresh
```

When `--profile` is enabled, ACE prints a shortened profile-output path after the TUI
exits and tries to copy that shortened path to the system clipboard (`pbcopy`,
`wl-copy`, `xclip`, or `xsel` when available).

### Clipboard Transports

Every copy inside the ACE TUI runs in the background and tries both a verifiable system
transport and OSC 52 for the client terminal. Inside tmux, ACE tries
`tmux load-buffer -w -` first; otherwise the system candidates are `pbcopy`, `wl-copy`,
`xclip`, and `xsel` as appropriate for the platform and display environment. A plain
`Copied …` toast means a subprocess transport confirmed success, while
`Copied … (OSC 52)` means ACE emitted the terminal escape sequence without a verifiable
subprocess result. OSC 52 payloads above the terminal-safe size limit are skipped. If
neither transport works, ACE opens the generated text in a read-only fallback view so it
can still be selected and recovered.

## Tab System

ACE has three tabs, cycled with `Tab` and `Shift+Tab`:

| Tab           | Description                                                                                                                                                                                |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Agents**    | View running and completed agents, their files and prompts                                                                                                                                 |
| **Artifacts** | Browse Stitch, Patch, Bead, configured document providers, and File. See the [Artifacts pane contract](artifacts_pane_contract.md) and [visual grammar](artifacts_pane_visual_grammar.md). |
| **Axe**       | Monitor the Axe daemon and background commands                                                                                                                                             |

Agents is the first tab and the startup default. Each tab has contextual help: press `?`
to open the Help modal on its **Keymaps** view, then `]` to switch to the tab's
**Guide** view. While Help is open, the configured tab-switch keys still switch ACE tabs
and refresh both views in place. By default those keys are `Tab` and `Shift+Tab`; if you
remap them, the modal follows the configured keys.

Press `/` in the Keymaps view to open a live filter bar. Typing splits the query into
whitespace-separated tokens that must **all** match — each token is checked against a
row's section name, key display, or description, so a token that matches a section name
(e.g. `beads`) pulls in every keymap in that section. Matched text is highlighted and a
counter shows how many keymaps and sections matched. The filter follows you across ACE
tab switches while Help stays open, but resets whenever the panel is closed and
reopened. `Esc` clears an active filter before it closes the Help modal.

On first use, empty tabs render onboarding states instead of blank panels: the Patches
view shows a getting-started card when no Patches or saved queries exist yet, and the
Agents tab walks through launching a first agent — the project/Patch launch hint appears
only when a launchable target exists — and can recommend installing plugins from the
Admin Center when no third-party plugins are installed. Onboarding cards carry "learn
more" links into the published docs. An empty Beads pane points agents to
`/sase_new_task`, calls out sized draft tasks, and explains how ready tasks enter
TaskTriage.

Within Artifacts, number keys follow the visible left-to-right order of the strip:
Stitch, Patch, and Bead are always **1**, **2**, **3**; configured document-provider
tabs such as Plan and Research take the next digits; and File, which always renders
last, always carries the highest digit — **4** with no provider tabs configured, **6**
with two. Digits stop at `9`, and File keeps its digit even then. Use `[` / `]` to cycle
through the complete runtime strip. As horizontal space tightens, the strip chooses the
widest tier that fits from a full → compact → micro ladder and re-renders only when the
tier changes. Compact removes outer padding; micro also tightens the separators and
hides inactive labels, leaving their digits and icons visible. If even micro is wider
than the available space, micro remains selected. Every Artifacts tab has an icon,
including provider tabs whose missing or invalid `ref.icon` falls back to the generic
`◆`, so the micro tier never leaves an inactive tab unidentified. These keys act only
while Artifacts is visible. Press `p` in Stitch, Bead, provider document panes, or File
to change the shared project scope, or use the command palette to jump directly to a
top-level view. Patches remains query-scoped and retains the existing Patch workflow.

### Split Modes in Artifacts Panes

Every Artifacts pane starts with an even left-list/right-detail split. Press `}` to grow
the list panel or `{` to shrink it. The mode is shared by every Artifacts sub-tab and
cycles with wraparound in either direction:

| Mode     | Left panel | Right panel |
| -------- | ---------- | ----------- |
| `narrow` | 30%        | 70%         |
| `even`   | 50%        | 50%         |
| `wide`   | 70%        | 30%         |

The `{████}` badge at the right of the sub-tab strip shows the current mode in the
active pane's accent color: one filled cell is narrow, two is even, and three is wide.
Clicking the badge cycles forward, like `}`.

The Patch pane remains content-sized instead of reserving empty list space. Its mode
sets the maximum list width for the available terminal width, while the existing 43-cell
readability floor and 80-cell upper bound still apply.

### Navigation in Stitches, Beads, Provider Documents, and Files

The non-Patches panes share fast navigation over their selectable left-panel entries.
Stitches and Files skip day headings; Beads and provider document panes skip section and
empty-state rows. Movement clamps at the first or last entry and silently does nothing
when a list is empty.

| Key                       | Action                                                                                  |
| ------------------------- | --------------------------------------------------------------------------------------- |
| `g` / `G`                 | Select the first / last commit, issue, bead, document, or file                          |
| `Enter`                   | Open the selected commit, document, bead, or file in its full-screen reader             |
| `Ctrl+F` / `Ctrl+B`       | Move down / up 10 selectable entries                                                    |
| `Ctrl+D` / `Ctrl+U`       | Scroll the active right-hand detail pane down / up (half page)                          |
| `'`                       | Show adaptive entry hints; press `'` again for the first entry or the last jump origin  |
| `Ctrl+O` / `Ctrl+Shift+O` | Walk backward / forward through the pane's jump stack; back falls through to first hint |

Hint keys select an entry without activating it. Jump-back history is kept separately
for each non-Patches pane, and stale origins disappear automatically after filtering,
changing project scope, refreshing data, or collapsing an expanded bead tree. Escape or
an invalid hint exits jump mode. These actions use the configured keymap values; the
keys above are the defaults.

When the selected entry has declared relationships, a relation panel appears at the
bottom of the list column, starting collapsed into a one-line rail that names its own
expand key (`.` by default) so it is never hidden knowledge. Press `.`
(`toggle_relation_panel`) or click the rail to expand it; the expanded panel's border
carries the reverse affordance (`{key} collapse`, bottom-right) so it can be collapsed
the same way. Its section names come from the pane contract, so examples include parents
and children, document lifecycle stages, dependencies, linked beads or plans, and
file-version families. Navigation is two keystrokes: first a relation mode, then the key
printed in square brackets beside the target row. The modes are `<` for ancestors, `>`
for descendants, and `~` for family or siblings, and the footer lists only the ones the
current entry actually has; these keys stay live even while the panel is collapsed. A
section header ending in `(N hidden)` means the query is filtering out that many
targets, a row ending in `(missing)` points at an entry that no longer exists, and a row
ending in `→ <pane>` crosses to another Artifacts pane.

On Patches, choosing a hidden same-pane target rewrites the query to reveal it rather
than failing. Patches saves the query and selection you started from first and pushes
the old query onto the same history stack `^` walks, so `^` returns to the exact view
you came from. Other panes do not rewrite their query: choosing a target they are
currently filtering out warns that it is not in the current results and leaves the
selection alone.

Shared entry-jump surfaces allocate hints from the zero-based alphabet `0`–`9`, `a`–`z`,
`A`–`Z`. A session with at most 62 targets uses one character (`0` through `Z`). A
larger session uses two characters for every target, beginning `00`, `01`, …, `0Z`, `10`
and ending at the fixed `ZZ` capacity. The first character of a two-character hint keeps
jump mode open; the second completes the jump. Hints remain case-sensitive.

Outside the Artifacts panes above, a single shared implementation backs `'` everywhere
it appears: each Admin Center working section (see
[Global Keybindings](#global-keybindings)) and four modals — the notification options
modal, the model picker, the saved-group revival modal, and
[Launch Control](#launch-control). In all of them, pressing `'` a second time while the
hints are painted is the **jump back** key: it pops the most recent origin off a bounded
stack of the last ten pre-jump positions, rather than toggling between one saved target
and the current row. With an empty stack it falls through to the first hinted row
instead. The footer shows which of the two the next `'` will do — `JUMP ' back` while
the stack holds an origin, `JUMP ' first` when it does not. Changes that shift which row
is where — refiltering the model picker, paging or deleting in the revival modal,
drilling into or out of a Launch Control bucket, or an async provider-snapshot reload —
discard the stored origins instead of leaving them pointing at whatever row inherited
the index.

### Copy Mode in Stitches, Beads, Provider Documents, and Files

Press `%` on any non-Patches Artifacts pane to open the context-aware **Copy as…**
palette for the visible entry. Rows are grouped by representation, show their configured
accelerator and a warm preview, and can be selected with the mouse, arrow keys or
`j`/`k` plus `Enter`, or the accelerator directly. `q`/`Esc` cancels. If an accelerator
is configured as `j`, `k`, or `q`, the configured copy target wins over navigation or
cancellation.

| Pane               | Keys                                                                                                                                                              |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stitches           | `%@` artifact ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` full SHA · `%m` message · `%r` `repo@sha` · `%p` plan               |
| Beads              | `%@` artifact ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` id · `%t` title · `%b` description and notes · `%d` design          |
| Provider documents | `%@` artifact ref · `%d` bead design ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` bead id · `%p` path · `%t` title · `%b` body |
| Files              | `%%` contents · `%@` artifact ref · `%L` Markdown link · `%p` stored path · `%o` source path · `%l` label · `%j` metadata JSON · `%!` ref in agent prompt         |

`%s` captures the current `sase ace` tmux pane on every view.

The palette and copied value follow the active pane. After selection or cancellation,
the footer returns to the active pane's normal bindings. An unknown printable key warns
but leaves the palette open so another choice can be made.

When entries are marked, `%@` copies newline-separated prompt references, `%l` copies a
Markdown bullet list, `%J` copies one JSON array, and `%!` seeds one prompt with the
marked set. Entries that cannot produce the selected representation are skipped; the
completion toast reports both the copied and skipped counts. The palette title reports
the visible marked count and applicable rows use plural labels such as **commit SHAs**.

The same `%` prefix opens the palette above copy-forwarding readers and modals,
including the preview panel. Dismissing the palette returns to the underlying modal.
Snapshot choices dismiss the palette before capture, so the palette itself is not
included in the copied pane.

### Marks in Stitches, Beads, Provider Documents, and Files

Press `m` to mark or unmark the selected entry and `u` to clear the active pane's marks.
Each non-Patches pane keeps an independent stable-target mark set, so marks survive
refreshes and switching panes without affecting marked PRs. Changing the shared
Artifacts project scope clears the non-Patches marks.

When marks exist, the pane's `%` copy targets operate on marked entries in visible order
instead of only the selected entry. Identity, location, and data representations use
paste-ready forms; content dumps retain labeled fenced sections. Content-shaped targets
are capped at 512,000 bytes per item and per assembled payload, with an explicit
truncation banner and toast. The footer shows the active pane's mark count only while
that count is nonzero.

### Filtering Patches, Stitches, Beads, and Plans

Patches keeps its canonical query visible in a persistent, read-only filter row at the
top of the detail column, so the active query is legible without opening anything. Press
`/` (or the local `f`) to start editing it. Typing re-filters the already-loaded Patch
snapshot on every keystroke, so previews are instant and never re-query the store.
`Enter` commits: it reloads Patches from the committed query, pushes the query you
replaced onto the `^` history stack, and returns focus to the list. `Escape` abandons
the edit, restoring the committed query, its result, and the row you had selected. A
parse error stays inline in the row and leaves the visible Patch list on the last valid
query. `Tab` accepts completions for keys, values, shorthand sigils, state predicates,
status macros, and — while the row is empty — saved-slot commands. Saved-query commands
such as `#3 status:Draft`, `# status:Ready`, and `#3` save, allocate, or delete a slot
without changing the active query or closing the editor.

Stitches keeps its effective canonical query visible above the timeline. Press `/` or
the local `f` shortcut to focus that row for live editing; `Enter` commits the query and
returns focus to the timeline, while `Escape` restores the last committed query and
result. The row remains visible in either case. Beads and Plans use the same live editor
interaction, but show the input row only during an edit session. The Beads info line
always shows its committed query, including the visible `-status:closed` startup
default. Tokens from different facets combine with AND semantics; comma-separated and
repeated values within one facet combine with OR semantics. Free-text terms must all
match. Press `Tab` to accept the highlighted key or value completion.

Stitches accepts singular `project:` plus `repo:`, `author:`, `origin:`, `since:`,
`until:`, `sidecar:`, `merges:`, and `limit:` and free text matched against the commit
subject. `origin:` accepts `stitch`, `auto`, and `manual`, and is repeatable,
comma-listable, and negatable like `repo:` and `author:`. `merges:hide/show/only`
controls merge-commit visibility exactly like `sase stitch list`'s `--merges` flag (see
[VCS Provider Reference](vcs.md#sase-stitch-list)). `project:` is not repeatable,
comma-listable, or negatable because it selects the repository constellation before
commits are collected. With no `project:` token, collection truly spans all projects. It
accepts a configured project name, ProjectSpec directory key, or alias; committed known
values are rewritten to the configured project name. The project picker replaces that
token while preserving every other committed token; its **All projects** choice removes
it. The compatibility `a` action removes an active project token and restores the last
automatic or picked project on the next press.

The bundled initial query is `sidecar:false merges:hide since:24h`; it is configurable
with `ace.artifacts.stitches.default_query` (`ace.artifacts.commits.default_query` is a
deprecated alias), and changes take effect the next time ACE starts. Before the pane is
mounted, an explicit project in the ACE query overrides a configured `project:`, a
configured project overrides current-directory inference, and an inferred registered
current project is added only when neither explicit source supplied one. An empty parsed
query includes sidecar repositories; at ACE startup it can also gain that inferred
visible project token. Canonical rendering always includes either `sidecar:true` or
`sidecar:false`, and the configured `d` action rewrites that same visible token.
Selecting a sidecar with `repo:` therefore requires `sidecar:true`. For example,
`project:sase repo:sase author:Ada origin:stitch since:7d sidecar:false fix` shows
recent tracked SASE commits by Ada whose subjects contain `fix`,
`repo:plans sidecar:true` shows that sidecar across all projects, and `limit:40` caps a
deliberately broad search. Day-granular `until:` values (`today`, `yesterday`, and
`YYYY-MM-DD`) include the full named day; relative and minute-precise values remain
instant bounds. Relative windows such as `since:24h` re-anchor whenever the pane
refreshes.

The repository legend starts with `[P/N]`, where `P` is the selected commit's one-based
position and `N` is the number of matched entries currently displayed. Day headings do
not count as entries. A `+` on the denominator, as in `[1/40+]`, means the displayed
total is only a lower bound. The persistent filter row reports the corresponding
coverage state (`exact`, `preview`, or `capped`) without repeating the match count. Each
timeline row also has a fixed origin glyph immediately before the subject: `✦ stitch`
for commits created through `sase stitch create`, `↻ auto` for other SASE-created
commits, and `✎ manual` when the commit has no SASE provenance footer. The legend lists
only the origins present in the displayed commits, so a result containing only tracked
work shows only `✦ stitch`.

Stitches queries are uncapped unless they include an explicit positive `limit:N`, so the
bundled 24-hour query shows all matching commits. When an explicit limit may have
omitted rows, the legend uses a lower-bound total such as `[1/40+]`, the filter row says
`capped`, and `limit:40` remains visible in the persistent filter row and pane header.
`limit:all` remains an accepted synonym for the unlimited state, but canonical query
text omits it. Provider or aggregate truncation metadata can still mark a count as
capped without inventing an active query limit.

Plans accepts `kind:`, `status:`, `tier:`, `project:`, `since:`, and `until:` plus free
text matched across plan-document metadata and content. `kind:` accepts `proposal`,
`active`, `archive`, and the document-sidecar roles present in the current scope, such
as `plans`, `research`, or `designs`. `kind:archive` matches committed documents that
are not linked from a live bead, while `kind:designs` narrows documents to that sidecar.

Beads accepts repeatable `type:`, `task_type:`, `tier:`, `status:`, `size:`, `project:`,
`assignee:`, `owner:`, `model:`, `has:`, `bug:`, `label:`, `since:`, and `until:` terms.
`task_type:` accepts catalog slugs plus `untyped` for legacy beads. Status values
include the five stored states plus the derived `blocked`, `launched`, and `triage`
states. `has:` accepts `plan`, `bug`, `deps`, `notes`, and `triage`. `bug:` matches
issue state, reference, relation, or project, with completion for `none`, `open`,
`closed`, `stale`, `drift`, `mirrored`, and `referenced`; `label:` matches cached
provider labels. Free text also searches cached external issue title, body, URL, and
labels alongside the bead id, title, description, notes, design, references, and
ownership metadata.

A leading unquoted `-` excludes a match. Stitches can exclude repositories, authors, and
subject text; Beads and Plans can exclude their filter facets and free text. Exclusion
wins when positive and negative constraints overlap: `repo:sase,plans -repo:plans`,
`author:Ada -author:bot`, and `status:open -status:blocked` are all valid. A comma list
negates the whole token, so `-repo:plans,research` excludes either repository. Date
bounds and `limit:` cannot be negated. `sidecar:` is singular and accepts only `true` or
`false`; canonical queries always render its explicit value. Quote the whole token to
search for a literal leading minus (`"-repo:plans"`); quote only the excluded value to
keep negation active (`-"generated rollout"`). Matching remains case-insensitive, and
repository/project aliases work for both inclusion and exclusion.

### Bead Pane

The top-level Beads view (`3`) is the work-item home for standalone tasks, epic plan
beads, and their phase beads. Every bead appears once: tasks occupy their own section,
while epics expand with `l` and collapse with `h` to reveal phases. Rows show stored
status and ownership metadata, `✦` when a task has a pending TaskTriage decision, and
`▤` when the bead links a plan document. Linked issue chips use `○` for open, `●` for
closed, and `?` for a stale issue absent from the complete cached listing; stale or
drifted links are highlighted, and `+N` summarizes additional links. Closed beads are
loaded but hidden by the visible `-status:closed` default; press `f` to edit or clear
that query. Section headings report matched and total counts while a filter is active.

The pane supports the full bead workflow:

| Key       | Action                                                                                |
| --------- | ------------------------------------------------------------------------------------- |
| `j` / `k` | Select the next / previous bead                                                       |
| `Enter`   | Open the complete bead detail in the preview reader                                   |
| `f`       | Edit the bead filter query                                                            |
| `l` / `h` | Expand / collapse the selected epic                                                   |
| `s`       | Cycle the selected bead's status using the type-aware sequence below                  |
| `z`       | Snooze the selected task bead (or edit/cancel an existing snooze)                     |
| `e`       | Edit the bead's valid fields                                                          |
| `N`       | Append a note without replacing prior notes                                           |
| `n`       | Create a task bead in the selected project                                            |
| `c`       | Close with a required reason and optional note, or reopen a closed bead               |
| `w`       | Launch an epic or launchable task; phase work launches with its epic                  |
| `E`       | Open a linked external issue                                                          |
| `y`       | Copy the bead's `@bead:` reference                                                    |
| `% u`     | Copy a linked issue reference (copy mode)                                             |
| `b`       | Enter issue-action prefix mode                                                        |
| `L`       | Jump to the linked plan document; the same key in Plans jumps back to the owning bead |
| `R`       | Refresh beads                                                                         |

When a bead has several issue links, `E`, `% u`, and the `b`-mode `v`, `e`, `s`, and `u`
actions first open a selector. In `b` prefix mode, press `v` to view the cached body,
`e` to edit supported title/body/label fields, `s` to close or reopen after
confirmation, `u` to copy the provider URL, `a` to attach an existing numeric issue, or
`c` to create and attach a new issue. Attach and create operate on the bead itself and
therefore do not select an existing link. Availability follows the active VCS provider's
capabilities. The detail reader shows each link's relation, state, labels, assignees,
author, update/comment metadata, and cached body. The info line reports linked,
remote-only, stale, and drifted counts, plus provider unavailability and per-project
errors, so tracker health remains visible without a separate Bugs pane.

Closing offers `done`, `canceled`, and `superseded` resolutions. A bead with unfinished
descendants is rejected unless the close modal's force option is enabled with a
non-`done` resolution; the modal previews those descendants first. Closing or launching
a task with a pending TaskTriage request settles that gate so the notification does not
outlive the decision. Mutation work runs as tracked procs and refreshes the pane after
completion.

The default `s` status action is type-aware:

```
task: open → ready → in_progress → closed → open
      claimed → ready
      snoozed → ready
other beads: open → in_progress → closed → open
```

The `s` action changes persisted status only; moving a task from `ready` to
`in_progress` does not itself launch a worker. Use `w`, the matching TaskTriage
notification, or `sase bead work <task-id>` to launch the work. The editor shows only
fields valid for the selected bead type, while dependencies remain read-only in the
detail panel. `s` only cycles a task _out_ of `snoozed` (back to `ready`, canceling the
snooze); entering `snoozed` needs `z`, since snoozing takes arguments (a wake time, and
optionally a `+1` target and a reason) that a blind status cycle cannot supply.

Press `z` on a task bead to open the snooze picker: presets for `4 hours`,
`Tomorrow morning`, `3 days`, and `1 week`, plus a custom duration field accepting the
same `"<duration> [+<N>]"` vocabulary as `sase bead snooze` (see
[Snoozing a Task Bead](beads.md#snoozing-a-task-bead)) and an optional reason field.
Pressing `z` on an already-snoozed task opens the same modal in re-snooze mode, showing
the current wake time and offering a cancel-snooze choice. A snoozed row in the list
shows the `snoozed` status glyph and a dim relative wake time.

When that worker appears on the Agents tab, its bead badge points directly to the task,
and its **SASE CONTEXT / BEAD** lane shows the task title and description, plus size
when one is stored, without trying to resolve an epic plan.

### Document Provider Panes

Artifacts includes one document pane per configured artifact-reference provider. The
fixed tabs are Stitch, Patch, Bead, and File; provider-backed document tabs such as Plan
and Research appear between Bead and File when an enabled project configures the
matching sidecar `ref:` policy. Persisted selections use stable ids such as `ref:plan`
and `ref:research`, so a missing provider falls back to Stitch instead of crashing
startup. Each pane renders an icon before its label — the four fixed marks (`◉` Stitch,
`⎇` Patch, `◈` Bead, `▤` File) are built in, and a provider pane's mark comes from its
sidecar `ref.icon`. The active tab's icon takes that pane's accent color; inactive icons
render dim. A missing `ref.icon`, one that fails validation, or one wider than two
terminal cells uses the generic `◆` provider icon instead.

Plans is the built-in provider-backed document pane for the plans sidecar. It keeps the
existing plan actions: `A` and `X` approve or reject pending proposals, and `L` appears
only when the selected document has an owning bead. That key jumps to Beads; pressing
`L` on the linked bead returns to the document. If a destination filter hides the
counterpart, ACE clears that filter before landing on the row. Other document providers
reuse the same list, filter, detail, preview, copy, and refresh behavior from their
declared properties and detail fields.

### Commit Detail and Linked Plans

Press `Enter` on a Stitches entry to open its full message and syntax-highlighted diff.
The modal uses `j` / `k` for line scrolling, `Ctrl+D` / `Ctrl+U` for half pages, `g` /
`G` for the ends, `y` to copy the full SHA, and `Esc` or `q` to close. When the current
result contains multiple commits, `Ctrl+N` / `Ctrl+P` move through them with wraparound.

The modal's header block carries a compact commit-time chip, right-aligned on the line
that also shows the diff path — an absolute stamp plus a relative age, such as
`Today 07:05:54 · 2h ago`. Today and yesterday show seconds; older commits show `HH:MM`
after their day label. Times are the commit's author time in the configured local
timezone. The chip is free on the Artifacts timeline, where the commit time is already
loaded; on the Agents tab, a commit whose stored metadata records no time has it looked
up from the VCS alongside the diff, so the chip appears once that load lands. Commits
made by SASE persist their author time in `commit_result.json` / `commit_results.json`,
so later views need no lookup at all. A commit whose time cannot be resolved simply
shows no chip.

Press `p` in the commit modal to load the last structured `SASE_PLAN` footer tag and
render its referenced local UTF-8 file as Markdown; press `p` again to return to the
cached diff. This is a local-only lookup: an absolute path is expanded and checked
directly, while a relative path is checked first in the commit repository, then in each
known project workspace and its plans store. ACE does not clone or materialize a missing
store. A missing tag, invalid reference, unavailable path, non-file path, or unreadable
file produces a specific toast and leaves the commit visible. Moving to another commit
always returns the modal to commit mode.

### Preview Reader

Press `Enter` on a Beads entry, provider document, or Files row to open its full
contents in the preview reader. Prompt-normal-mode `K` opens the same reader for a
previewable xprompt, skill, or file. When ACE knows a canonical artifact reference, the
title shows that logical reference beside the resolved local path.

| Key                 | Action                                                     |
| ------------------- | ---------------------------------------------------------- |
| `j` / `k`           | Scroll down / up one line                                  |
| `Ctrl+D` / `Ctrl+U` | Scroll down / up half a page                               |
| `g` / `G`           | Jump to the top / bottom                                   |
| `y`                 | Copy the complete preview contents                         |
| `Y`                 | Copy the local source path, when available                 |
| `%`                 | Open the active Artifacts sub-tab's **Copy as…** palette   |
| `R`                 | Toggle Markdown previews between rendered and source views |
| `p`                 | Toggle the full xprompt properties view                    |
| `/`                 | Open source search (smartcase substring matching)          |
| `n` / `N`           | Jump to the next / previous match with wraparound          |
| `o`                 | Open the source path in `$EDITOR` (falling back to `nvim`) |
| `Z`                 | Hand the source path to the rich terminal artifact viewer  |
| `Esc`               | Cancel input, clear active search, then close the reader   |
| `q`                 | Close the reader                                           |

Path-only actions are omitted from the footer when the preview has no local source path;
invoking one still produces a specific warning instead of failing. Clipboard operations
run in the background and report when no clipboard tool is available. Plans open in
rendered Markdown by default when they fit the reader's bounded render budget; xprompts,
skills, files, and oversized documents open as source.

For an xprompt or skill preview with declared properties (inputs, tags, skill/snippet/
memory flags, local xprompts, or steps), a compact band appears above the source pane
showing its description, an inputs table, and a dim chips summary of everything else it
declares. `p` opens a full, scrollable properties view — the same projection
`sase xprompt show` renders — with the band hidden while that view is active; `p` again
restores whichever mode was showing before. A preview with no declared properties (a
bare-body xprompt, a plain file, a bead, and so on) shows no band, no `p` row in the
footer, and `p` emits a warning toast instead of switching views.

Search is commit-on-enter: `/` opens a one-line input prefilled with the last committed
query, and `Enter` highlights every matching source line before jumping to the first
match at or below the current viewport. Queries containing an uppercase character are
case-sensitive; other queries are case-insensitive. Starting search from rendered
Markdown switches to source view. `Esc` in the input cancels the edit, while `Esc` after
a committed search first clears the matches and only closes the reader on the next
press.

### File Pane

Files browses the artifact-file index that backs [`sase artifact list`](cli.md). The
pane is one of the four fixed Artifacts views: Stitch, Patch, Bead, and File. Configured
document-provider panes appear between Bead and File in the runtime tab strip. Rows are
grouped by logical file identity, so repeated captures of `@file:~/bob/gtd.md` or
repeated `sase artifact create` rows for the same logical artifact appear as one
selectable row with versions.

Each row shows a view-mode glyph, the project, the producing agents, an origin badge,
the logical label, the latest selected version's timestamp, and the indexed size.

| Glyph | View mode  | Opens with                                                 |
| ----- | ---------- | ---------------------------------------------------------- |
| `▨`   | `image`    | The rich terminal viewer (`kitten icat`)                   |
| `▶`   | `video`    | The rich terminal viewer (`mpv`)                           |
| `▤`   | `pdf`      | The rich terminal viewer (PDF pages rendered to PNG)       |
| `▤`   | `markdown` | The [preview reader](#preview-reader), rendered by default |
| `•`   | `text`     | The [preview reader](#preview-reader), as source           |

The glyph comes from the same classifier that chooses the viewer, so it can never
disagree with what `Enter` actually opens. Origin badges distinguish files cited in a
prompt (`ref`), files registered explicitly with `sase artifact create` (`created`), and
automatic captures (`capture`).

The info line above the list summarizes the loaded snapshot as kind chips and origin
chips, where `documents` totals PDFs and Markdown. The index loads off the message pump
in two pages: a first bounded page paints immediately, then the full index replaces it,
and the status line reports both the loaded row count and any in-flight extension.

Selecting a row loads its detail panel off-thread. The detail header shows
`version i/n`, the durable `file:<id>` or logical `@file` reference, digest, capture
time, project, agent, origin, MIME type, and size. Markdown and text rows include a
bounded preview. `(`/`)` cycle the selected row's versions without moving to another
logical file; repeated captures with the same SHA-256 share one version and accumulate
provenance.

| Key       | Action                                                                          |
| --------- | ------------------------------------------------------------------------------- |
| `j` / `k` | Select the next / previous file, skipping day headings                          |
| `Enter`   | View the file: preview reader for Markdown and text, rich viewer for media      |
| `Z`       | Hand the marked visible rows — or the selection — to the rich terminal viewer   |
| `E`       | Open text in `$EDITOR` (falling back to `nvim`); open media with `xdg-open`     |
| `a`       | Jump to the producing agent on the Agents tab, reviving it first when dismissed |
| `f`       | Edit the pane's filter query                                                    |
| `z`       | Cycle the kind filter through All and the stored kinds present in the snapshot  |
| `(` / `)` | Select previous / next version for the current logical file                     |
| `y`       | Copy the row's `@file:<id>` reference                                           |
| `Y`       | Copy the row's anchored stored path                                             |
| `m` / `u` | Mark / unmark the selected file · clear this pane's marks                       |
| `%`       | Open the Files **Copy as…** palette                                             |
| `R`       | Refresh the index                                                               |
| `p`       | Change the shared Artifacts project scope                                       |

These are the default keymap values; the Files-pane actions retain their `files_*`
configuration names and are remappable under
[`ace.keymaps.app`](configuration.md#acekeymaps) as `files_next`, `files_prev`,
`files_view_selected`, `files_open_viewer`, `files_open_external`, `files_open_agent`,
`files_filters`, `files_cycle_kind`, and `files_copy_path`. `y`/`R` are the shared
`artifacts_copy_reference`/`refresh` actions every Artifacts pane binds. Version cycling
uses the old nested-files sub-tab keys. The pane also shares the navigation and jump
keys described in
[Navigation in Stitches, Beads, Provider Documents, and Files](#navigation-in-stitches-beads-provider-documents-and-files).

`Y` copies the anchored stored path, except that PDF rows deliberately yield the live
Markdown source they were rendered from when the index recorded one. Relative index
paths are anchored to the producing workspace, so a copied path is always usable outside
the workspace that created it, and the completion toast says when the copied path no
longer exists. The palette previews that same preferred path, so what a PDF row shows is
what `%p` copies. `%` adds the rest of the Files-pane copy targets: contents, Markdown
link, source path, label, and metadata JSON, each of which also operates on the marked
set.

`a` resolves the producing agent from already-loaded live and dismissed agents by
artifact directory, then by raw name suffix, then by recorded agent name, always within
the row's own project. A file whose source workspace was recycled still opens and still
copies — only its `Source` path reports `missing`.

#### Filtering Files

`f` opens the same live filter row provider document panes use, visible only during an
edit session, and `/` opens it too. Filtering is purely in-memory over the loaded
snapshot, so a query narrows thousands of rows without a re-query. Files accepts
`kind:`, `project:`, `agent:`, `workflow:`, `origin:`, `since:`, and `until:`, plus free
text matched against the label, logical path, stored path, source path, digest, and
artifact id. Tokens from different facets combine with AND semantics, while
comma-separated or repeated values within `kind:`, `project:`, `agent:`, `workflow:`,
and `origin:` combine with OR semantics. `kind:` accepts the stored kinds `chat`,
`plan`, `image`, `markdown`, `pdf`, and `file`; `origin:` accepts `ref`, `created`, and
`capture`; `since:` and `until:` accept `YYYY-MM-DD`, `YYYY-MM`, `YYYYMM`, or a relative
`Nd` / `Nw` / `Nm` offset and may each appear once.

Files-pane filters do not support negation; a leading `-` is rejected with an explicit
error rather than excluding a match. `s` and the `kind:` token drive the same filter
state: cycling with `s` closes an open edit session and sets `kind:` to the next stored
kind actually present in the snapshot, wrapping back to All. A query listing several
kinds is treated like All, so the next press selects the first present kind. When a
filter hides every row, the pane says so and names the key that reopens the query row.

### Epic phase sizes across plan surfaces

ACE uses the literal scope labels `xsmall`, `small`, `medium`, `large`, and `xlarge`,
with mint, sky, gold, rose, and violet chips whose text remains the primary signal.
Valid older plans and phase beads with an omitted size use the stable `small` fallback,
while an invalid authored value never produces a confident chip or count. The Plans pane
also uses that shared display fallback for a legacy standalone task with no stored size;
launch routing uses the same `@small` fallback.

| Surface                                                                  | Size contract                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Agents author and lander                                                 | Shows every normalized authored size in roadmap order.                                                                                                                                                                                                                                                 |
| Agents phase worker                                                      | Shows only that worker's normalized authored size, preserving phase isolation.                                                                                                                                                                                                                         |
| Artifacts / Beads epic, phase, and task beads                            | Shows current persisted bead sizes in rows and details; the epic detail summarizes direct children in `xsmall`, `small`, `medium`, `large`, `xlarge` order. Standalone tasks appear in their own section. A legacy task with no stored size displays and launches through the shared `small` fallback. |
| Artifacts proposals, linked plans, and archives                          | Retains the authored `phases` property exactly once instead of adding a competing roadmap.                                                                                                                                                                                                             |
| Telegram epic review                                                     | Adds a validated textual size breakdown while retaining the detailed Properties card and source/PDF attachment.                                                                                                                                                                                        |
| Epic clan summary, `sase bead show`, and epic work preview               | Continues using persisted bead sizes, which these execution surfaces already exposed.                                                                                                                                                                                                                  |
| Raw approval, validation/schema, source/PDF, and mobile attachment paths | Remains a lossless generic/source view; authored phase metadata is preserved without a second summary.                                                                                                                                                                                                 |

## Keybindings: Artifacts / Patches

### Navigation

| Key                       | Action                                                                                       |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| `j` / `k`                 | Move to next / previous visible row (banner at fold `< L2`, PR at the leaf level)            |
| `<` / `>` / `~`           | Navigate to ancestor / child / sibling PR                                                    |
| `'`                       | Jump by adaptive hint (current tab); hints land on collapsed banners too                     |
| `Ctrl+O` / `Ctrl+Shift+O` | Walk backward / forward through the current-tab jump stack; back falls through to first hint |
| `` ` ``                   | Jump to entry across all tabs (see [Jump All Modal](#jump-all-modal))                        |
| `o` / `O`                 | Cycle PR grouping mode forward / reverse (`BY_PROJECT` ↔ `BY_DATE` ↔ `BY_STATUS`)            |
| `g` / `G`                 | Scroll detail panel to top / bottom                                                          |
| `Ctrl+D` / `Ctrl+U`       | Scroll detail panel down / up (half page)                                                    |
| `{` / `}`                 | Narrow / widen the shared Artifacts list panel (with wraparound)                             |

> **Note:** `o`/`O` cycle the L0 grouping bucket forward / reverse on the Agents tab and
> on every Artifacts pane that has a grouping mode (each surface keeps its own
> in-session mode). Beads and Plans have no grouping-mode data, so the keys are a silent
> no-op there; the same is true on the AXE tab. The Artifacts open-externally verb moved
> to `E`; bang-mode `!o` still marks PR origin. See
> [PR Grouping and Folding](#pr-grouping-and-folding) and the Agents-tab
> [Grouping Modes](#grouping-modes) below.

### PR Actions

| Key             | Action                                                                                       |
| --------------- | -------------------------------------------------------------------------------------------- |
| `A`             | Accept proposal (`!` = spec only, `@` = mark ready to mail)                                  |
| `b`             | Rebase PR onto parent                                                                        |
| `C` / `c1`-`c9` | Checkout PR (primary / workspace 1-9)                                                        |
| `d`             | Show diff (Patches sub-tab only; `d` is the Axe description toggle elsewhere)                |
| `e`             | Edit spec file                                                                               |
| `f`             | Edit hooks (re-run / delete via hint input)                                                  |
| `M`             | Mail PR                                                                                      |
| `m`             | Mark / unmark current PR (auto-advances to next)                                             |
| `n`             | Rename PR (non-Sub/Rev PRs only)                                                             |
| `!o`            | Mark PR origin (`sase`/`external`/`unknown`)                                                 |
| `!R`            | Rewind to previous commit (`!` suffix skips VCS operations)                                  |
| `R`             | Refresh (the shared `artifacts_copy_reference`/`refresh` actions every Artifacts pane binds) |
| `y`             | Copy the PR's `@patch:` reference                                                            |
| `s`             | Change status (opens status modal)                                                           |
| `S`             | Bulk status change for all marked PRs                                                        |
| `T`             | Checkout + tmux (opens workspace input modal for number)                                     |
| `u`             | Clear all marks                                                                              |
| `v`             | View files (hint mode)                                                                       |
| `w`             | Reword PR description                                                                        |
| `W`             | Add tag to PR description                                                                    |
| `x`             | Show/hide submitted PRs                                                                      |
| `X`             | Show/hide reverted PRs                                                                       |
| `Y`             | Sync workspace                                                                               |

### PR Grouping and Folding

The Patches sub-tab is always grouped — the renderer walks one of `BY_PROJECT`,
`BY_DATE`, or `BY_STATUS` and emits a banner row above each bucket. `BY_PROJECT` is the
startup default; `o` cycles `BY_PROJECT → BY_DATE → BY_STATUS` for the current session.

| Mode         | L0 buckets                                                                   | Notes                                                                                                                                                                                                                                                                                                       |
| ------------ | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BY_PROJECT` | Project name                                                                 | Adds an L1 sibling-root sub-banner shared by `foobar_1` / `foobar_2` style suffixed siblings. Singletons suppress their L1 banner.                                                                                                                                                                          |
| `BY_DATE`    | `Today` / `Yesterday` / `This Week` / `Earlier`                              | Bucket from the latest TIMESTAMPS entry. Today/Yesterday add 4-hour L1 windows; hourly L2 headings appear only inside 4-hour windows with 2+ PRs. This Week adds day headings; Earlier adds week headings plus `(no timestamp)`.                                                                            |
| `BY_STATUS`  | `Mailed` / `Ready` / `WIP` / `Draft` / `Submitted` / `Reverted` / `Archived` | Bucket from the literal `status` field; actionable buckets first (`Mailed` = awaiting response, `Ready` = next to mail), terminal states last. Adds an L1 sibling-root sub-banner shared by `foobar_1` / `foobar_2` style suffixed siblings inside each status bucket. Singletons suppress their L1 banner. |

In `BY_DATE` mode, PRs sort newest-first within each date bucket. `Today` and
`Yesterday` are grouped first by compact 4-hour windows (`8AM-12PM`); one-hour headings
(`09:00`) appear only when that 4-hour window contains at least two PRs. `This Week`
uses calendar-day subgroups; `Earlier` uses Monday-start week ranges. PRs without a
parseable TIMESTAMPS entry fall into `(no timestamp)` under `Earlier`.

The active grouping mode is shown in the Patches sub-tab's info-panel header as a
`[group: <label>]` badge.

| Key  | Action                                                                                                                                 |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `l`  | Expand the focused banner one level (or peel one layer of the visible tree)                                                            |
| `h`  | Collapse the focused banner; on a collapsed L1 banner, escalate to its parent. With agent focus, collapse the deepest enclosing group. |
| `zL` | Snap to fully expanded — all banners and Patch rows visible (`z` fold-mode prefix; bare `L` is siblings' `artifacts_link_jump`)        |
| `H`  | Snap to fully collapsed — collapse every visible banner                                                                                |

Collapsed banner rows are first-class navigation stops: `j`/`k` step through them just
like Patch rows, and `'` jump-hints land on them too. After a fold change that hides the
focused PR, focus snaps to the deepest collapsed ancestor banner so the cursor always
sits on a row the user can see.

### Fold Mode (`z` prefix)

| Key     | Action                                                 |
| ------- | ------------------------------------------------------ |
| `z` `c` | Cycle stitches section (expand → collapse)             |
| `z` `d` | Cycle deltas section (folded ↔ unfolded)               |
| `z` `h` | Cycle hooks section (expand → collapse)                |
| `z` `m` | Cycle mentors section (expand → collapse)              |
| `z` `t` | Cycle timestamps section (expand → collapse)           |
| `z` `C` | Toggle stitches section (collapsed ↔ fully expanded)   |
| `z` `D` | Toggle deltas section (folded ↔ unfolded)              |
| `z` `H` | Toggle hooks section (collapsed ↔ fully expanded)      |
| `z` `M` | Toggle mentors section (collapsed ↔ fully expanded)    |
| `z` `T` | Toggle timestamps section (collapsed ↔ fully expanded) |
| `z` `z` | Cycle all sections                                     |
| `z` `Z` | Toggle all sections (expand ↔ collapse)                |
| `z` `1` | Set every section to collapsed (level 1)               |
| `z` `2` | Set every section to expanded (level 2)                |
| `z` `3` | Set every section to fully expanded (level 3)          |

STITCHES, HOOKS, MENTORS, and TIMESTAMPS sections each cycle through three fold levels:

| Level              | Behavior                                                                           |
| ------------------ | ---------------------------------------------------------------------------------- |
| **Collapsed**      | Notes truncated to fit; multi-line body shown as `[+N lines]`; only latest drawers |
| **Expanded**       | Full notes; body shown in dimmed text; all CHAT/DIFF/PLAN drawers visible          |
| **Fully Expanded** | Everything visible including rejected proposals                                    |

The lowercase cycle keys (`z` `c`, `z` `h`, `z` `m`, `z` `t`) step through all three
levels in order. The uppercase toggle keys (`z` `C`, `z` `H`, `z` `M`, `z` `T`) skip the
intermediate **Expanded** state, jumping directly between **Collapsed** and **Fully
Expanded**.

When collapsed, a `[folded: CHAT + DIFF + PLAN + N proposals]` indicator appears on
STITCHES entries with hidden content. The indicator width is pre-calculated so that note
truncation accounts for it. TIMESTAMPS shows a `[folded: N]` indicator inline with the
header and displays the most recent timestamp entry when collapsed, giving a quick view
of the last lifecycle event.

The DELTAS section uses two semantic states. When **folded**, the section renders a
one-line file and line-count summary such as
`DELTAS:  +3 (+428) ~6 (+91 ~37 -14) -1 (-22) (10 files)`. When **unfolded**, the
alphabetical entry list is shown with colored glyphs (green `+`, gold `~`, red `-`) and
inline line-count tokens. Binary files display `binary`; zero-count entries display
`0 lines`. The section is omitted entirely when the Patch has no deltas.

### Workflows and Agents

| Key     | Action                                             |
| ------- | -------------------------------------------------- |
| `r`     | Run workflow on current PR                         |
| `+`     | Run a custom agent (opens project/Patch selection) |
| `Space` | Run agent from current PR                          |

If ACE cannot detect a workspace provider for the selected Patch or agent, the
quick-launch actions show an error toast instead of opening a prompt with a broken VCS
prefix.

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

The modal supports live filtering as you type in the search box and displays last-used
timestamps for each hook.

### Leader Mode (`,` prefix)

Help is not a leader command: press the app-level `?` on any tab to open the Help modal.

| Key        | Action                                                                                 |
| ---------- | -------------------------------------------------------------------------------------- |
| `,,`       | Repeat the last leader command                                                         |
| `,!`       | Run command using current PR context                                                   |
| `,A`       | Open the Agent Run Log modal for the current PR                                        |
| `,c`       | Clear COMMENTS field (kills CRS agents, deletes CRS proposals)                         |
| `,C`       | Review mentors (opens Mentor Review modal)                                             |
| `,h`       | Run agent from home prompt context; bare prompts default to `#git:home`                |
| `,m`       | Open Launch Control (view/manage model aliases; see [Launch Control](#launch-control)) |
| `,U`       | Update SASE/agent CLIs and import cached agent hoods                                   |
| `,M`       | Kill running mentors                                                                   |
| `,R`       | Show runners info                                                                      |
| `,<space>` | Run agent from current PR (skips project selection)                                    |
| `,.`       | Open prompt history modal                                                              |
| `,Ctrl+G`  | Open prompt history and edit the newest entry immediately                              |
| `,>`       | Open prompt history modal with cancelled prompts visible                               |
| `,@`       | Open the prompt stash picker without auto-restoring a lone entry                       |

The `,h` shortcut opens a home-context prompt directly. Project and PR launch pickers
use lifecycle-aware discovery: project entries, including `home` when it appears in
picker lists, must have enabled and launchable ProjectSpecs; PR choices come from
enabled ProjectSpecs. Disabled projects do not appear in normal launch pickers until
they are enabled with `sase project enable <project>`. You can also type a known-project
VCS ref explicitly; launch preparation treats that as intent to resume work and
re-enables the project before claiming a workspace.

Project launch pickers also support `Ctrl+D` for cleanup of empty project entries. This
deletes only the highlighted project's active/archive ProjectSpec files, refuses entries
whose ProjectSpec files still contain Patches, and does not delete workspace checkouts
or other SASE state. For lifecycle changes, bulk operations, ProjectSpec editing, or
deleting the whole SASE project directory, use the **Projects** tab of the SASE Admin
Center (press `#`).

The repeat binding is the leader prefix followed by the configured `repeat_last` key.
With the defaults both are comma, so the sequence is `,,`; if the leader prefix is
changed but `repeat_last` is not, the second key remains comma. Repeat re-dispatches the
last recognized leader subkey against the current tab and selection. If no leader
command has been run yet, ACE shows a toast and does nothing.

> **Note:** `,x` (kill & edit) is only available on the Agents tab — see
> [Agents Tab Leader Mode](#leader-mode-prefix_1).

### Mentor Review Modal

Press `,C` to open the Mentor Review modal, which lets you navigate mentor comments,
accept or reject suggestions, and apply accepted changes. See
[docs/mentors.md](mentors.md) for the full mentor system reference.

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

Press `%` to open the **Copy as…** palette for the selected Patch. Select a row with the
mouse, arrows or `j`/`k` and `Enter`, or complete any configured two-key accelerator
directly. `q`/`Esc` cancels; configured target keys take precedence if rebound to `j`,
`k`, or `q`.

| Key  | Action                 |
| ---- | ---------------------- |
| `%%` | Copy Patch             |
| `%!` | Copy Patch + snapshot  |
| `%b` | Copy bug number        |
| `%c` | Copy PR number         |
| `%n` | Copy PR name           |
| `%l` | Copy Markdown link     |
| `%p` | Copy project spec file |
| `%s` | Copy sase ace snapshot |

## Keybindings: Agents Tab

### Navigation

| Key                       | Action                                                                                                                                                      |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `j` / `k`                 | Move to the next / previous visible row; while a whole panel is selected, or when the focused panel has no other selectable row, cycle whole panels instead |
| `J` / `K`                 | Cycle focus across expanded tribe side panels (forward / reverse)                                                                                           |
| `'`                       | Jump to a row, collapsed grouping banner, or split-panel title by adaptive hint                                                                             |
| `Ctrl+O` / `Ctrl+Shift+O` | Walk backward / forward through the current-tab jump stack; back falls through to first hint                                                                |
| `Ctrl+J` / `Ctrl+K`       | Cycle metadata sections forward / backward through the document top                                                                                         |
| `` ` ``                   | Jump to entry across all tabs (see [Jump All Modal](#jump-all-modal))                                                                                       |
| `0`–`9`                   | Jump from a selected clan, agent node, family member, or whole-panel roster to its numbered member or neighbor                                              |
| `o` / `O`                 | Cycle grouping mode forward / reverse (`STANDARD` ↔ `BY_DATE` ↔ `BY_STATUS`)                                                                                |
| `~`                       | Jump among agent-node-name ancestors, descendants, and shared-hood neighbors (see `NEIGHBORS`)                                                              |
| `g`                       | Scroll to top (file, tools, or metadata panel)                                                                                                              |
| `G`                       | Scroll to bottom (file, tools, or metadata panel)                                                                                                           |
| `Ctrl+D` / `Ctrl+U`       | Scroll file panel down / up                                                                                                                                 |
| `Ctrl+F` / `Ctrl+B`       | Scroll prompt panel down / up                                                                                                                               |

> **Note:** `o`/`O` cycle the L0 grouping bucket forward / reverse on the Agents tab and
> on every Artifacts pane that has a grouping mode (each surface keeps its own
> in-session mode). Beads and Plans have no grouping-mode data, so the keys are a silent
> no-op there; the same is true on the AXE tab. The Artifacts open-externally verb moved
> to `E`; bang-mode `!o` still marks PR origin. `g`/`G` keep their conventional
> vim-style scroll-to-top/bottom meaning on every tab. See
> [Grouping Modes](#grouping-modes) below.

On the Agents tab, `~` uses dotted agent-name relationships rather than Patch sibling
families. Relations are keyed on the name a row presents as its **sase agent** name, so
a family participates under its bare family name rather than its root member's `--`
name. ACE includes visible ancestors and descendants plus neighbors from every dotted
hood that contains the selected sase-agent name — including the hood that matches that
name exactly. For example, `foo.bar.worker` can offer peers under `foo.bar` and cousins
elsewhere under `foo`, grouped deepest hood first, and a family `fam` offers
`fam.helper` as a descendant while `fam.helper` offers `fam` back as its ancestor.
Dotless names can still have descendants such as `foo.child`. If there is exactly one
related visible row and no dismissed descendant to offer, ACE jumps directly. Otherwise
it opens a chooser that can also revive same-session dismissed descendants. A chosen
target is resolved by stable identity and revealed through any clan, family, workflow,
or grouping folds before focus moves.

When a clan or a sase agent is selected, its metadata panel assigns a fixed number to
each numbered row, up to 100 targets. A sase agent is a multi-member family container or
a single agent; sase-agent panels number their `FAMILY MEMBERS` roster (when present)
and then their `NEIGHBORS` section from one continuous ladder. A selected family
**member** row numbers its enclosing family's `FAMILY MEMBERS` roster the same way,
listing every sibling except itself from the same ladder; a member row owns no sase
agent, so it has no `NEIGHBORS` rows to follow the roster. Documents with at most ten
numbered rows use `0`–`9`; larger documents number the first 100 rows with two-key
values `00`–`99` and show any remaining entries as an unnumbered count. After the first
digit of a two-key jump, press `Esc` to cancel or any non-digit key to cancel and
continue with that key's normal action. A successful jump expands only the target's
ancestor chain, switches tribe panels when needed, and participates in the normal
`Ctrl+O` jump-back history. A digit on a dismissed neighbor revives that agent instead
of jumping, exactly as `<enter>` does in the `~` chooser. If the roster or the neighbor
relationship changed since the panel was drawn, the jump is cancelled with a warning
rather than landing somewhere stale.

### Agent Actions

| Key                 | Action                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------- |
| `!R`                | Revive a previously dismissed agent                                                                           |
| `a`                 | Open completion artifacts for the focused agent; in tmux, press again to close the viewer pane                |
| `+`                 | Run custom agent                                                                                              |
| `A`                 | Open auto-approve menu / answer HITL                                                                          |
| `f`                 | Prepare a fork of the selected agent/family, clan container, or focused named tribe panel                     |
| `n`                 | Name agent                                                                                                    |
| `r`                 | Edit prompt and relaunch agent (retry without killing)                                                        |
| `v`                 | View files (hint mode; annotates clan/family containers in place)                                             |
| `D`                 | Toggle prior-attempt view (only shown when the agent has retried)                                             |
| `V`                 | Open the Agent Run Log modal for the focused agent                                                            |
| `w`                 | Wait/unwait agent (opens WaitModal — see below)                                                               |
| `W`                 | Prepare a prompt that waits for the selected agent/family, clan, or named tribe; marks produce `%w:a,b,c`     |
| `m`                 | Mark / unmark current agent, or all top-level agents in focused collapsed group (auto-advances to next)       |
| `s`                 | Save and dismiss marked agents as a revivable group (opens optional group-name modal)                         |
| `U`                 | Toggle the focused agent's unread marker                                                                      |
| `u`                 | Clear all agent marks                                                                                         |
| `x`                 | Kill / dismiss agent, stop a running monitor, or act on every marked agent or focused group                   |
| `X`                 | Open the cleanup panel for panel, global, tribe, clan, marked, group, or custom cleanup                       |
| `Enter` / `L`       | Jump to PR (for agents with `meta_new_cl`/`meta_new_pr`)                                                      |
| `e`                 | Edit chat in editor; with marks, open all editable marked transcripts in one editor invocation                |
| `E`                 | Edit panel content in editor                                                                                  |
| `t`                 | Open the focused agent's tmux target; agents with opened linked-workspace context show a workspace chooser    |
| `T`                 | Open tmux window in the agent's primary project workspace                                                     |
| `N`                 | Open the agent tribe modal (input is pre-seeded with `pinned` for agents without a tribe; empty clears it)    |
| `]` / `[`           | Cycle panels: file → tools → metadata (forward / reverse)                                                     |
| `p`                 | Toggle file / prompt layout                                                                                   |
| `z`                 | Start metadata fold mode for clan, agent node (family or single agent), or selected whole-tribe detail panels |
| `Z`                 | Zoom the active agent or tribe detail panel                                                                   |
| `=`                 | Isolate the focused tribe panel, or restore the remembered pre-isolation layout                               |
| `-`                 | Collapse every open agent-node/clan fold in the focused tribe panel, or restore the last sweep's folds        |
| `Ctrl+N` / `Ctrl+P` | Next / previous file in panel                                                                                 |

### Forking Agents and Groups

With a named agent selected, press `f` to open a prompt prefilled with `#fork:<agent>`.
Selecting a family root uses the family name instead. The same action works on the
synthetic container row for a clan (`#fork:<clan>`) and while an expanded or collapsed
named tribe panel has whole-panel focus (`#fork:@<tribe>`). The reserved `@default`
panel and grouping banners are not fork targets.

Press `W` on the same selections to prepare `%w:<agent-or-family>`, `%w:<clan>`, or
`%w:@<tribe>`. A non-empty marked set takes precedence and produces one comma-separated
wait over the named marked rows instead of the focused group. The reserved `@default`
panel and grouping banners are not wait targets either.

Group references are dynamic; pressing `f` does not snapshot the selected transcripts. A
family reference contributes the readable transcripts of successful members in
sequential chain order. The injected context also lists excluded members, whether they
are still running, ended unsuccessfully, or have a missing or unreadable transcript. An
explicit `--<suffix>` reference contributes only that member. A clan reference resolves
the newest clan generation when the deferred launch proceeds and requires every member
of that generation to have succeeded. A tribe reference follows the next-entity rule:
the new run waits for the earliest successful entity in that tribe launched after its
own artifact was created. It does not fork the agents currently visible in the selected
tribe panel. See
[Tribe wait and fork targets](agent_families.md#tribe-wait-and-fork-targets) for the
full ordering rules.

ACE also tries to carry VCS context into either prefilled prompt. For one selected agent
or family row, it uses that row's launch ref when it can resolve it. For a selected clan
or tribe, it adds a VCS tag only when every real agent in the current scope resolves to
the same workflow and ref. Mixed or missing context produces only the `#fork` or `%w`
reference, leaving you to add the desired `#git`, `#gh`, or other VCS tag. A marked wait
is different: one mark uses that row's context; multiple marks use the selected marked
row, or the first named mark when the selection is elsewhere. The VCS lookup runs off
the UI thread. Before opening the prompt, ACE verifies that the selected scope and its
members did not change; marked waits instead verify the marked target set. A stale
selection cancels with a warning rather than opening a prompt for the wrong target.

### Clan and Family Detail Panels

Selecting a clan container shows a `CLAN` summary; selecting a real multi-member family
root shows that family's normal agent metadata plus a `FAMILY MEMBERS` roster. Both
rosters use the numbered member jumps described above. Clan direct members in the Agents
list sort by status priority — Failed, Stopped, Running/Starting, Queued, Waiting, Done
— with launch recency breaking ties. The clan metadata roster instead keeps
chronological launch order so its numbers do not change as statuses change; a nested
family remains one direct entry with its chain indented beneath it. Family rosters
retain sequential chain order.

Selecting a family **member** row (not the container) also shows a `FAMILY MEMBERS`
roster: the same enclosing family's members, in the same chain order, minus the selected
member itself. The heading carries a dim ` · <family name>` suffix naming the family,
since the count shown is one less than the family's full size. Unlike a container panel,
a member panel folds this roster (and the rest of its own sections) using the selected
member's own three-level agent scale rather than the family's two-level scale, so no
`Fold: N/M` header line appears.

Clan metadata has three session-only detail levels. Family metadata uses the last two
effective states as its two-level scale for fold-aware metadata: family level 1 is
expanded and level 2 is fully expanded.

| Level | Content                                                                                                        |
| ----- | -------------------------------------------------------------------------------------------------------------- |
| 1     | Core member rows plus headings and counts; expensive disk-backed bodies remain deferred                        |
| 2     | Bounded triage detail such as activity, wait/retry state, context summaries, and compact member metadata       |
| 3     | Full available sections and the richest member annotations, including workspace, timestamps, and attempt count |

The compact clan roster and its fixed numeric member jumps remain available at all three
levels. Clan sections appear only when their content is known to exist: known-empty
sections are omitted, while unknown required disk-backed content produces one dim
`⋯ scanning member data…` tail for the document instead of a placeholder for each
section. Family rosters and their numeric jumps likewise remain available at both
effective levels. Family xprompt and prompt sections are omitted when absent, while an
unfinished reply remains visible as pending rather than disappearing as empty.
`AGENT XPROMPT`, `AGENT PROMPT`, and the consolidated `AGENT REPLY` are plain navigation
anchors whose available conversation bodies stay fully visible at both family levels.

`v` annotates a clan document in place rather than replacing it: the panel keeps its
current sections and fold level and gains inline `[N]` markers. Clan hints come from the
clan summary, member-attributed `ERRORS`, variable, `REPLIES`, and `PROMPTS` bodies,
per-entry `SASE CONTEXT` rows, `SLOW TOOL CALLS` rows, and the `COMMITS` lane; each path
resolves against the workspace of the member that produced it, and summary paths that
name a plan, artifact, or delta resolve through an index computed during clan enrichment
rather than a blind workspace join. A logical `plan:` reference is marked and resolved
as one token including the prefix, and an archived `prompts/<YYYYMM>/<name>.md`
reference resolves into the project's agents sidecar checkout rather than the agent
workspace. Hints exist only where text is actually visible, so availability follows the
active fold level — level 1 hints the clan summary only, level 2 adds the bounded triage
lines, and level 3 adds full bodies and per-entry context, tool-call, and commit rows.
Markers are numbered in document order and are distinct from the roster's fixed 0-9
member jump gutter, which never carries a marker and never renumbers in hint mode. While
clan enrichment is still in flight the hint bar stays open and the document is
re-annotated when the deferred sections land.

The default fold chords are:

| Key       | Action                                                                                  |
| --------- | --------------------------------------------------------------------------------------- |
| `zz`      | Cycle the whole metadata panel forward through its active scale                         |
| `zZ`      | Open every fold to the active maximum; at that maximum, close every fold to the minimum |
| `za`      | Cycle the foldable section or numbered member at the top of the metadata viewport       |
| `zA`      | Toggle that foldable section or member between collapsed and fully expanded             |
| `z1`-`z2` | Set a family directly to level 1 or 2                                                   |
| `z1`-`z3` | Set a clan or regular-agent session scope directly to level 1-3                         |
| `z1`-`z4` | Set a selected whole tribe panel directly to level 1-4                                  |

The `Fold: N/M` header field reports the position within the active scale, while glyphs
on foldable headings show their effective per-section levels. Only family panels print
that header line; a single sase agent relies on the `NEIGHBORS` and `SLOW TOOL CALLS`
heading glyphs instead. On a family conversation heading, `za` and `zA` refresh normally
but do not create or change a section override. A valid panel-level cycle, extreme
toggle, or direct selection clears real per-section overrides. Fold state is shared by
the Agents metadata panel: an ordinary agent's own three-level scale shapes its
`NEIGHBORS` and `SLOW TOOL CALLS` sections, so `z*` chords have a visible effect on a
regular sase agent, and the same session scope carries over to the next selected clan or
family container. Most other sections on a regular-agent panel stay fold-inert, except
the `SASE CONTEXT / BEAD` lane's multi-line values: at scale position 1 (`z1`,
Collapsed), a task or phase worker's `Notes`, and a task worker's `+1 Evidence`,
collapse to a one-line digest, `N lines (zz to show)`; single-line values never fold,
and at positions 2-3 the full value renders. A selected whole tribe panel adds level 4
for exhaustive detail. These keys are configurable; see
[Agent Clans, Families, and Tribes](agent_families.md) for the grouping model.

When ACE knows a planner/author or epic lander's associated plan, the metadata panel
adds a `PLAN` lane in `SASE CONTEXT`. A task worker that authored a plan in the same run
also shows a `PLAN` lane beside its task `BEAD` lane. The lane order is `PLAN`, `BEAD`,
`ARTIFACTS`, the audited `MEMORY`, `GLOSSARY`, `SKILLS`, and `WORKSPACES`, with absent
lanes omitted once they have resolved. A plan or any recorded output is enough to show
the context section. An epic phase worker never shows its parent epic as a `PLAN` lane.
Instead, its launch metadata identifies the epic plan and exact phase bead, and ACE
derives one phase-local `BEAD` lane from that phase's validated, frontmatter-ordered
entry. The lane shows `Phase Title`, `Description`, `Size`, `Epic Plan`, and
`Epic Title`; `Size` uses the literal `xsmall`, `small`, `medium`, `large`, or `xlarge`
label and the same accessible chip palette as epic summaries. The phase title comes from
the same validated entry, is normalized to one line, and wraps losslessly like the other
values. Authored descriptions are also normalized to one line; a missing description
uses the same stable plan-and-phase pointer generated during deterministic bead
creation. This modern path does not read the bead store, and missing, unreadable,
damaged, explicitly invalid, or out-of-range metadata keeps the known identity/path
fallbacks while rendering optional fields as `unavailable`, without exposing the epic
goal, dependencies, or any peer phase.

`SASE CONTEXT` **streams**: its lanes are resolved cheapest-first in batches and each
batch is published as it lands, so the section appears almost immediately instead of
waiting for the slowest lane. A lane that has not resolved yet is not the same as a lane
that resolved to nothing — while a lane is still in flight it renders a dim,
non-interactive `resolving…` row that holds its position in the order above, so the
section fills in rather than reshuffling as the remaining lanes arrive. `PLAN` and
`BEAD` share one backing lane, so both show their own `resolving…` row until it lands
and the panel can tell which of the two actually has content. Repaints coalesce through
the same debouncer that drives the rest of the header, leaving hint mode and scroll
position undisturbed.

For planner/author and lander rows, the lane body contains the complete normalized
`Title`, `Goal`, and canonical `Path`; a tale additionally gets a `Size` row between
`Goal` and `Path`, showing the authored `xsmall`/`small`/`medium` chip, or the `medium`
chip plus a `(default)` marker when the tale's `size` was missing or an over-sized
legacy `large`/`xlarge` normalized at launch (see
[Plan Frontmatter Schema and Validation](sdd.md#plan-frontmatter-schema-and-validation));
epics never show a `Size` row here. The lane header shows the effective user-facing tier
(`plan`, `tale`, or `epic`) and, for epics, the phase count. The tier records how the
user approved the plan: `approve` means a plan approved without an SDD commit, `tale`
(and the legacy commit-only action) means a committed tale, and `epic` means a committed
or launched epic. That displayed choice survives a later commit or launch failure. When
action metadata is absent, ACE falls back to a valid authored `tier: tale` or
`tier: epic`; a legacy committed record without a readable authored tier falls back to
`tale`, while a genuinely unresolved tier renders `tier unavailable`. Path selection is
independent: committed paths are relative to the agent workspace (including SDD sidecars
such as `sase/repos/plans/...`), while pending and explicitly uncommitted archives use
`~/.sase/plans/...`.

Validated authored epics add a phase roadmap beneath those three rows. ACE validates
this display as a launch consumer: modern phases retain their authored `xsmall`,
`small`, `medium`, `large`, or `xlarge` size, while historical phases with an omitted
size normalize to `small`; an explicit invalid size or other schema damage makes all
phase metadata unavailable. Each entry shows its one-based authored order and diamond,
title, fixed-width literal size chip, canonical ID, `no dependencies` or
`after <id>, ...`, plus an authored phase model when present. Optional descriptions get
their own hanging-indented line. The order and diamond glyph describe static plan
structure, not execution state or live bead progress. Tales retain the compact four-row
form (`Title`, `Goal`, `Size`, `Path`). The chip remains visible while the title and
other long ASCII or wide-Unicode values fold completely without ellipses; the lane caps
content at 80 terminal cells on wide panels and reflows to the normal metadata panel or
metadata zoom width. Logical header text contains the same size labels for search, copy,
and style inspection. In hint mode only `Path` receives a numbered file hint, allocated
in the plan's visual reading order. Missing or damaged plans keep their known lane and
path visible; when epic context is known, validation failure renders one quiet
`phases unavailable` header state rather than partial phase data.

ACE separates fast visible-inbox loads from full-history scans. The visible inbox is the
normal Agents-tab working set: active rows plus recent completed, non-hidden rows.
Startup, manual refresh (`y`), and active agent search use that path through the
persistent artifact index when it is available.

If the index is missing or unhealthy, ACE falls back to a bounded source-artifact scan
for the first paint and shows a repair warning with the reason. That repair state can
arm a deferred full-history reconcile after input has been quiet, but normal `y`
refreshes still stay on the visible-inbox path. Use `sase agent index status --json` for
a lightweight check that does not scan source artifacts, `sase agent index verify` to
compare the index with source artifacts, and `sase agent index gc` to rebuild the index
and dismissed projection. Use the Agents-tab leader command `,y` when you want an
immediate full-history refresh from source artifacts. If historical agent imports wrote
future-dated artifacts or dismissed bundles, `sase agent index repair` reports that
imported state (dry run by default) and `-a`/`--apply` removes it and rebuilds the
affected projections; locally produced records are never touched.

The dismissed projection that hides agents from the visible inbox is rebuilt from the
in-memory dismissed set _unioned with every dismissed-bundle summary_. Reviving an agent
now purges its dismissed bundle, so a revived agent stays visible. For archives that
accumulated stale bundles before that fix, plain `sase agent index gc` is **not** a
repair on its own -- it rebuilds the projection _from_ those lingering bundles and
re-hides the revived agents. Run `sase agent index gc --purge-revived-bundles` (`-r`) to
first delete dismissed-bundle files and summary rows for suffixes that are no longer
present in `dismissed_agents.json`, then rebuild the corrected projection.

When one or more agents are marked, `e` edits the marked set instead of only the focused
row. ACE opens editable completed transcripts in visible row order, deduplicates
repeated paths, skips live marked rows that are still running or have no chat file, and
reports that live skip count. Stale marks are ignored for this action, and marks remain
in place after the editor exits.

### Sase Agent Neighbors Section

Every sase agent panel carries a numbered `NEIGHBORS` roster in its metadata region. The
section appears on family container panels below their `FAMILY MEMBERS` roster and on
ordinary agent panels. Clan containers, tribe panel summaries, family member child rows,
and workflow aggregate rows have no `NEIGHBORS` section. A selected family member row
owns no sase agent, so its panel carries only the `FAMILY MEMBERS` roster (siblings,
minus itself) and never a `NEIGHBORS` section.

The rows are exactly the rows the `~` chooser offers for that sase agent — ancestors,
descendants including same-session dismissed descendants, then hood neighbors grouped by
hood, nearest hood first — under dim `ancestors`, `descendants`, and `<hood> hood` group
labels. A sase agent joins the hood that matches its own name, and a family uses its
bare family name for that match, so a family `visual.worker` and a single agent
`visual.worker.notes` relate as ancestor and descendant exactly as two single agents
with those names would. Row labels are shortened relative to their group, so a `myclan`
hood neighbor reads `.code` and a descendant reads `--impl.helper`. A `⊘` glyph and a
`dismissed` annotation mark dismissed rows, and `folded` marks a prospective row that
currently lives inside a collapsed clan. The section sits directly below
`WORKFLOW VARIABLES` and immediately above `SASE CONTEXT`, so a sase agent's numbered
neighbors stay reachable without scrolling past the context, slow-call, and error
sections.

The row count follows the sase agent's fold scale by position, not by level name: the
first position shows 3 rows, the last position shows all of them, and any middle
position shows 10. A family therefore shows 3 rows at level 1 and every row at level 2,
while a single sase agent shows 3 / 10 / all across its three levels. The heading count
is always the sase agent's total neighbor count, and a dim
`… +N more neighbors (zz / za to show more)` tail reports what is hidden. Only visible
rows get digits. On a family, siblings that already appear under `FAMILY MEMBERS` are
not repeated; they are reported by a dim `… +N also listed under FAMILY MEMBERS` tail
instead. That suppression applies only to this section — the `~` chooser and the info
panel's `neighbors:` badge still count them.

### Opened Repository Context

Configured `linked_repos` are recorded in agent metadata at launch time, while linked
and external repos opened during a run are recorded in opened-repository markers. For
non-terminal agents, ACE can include dirty opened repos in the agent detail
`SASE CONTEXT` `ARTIFACTS` lane under `Deltas`. The field counts primary and opened-repo
changes together, groups linked and external entries under distinct glyphs and canonical
repo names, and resolves file hints relative to the opened repo directory. Missing
workspace directories, clean repos, and completed/failed agents are not part of this
live delta display.

When a SASE-launched agent uses `/sase_repo`, the run records an opened-repository
marker. The underlying command infers the host project and workspace from cwd;
configured linked repos remain backed by hidden `PROJECT_STATE: sibling` project
records, while external repos remain workspace-local and create no project record. ACE
shows the markers in the prompt/detail `SASE CONTEXT` section with the repo name, kind,
resolved path, open time, and reason. Live deltas, commit diffs, and revert all retain
the canonical external name (for example, `gh:pallets/click`); reverting an external
repo discards local clone changes without re-cloning from the network.

### Wait Modal

Press `w` on the Agents tab to open the WaitModal. It has five editable fields —
**Agents**, **Beads**, **Time**, **Runners**, and **Priority** — each prefilled from the
agent's current wait. Time, Runners, Priority, and Beads render a live preview of how
the typed value will be interpreted; an invalid Time, Runners, or Priority value blocks
apply and focuses the offending field.

Beads completes against every non-closed bead in the agent's project, read from the same
canonical store the wait resolver consults, so a bead offered by the picker is always
one the resolver can see. The agent's own epic/phase bead is excluded from candidates —
an agent can never wait on the bead it exists to close. Candidates are ordered by status
(`in_progress`, `claimed`, `ready`, `open`, `snoozed`), then by most-recently-updated,
then by ID; the filter fragment matches bead ID or title. At most 100 rows render per
keystroke, with a trailing `…N more — keep typing` row when more match. A bead already
present in the field renders with a dim `· selected` suffix.

The Agents and Beads fields each have their own completion list directly beneath them,
but only one is ever visible at a time — whichever of the two fields was focused most
recently (Agents by default). Focusing Time, Runners, or Priority never changes which
list is shown, and the hidden list is not part of keyboard focus traversal.

The beads preview reports one of: an empty-field neutral message, a loading message
while the bead catalog loads in the background, a neutral "bead store unavailable" state
when the project's store can't be read (IDs are not verified in that case), a valid
summary of up to three typed beads with their status glyphs plus an aggregate count, or
an error when a typed ID isn't in the project's bead store or is the agent's own bead.
Applying an error-state bead wait is a soft, two-step guard rather than a hard block:
the first `Enter` focuses the Beads field and changes the footer instead of dismissing;
a second `Enter` applies the wait as typed. Any edit to the Beads field disarms the
guard. A store that can't be read never arms the guard, since bead stores sync through
git and a locally-missing ID can still be valid upstream.

Behavior depends on the agent's status:

- **WAITING or QUEUED agent**: Edit dependency names, bead gates, a time floor, the
  `runners` threshold, or the runner-slot `priority`. A runner-slot-parked agent applies
  a runners- or priority-only edit live on its next poll; changing earlier wait stages
  restarts the agent. Clearing an explicit runner threshold returns it to the global
  `max_running_agents` cap rather than bypassing that cap.
- **RUNNING agent**: Enter a dependency, bead gate, time floor, runners threshold, or
  priority to kill and restart the current agent with a canonical `%wait(...)`
  directive.

The **Runners** field is an admission threshold against the sase-agent occupancy count
`R` in the Agents header, not a count of individual shells. A serial family — including
its monitor and `--next` follow-up — still occupies one slot, so it still counts against
this threshold. Only a root or a live parallel family member waits here; a serial family
member rides the family's slot and never parks.

Priority must be a non-negative integer and defaults to `10`; lower values are admitted
first. See [Runner slot waits](troubleshooting/runner-slots.md) for how priority
interacts with FIFO order and the bounded deference window applied to deprioritized
waiters.

`Enter` applies, `Tab` accepts a highlighted agent- or bead-name completion and
otherwise moves focus to the next field, `Ctrl+R` runs the agent now by clearing every
wait condition, and `Escape` cancels. The modal supports readline-style keybindings
(`Ctrl+F`/`Ctrl+B`/`Ctrl+A`/`Ctrl+E`) for cursor movement.

`Ctrl+J` and `Ctrl+K` walk forward and backward through the five fields directly, in the
displayed order (Agents, Beads, Time, Runners, Priority), wrapping around at either end
and placing the cursor at the end of the field's current value. Unlike `Tab`, they never
consume a highlighted completion, so they move focus even while a completion list is
open; when focus is on the Agents or Beads completion list itself, the step is taken
from that list's own field. `Up` / `Down` and `Ctrl+P` / `Ctrl+N` move within the
visible completion list rather than between fields.

### VCS Tag Resolution in Fork/Wait

When forking or waiting on an agent, VCS tags in the prompt (e.g., `#git(ref)`,
`#gh:ref`) are automatically updated to point to the correct branch. For non-project
agents, the ref is replaced with the agent's PR name (branch). For project agents using
`#pr`, the ref is replaced with `@<name>` which resolves to the agent's branch. HITL
suffixes (`!!`, `??`) are stripped during replacement since fork scenarios should not
carry over HITL overrides.

### Workflow Visibility

Workflows launched via `sase run` are visible in the Agents tab alongside ACE-launched
workflows. The TUI scans `artifacts/run/*` directories in addition to `workflow-*` and
`ace-run` directories, and writes an initial `workflow_state.json` before execution so
that step data appears immediately rather than showing a bare RUNNING entry. Anonymous
`tmp_*` workflows are included in the normal visible-inbox index when their workflow
state has `appears_as_agent: true` and does not set `hidden: true`; explicitly hidden
workflow rows are omitted from the default view. Specialized review runners launched by
axe (mentor, CRS, fix-hook, and summarize-hook review agents) are also visible and are
automatically grouped into tribe `@review`, matching the behavior of a
`%id(..., tribe=review)` prompt launch.

### Agent Artifacts

Press `a` on a focused agent to open the artifact panel whenever artifacts are
associated with that agent. The list can include chat transcripts, plan files, generated
Markdown PDFs, generated images, generated videos, prompt-referenced media from saved
prompt artifacts, and explicit files saved with
`sase artifact create -p <path> [-l <label>] [-k <kind>]`. ACE always opens the panel,
even for a single artifact, so the label, kind, and path are visible before launching
the terminal viewer.

The prompt/detail header includes those non-chat entries in the plan-adjacent
`SASE CONTEXT` `ARTIFACTS` lane. Within that lane, `Commits`, `Deltas`, and `Files` stay
in that order when present. Paths are made workspace-relative when possible, and hint
mode assigns numbers to those paths so they can be opened with the normal file-hint
flow.

Artifact panel controls:

| Key         | Action                                                                  |
| ----------- | ----------------------------------------------------------------------- |
| selector    | Open the artifact with that one-key selector (`1`-`0`, then letters)    |
| `j` / `k`   | Move through artifact rows                                              |
| `m`         | Mark / unmark the highlighted artifact and advance to the next row      |
| `%`         | Open the file-kind **Copy as…** palette                                 |
| `y`         | Copy Markdown contents (an accelerator for the palette's `c` row)       |
| `Y`         | Copy the preferred anchored stored/source path                          |
| `Enter`     | Open marked artifacts in list order, or the highlighted row if unmarked |
| `A`         | Open all artifacts in list order, ignoring marks                        |
| `q` / `Esc` | Close the panel                                                         |

The modal-local file palette offers `@` prompt-form references, `l` Markdown links, `c`
Markdown contents, `p` stored paths, `P` source paths, `J` metadata JSON, and `s`
snapshots. Stored and source paths are separate, anchored answers; an absent source is
labeled “not recorded,” and copying a stale source keeps the “no longer exists” warning.
With marks, the palette copies rows in visible order: references and paths are
newline-separated, links form a Markdown list, metadata is a JSON array, and Markdown
contents use bounded fenced sections. Unavailable rows are skipped with an explicit
count. These modal-local `l`/`J` accelerators are distinct from the Artifacts Files
pane's compatibility-preserving `%L`/`%j` keys. The legacy `y` and `Y` accelerators
remain available and apply to the same marked set.

`Y` shares one helper with the [Files pane](#file-pane), so both copy the same anchored
path: the stored path, except that PDF rows yield the live Markdown source they were
rendered from when the index recorded one. Relative index paths are anchored to the
producing workspace — including legacy rows whose workspace is discoverable only through
the agent's artifact metadata — and the completion toast says when the copied path no
longer exists.

When ACE is running inside tmux, artifact viewing opens in a right-side tmux pane so the
TUI remains visible. The Agents list collapses while the tracked pane is live,
row-changing navigation shows a warning instead of moving to a different agent, `l`
focuses the tracked pane, and lowercase `a` closes it. If the pane was already closed,
lowercase `a` opens the artifact panel normally. Outside tmux, ACE suspends while the
terminal viewer runs in the current pane. The viewer supports image, video, Markdown,
PDF, and text artifacts: images are displayed directly with `kitten icat`, videos play
with `mpv`, Markdown is first rendered to PDF, PDFs are converted to PNG pages for
paging, and unknown file artifacts fall back to a text viewer. The viewer needs `kitten`
for image/PDF/Markdown display, `mpv` for videos, `pdftoppm` for PDF/Markdown paging,
and `pandoc` plus a supported PDF engine for Markdown rendering. Missing tools produce a
warning instead of failing the TUI.

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

Only one plan artifact is shown for an agent. When both an archived plan and an SDD tale
path are present, ACE prefers the committed SDD plan; otherwise it keeps the path that
best matches the run metadata.

During successful-agent finalization, Markdown-to-PDF rendering updates
`workflow_state.json.pdf_status` and a compact activity label. ACE renders that label
only in the prompt/detail header's labeled `Activity:` field, so long conversions show
progress such as `PDF 2/4 <path>` or `PDFs done 3/4 (1 skipped)` instead of looking
idle.

### Tribe Side Panels

The Agents tab is laid out as a series of vertically-stacked side panels, one per
effective agent **tribe**. Agents without a stored tribe live in the reserved `@default`
panel; an explicit `default` assignment converges on the same panel, so the UI never
creates a duplicate default bucket. `@default` is derived for presentation and is not
backfilled into `agent_meta.json` or `agent_tribes.json`; clearing a user-managed tribe
returns the agent to this panel. Every tribe renders as `@<tribe>` with a sase-agent
count in the panel title. One standalone agent or one sequential family is one sase
agent, and a rootless clan contributes one sase agent per direct member rather than one
for its synthetic container. Per-tribe icons, identity colors, and initial expansion are
configurable through [`ace.tribes`](configuration.md#acetribes); the special `default`
entry styles the reserved panel. A manual panel fold lasts for that panel's current
lifetime, and the configured initial state is applied again when the panel appears after
a restart or after the tribe disappears and returns. Across structured ACE TUI surfaces,
identity colors apply only to an existing configured icon and the `@tribe` name; they do
not recolor free-form `@...` text or selection, fold, count, heading, and status chrome.
Configured icons remain limited to surfaces that already show an icon. Each panel title
can also show compact scoped metrics in the form `[S1 R2 W1 F1 U1 D3]`: `S` is stopped
for human input, `R` is running, `W` is waiting to start, `F` is failed, `U` is unread
terminal work, and `D` is done/read terminal work. Zero-count metrics are omitted. The
status metrics use the same sase-agent projection as the adjacent total and classify a
sequential family once from its normalized owner status. The selected whole-panel
`TRIBE` header uses that same projection, while its nested count and per-family/per-clan
member summaries preserve the concrete-member distinction. On the selected whole panel,
the title marker, total, brackets, and metric letters use the focus accent; each numeric
metric count retains its semantic status color. Panel heights are sized to their content
and separated by a one-row gap. When the panels fit, the first panel grows to absorb
leftover vertical space while later panels stay pinned to their natural height; when the
panels overflow, space is weighted by each panel's rendered row count.

A selected tribe panel's `TRIBE` header ends with an unlabeled description row only when
the tribe has a configured [`description`](configuration.md#acetribes). That row is set
off from the field stack (`Name`, `Status`, `Composition`, `Runtime`, `Fold`) by a blank
line and wrapped at a fixed 80-cell measure (no hanging indent — there is no label to
indent past). A tribe with no configured description renders no row there at all,
including unconfigured ad-hoc tribes with no `ace.tribes` entry. To find configured
tribes that are missing a description, run `sase doctor -C config.tribes`.

Use `J` / `K` to move across expanded panels (forward / reverse) and enter the first or
last selectable row in the destination; collapsed panels are skipped entirely, and the
keymaps do nothing when no other panel is expanded. Collapsed grouping banners count as
rows. When the focused panel's only selectable row is already selected — or it renders
none — lowercase `j` / `k` select the adjacent whole panel, wrapping across every panel
including collapsed ones; `l` or `Esc` then descends into the newly selected panel's
remembered row. This differs from `J` / `K`, which skip collapsed panels and land
directly on a row. Whole-panel focus is available only in the split layout. Lowercase
`h` walks from any agent or workflow-step row to its validated immediate workflow,
family, clan, and finally tribe parent without changing structural or grouping folds. It
also selects a lone split panel after the structural chain is exhausted. A selected
panel has a `❖` title and shows a fold-aware `TRIBE` summary in the metadata pane. While
it is selected, `j` / `k` cycle whole panels without descending; `l` or `Esc` returns to
the remembered row. A second `h` collapses the selected panel when another panel remains
visible. On a collapsed panel, the first `l` expands it while keeping whole-panel focus
and the second returns to the remembered row; `L` on a collapsed panel does not expand
it — it repeats the usual already-collapsed warning instead (see uppercase `H`/`L`
below). Lowercase `h` on a collapsed panel selects the visually bottom-most expanded
panel without changing any panel folds, and `Ctrl+O` returns to the collapsed origin.
When every live panel is collapsed, `h` remains a no-op and shows the existing
`Panel is already collapsed` warning. Apostrophe jump hints include every split-panel
title, even a lone expanded panel, as well as collapsed titles, and support the normal
`Ctrl+O` jump back.

Lowercase `l` only advances a real fold owned by the selected row or its immediate
workflow/family owner, so a visible hidden leaf under an already fully expanded workflow
is a no-op. Uppercase `H` is the structural mutation key. When the selected row owns an
open workflow or sequential-family agent node, the first press retreats that agent node
one fold level. From a visible hidden step that hides the selected row, selection
re-anchors to the agent-node owner. After the selected agent node is collapsed, later
presses fully collapse every remaining open agent node in the next grouping scope, then
only the open canonical clan enclosing the selected row. With that now-collapsed clan
container still selected, another press collapses every remaining open canonical clan in
the group; only a later press collapses the grouping banner. A banner, already-collapsed
agent node, or already-collapsed clan selection proceeds directly to that
remaining-agent-node or group-wide clan sweep. Tools detail still takes priority. On a
selected expanded whole panel, `H` hints every currently expanded agent node, clan, and
top-level grouping banner in that panel — the same `L` hint affordance restricted to
collapsible targets — and fully collapses whichever one you pick; it never expands and
never touches the panel itself, which stays lowercase `h`'s job. A panel with nothing
expanded warns without arming hint mode; an already collapsed panel keeps the usual
already-collapsed notification. The merged layout has no whole-panel focus and keeps the
row-focused group scope across the merged roster.

Press `Z` with a whole tribe panel selected to zoom that tribe's metadata document.
Press `=` to isolate the focused tribe panel: it keeps that panel expanded and collapses
every sibling panel. If that changes the layout, ACE remembers the prior collapsed-panel
set for one session-local restore. Panels whose state would change back show `↺` in
their titles, the footer changes to `= restore panels`, and the next `=` restores the
remembered layout. A separate sibling-panel or layout mutation invalidates the pending
restore. An already isolated panel is an idempotent no-op and does not arm a restore.
`=` works from whole-panel focus and from a row selection inside a panel alike — from a
row, it isolates the panel that holds the cursor without changing the selected row. This
action preserves the selected panel's remembered row and is available only in the split
layout.

Press `-` to sweep every open structural fold — agent nodes and clans, never grouping
banners such as `Done` or `Running` — closed in the tribe panel that holds focus, in one
press. It resolves scope the same way `=` does: from whole-panel focus, from a row or
banner selection inside a panel, and in the merged layout, where it treats the merged
roster as one scope. `-` never collapses the panel itself; that stays lowercase `h`'s
job, and it never touches an open grouping banner either — use `H` for that. When the
focused panel has nothing left to collapse, `-` reverses itself: it re-expands exactly
the folds its own last sweep in that panel closed, restoring each structural fold to the
level it held before (a fully expanded agent node comes back fully expanded, not merely
expanded). The restore is filtered at press time to folds that are still live in that
panel and still collapsed, so it is forgiving of folds the user re-expanded by hand or
owners that disappeared, and it never resurrects a fold that no longer exists. Each
panel remembers at most one sweep; a fresh sweep replaces that panel's record, and a
panel that stops being live drops it. While a restore is armed, the panel marks every
fold `-` would re-expand with a gold `▿` on the owner row and `▿N` in the panel title;
those markers clear as soon as the next `-` press would sweep instead of restore. The
footer shows `- collapse folds` when the focused panel has an open agent-node or clan
fold to sweep, or `- restore folds` when nothing is left to collapse but a prior sweep's
reverse is still armed. A panel with only open grouping banners and no open agent node
or clan reports nothing to collapse or restore.

Per-panel actions (kill, dismiss, expand, etc.) operate on whichever panel currently
holds focus. Press `X` to open the cleanup panel: `d` dismisses completed agents in the
focused panel, `D` dismisses completed agents across loaded panels, `k` cleans the
focused panel, `K` cleans all loaded panels, `m` cleans marked agents, `g` cleans the
focused group, `t` opens the tribe chooser, `C` opens the clan/member chooser scoped to
the focused tribe, and lowercase `c` opens the custom selector. Whole-clan selections
are planned by clan name and generation; member subsets and mixed selections use
explicit agent identities. Both paths continue through the shared bulk-cleanup
confirmation and execution flow.

The `TRIBE` summary has four metadata detail levels, controlled by the same `zz`, `zZ`,
`za`, and `zA` chords used for clan and family detail. From levels 1-3, `zZ` opens every
fold to level 4; at level 4, it closes every fold to level 1:

| Level | Name      | Tribe summary content                                                                                         |
| ----- | --------- | ------------------------------------------------------------------------------------------------------------- |
| 1     | Glance    | Header, compact numbered top-level roster, attention previews, and headings/counts for non-empty sections     |
| 2     | Triage    | Bounded previews for every represented section                                                                |
| 3     | Inspect   | Nested roster detail and grouped full section bodies, still with protective bounds                            |
| 4     | Forensics | Unbounded bodies, tracebacks, the richest member annotations, and all-time runtime statistics and percentiles |

The compact roster and its fixed numeric jump targets exist at all four levels. Number
keys jump to a top-level clan, family, workflow, or agent, expanding the required panel
and ancestor folds first. These metadata-member numbers are separate from ordinary
apostrophe entry hints, whose adaptive target keys may use two characters in a large
list.

Reply and slow-call presence enrichment is requested off-thread at every tribe level so
known-empty sections can remain absent. Full bodies still follow the level-specific
bounds above, and all-time runtime statistics remain level-4-only. When required
disk-backed content is not known yet, the document ends with one dim
`⋯ scanning member data…` tail; known-empty content produces no section or placeholder.
Section-level overrides inherit from the panel level and are cleared by a valid
panel-level cycle, `zZ` extreme toggle, or direct `z1`-`z4` selection.

Tribes are set or cleared with `N` (see [Agent Actions](#agent-actions)). When opening
the modal on an agent without a tribe the input is pre-seeded with `pinned` so a single
Enter promotes the agent into the standard "pinned" panel; that default makes tribe
removal discoverable too — opening the modal on an assigned agent and submitting an
empty string clears the tribe. The `tribe=<name>` keyword on `%id` assigns the tribe at
launch, and `#tribe:<name>` combines it with an automatic id; `sase agent tribe` manages
it from the CLI.

### Group Banners and Folding

In `STANDARD` mode, agents within each tribe side panel use either a two-tier or
three-tier banner hierarchy depending on whether any agent in the panel targets a Patch:

- **3-level layout** (panel contains at least one Patch-scoped agent): **project → Patch
  → name-root**. Project-scoped agents and agents with no `cl_name` fall into a
  synthetic `(no Patch)` bucket that sorts last.
- **2-level layout** (no Patch anywhere in the panel): **project → name-root**.

Banners are rendered between agent rows and carry a summary chip
(`N agents · K running · M failed`). Workflow children inherit grouping identity from
their parent agent so banners never appear between a parent and its workflow steps.
Optional name-root and dotted-prefix banners appear only when they group at least two
rows.

Labels such as L0, L1, and L2 describe a banner's nesting depth, not a shared fold
setting. Every emitted grouping banner has its own binary expanded/collapsed state, kept
separately for each tribe panel and grouping mode. Three independent folding layers can
therefore be visible at once:

| Layer             | What it controls                                         | Default keys                                                                                                                                                          |
| ----------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Grouping banner   | Project, Patch, date, status, and name buckets           | Repeated `H` collapses after scoped agent nodes/clans; `l` expands; `-` never sweeps banners                                                                          |
| Structural row    | Clan members, family members, and workflow descendants   | `H` retreats a selected workflow/family one level, then remaining group agent nodes, then group clans; `l` expands; `-` sweeps every open agent node and clan at once |
| Split-panel title | A whole tribe panel; collapsing requires multiple panels | `h` or `'` selects; `h` collapses; `l` expands; on an expanded panel `L` hints an agent-node/clan/banner fold to toggle                                               |

| Key | Action                                                                                                                                                                     |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `l` | Expand the selected collapsed grouping banner or structural row; on whole-panel focus, expand or enter the panel                                                           |
| `h` | Navigate outward; collapse selected expanded panel; from collapsed panel, select the last expanded panel if one exists                                                     |
| `L` | On an expanded selected panel, hint every visible agent-node/clan/banner fold to toggle expand/collapse; on a collapsed panel, no-op with the already-collapsed warning    |
| `H` | Collapse selected workflow/family one level, then remaining group agent nodes/clans/group, or hint a fold to collapse in the selected panel; compact expanded Tools detail |
| `=` | Isolate the focused tribe panel, or restore the pre-isolation layout; works from whole-panel focus or a row selection                                                      |
| `-` | Sweep every open agent node and clan in the focused panel closed in one press, or restore the last sweep; never touches grouping banners or the panel itself               |

Collapsed grouping banners at any depth are selectable rows; expanded banners remain
visible headings but are skipped by row navigation. When a collapsed banner is focused,
`l` expands only that banner and moves focus to the next visible child banner or first
agent row. When a banner is focused, `m` toggles marks for all top-level agents in that
group; workflow child rows are not marked independently by the banner shortcut. `x`
performs a bulk kill/dismiss on every top-level agent in that group (single confirmation
modal). Marked collapsed banners show `[✓]` when all covered top-level agents are marked
and `[~]` when only some are marked. Marks take priority over the group for bulk
actions, so a non-empty mark set always drives the bulk action regardless of banner
focus. When a fold change hides the previously focused agent, focus snaps to the nearest
visible ancestor banner so navigation context is never lost.

Clan and family rows add an agent-tree hierarchy inside those grouping banners. Their
trailing names are color-coded by kind without an additional icon. A clan is a
selectable synthetic container, never an agent, and ends in an orchid `<name>` after its
rolled-up status and member counts. A real multi-member family root remains a teal agent
row and ends in an azure `<name>`; ordinary agent annotations and lone plan proposers
with only their display-only planner child remain gold. Clan `@tribe` labels follow the
orchid name. A clan's outer fold is binary: from a collapsed clan row, press `l` once to
reveal its direct agents, family rows, and visible workflow rows. The clan row's fold
count and status chrome count those direct clan agent nodes once; nested family or
workflow members do not inflate them. To reveal descendants within a family or workflow,
move to that row and press `l` there; pressing `l` again on the clan row itself has no
effect. Lowercase `h` moves to the validated parent without changing fold state.
Sequential family members use `--<suffix>` names and run one after another. Killing or
dismissing a clan row cascades to the clan's live members; acting on one member leaves
its siblings alone. Direct clan members always sort by the clan-local status priority
Failed, Stopped, Running, Queued, Waiting, Done in every grouping mode; Starting shares
Running's rank. Launch recency orders only members in the same status bucket. A family
row moves as one unit with its follow-ups and workflow steps, preserving their adjacency
and internal order.

Clan rows aggregate member status using the same operational precedence: human-input
questions, pending plan review, failure, and running/starting states outrank queued
work; `QUEUED` then outranks `WAITING`, followed by an all-done result. Consequently, a
clan with queued work and ordinary waiters displays `QUEUED` unless a higher-priority
member state is present. Its count chip remains concrete and independent, so
`QUEUED [Q3 W6]` reports three runner-slot waiters and six dependency, bead, or time
waiters without merging the two categories.

The uppercase `H` ladder starts with the selected workflow or sequential-family agent
node when that agent node is still open. The first press retreats that agent node by
exactly one fold level. From a visible hidden step, that press hides hidden steps while
leaving ordinary descendants visible and re-anchors selection to the agent-node owner;
the next press then collapses that still-selected agent node. Clans stay binary and do
not take this two-level path. After the selected agent node is collapsed, later presses
continue through the existing group-scoped remaining-agent-node, selected-clan,
remaining-clans, structural-fallback, and grouping-banner ladder. If the grouping banner
that `H` would collapse next contains any open standalone workflow, agent, or
sequential-family sase agent, and the selection does not own an open workflow or family
fold, the next press drives every such remaining agent node directly to fully collapsed
while leaving the banner open. Once remaining agent nodes are saturated, a selection
inside an open canonical clan makes the next press collapse only that clan. A selected
descendant re-anchors to its visible clan container; selecting the container itself
preserves selection without writing new selection memory. With the collapsed container
still selected, the following press drives every remaining open canonical clan in the
group directly to collapsed. A grouping banner, already-collapsed agent node,
already-collapsed clan, or invalid clan owner falls through to that group-wide sweep
immediately. The footer advertises `H collapse workflow` or `H collapse family` while
the selected agent node is open, then `H collapse sase agents`, then `H collapse clan`,
then `H collapse clans`, and only then `H collapse group`. Equal group names in other
tribe panels are never affected; merged layout intentionally treats the merged panel as
one scope. Ambiguous or malformed clan owners are skipped without blocking valid
siblings.

Whole-panel focus gives `H` a hinted collapse instead of the group-scoped ladder,
because it has no selected row or grouping scope to walk. It enumerates every currently
visible expanded agent node, clan, and top-level grouping banner in the selected panel —
never an owner hidden behind a still-collapsed parent banner, since that owner isn't
emitted as a row at all until its parent is expanded — assigns each one an adaptive hint
key, and shows the chips in place of jump hints. Typing a hint fully collapses that one
fold; an already collapsed fold is never offered, so every hint does something. `H`
never expands and never collapses the panel itself, which stays lowercase `h`'s job. A
panel with no expanded folds warns without arming hint mode; an already collapsed panel
keeps the existing `Panel is already collapsed` warning. The footer shows the configured
`hooks_or_collapse_all` key as `collapse fold` whenever the selected panel has an
expanded agent node, clan, or top-level banner to hint. `L`'s hint mode uses the same
enumeration but is not restricted to collapsible targets, so it also offers currently
collapsed agent nodes, clans, and banners and toggles whichever one you pick.

Visual treatment: every row carries a fixed-width tier-guide gutter built from one `│  `
segment per ancestor L0/L1 banner (in the parent tier's dim accent — project blue or
Patch cooler accent), so nesting reads as a tree at a glance. L0 project / bucket
banners use a sky-blue `▌` left bar and a heavy `━` rule. Patch banners, `BY_DATE`
subgroups, and banners that own another dotted-prefix subgroup use a cooler `▎` bar and
lighter `─` rule. Leaf name-root and dotted-prefix banners use a `▸` branch glyph with a
teal label. Singleton name-root groups suppress their banner entirely to reduce visual
noise.

The currently-focused side-panel row is marked with a thick accent-colored left bar,
**bold** text, and a translucent accent tint applied to the row background. The tint is
intentionally light so per-token status colors (running cyan, failed red, waiting
yellow, etc.) remain readable through the highlight — the bar and bold weight do most of
the work of marking the selection.

After a kill or dismiss, focus re-anchors on the visually-next row (rather than the next
row in input order) so the selection always lands somewhere meaningful in the rendered
tree.

### Grouping Modes

Press `o` on the Agents tab to cycle the L0 grouping bucket through three modes, or `O`
to cycle it in reverse. The Agents tab shows a brief toast (`Grouping: by project` /
`by date` / `by status`) on each cycle:

| Mode        | L0 buckets                                                                    | Notes                                                                                                                                                                               |
| ----------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `STANDARD`  | Project (with optional Patch sub-level)                                       | The "by project" default. Uses the 2-/3-level layout described above.                                                                                                               |
| `BY_DATE`   | `Today` / `Yesterday` / `This Week` / `Earlier`                               | Date bucket at L0, then a date-aware L1 subgroup. Sorted newest-first within each bucket.                                                                                           |
| `BY_STATUS` | `Stopped` / `Failed` / `Running` / `Queued` / `Waiting` / `Done` / `Starting` | Bucketed by shared status semantics; status priority fixes bucket position. Standalone agent nodes precede name subgroups, with launch recency sorting units inside each partition. |

In `BY_DATE` mode, ACE chooses one L1 subgroup style from the L0 date bucket: one-hour
windows (`09:00`) for `Today` and `Yesterday`, calendar-day labels for `This Week`, and
Monday-start week ranges for `Earlier`. The time anchor is `stop_time` for terminal
agents and `start_time` otherwise. The same anchor selects the L0 date bucket, so an
agent that started Friday evening and finished Saturday morning renders under Saturday's
bucket, matching the finish timestamp on its row. Buckets and their subgroups sort
newest-first. Workflow children inherit the parent's anchor so they stay adjacent
regardless of their own start time, and agents with no usable timestamp fall into a
`(no time)` subgroup that sorts last.

In `BY_STATUS` mode the L0 banner is the status bucket and L1 is the name-root, with the
same singleton-suppression rule as `STANDARD`. Status priority fixes the bucket order:
Stopped, Failed, Running, Queued, Waiting, Done, Starting. Within each bucket,
standalone sase agents render before every visible name-root subgroup; `start_time`
sorts agent nodes newest-first inside the standalone partition and subgroup units
newest-first inside the subgroup partition. The same partitioning rule applies under a
name-root, where directly contained agent nodes precede visible dotted-prefix subgroups.
Units with no launch timestamp sort after timestamped units within their partition, with
structural names and input order providing deterministic tie-breakers. A family, clan,
or workflow subtree uses its outer/root agent's launch time and remains contiguous.
Inside a clan, direct members still use the clan-local Failed, Stopped,
Running/Starting, Queued, Waiting, Done priority described above, with launch recency
breaking same-status ties; that order intentionally differs from this L0 bucket order.
Family follow-ups and workflow steps remain adjacent to their direct-member anchor in
their established internal preorder, including any name-prefix banners. The `Starting`
bucket remains last and its transient rows remain hidden, so startup-only work does not
displace active rows during daemon or launch refreshes. Each mode keeps its own
per-group fold registry, so collapsing buckets in `BY_STATUS` doesn't affect the project
layout you had in `STANDARD`. `BY_STATUS` banners are prefixed with semantic glyphs
(`▲`, `✗`, `▶`, `…`, `⏳`, `✓`, `◐`) so the bucket title still leads visually.

The active grouping strategy is also surfaced in the Agents tab header via a
`[group: <label> (o)]` badge so the current session mode is always visible after the
cycle toast fades. After the first scan, the header starts with the visible sase-agent
total `N`. One standalone agent or one sequential family is one sase agent, regardless
of whether the family is folded. A rootless clan container contributes no sase agent
itself; each direct clan member contributes one, and a direct member that is a
sequential family still contributes only one. A hidden top-level `STARTING` agent
contributes one sase agent even though it is not selectable yet. Grouping mode, tribe
ownership, and fold state do not change this projection.

The sase-agent total is followed by an always-visible capacity chip in the form
`[R/L · Q queued]`: `R` is the global number of runner slots currently held — the same
occupancy the admission gate uses — `L` is the current effective `max_running_agents`
limit (temporary override first, configured value second), and `Q` counts every live
agent parked at the runner-slot admission gate, whether its threshold comes from that
effective cap or an authored `%wait(runners=N)`. A standalone agent holds one slot. A
serial family holds one slot for as long as any of its shells is live (root, serial
child, monitor proc shell, or post-handoff `--next` agent). Independently launched clan
members each hold one slot. Each live parallel family member holds its own slot. Roots
and parallel members wait at the gate; serial family members ride the family's slot and
do not appear in `Q`. Workflow Python/bash steps and axe Patch runners hold none of
these slots. The occupancy count `R` always renders green, so it reads as a plain count;
capacity pressure is carried by `L`, which escalates from dim through gold at half the
limit, orange at three quarters, and red once `R` reaches or passes it. A nonzero queue
count is cornflower blue.

An optional status strip follows in the form
`[S stopped · T starting · R running · W waiting · F failed · U unread · D done]`, with
numeric counts in place of the letters and zero-count metrics omitted. These buckets
classify the same sase agents as the leading total, using a sequential family's
normalized owner status instead of counting historical members separately. `stopped`
counts agents paused for plan approval, questions, or workflow human-input steps;
`starting` counts just-launched agents that have not yet surfaced as visible rows;
`running` excludes queued, waiting, failed, and stopped agents; `waiting` contains
genuinely blocked dependency, bead, and time waits, while the capacity chip's `queued`
count contains every live runner-slot waiter; `failed` is terminal failed work; `unread`
counts terminal sase agents that still need acknowledgement; and `done` is completed
visible work that has already been acknowledged. Nested family/clan member summaries
remain concrete. The position/navigation denominator is a separate count: rendered
selectable roots, where a clan container is one row and a hidden `STARTING` agent is
excluded. During startup the header renders `Agents: …` until the first agent scan has
loaded, avoiding a misleading zero-agent count. Each TUI launch starts in by-project
grouping; cycling only changes the current session.

**Queued** holds `QUEUED` agents that have cleared every dependency, bead, and time wait
and need only runner capacity, whether their threshold comes from the global cap or an
authored `%wait(runners=N)`. A queued row renders as `QUEUED #3/12`; an explicit runner
threshold keeps its arrow qualifier, such as `QUEUED #4/12 ▶7→0 p20`, so a drain barrier
cannot be mistaken for a fraction. Implicit-cap rows omit the repeated capacity suffix.
**Waiting** holds genuinely blocked but self-progressing agents — `WAITING` with a time
wait (`%wait(time=5m)`, `%wait(time=1430)`), a non-empty `waiting_for` dependency, or a
bead wait. **Stopped** keeps the strict "you need to act" semantics for plan approval,
questions, and workflow input.

### Agent Row Glyphs

To keep rows compact, agent statuses and types are rendered as one- or two-character
badges instead of verbose text:

| Glyph | Meaning                                              |
| ----- | ---------------------------------------------------- |
| `▶`   | RUNNING                                              |
| `✓`   | DONE                                                 |
| `✓P`  | PLAN DONE                                            |
| `▶P`  | PLAN APPROVED                                        |
| `★E`  | EPIC CREATED                                         |
| `✎`   | PLAN                                                 |
| `✗`   | FAILED                                               |
| `…`   | QUEUED                                               |
| `⏳`  | WAITING                                              |
| `?`   | QUESTION                                             |
| `↻`   | RETRYING (followed by attempt count, e.g. `↻2`)      |
| `≡`   | Workflow row (top-level)                             |
| `❑`   | Patch / Patch row (top-level)                        |
| `⚡`  | Autonomous (`%auto`) agent                           |
| `◌`   | Hidden agent (visible only when `.` toggles them in) |
| `⚙`   | Monitor shell (row label)                            |
| `⚙N`  | N running monitors in a family/clan subtree (amber)  |
| `⚙N`  | N finished monitors in a family/clan subtree (grey)  |

A monitor shell (a family member whose work is a supervised command, started with
`sase monitor start`) renders its own amber `⚙` glyph beside the bash/python step glyphs
below, with its configured label as the row title and a live elapsed suffix or
exit-code/timeout badge instead of the statuses above. Two extra badges mark a stalled
monitor handoff: a red `⚠` replaces the exit-code badge when a terminal monitor's
supervisor never reported a real exit code, and an amber `⚑` follows the row when its
`--next` follow-up was dropped or launched degraded — a monitor can finish cleanly and
still strand its follow-up. See [Monitors](monitors.md).

A monitor row nests under the agent that started it, not under a synthetic aggregate —
one gear-glyph row at the starter's depth plus one. It is revealed by its **agent
family's** fold rather than its starter's own: a collapsed family shows an amber `⚙N`
badge for its running monitors and a grey `⚙N` badge for its finished ones — the two
counts partition the subtree's monitors, with a monitor that has not reported a terminal
state counting as running — and counts every monitor in its collapsed ` ×N`, but renders
no monitor row, even when the family root itself is the starter. A single `l` on the
family container row reveals every member and monitor in that family in one step;
monitors are not deferred to a further "fully expanded" press the way hidden workflow
steps are. Selecting a monitor row and pressing `l` or `H` acts on that governing family
fold — `H` collapses the family and reanchors the cursor there — while `h` still walks
up to the monitor's starter.

A monitor has no LLM process to kill, so `x` on a selected **running** monitor row is
routed off the ordinary kill/dismiss path: it opens a `Stop Monitor` confirmation
(defaulting to **Keep running**) and, once confirmed, terminates the supervised command
through the same code path as `sase monitor stop`. As with the CLI, stopping never
launches the recorded `--next` follow-up agent. The stop itself runs as a tracked proc,
so a slow teardown does not block the TUI. `x` on a monitor row that has already settled
falls through to the normal dismiss behavior, and bulk scopes still win over the single
row: marks, a focused panel, and a focused group are all handled before ACE looks at
whether the selected row is a monitor.

Agents launched by `sase bead work` also show a gold `◆ <bead_id>` badge between the
status glyph and the tribe/name. A phase agent named `<epic_id>.<N>` displays that phase
bead ID; the final `<epic_id>.land` agent displays the parent epic bead ID; a standalone
task worker named `<task_id>` displays its task bead ID. Legacy plain `<epic_id>` land
agents keep the same badge. Legacy dismissed names keep the badge after their historical
date prefix is stripped. Modern phase and task rows use their explicit launch metadata
immediately; legacy bead-shaped names retain the deferred bead-store confirmation
fallback.

Each agent row also carries a per-provider emoji badge before the display name so the
LLM provider behind a row is readable at a glance without scanning the right-hand model
suffix:

| Badge | Provider          |
| ----- | ----------------- |
| 🎭    | Claude            |
| 🪐    | Antigravity (agy) |
| 🤖    | Codex             |
| 🐼    | Qwen              |
| 🐙    | OpenCode          |
| ♾️    | Muse Code (Meta)  |
| 🛰️    | Grok Build (xAI)  |

The same provider palette also colors the `<PROVIDER>(<model>)` suffix on the right edge
of the row — the provider name, the parentheses, and the model name each render in a
distinct shade from that provider's palette so multi-model fan-outs are easy to scan.
Providers without a dedicated palette (anything outside the table above) fall back to a
neutral purple palette and render no emoji badge.

Workflow child rows for `python` and `bash` steps render a leading `❯` glyph after the
`N/M` step number, styled with the matching step-type accent — bash amber, python green.
The glyph's presence is a stronger signal than the step-type color alone for colorblind
users and for rapid scanning; color still carries the bash/python distinction. Agent,
parallel, and `prompt_part` step rows are left unchanged — agent rows already carry a
meaningful display name, parallel rows fan out into structural children, and
`prompt_part` rows are invisible by default.

The right-hand edge of each row carries a runtime suffix
(`<start-timestamp> · <elapsed>`) right-aligned within the panel. Active rows that have
actually started include a `🏃‍♂️` marker before the ticking elapsed duration; unread
completed rows use a `✅` marker in the same suffix slot, or `❌` when the agent
finished in a `FAILED` state; and user-paused rows (`PLAN`, `QUESTION`, `WAITING INPUT`)
use a `✋` marker while waiting for a human response. Pre-run `WAITING` and `QUEUED`
rows with no `BEGIN` time hide the suffix so admission waits do not look like live
runtime. For finished agents, the start-timestamp half is rendered as a humanized
`(date_prefix, time)` pair sized to fit the existing 15-cell slot:

- **Same day**: `HH:MM:SS`
- **Prior day, same year**: `Mon DD HH:MM` (drops seconds — they're noise once a row
  finished hours ago)
- **Different year**: `Mon DD 'YY` (date only)

The elapsed duration starts at `BEGIN` when a row recorded wait-before-run metadata,
otherwise at the row start time. For slot-participating user agents, `BEGIN` is runner
admission and includes primary and linked-workspace preparation in the active runtime.
Completed `DONE` / `PLAN DONE` / `TALE DONE` workflow rows use the terminal agent stop
time when one exists; plan-step rows that finish without a subprocess stop time anchor
to the latest recorded plan submission time so completed planning rows do not keep
ticking. `PLAN APPROVED` rows with a running follow-up show active elapsed time for the
planner segment plus the coder segment, excluding the idle approval gap between plan
submission and code launch. The date prefix uses a softer `dim #8787AF` while the time
half keeps the standard `#8787AF`, giving the column internal hierarchy without
inflating the palette. Statuses not in the table fall back to `(STATUS)` text for
forwards compatibility.

### Agent Search

Press `,/` (leader mode) on the Agents tab to open the query editor. The query language
is a **structured Boolean expression** — parallel to the Patch query language but with a
property-key allowlist tailored to agents. Bare words are substring-matched against an
agent's `cl_name`, `display_name`, `agent_name`, and `status`, plus its **xprompt, live
reply/response, chat transcript, and prior attempt replies**.

Property keys (closed allowlist):

| Key                                                    | Form                                | Matching behavior                                        |
| ------------------------------------------------------ | ----------------------------------- | -------------------------------------------------------- |
| `status`, `cl`, `project`, `name`, `model`, `provider` | `key:value`                         | Case-insensitive substring; e.g. `status:queued`.        |
| `text`                                                 | `text:value`                        | Case-insensitive substring over the full text corpus.    |
| `tribe`                                                | `tribe:value` or `tribe:`           | Exact, case-insensitive; empty means any assigned tribe. |
| `type`                                                 | `type:workflow`, `type:run`         | `type:running` is an alias for `type:run`.               |
| `source`                                               | `source:axe`, `source:manual`       | Axe workflow/step or manually launched agent.            |
| `needs`                                                | `needs:input`                       | Question/waiting-input or approved/working plan handoff. |
| `pinned`, `hidden`, `attention`                        | `key:true` / `key:false`            | Boolean properties; `pinned:true` equals `tribe:pinned`. |
| `age`                                                  | `age<5m`, `age>=2h`, `age:1d`, etc. | `:` is sugar for `>=`. Suffixes: `s`/`m`/`h`/`d`.        |

Boolean operators: juxtaposition is implicit `AND`; explicit `AND`, `OR`, and `NOT`
(with parentheses) are honored. Precedence is `NOT > AND > OR`. The help modal carries
an **Agent Query Syntax** section listing the same grammar.

Parse failures are non-fatal: the loader falls back to "no filter" for that render and
surfaces a transient toast; the query-edit modal re-validates on Apply, keeping itself
open and rendering the error inline (in red) on failure.

Transcript files are read lazily (only while a query is active) and cached by
`(path, mtime_ns)` so auto-refresh stays cheap. Per-file reads are capped at 512 KB;
missing or unreadable files are skipped silently. Parsed ASTs are also cached by raw
query string so re-renders skip the parse.

### Leader Mode (`,` prefix)

Leader mode is available on every tab. In the Agents tab it also exposes layout and
notification shortcuts for the currently loaded agent list; global entries such as `,m`
and `,U` behave the same from other tabs. Unread-completed actions operate on terminal
rows that are loaded in the Agents tab; `,j` can reveal a direct member hidden by a
collapsed clan. Help is not a leader command: press the app-level `?` to open the Help
modal.

| Key        | Action                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------- |
| `,,`       | Repeat the last leader command                                                                    |
| `,/`       | Edit the Agents query                                                                             |
| `,h`       | Run agent from home prompt context; bare prompts default to `#git:home`                           |
| `,g`       | Toggle between tribe-split panels and one merged agent panel                                      |
| `,j`       | Jump to the next unread completed agent, revealing a collapsed clan when needed, and mark it read |
| `,J`       | Jump to the next visible stopped/terminal agent, newest first, without changing unread state      |
| `,y`       | Refresh the Agents tab from full artifact history                                                 |
| `,u`       | Mark all loaded unread completed agents as read                                                   |
| `,n`       | Jump to agent notification (plan or question; auto-unhides if needed)                             |
| `,m`       | Open Launch Control (view/manage model aliases; see [Launch Control](#launch-control))            |
| `,U`       | Update SASE/agent CLIs and import cached agent hoods                                              |
| `,B`       | Capture an Agents-tab reproduction bundle for debugging row disappearance or duplication          |
| `,T`       | Toggle continuous Agents-tab repro invariant checks and auto-capture on violation                 |
| `,r`       | Revert focused or marked agent commits, including recorded linked repos                           |
| `,x`       | Kill focused or marked agent(s) and edit their prompt(s)                                          |
| `,<space>` | Run agent from current agent's PR (skips selection)                                               |
| `,.`       | Open prompt history modal                                                                         |
| `,Ctrl+G`  | Open prompt history and edit the newest entry immediately                                         |
| `,>`       | Open prompt history modal with cancelled prompts visible                                          |
| `,@`       | Open the prompt stash picker without auto-restoring a lone entry                                  |

Here, "stopped" means a dismissable terminal row such as `DONE`, `FAILED`, `PLAN DONE`,
`TALE DONE`, `PLAN REJECTED`, `PLAN COMMITTED`, or `EPIC CREATED`; it is separate from
the Agents header's "stopped" attention bucket for rows paused on user action.

The CLI equivalent of `,x` without the edit pause is `sase agent restart NAME`: it stops
the named agent and immediately relaunches the stored prompt under the same name.

If any agents are marked, `,x` acts on that marked set instead of the focused row. Stale
marks are ignored; if any remaining marked agent has no recoverable prompt, ACE warns
and leaves the set untouched. After confirmation, ACE kills or dismisses the marked
agents and opens a prompt stack with one editable pane per original prompt in mark
order. Embedded `---` inside an individual agent prompt stays inside that agent's pane.

Each recovered prompt is marked for forced name reuse so the relaunch keeps the original
agent's name instead of claiming `<name>1`. The marker is a `!` on the `%id` directive,
and its exact shape follows the prompt:

| Original prompt          | Rewritten as                      |
| ------------------------ | --------------------------------- |
| `%id:foo`                | `%id:!foo`                        |
| `%id(foo)`               | `%id(!foo)`                       |
| a clan member's prompt   | `%id(!<suffix>, clan=<clan>)`     |
| a family member's prompt | `%id(!<suffix>, family=<family>)` |
| no `%id` directive       | unchanged — a fresh name is used  |

Note that the clan and family forms carry the member's trailing `<suffix>` — the part
after the `<clan>.` prefix, or the family role segment — not the full agent name; the
membership keyword supplies the rest. An existing `bead=` value is carried across, and a
standalone `clan:` declaration is dropped in favor of the `clan=` keyword. The last row
is not a failure: a prompt that never named its agent has nothing to reuse, so it simply
relaunches under a newly allocated name.

ACE is the surface that confirms that reuse, and it carries the authorization through to
the launch, so no second confirmation is asked for. Forced reuse cannot be combined with
alt/fan-out directives in one segment; such a prompt is rejected with an explanatory
error and preserved in prompt history, so you can reopen it from `,.` and split the
launch.

Press `,r` on a `DONE` or `FAILED` agent to preview commits attributed to that agent
before creating git revert commits. For plan/follow-up families, ACE reverts the family
scope when the row carries family metadata; otherwise it reverts the focused agent name.
The preview includes the primary workspace plus recorded `linked_repos` metadata entries
that still point at an existing workspace directory; never-opened linked workspaces are
not part of this action. Each repository is checked before execution, and a dirty or
non-git linked repo is reported and skipped while clean repositories can still be
reverted. Successful execution creates one revert commit per repository, pushes when a
remote tracking branch is available, and writes `revert_result.json` beside the agent
artifacts.

When agents are marked, `,r` previews the combined commit set for the marked `DONE` /
`FAILED` rows. Marked agents must come from the same primary workspace. The bulk path
still groups work by repository, deduplicates overlapping family matches, skips marked
rows with no matching commits, and reports partial linked-repo failures instead of
hiding them.

### Agents Tab Reproduction Bundles

Agents-tab reproduction bundles capture the loader/apply sequence that determines which
rows are visible. Use them when the Agents tab briefly drops historical rows, re-adds
them, or shows duplicate workflow parents.

When you see one of these bugs in a live ACE session, switch to the Agents tab and press
`,B` before refreshing again. ACE writes a commit-safe bundle to
`~/.sase/repros/<timestamp>-manual-.../agents_tab_repro.json` and shows a toast with the
path. "Commit-safe" means local names and paths are redacted, and prompt, response,
chat, and diff bodies are omitted. The bundle keeps the row identities, loader state,
app projection state, screen text, and an SVG screenshot needed to replay the row-list
behavior.

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

Add `--write-artifacts /tmp/sase-agents-tab-repro-artifacts` to write one `.txt` screen
dump and one `.svg` screenshot per replay step. The replay JSON lists those paths in
`screen_paths` and `screenshot_paths`.

Use out-of-band capture only when you need a filesystem baseline and did not have the
live TUI capture running:

```bash
sase repro capture agents-tab --output /tmp/sase-agents-tab-capture --commit-safe --json
```

Out-of-band capture is labeled `capture_mode=out_of_band` because it loads the current
filesystem state and cannot reconstruct transient refreshes that already passed through
the running TUI. The replay harness is scoped to the known Agents-tab
disappearance/reappearance and duplicate-parent bug class; it is not a general proof for
arbitrary rendering races.

For continuous diagnosis, press `,T` on the Agents tab to enable invariant checks after
each load/apply cycle. On the first violation in a burst, ACE auto-captures one bundle
under `~/.sase/repros/<timestamp>-auto-.../` and shows a warning toast. It does not
write a new bundle every refresh while the same violation remains active.

### Bang Mode (`!` prefix)

| Key  | Action                               |
| ---- | ------------------------------------ |
| `!!` | Run background command               |
| `!x` | Start / stop axe (or select process) |

### Copy Mode (`%` prefix)

Press `%` to open the **Copy as…** palette for the focused agent. It supports mouse
selection, arrows or `j`/`k` plus `Enter`, and every configured direct accelerator
below. `q`/`Esc` cancels unless that key is itself configured for a copy target, in
which case the target wins.

| Key  | Action                                                                                      |
| ---- | ------------------------------------------------------------------------------------------- |
| `%c` | Copy chat file path                                                                         |
| `%E` | Copy file path                                                                              |
| `%@` | Copy the focused concrete agent's durable global `@agent:` reference                        |
| `%n` | Copy the focused agent's `agent_name` (falls back to `display_name`; toast indicates which) |
| `%p` | Copy agent prompt                                                                           |
| `%s` | Copy sase ace snapshot                                                                      |

## Keybindings: Axe Tab

### Sidebar Row Taxonomy

The Axe sidebar renders three row types so the operational tree reads at a glance:

- **Lumberjack** rows are top-level sections with a solid left accent bar (`▌`) in the
  lumberjack hue, a `[*]` / `[!]` / `[·]` running/error/idle marker, the lumberjack
  name, and an optional compact `Nc / Ne` cycles/errors chip at the end.
- **Chop** rows are child rows indented under their parent with a `  └─` tree connector,
  a per-run status icon (`✓` success, `!` failure/timeout, `?` missing script, `●`
  running, `*` agent-launched, `·` no runs), and the chop name in a dim-gold child hue.
  Disabled chops remain visible with a quiet `disabled` chip but cannot be run manually.
- **Background command** rows (run via `!!`) live below the lumberjack tree, separated
  by a dim divider line when both groups are present, and use a distinct command/slot
  badge so they cannot be mistaken for scheduled AXE work.

### Description Panel

The right-hand dashboard keeps the selected lumberjack or chop description in a
dedicated panel between the status line and scrolling output. Every row of the panel
carries a solid left accent gutter (`▌ `) in the row's own hue, so the block reads as a
blockquote and stays visually distinct from the output pane below. Generated `for_each`
chop instances also show their target key on the summary row. The panel stays fixed
while output scrolls and disappears for background-command and empty AXE views.

The panel has two states, and `d` toggles between them for the rest of the session. The
summary row ends with a `▸ d` / `▾ d` disclosure hint whenever there is a body to reveal
and the row has room for it:

Collapsed — one row, ellipsized at the pane width:

```
▌ Complete finished hooks and start stale ones, with zombie detection            ▸ d
```

Expanded — the summary, a blank gutter row, and the reflowed body:

```
▌ Complete finished hooks and start stale ones, with zombie detection            ▾ d
▌
▌ Scans every Patch matching the axe query, completes hooks whose runner exited, and
▌ starts the next stale hook when a runner slot is free.
▌
▌ • Honors max_hook_runners; a full slot table defers work to the next tick rather than
▌   queueing.
▌ • Hooks still running past zombie_timeout_seconds are marked ZOMBIE and stop holding a slot.
```

The body is reflowed rather than replayed: blank lines separate blocks, a block whose
first line starts with `-`, `*`, or `•` renders as a hanging-indent bullet list, and
every other block is joined into one paragraph and re-wrapped to the current pane width.
See [Description Grammar](axe.md#description-grammar) for the authored form.

`ace.axe_description_expanded` (default `true`) sets the state each `sase ace` session
starts in. `d` flips an in-memory session state and repaints from cached snapshot data —
it never reloads config, reads disk, or writes the toggle back.

An expanded panel never crowds out the chop output it exists to explain. The dashboard
budgets `max(3, min(16, floor(pane_height * 0.45)))` rows for the panel, falling back to
10 rows before its height is known. If the rendered block exceeds that budget, the last
row becomes a dim `… +N more · e` marker: nothing is silently dropped, and `e` opens the
AXE entry editor, whose first field is the full description in a multi-line text area.

Because `d` belongs to the Axe tab, `show_diff` is scoped to the Patches sub-tab.
Pressing `d` outside Patches no longer opens a diff for an unrelated Patch.

### Dynamic Sidebar Width and No-Wrap Rows

Every sidebar row is rendered as single-line Rich `Text` with `no_wrap=True` and
`overflow="ellipsis"`. After each refresh the widget computes the widest formatted row
and emits a `WidthChanged` message; the AXE container resizes between a 35-cell minimum
and an 80-cell maximum, clamped further so the right-hand dashboard always keeps at
least 40 cells. On terminals too narrow to fit a label even at the clamped width, the
row ellipsizes rather than wrapping onto a second line.

### Controlled-Output Highlighting and ANSI Fallback

Output in the dashboard right panel uses a semantic highlighter for sources whose shape
is controlled by sase, and falls back to ANSI rendering for everything else:

- **Lumberjack aggregate logs** (`[YYYY-MM-DD HH:MM:SS] [lumberjack] message`) get
  timestamp, lumberjack name, status words (`success`, `failure`, `timeout`, `running`,
  `error`, …), PIDs, durations, exit codes, and counts colored by severity and
  consistent with the sidebar taxonomy.
- **Controlled chop output** — runner lifecycle lines such as
  `Launched proposal 1 as <name> (PID <pid>)` use the same status-word, PID, duration,
  and count highlighting as other lumberjack messages.
- **External chop scripts** and **background command output** are arbitrary text and
  stay on the ANSI fallback (`Text.from_ansi`) with the existing capping and tail-biased
  caching behavior.

Render cache slots are keyed on `(source_id, source_type)` so the semantic and ANSI
paths cannot collide for the same numerical identity.

### Chop Result Documents

Selecting a recorded chop run composes three sections inside the existing scroll region:

1. **RESULT** is always present and is derived entirely from the cached run entry. It
   includes the status, structured summary and reason, counters, proposal and launch
   rosters, evidence, dry-run/source markers, and any error or traceback.
2. A chop-authored structured **report** follows when the result document supplies one.
   Semantic tones map to the AXE palette, tables elide cells at wide widths and stack at
   widths below 60 cells, and all chop strings are rendered literally rather than parsed
   as Rich markup or ANSI.
3. **OUTPUT** contains the existing ANSI-rendered log tail and retains the waiting,
   failure, reason, and no-output fallbacks for runs with an empty log.

The card and report are cached by run identity, lifecycle state, completion timestamp,
and rendered width. They paint only from the in-memory chop snapshot; navigation does
not read, stat, or glob the run files. Auto-scroll continues to follow active `running`
and `launched` output, but terminal runs open at the RESULT card so the report is not
scrolled off screen on selection.

### Navigation

| Key                       | Action                                                                        |
| ------------------------- | ----------------------------------------------------------------------------- |
| `j` / `k`                 | Move to next / previous sidebar row (lumberjack, chop, or background command) |
| `Ctrl+N` / `Ctrl+P`       | Page through the focused chop's run history (newer / older)                   |
| `'`                       | Jump to a current-tab entry by adaptive hint                                  |
| `Ctrl+O` / `Ctrl+Shift+O` | Walk backward / forward through the current-tab jump stack                    |
| `` ` ``                   | Jump to an entry across all tabs                                              |
| `g`                       | Scroll to top                                                                 |
| `G`                       | Scroll to bottom (pins auto-scroll)                                           |

### Commands

| Key | Action                                                                                               |
| --- | ---------------------------------------------------------------------------------------------------- |
| `a` | Add a lumberjack, or add a chop under the selected lumberjack                                        |
| `d` | Expand / collapse the [description panel](#description-panel) for this session                       |
| `e` | Edit the selected lumberjack or chop configuration                                                   |
| `E` | Open the selected recorded chop output in `$EDITOR`                                                  |
| `+` | Run agent                                                                                            |
| `r` | Run an enabled selected chop manually, or re-run the focused completed background command (`!!`) row |
| `x` | Start / stop axe (or kill the focused background command)                                            |
| `X` | Clear output                                                                                         |
| `/` | Edit the current Axe query                                                                           |

The `a` flow discovers installed `sase_chop_*` executables and also accepts a custom
executable. Both add and edit open a single-page property sheet showing every schema
field, including unset and inherited fields. The active row's detail dock shows its
schema help plus effective, target-layer, and inherited values. Edits remain sparse: an
inherited field is not copied into the selected writable scope unless you touch it.
Compound and advanced fields expand in place as raw YAML, with inherit/reset available
for removing a target-layer override.

Editing a generated chop row edits its immutable base chop and warns that every
generated instance is affected. Before writing, the panel shows an exact effective
before/after preview plus a source-file diff. When AXE is running, the preview makes
restart explicit: save and restart AXE to reconcile the daemon immediately, or save only
and leave the current daemon configuration active until the next restart. `E` remains
reserved for opening recorded chop output.

#### AXE Property Sheet

The panel opens existing entries in browse mode, with no editor focused, so property
navigation works immediately. A new entry opens in cell mode on its first required
property.

| Browse key            | Action                                                         |
| --------------------- | -------------------------------------------------------------- |
| `j` / `k` / `↑` / `↓` | Move to the next / previous property                           |
| `g` / `G`             | Move to the first / last property                              |
| `Enter` / `i`         | Edit the active value in place; toggle a boolean               |
| `Space`               | Toggle a boolean or cycle an enum forward                      |
| `h` / `l` / `←` / `→` | Cycle an enum backward / forward                               |
| `Ctrl+R`              | Mark inherit/reset; press again to restore the original value  |
| `1`…`9` / `Ctrl+T`    | Select a numbered writable scope / cycle scopes                |
| `Ctrl+S`              | Build the validation and source-diff preview                   |
| `Ctrl+L`              | Reload after a stale-write conflict while preserving the draft |
| `q`                   | Close the panel directly and discard unsaved edits             |
| `Esc`                 | Close the panel                                                |

| Cell key                       | Action                                                             |
| ------------------------------ | ------------------------------------------------------------------ |
| `Enter`                        | Commit a single-line value; insert a newline in a multi-line value |
| `Esc`                          | Leave INSERT for NORMAL, then commit and return to browse mode     |
| `q`                            | Type `q` in INSERT; close the panel directly from NORMAL mode      |
| `Tab` / `Shift+Tab`            | Commit and edit the next / previous property                       |
| Vim keys                       | Edit through the standard `VimTextArea` layer                      |
| `Ctrl+S` / `Ctrl+R` / `Ctrl+T` | Preview, inherit/reset, or cycle scope while the editor is focused |

| Preview key                     | Action                                  |
| ------------------------------- | --------------------------------------- |
| `↑` / `↓` / `Ctrl+D` / `Ctrl+U` | Scroll by line or page                  |
| `g` / `G`                       | Scroll to the top / bottom              |
| `Enter`                         | Save, restarting AXE when it is running |
| `Ctrl+O`                        | Save without restarting AXE             |
| `q`                             | Close the panel directly                |
| `Esc`                           | Return to the property sheet            |

### Leader Mode (`,` prefix)

Help is not a leader command: press the app-level `?` on any tab to open the Help modal.

| Key       | Action                                                                                 |
| --------- | -------------------------------------------------------------------------------------- |
| `,,`      | Repeat the last leader command                                                         |
| `,h`      | Run agent from home prompt context; bare prompts default to `#git:home`                |
| `,m`      | Open Launch Control (view/manage model aliases; see [Launch Control](#launch-control)) |
| `,U`      | Update SASE/agent CLIs and import cached agent hoods                                   |
| `,R`      | Show runners info                                                                      |
| `,.`      | Open prompt history modal                                                              |
| `,Ctrl+G` | Open prompt history and edit the newest entry immediately                              |
| `,>`      | Open prompt history modal with cancelled prompts visible                               |
| `,@`      | Open the prompt stash picker without auto-restoring a lone entry                       |

### Bang Mode (`!` prefix)

| Key  | Action                               |
| ---- | ------------------------------------ |
| `!!` | Run background command               |
| `!x` | Start / stop axe (or select process) |

### Copy Mode (`%` prefix)

Press `%` to open the **Copy as…** palette for the selected AXE row. Choose with the
mouse, arrows or `j`/`k` plus `Enter`, or use a configured direct accelerator. `q`/`Esc`
cancels, with configured target keys taking precedence.

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

`/` is the app-level query key on every Artifacts pane. On Patches and Stitches it
focuses a filter row that is always on screen; on Beads, provider document panes, and
Files it opens an inline filter bar that is only visible while you are editing. Each of
those panes also accepts a local `f` for the same thing. Agents reserves bare `/` for
forward inline metadata search, so its structured query editor uses the independent `,/`
leader chord instead. Help is the app-level `?` on every tab.

| Context                 | Default query key  |
| ----------------------- | ------------------ |
| Patches                 | `/` (or local `f`) |
| Stitches                | `/` (or local `f`) |
| Beads                   | `/` (or local `f`) |
| Provider documents      | `/` (or local `f`) |
| Files                   | `/` (or local `f`) |
| Agents structured query | `,/`               |

The Axe tab has no query editor. Its `?` help modal and the command palette both still
offer "Edit search query" there, but the action currently does nothing on Axe; use the
tab's own filtering and navigation keys instead.

To save a query, prefix with `#`:

- `#3 "myproject"` -- save to slot 3
- `# "myproject"` -- save to next available slot
- `#3` (no query) -- delete slot 3

On Patches these commands run inside the inline filter and leave both the active query
and editor session in place.

### Saved Queries

On the Artifacts tab, press `0` followed by a slot digit (`1`-`9`, then `0` again for
slot 0) to load that saved Patches query directly -- e.g. `02` loads slot 2. This works
from any Artifacts sub-tab, not just Patches, and always lands on the Patches sub-tab.
`Esc` or any other non-digit key after `0` cancels without changing the query. Bare
digits still select the corresponding visible Artifacts sub-tab; the saved-query slot
keys live behind the `0` prefix so the two never collide.

Press `*` on the Patches sub-tab to open the saved-query chooser instead. Press a
populated slot (`1`–`9`, then `0`), move with `j`/`k` or the arrow keys and press
`Enter`, or click a row. `q`/`Esc` closes the chooser without changing the query. The
chooser shows the saved query text and marks the active query; an empty chooser also
repeats the save syntax. The chooser itself is unavailable from Agents, Axe, Stitches,
Beads, and Plans.

### Query History

| Key | Action                                |
| --- | ------------------------------------- |
| `^` | Navigate to previous query in history |
| `_` | Navigate to next query in history     |

Query history is available on the Patches sub-tab and tracks queries as you switch
between them.

See [`docs/query_language.md`](query_language.md) for the full query syntax reference,
including boolean expressions, status shorthands, property filters, and searchable
fields.

## Global Keybindings

These work on all tabs:

| Key                 | Action                                                                                                                                                   |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Tab` / `Shift+Tab` | Switch between Agents, Artifacts, and Axe tabs                                                                                                           |
| `#`                 | Open SASE Admin Center home (repeat on home to resume the last section); inside a working section, jump to the alternate section (repeat to toggle back) |
| `.`                 | Artifacts: collapse/expand the relations panel; Agents: show/hide non-run agents; Axe: show/hide axe commands                                            |
| `:` / `;`           | Open the context-aware [Command Palette](#command-palette)                                                                                               |
| `i`                 | Show notifications inbox                                                                                                                                 |
| `Ctrl+G`            | Open the agent editor pre-filled with the most recent VCS xprompt prefix                                                                                 |
| `Ctrl+L`            | Dismiss all currently-visible toast notifications                                                                                                        |
| `@`                 | Open the stashed-prompt restore picker                                                                                                                   |
| `Q`                 | Open the quit / restart menu                                                                                                                             |
| `R`                 | Refresh current tab                                                                                                                                      |
| `q`                 | Quit                                                                                                                                                     |
| `?`                 | Show help modal                                                                                                                                          |

The generic **Open SASE Admin Center** action and the first `#` always open a
lightweight landing page without mounting a working pane. Press `#` again while home is
visible to resume the last section that was successfully active. With no prior visit,
the repeated key stays on home and loads nothing. Inside a working section, the same key
takes on a second meaning: it jumps to the section you were in immediately before the
current one, and pressing it again toggles back — exactly two sections remembered, like
a two-slot alternate. A color-coded, clickable footer along the bottom of the working
section names the jump target (or explains that none exists yet). The numbered strip
remains clickable, `Tab` enters Config, and `Shift+Tab` enters XPrompts. Each working
pane and its data are loaded only on first entry, then cached while the modal remains
open. Command-palette actions such as **Open logs panel**, **Open procs panel**, and
**Open statistics**, plus update shortcuts and indicators, enter their requested pane
directly and make a successful entry the next resume target. Closing from home does not
clear an older target.

Both the top-level resume target and the alternate are persisted machine-locally and
survive across ACE process restarts. Within one running ACE process, closing and
reopening Admin Center also remembers each selectable pane's last logical entry by
stable identity, plus the minimal scope or sub-tab needed to show it again. Filters,
marks, scroll position, loaded data, pane instances, Statistics controls, and other
pane-local state still end with the modal. If `ace.keymaps.app.open_config_center` is
rebound, repeat that configured key instead; the footer and landing page display the
effective binding and destination.

Inside every working section, `'` is an Admin Center-wide entry-jump key: it paints
adaptive hints over that section's selectable rows using the same hint alphabet
described under
[Navigation in Stitches, Beads, Provider Documents, and Files](#navigation-in-stitches-beads-provider-documents-and-files),
a hint character moves the selection there, `'` again returns to the previous position
(or the first hint with an empty back stack), and `Esc` cancels. Each working section's
own keybindings table names its jump targets; two are deliberate exceptions. The
Statistics tab has no row cursor, so `'` there arms the same numbered-view selection the
`0` prefix already arms, using the visible strip numbers as hints. The Updates tab's
Core sub-tab has no list at all, so `'` is a silent no-op there while Plugins and Agent
CLIs jump normally.

### Quit / Restart Menu

Pressing `Q` opens the **quit / restart menu**. When procs are still running, the menu
warns inline with the count that leaving will stop (`N procs will be stopped`), and it
offers three actions:

- `1` / `s` — quit ACE and stop the axe daemon
- `2` / `r` — restart the TUI, leaving axe running
- `3` / `a` — restart the TUI and restart axe

Press `esc` (or `q`) to cancel and return to the TUI.

A plain `q` quits ACE directly. When procs are still running, `q` first shows a
confirmation dialog listing the active procs and asks whether to kill them and quit;
declining returns to the TUI.

## Command Palette

Press `:` or `;` from any tab to open the **Command Palette** — a context-aware modal
listing every keymapped action that is currently runnable. The palette is the discovery
surface for the TUI: rather than memorizing every chord, you can search by command
label, key sequence (e.g. `%n`, `,A`, `zc`), category, or alias.

**Behavior:**

- Only commands applicable to the current tab and selected entry are shown by default.
  For example, PR diff appears only when a PR is selected; AXE start/stop appears only
  on the AXE tab; agent-specific actions appear only when an agent row (not a group
  banner) is focused.
- Each row shows the keybinding, the command label, and a category badge such as
  `Navigation`, `PR Actions`, `Agent Actions`, `Copy`, or `Leader`.
- A title-bar badge (`Agents`, `Artifacts`, or `AXE`) reflects the current tab.

**Keybindings inside the palette:**

| Key                 | Action                                       |
| ------------------- | -------------------------------------------- |
| `Type`              | Filter commands (case-insensitive substring) |
| `↑` / `↓`           | Move highlight                               |
| `Ctrl+P` / `Ctrl+N` | Move highlight                               |
| `Enter`             | Run the highlighted command                  |
| `Esc`               | Close without running anything               |

The palette delegates execution to the same handlers that the keybindings use, so
behavior matches pressing the chord directly. Selecting a built-in mode subcommand (e.g.
`%n` to copy an agent name) runs the action without forcing you through the transient
prefix mode. Custom modes defined in `sase.yml` are also represented per-command.

The `:` / `;` binding follows your configured keymap. To rebind it, set
`ace.keymaps.app.open_command_palette` in `~/.config/sase/sase.yml`; comma-separated
keys in that setting are treated as alternate bindings for the same action.

## Projects Tab

Open the SASE Admin Center with `#` and switch to the **Projects** tab with `3`, `Tab` /
`Shift+Tab`, or the main tab strip. The tab contains a second clickable strip:
**Projects · Repos · Workspaces**. `[` / `]` cycle these sub-tabs while `Tab` /
`Shift+Tab` continue switching the main Admin Center tabs.

The **Projects** sub-tab lists true, non-system projects only, with enabled projects
first and disabled projects still visible. Here, "true project" means a project backed
by its own main ProjectSpec, rather than an internal linked-repo backing record; a true
project can be enabled or disabled. Rows show the display/canonical name, VCS kind
(`git` or `gh`), lifecycle state, active claims, workspace/repo counts, and warnings.
Telemetry-only directories and linked-repo backing records cannot appear.

| Key       | Action                                                              |
| --------- | ------------------------------------------------------------------- |
| `j` / `k` | Move selection                                                      |
| `'`       | Jump to a row via adaptive hints, within the active sub-tab only    |
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

When one or more projects are marked, `a`, `d`, and `Ctrl+D` target the marked set
instead of only the highlighted row. Successful lifecycle changes clear the affected
marks; blocked or failed rows stay marked so you can inspect or retry them. Disabling
uses the same locked mutation path as `sase project disable`; live `RUNNING` claims or
artifact markers block it unless the `F` force retry is intentional.

The **Repos** sub-tab inventories every known primary, sidecar, linked, and opened
external repo for enabled projects by default. Rows show owning project, checkout
presence, and path; details include source, description, `auto_clone`, environment name,
and SDD storage mode. The **Workspaces** sub-tab joins every registry entry with its
claim, PID liveness, pin, last-used time, TTL staleness, and checkout presence. Missing
checkouts point to `sase workspace repair`, and dead claims are warning-styled. Both
sub-tabs load off-thread and show cached rows during refresh.

Press `p` on either inventory to choose all projects, an enabled project (`●`), or a
disabled project (`○`). Explicitly selecting a disabled project is how its
repos/workspaces become visible. `/` then filters within that project scope; `Esc`
clears the scope. The picker is filterable by display name, canonical key, or state and
shows repo/workspace counts for each project.

`e` suspends ACE, opens the selected ProjectSpec in `$EDITOR` (falling back to `nvim`),
holds the ProjectSpec edit lock for the editor session, then reloads project records. In
this panel, `Ctrl+D` asks for confirmation before deleting the entire SASE project
directory: ProjectSpecs, project-local config, artifacts, and related state under
`~/.sase/projects/<project>/`. Deletion is refused while the project still has `RUNNING`
claims or live artifact markers. It does not delete workspace checkouts, and
system-managed projects such as `home` are excluded from the panel.

## Statistics Tab

Open the SASE Admin Center with `#`, then press `4` or switch to **Statistics**. Its
eight sub-tabs summarize overview, runners, projects, providers, agent activity, xprompt
usage, plan/question activity, and performance for the selected time range. The strip is
numbered **1 Overview · 2 Runners · 3 Projects · 4 Providers · 5 Activity · 6 XPrompts ·
7 Plans & Questions · 8 Perf**; press `0` and then that digit to jump straight to a
view. The Admin Center-wide `'` entry-jump key arms this same numbered-view selection
instead of painting row hints — Statistics has no row cursor, so the already visible
strip numbers act as its jump hints; `Esc` or any non-digit cancels. Use `[` / `]` to
move between views, `t` / `T` to cycle time ranges, `p` / `P` to cycle project scope,
and `r` to refresh. On Overview, Agents Run, Success Rate, and Commits open Projects;
Plans Proposed and Questions open Plans & Questions.

The **Perf** sub-tab combines five headline measures—Startup (median visible-ready),
Stalls (stall count, with hitches named separately in the tile's detail line), Launch
(p95 total launch time), Agent p95, and LLM p95—with startup stages, stall/hitch events,
grouped latency and reliability, and source-coverage diagnostics. Press `g` to group
latency by subsystem, provider, or workflow; the grouping also decides what the count
column counts (LLM invocations, agent runs, or an ungrouped count) and whether a Share
column applies. Perf counts come from telemetry and TUI logs, not the artifact index, so
they are not comparable with the run counts on the other sub-tabs. Perf is global: the
project chip remains visible but is marked **not applied**. See
[Reading the Admin Center Perf view](perf_runbook.md#reading-the-admin-center-perf-view)
for data sources, retention, and probe details.

The Statistics **XPrompts** sub-tab reports xprompts referenced by agent launch prompts:

- **By Usage** ranks xprompts by runs and shows references, share, agents, success,
  runtime, and recency.
- **By Model** breaks each xprompt down by model.
- **By Project** breaks it down by project.
- **Used With** shows xprompts referenced together in the same run.

Press `g` to cycle those four groupings without reloading the underlying statistics.
Press `x` to choose one xprompt and replace the ranking with its full time, model,
project, provider, tribe, and co-usage breakdown; press `X` to clear that focus. The
range and project filters apply before all xprompt aggregation.

These counts come from each run's launch-boundary `xprompts.json`, recorded before
prompt expansion. A run counts once per xprompt name, while **Refs** counts distinct
argument variants of the same name separately. References introduced inside workflow
step templates are intentionally excluded. Historical runs appear after the
agent-artifact index rebuilds at the current schema.

Each record carries a kind — `workflow`, `part`, or `swarm`. An xprompt swarm is
consumed by the dispatcher before any agent starts, so it never appears as a lexical
reference in a child's prompt; instead the swarm is attributed to every agent it
launched, and a nested swarm records every link of its chain. Because swarm records
carry no arguments, **Refs** equals **Runs** for a swarm row. Attribution is
forward-only: runs launched before this feature shipped are not backfilled.

This Statistics sub-tab is distinct from the Admin Center's top-level **XPrompts** tab
described in [XPrompt Browser](#xprompt-browser): the top-level tab browses and edits
xprompt definitions, while the Statistics sub-tab measures how launch prompts used them.

<a id="models-panel"></a>

## Launch Control {#launch-control}

Press `,m` from any tab to open **Launch Control** — one keyboard-driven surface for
launch configuration, model aliases, and temporary provider routing. The top level has
three visible sections: **Launch settings**, **Built-in size aliases**, and **Your
aliases**. Consecutive visible sections are separated by exactly one non-selectable
blank row; there is no leading, trailing, or doubled spacer.

Data rows use the grid `ownership gutter | name | value/model | state`. The former row
kind column is gone: labels such as `launch`, `setting`, `role`, `user`, and `bucket` do
not appear as their own column. User-owned aliases and buckets still have the tan `▌`
ownership gutter, misplaced built-in aliases keep a gold `!` marker in the name cell,
and collapsed buckets put `▸` directly before the bucket name.

**Launch settings** contains six rows: `default model`, `epic lander`,
`big epic lander`, `big epic starts at`, `default effort`, and `max runners`. The three
model rows show raw alias/config value → effective provider/model. `big epic starts at`
shows the effective `bead.big_epic_phase_threshold` as `<N> phase` or `<N> phases`:
epics with `N` or more authored phases use the big epic lander, while smaller epics use
the regular epic lander. `default effort` and `max runners` show their launch-effective
scalar values and any active temporary override state.

Alias rows show the alias name, effective provider/model as a provider-themed badge, and
a state tag — `configured`, `implicit` / `implicit → @<fallback>` /
`implicit → @<fallback> @ <effort>`, or an `override · <time> left` /
`override · until cleared` chip when a temporary override is active. Configured
references use the same `configured → @<target> @ <effort>` form. A model-specific
effort carried by an override appears beside the effective provider/model badge. When
one or more providers are temporarily disabled, the title adds a compact
`disabled providers:` line with each active provider and its remaining time, or
`until cleared` for a no-expiry disable.

The alias area is split into **Built-in size aliases** and **Your aliases**. Each header
reports the aliases represented by its rows (including members of collapsed custom
buckets) and its bucket count. **Built-in size aliases** always lists exactly five rows
in size order — `@xsmall`, `@small`, `@medium`, `@large`, `@xlarge` — with no bucket to
drill into; each row is edited, overridden, reset, or cleared directly like any other
alias row. **Your aliases** holds only user-owned aliases and custom buckets, in
alphabetical order. If there are no custom aliases or buckets, **Your aliases** remains
visible with a non-selectable hint naming `llm_provider.model_aliases.custom`.

Custom buckets group your own aliases under a shared display name, either through
`model_aliases.buckets.<name>` or a custom alias's `bucket:` tag; there is no built-in
bucket for a custom alias to join, so every bucket that appears is entirely user-owned.
Each collapsed bucket row reports the member count and active overrides, while the
description strip summarizes distinct effective models. Open a bucket with `l`, Right,
or Enter; return with `h` or Left. Inside the bucket, each alias keeps its own
configured/implicit state and can be edited, reset, overridden, or cleared
independently. A configured description under `model_aliases.buckets.<name>` replaces
the default. A custom bucket renders its bucket state in the ownership accent, and the
drilled-in title ends with `· custom bucket` plus the ownership glyph.

The two-line strip below the list explains the highlighted row. Launch settings show
their config path, effective value, and boundary/override context. Builtin aliases use
fixed descriptions. User aliases use
`llm_provider.model_aliases.custom.<name>.description`; a malformed user alias without
one shows that config path as the fix. A non-pool alias with an explicit effort uses the
second line to say whether it matches or overrides the configured default. For a
selector-valued alias, the strip lists every parsed member with an available/unavailable
marker. A round-robin pool's row state includes an availability count such as
`pool 2/2`, and `→` marks the exact next peeked selection without advancing its cursor.
An ordered fallback labels candidates in priority order, marks the current winner, and
never reads rotation state. The row's provider/model/effort badge is derived from that
same selected member. Temporarily disabled providers count as unavailable for this
display. If a temporary alias override targets a disabled provider, the override is
preserved but paused: the row shows the live fallback/pool target, the state tag says
the override is paused, and the description names the disabled provider that must expire
or be re-enabled before the override resumes. An active override whose provider remains
available still bypasses selector choice for the override's lifetime.

If a builtin size alias is mistakenly configured under
`llm_provider.model_aliases.custom`, opening the panel emits one warning toast listing
every affected `@alias`. A gold warning glyph remains on the affected alias row even
while a temporary override is active, and highlighting it replaces the normal
description with the same actionable advice. Move the entry's `model` value from
`llm_provider.model_aliases.custom` to `llm_provider.model_aliases.builtin`; ACE
identifies the misplaced entry but does not rewrite the configuration automatically.
Because ownership follows the alias kind rather than where it is configured, the
misplaced alias stays in the **Built-in size aliases** section — never inside a custom
bucket — and does not receive the ownership gutter.

Navigate with `j`/`k` (or arrows / `Ctrl+N` / `Ctrl+P`) and act on the highlighted row.
Navigation, and jump hints, skip headers, spacer rows, and the empty-custom hint.

| Key                   | Action                                                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `l` / Right / `Enter` | **Open** the highlighted bucket                                                                                     |
| `h` / Left            | **Back** to the top level from an open bucket                                                                       |
| `'`                   | **Jump** — paint adaptive hints; a hint moves the highlight without activating the row, and a second `'` jumps back |
| `o`                   | **Override** — set/change a time-bound temporary alias/default-effort/runner-limit override                         |
| `x`                   | **Clear** — remove the active temporary override on the highlighted override-capable row                            |
| `e`                   | **Edit** — change the persistent configured value                                                                   |
| `r`                   | **Reset** — unset an alias/model setting or the big-epic threshold                                                  |
| `p`                   | **Providers** — disable, extend, or re-enable registered providers for future routing                               |
| `H`                   | **History** — view recorded prior runs for the highlighted alias, alias-backed launch setting, or bucket            |
| `Ctrl+E`              | **Effort** — persistently edit, temporarily override, or clear the global default effort                            |
| `Ctrl+R`              | **Limit** — persistently edit, temporarily override, or clear the global runner limit                               |
| `Esc` / `q`           | Close the panel                                                                                                     |

On `big epic starts at`, `Enter` and `e` open a focused positive-integer editor, and `r`
previews a reset. The input accepts an unsigned base-10 whole number with minimum `1`
and no spaces, signs, floats, or booleans; the inline constraint reads
`minimum 1 · package default 5`. The preview targets the writable user-base `sase.yml`
or its chezmoi source at `bead.big_epic_phase_threshold`. Reset uses an unset operation
so lower-precedence or package defaults resume; it does not write a literal `5`. There
is no temporary threshold override. Pressing `o` or `x` on that row warns and points
back to Edit/Reset.

After a successful threshold write, Launch Control reloads the effective value and the
epic-lander row descriptions from the same provider/launch snapshot. If a
higher-precedence layer keeps the requested user value from winning, the notification
reports the actual effective value and the requested value. Dirty Git-backed targets
receive the standard tracked commit/pull/push offer with
`chore: update big epic phase threshold`.

### Default effort controls

`Ctrl+E` works from every alias and bucket row because default effort is global. The
**Default Effort** card shows the exact value used for new launches and, while a
temporary override is active, the configured value beneath it. Press `e` to edit
permanently, `o` to override temporarily, or `x` to clear the active temporary override;
`x` is shown only when there is something to clear. Explicit prompt effort and effort
carried by an alias or selected pool member still win, and already-running agents are
unaffected.

Both Edit and Override open the same ordered, single-key effort ladder: `1` `none`, `2`
`minimal`, `3` `low`, `4` `medium`, `5` `high`, `6` `xhigh`, and `7` `max`. Edit also
offers `0` **Provider default**. That option writes the schema's empty sentinel into the
user-base `sase.yml`, deliberately masking a lower-precedence package/plugin value;
Override does not offer a pseudo-level, because cancelling or clearing honestly resumes
configured/provider behavior. Config-derived values are best-effort: a provider that
cannot honor a level retains its provider behavior.

Temporary effort Override reuses the model-alias duration workflow unchanged: `15m`,
`30m`, `1h`, `2h`, `4h`, Until cleared, a combined custom duration, or `t` for an exact
local time/date. It is machine-wide state in `~/.sase/llm_effort_override.json`; setting
replaces the prior effort override, expiry is enforced on the next launch, and Clear is
idempotent. This state is independent of `~/.sase/llm_override.json`, which stores
concrete model-alias overrides.

Permanent Edit always targets the writable **user base** config rather than a
project-local layer. Its preview shows `llm_provider.default_effort`, configured
before/after values, the actual target, validation, and the source-preserving YAML diff.
With `use_chezmoi: true`, the actual write goes to the chezmoi source and the target is
applied before ACE reports success. A dirty Git-backed target receives the usual tracked
commit/pull/push offer with `chore: update default model effort`. An active temporary
override remains launch-effective after this write until it expires or is cleared; the
preview and success notification both make that explicit.

### Max running agents controls

`Ctrl+R` is a fixed Launch Control binding and works from every alias, collapsed bucket,
and open bucket. It is not a leader-keymap setting. The **Max Running Agents** card
shows the current effective global cap and, while a temporary override is active, its
remaining time plus the configured value. Press `e` to edit the user-base configuration,
`o` to set a temporary machine-wide override, or `x` to clear an active override.

Edit and Override open a focused positive-integer card. Edit is prefilled with the
configured value; Override is prefilled with the current effective value. The input
accepts an unsigned base-10 whole number with minimum `1` and no product maximum. A
persistent edit previews the exact `max_running_agents` path, actual user or chezmoi
source target, configured before/after values, validation diagnostics, and
source-preserving YAML diff. Its tracked commit offer uses
`chore: update max running agents`. A higher-precedence overlay can keep the configured
effective value different from the requested user-layer value, which the reload
notification reports truthfully.

Temporary Limit overrides reuse the same relative/custom/exact-time duration cards as
model and effort overrides. The versioned machine-wide record is
`~/.sase/max_running_agents_override.json`; setting a value replaces the previous
runner-limit override, `now >= expires_at` expires it, and Clear is idempotent. A
persistent edit does not clear a live temporary override. Lowering the effective cap
never stops an already-running agent: occupancy may temporarily exceed the cap, and new
implicit-cap work waits until enough slots drain. Raising the cap lets eligible parked
agents advance through the existing priority/FIFO gate on their next poll. Launches with
an explicit `%wait(runners=N)` retain their own initial-admission threshold, while
question continuations reacquire against the current effective global cap.

### Provider routing controls

Press `p` from Launch Control to open **Provider Routing**. The modal lists every
user-facing registered LLM provider in stable order with its model count and one of
these states:

| State                                            | Meaning                                                              |
| ------------------------------------------------ | -------------------------------------------------------------------- |
| `available`                                      | The provider is registered and its declared CLI is present.          |
| `CLI unavailable`                                | Automatic alias routing already skips it because its CLI is missing. |
| `disabled · manual · <time> left`                | Launch Control manually disabled it until expiry or clearing.        |
| `disabled · usage-limit automatic · <time> left` | Usage-limit detection automatically disabled it.                     |

Hidden testing providers stay out of this human-facing modal. Disabling a provider does
not unregister it, change `sase.yml`, change model aliases, or stop provider processes
that are already running. It only affects new launches, follow-ups, later retry/fallback
resolution, model pickers, and completion catalogs.

On an enabled row, press `d` or Enter to choose how long new launches should route
around that provider. The flow uses the same duration choices as alias overrides: `15m`,
`30m`, `1h`, `2h`, `4h`, `Until cleared`, a custom duration, or `t` for an exact local
time/date. On a disabled row, `d` or Enter replaces the duration and `x` enables the
provider immediately, including an automatic usage-limit disable. Pressing `x` on an
enabled row warns without mutating state. Successful changes refresh the provider rows,
Launch Control title, alias routing rows, and the top-bar indicators without closing the
modal, so several providers can be managed in one pass. Unknown disable sources are
shown as readable labels instead of being folded into the manual state.

ACE also shows active provider disables in a compact top-bar pill beside the model
override indicators. One disabled provider renders like `CLAUDE off 42m`; several render
as the alphabetically first provider plus a count, such as `CLAUDE +2`. Hover lists
every active provider, provenance, and expiry, and clicking the pill opens Launch
Control.

### Alias History

Press `H` on an alias row, an alias-backed launch setting (`default model`,
`epic lander`, `big epic lander` when configured as a raw `@alias` reference), or a
collapsed bucket to open **Alias History** — bounded prior runs for that alias or, for a
bucket, every member alias. A concrete (non-alias) launch setting and the
`default effort`, `max runners`, and `big epic starts at` scalar settings are not
aliases; pressing `H` on one of those rows only shows a warning toast. The panel loads
off-thread and never changes Launch Control's own state.

The title names the alias or bucket, keeps the tan ownership accent for a user-owned
source, shows the effective provider/model/effort badge when a single alias supplied it,
and reports the total recorded, returned (currently visible), and done/failed/running
counts. A bucket's runs are grouped under a disabled header per member alias, separated
by the same single-spacer convention used elsewhere in Launch Control; headers, spacers,
and per-group empty hints are never jump targets. Rows render newest first exactly as
recorded, with a status marker, relative time, agent/workflow identity, the configured
project display name, a provider-themed model badge with effort, and one of four
provenance chips:

| Chip         | Meaning                                                                   |
| ------------ | ------------------------------------------------------------------------- |
| `direct`     | An explicit `%model` directive named this alias.                          |
| `default`    | The configured default model resolved to this alias.                      |
| `via @<...>` | This alias was reached indirectly, through an earlier alias in the chain. |
| `unrecorded` | No alias origin was captured for this run — recording predates it.        |

The fixed detail strip below the list explains the highlighted run: the recorded alias
trail resolved to its concrete provider/model/effort, the same origin explanation as the
chip (an honest, non-speculative note for `unrecorded` rather than a guessed reason),
and the prompt snippet plus whichever of project, workspace, bead, Patch, start time and
duration, retry attempt, hidden state, and xprompt context are actually present —
nothing is invented for a field the query did not return. The returned window is a
display limit, not the full retention history; the title's recorded/shown counts and the
footer's "more available" hint make the difference visible.

| Key                                 | Action                                                                             |
| ----------------------------------- | ---------------------------------------------------------------------------------- |
| `j`/`k` (arrows, `Ctrl+N`/`Ctrl+P`) | Navigate                                                                           |
| `'`                                 | **Jump** — adaptive hints over selectable runs only                                |
| `Enter`                             | Open the highlighted run's full prompt in the preview panel                        |
| `y`                                 | Copy the highlighted run's durable `@agent:...` reference                          |
| `Ctrl+K`                            | **Load more** — double the per-alias limit and reload, keeping the highlighted run |
| `r`                                 | **Refresh** — revalidate this load, bypassing the cache once                       |
| `.`                                 | Toggle hidden runs in or out of the results                                        |
| `Esc` / `q`                         | Close and return to Launch Control, unchanged                                      |

A run without a durable agent name warns instead of copying a guessed reference, and a
missing or unreadable `raw_xprompt.md` warns instead of closing the panel.

### Temporary overrides

`Edit` and `Override` open the shared model picker with an `ALIASES` group before the
provider-grouped concrete models. Alias rows show the exact `@name` token and its
current effective provider/model; filter by either `@medium` or `medium`, an alias kind
or description, or the displayed target. For persistent edits, the current alias and any
alias that would introduce a direct or transitive cycle remain visible but unavailable
with a concise reason. `Custom...` accepts a concrete model string, `provider/model`
path, or bare `@alias` reference in both flows and applies the same safety check to
free-form `@alias` values. Concrete model rows for temporarily disabled providers are
omitted; alias rows remain visible and show their current live fallback target.
Free-form explicit input is validated before submission and reports the same
disabled-provider diagnostic as a launch. In `Edit`, `Custom...` additionally accepts a
typed `|` pool or `||` fallback expression and opens prefilled with the alias's current
value, so changing one member of an existing selector no longer means retyping the whole
expression; `Edit` also offers a guided `Pool / fallback...` row next to `Custom...`
that builds a selector from the picker without typing `|` by hand (see
[Persistent edits](#persistent-edits) below). In `Override`, a typed pool or fallback is
refused outright with a message pointing at `e` — selectors are config-only and
overrides take a single target, so `Override`'s `Custom...` never shows the
`Pool / fallback...` row.

`Override` continues from the picker to the duration picker (`15m`, `30m`, `1h`, `2h`,
`4h`, `Until cleared`, or a custom duration like `45m`, `1h30m`, `90m`). Press `t` in
the duration picker to choose **Until a specific time**. The focused time popup accepts
local forms such as `5pm`, `5:30 PM`, `17:30`, `1730`, `today 5pm`, `tomorrow 9am`, and
`2026-07-12 09:00`. An undated clock means its next occurrence (later today or
tomorrow); an explicit day/date must still be in the future.

The popup previews the resolved weekday/date, local time and abbreviation, configured
IANA timezone, and remaining duration before Enter writes anything. Daylight-saving gaps
are rejected; repeated fall-back times require an offset-qualified ISO value such as
`2026-11-01T01:30-04:00`. Invalid input stays focused with an inline explanation. `Esc`
goes back to the duration picker, where a second `Esc` cancels the override flow.
Overrides are per-alias and per-launch-setting, and independent:

- An override on **`default model`** drives the no-`%model` launch default. It renders
  in a gold top-bar pill as `PROVIDER(model)[@<effort>] <time-left>`.
- An override on **any built-in size alias or custom alias** takes effect wherever that
  alias is resolved. A size-specific phase or task override affects only that alias. An
  override on a selector-valued alias — a `|` load-balanced pool or `||` ordered
  fallback, such as the shipped `@xsmall`, `@small`, `@medium`, `@large` pools or the
  `@xlarge` ordered fallback — suspends that alias's own rotation/fallback for a single
  concrete target until the override expires or is cleared.
- An override on **`epic lander`** or **`big epic lander`** affects only epic land
  agents below, or at/above, `bead.big_epic_phase_threshold`, independently of
  `default model` and of each other.

Every non-default override (an alias, `epic lander`, or `big epic lander`) is surfaced
by a distinct, concise violet top-bar pill: a single active override renders as
`@<alias>[@<effort>] <time-left>` or as `epic lander <time-left>` /
`big epic lander <time-left>`, and several render as `<first> +N`, naming the
alphabetically first overridden alias or launch-setting label and counting the rest. In
both pills, lane color carries the "override" meaning while the effort suffix and time
use a recessive tone; `∞` means until cleared. Hover either pill for full target and
expiry details, or click it to open Launch Control.

When no override is active, the same top-bar pill instead names the current launch
default — `PROVIDER(model)`, in a calmer dim-cyan tone — and stays live for the whole
ACE session. If `llm_provider.default_model` (directly or through a referenced alias,
such as the shipped `@large`) is a load-balanced `|` pool, the pill follows the pool's
round-robin cursor as it advances: a launch consumes one member, and within a few
seconds the pill flips to name whichever member runs next. It never resolves on the UI
thread and never advances the cursor itself — it only reflects state that a real launch
already changed. Hover the pill for a
`<alias> rotates across N models; PROVIDER(model) is next` line whenever the default
routes through such a pool.

Overrides do not displace explicit launch intent: explicit prompt directives
(`%model:codex/o3`, `%model:opencode/anthropic/claude-sonnet-4-5`) and an explicit
`provider_name` argument always win, already-running agents keep their current
provider/model. A temporary provider disable is different: an explicit request for a
disabled provider fails with a provider-and-expiry diagnostic rather than silently
switching providers. Override state is persisted to `~/.sase/llm_override.json` — shared
across all sase processes on the machine — and is best-effort self-cleaning: expired or
malformed entries are pruned on next read. `Until cleared` is a no-expiry mode —
convenient, but still a _temporary_ state, not a permanent config edit. The temporary
override is independent of `SASE_MODEL_TIER_OVERRIDE`; a concrete override takes the
full provider/model path, while the tier override only applies when no concrete override
is active.

Delegated launches (plan coder follow-ups and `sase bead work` phase, task, and land
agents) route directly through the
[built-in size aliases](llms.md#role-aliases-for-delegated-work) configured under
`llm_provider.model_aliases.builtin`, plus the `epic lander`/`big epic lander` launch
settings — there is no more role-alias indirection through a separate
`default`/`smart`/`cheap`/etc. lane. A phase or task selects `@xsmall`, `@small`,
`@medium`, `@large`, or `@xlarge` by its normalized size directly; a phase or task
without size metadata uses the `@small` fallback. Epic land agents without an explicit
land model use `epic_lander_model` (shipped `@large`) below
`bead.big_epic_phase_threshold`, or `big_epic_lander_model` (shipped `@xlarge`) at or
above it. Because `epic lander` and `big epic lander` are configured as raw alias
references, a temporary override on the alias they reference (`@large` and `@xlarge` by
default) cascades into their effective resolution; overriding `epic lander` or
`big epic lander` directly takes precedence over that nested reference. A temporary
override on a selector-valued built-in size alias — the shipped `@xsmall`, `@small`,
`@medium`, and `@large` pools, or the `@xlarge` ordered fallback — suspends only that
alias's own rotation and does not cascade to any other alias or launch setting.

### Persistent edits

`Edit` and `Reset` change the alias's value in `sase.yml` itself, written through the
Rust-backed, source-preserving config-edit path (comments and key order are preserved).
The change is shown in a preview/confirm step before it is written, and after a
successful write the panel offers to **commit and push** it (`y`/`n`). With
`use_chezmoi: true` the edit targets the chezmoi source and the commit/push runs against
the chezmoi repo followed by `chezmoi apply`; when the target file is not in a git repo
the commit offer is skipped and the file is simply written. An active temporary override
visually "wins" the effective-target column even after a persistent edit; the state tag
distinguishes the _configured_ value from the _currently effective (overridden)_ one.

Selecting an alias during `Edit` stores the raw reference (for example, editing
`epic lander` to `@xlarge`), so it remains a dynamic link and follows future changes to
`@xlarge`. Selecting an alias during `Override` instead resolves it when the override is
written and stores that concrete provider/model snapshot together with the raw token;
later changes to the referenced alias do not change the active override. A canonical
trailing effort is snapshotted with the target and shown in the row, success
notification, and single-override top-bar pill. A known suffix on an alias reference is
ignored for dependency/cycle checks but retained for the written value; unknown trailing
`@token` text is not treated as effort.

Builtin aliases edit under `llm_provider.model_aliases.builtin.<name>`. User aliases
under `llm_provider.model_aliases.custom.<name>` edit their `model` field and reset by
deleting the whole custom alias entry. The custom input also accepts a `|`-separated
load-balanced pool or a `||`-separated ordered fallback. The editor rejects empty or
mixed selectors and alias references that would reach any nested selector before opening
the write preview.

Choosing `Pool / fallback...` from the `e` picker opens a guided builder instead of
typing an expression by hand. It seeds its state from the alias's current value — an
existing `|` or `||` expression expands into its members and mode, a single target
becomes a one-member list, and an empty value starts blank — and shows the live
normalized expression as members change. `a` adds a member through the same model picker
and effort ladder used elsewhere in the panel (its own `Custom...` accepts a bare model,
`provider/model` path, or `@alias`, with an optional trailing `@effort`); `d` removes
the highlighted member; `J` / `K` reorder it down and up; `E` sets or clears that
member's effort; `t` toggles between round-robin pool and ordered fallback; `enter`
confirms and routes the composed expression to the same preview/write path as a typed
value; `esc` cancels back to the picker. As in the top-level Edit picker, an alias
reference that would reach another pool or fallback is unselectable here. Confirm is
blocked, with an inline reason, while the selector has fewer than two members or the
live validation line reports an error.

### Examples

- Highlight `default model`, `o`, pick `codex/o3`, duration `1h` — launches with no
  `%model` directive use Codex `o3` for the next hour, then revert to the configured
  default.
- Highlight `@medium`, `o`, pick a model, then `t`, enter `5pm` — the preview resolves
  the next 5:00 PM in the configured timezone and the override expires at that exact
  instant.
- Highlight `@small`, `o`, pick `claude/opus`, and choose `Until cleared` — small phases
  and tasks without an explicit model use CLAUDE(opus) until you clear it; the violet
  non-default pill appears in the top bar.
- Highlight `@large`, `e`, pick `claude/opus`, and confirm — only large phases and tasks
  without an explicit model use that target; other-sized phase/task routing is
  unchanged.
- Highlight `@xlarge`, `e`, pick `claude/opus`, and confirm — xlarge phases and tasks
  use that target directly, and `big epic lander` (left at its shipped `@xlarge`
  reference) inherits the same change.
- Leave `@xlarge` implicit — xlarge phases, tasks, and threshold-selected epic landers
  (which reference `@xlarge` by default) all follow whichever candidate in its shipped
  ordered fallback is currently selected.
- Highlight `@xsmall`, `e`, choose `Custom...`, enter
  `claude/haiku@minimal | codex/gpt-4.1-mini@low`, and confirm — xsmall phases and tasks
  round-robin across installed providers while the panel continues to show the next
  selection without consuming it.
- Highlight `@small`, `e`, choose `Custom...`, enter
  `claude/haiku | codex/gpt-4.1-mini`, and confirm — small phases and tasks round-robin
  across this independent pool without consuming the `@xsmall` cursor.
- Highlight `@medium`, `e`, choose `Custom...`, enter
  `claude/haiku@minimal | codex/gpt-4o-mini`, and confirm — medium phases and tasks
  round-robin across this independent pool without consuming the `@xsmall` or `@small`
  cursor.
- Press `p`, highlight `claude`, `d`, choose `1h` — new alias-backed launches route
  around Claude for the next hour, direct `%model:claude/opus` launches fail explicitly,
  and already-running Claude processes continue.
- With `claude` disabled, an override on `@medium` that targets `claude/opus` pauses;
  the row shows the live fallback target until Claude is re-enabled or the disable
  expires.
- Highlight `big epic lander`, `e`, pick a model, and confirm — only threshold-selected
  epic landers use that persistent target; leaving it implicit inherits through its
  shipped `@xlarge` reference, independently of `epic lander`.
- Highlight `big epic lander`, `e`, filter for `@large`, select it, and confirm — the
  persistent value is the dynamic `@large` reference, not a copied concrete model.
- Highlight `@medium`, press `o`, select `@xlarge`, then choose `1h` — the override
  records the concrete provider/model to which `@xlarge` resolves at write time while
  retaining `@xlarge` as its raw input.
- Highlight an alias or launch setting, `x` — clear its temporary override; `r` — unset
  its configured value back to its implicit fallback.

See [docs/llms.md](llms.md#temporary-model-overrides) for the resolution order and
state-file format.

## Notifications Modal

Press `i` (or the `,n` leader chord to jump straight to an agent's notification) to open
the notifications modal. See [`docs/notifications.md`](notifications.md) for the full
keybinding reference, modal tabs, priority/error/muted classification, and the
per-notification snooze and mute affordances.

Rows and the detail header begin with the notification's single-glyph icon when one is
present, with a per-action fallback icon otherwise. The text action badge remains
visible as the secondary label.

Press `d` on the highlighted inbox row to open Gate Debug, even when the row is not
gate-backed or its gate modal can no longer load. The same `d` binding is available
inside plan/epic approval, user-question, launch-approval, custom-gate, and workflow
HITL panels. Gate Debug presents Overview, Request, Response, Errors, and raw Row tabs;
`[` / `]` switch tabs, `y` copies the current tab, `Y` copies the bundle path, `e` opens
the backing file, and `d`, `q`, or `Esc` closes the overlay without losing state in the
underlying panel.

The top-bar notification indicator color reflects the highest-priority unread bucket:
orange for unmuted priority or error notifications (plan approvals, launch approvals,
user questions, mentor reviews, axe errors, CRS results, agent error reports), gold for
regular unmuted notifications, and cyan when only muted or snoozed notifications remain.
A trailing dot means muted unread rows also exist while the badge is showing the
actionable count.

### Snooze Reminder Scheduling

Snooze expiry does not depend on the general refresh cadence. ACE keeps at most one
timer for the nearest deadline reported by the current notification snapshot, so
reminders fire on time even with clean inotify state or `--refresh-interval 0` (which
disables ordinary auto-refresh). The timer callback stays thin and synchronous: it
compares cached wall-clock values on Textual's message pump and hands the store read to
a coalesced proc, so no disk or worker I/O runs on the pump and an expired snooze never
triggers a full Agents-list rebuild.

While any snooze is pending, ACE rechecks the wall clock at most one second apart, so a
suspended host, a resumed session, or a forward/backward system-clock change
re-evaluates the authoritative UTC deadline promptly instead of waiting out a monotonic
timer. Startup reconciliation, notification-file watcher events, ordinary polling, and
modal snooze/resnooze/unmute/dismiss completions all route through the same coalescing
guard, so an external mutation can replace or cancel the cached nearest deadline
immediately. The coordinator starts after first paint and its timer and task are
cancelled during normal and controlled teardown.

Once due, ACE performs one current-state snapshot read, applies counts, toasts, and
status projections, then schedules the next future deadline. Each observed resurface
batch produces one toast and one tmux bell — including rows that were marked read while
snoozed — and no repeat on later polls. Cancelled, dismissed, permanently muted, and
not-yet-due rows never ring. If another process wins the expiry, the persisted unread
state and `resurfaced_at` still make the transition observable here. Resurfaced rows
sort as recent activity in the modal while continuing to display their original sent
time. See [`docs/notifications.md`](notifications.md#snooze-expiry-and-resurfacing) for
the full state and timing contract.

## Notification Actions

Some notifications carry an `action` field that triggers a handler when the notification
is selected. The following notification action types are supported:

| Action               | Source          | Behavior                                                                        |
| -------------------- | --------------- | ------------------------------------------------------------------------------- |
| `CustomGate`         | Agent/tool      | Opens the generic choices, add-ons, and feedback modal                          |
| `HITL`               | Workflow        | Opens the workflow human-in-the-loop response modal                             |
| `JumpToAgent`        | Agent/workflow  | Jumps to the matching Agents-tab row                                            |
| `JumpToPatch`        | Sync/workflow   | Jumps to the referenced Patch on the Patches sub-tab                            |
| `JumpToMentorReview` | Mentors         | Jumps to the Patch and opens mentor review output when available                |
| `LaunchApproval`     | Agent           | Opens the launch approval modal for an agent-requested launch                   |
| `PlanApproval`       | Agent           | Opens the plan approval modal                                                   |
| `Tmux`               | External bridge | Runs `tm <workspace-name>` for the notification's `action_data.workspace_dir`   |
| `UserQuestion`       | Agent           | Opens the structured user-question response modal                               |
| `ViewErrorReport`    | Axe/agent       | Opens `action_data.error_report_path`, or the first attached file, in `$EDITOR` |
| `memory_review`      | Memory          | Suspends ACE and opens the memory proposal review TUI at that proposal          |

The axe `error_digest` chop creates `ViewErrorReport` notifications whose digest files
live under `~/.sase/axe/error_digests/digest_<timestamp>.txt`; user-agent failures can
use the same action for their own attached error reports. Memory proposal notifications
created by `sase memory write --notify` use `memory_review` with
`action_data.proposal_id`. Selecting one opens the same review UI as
`sase memory review`, preselected on that proposal; approval or rejection still happens
inside the review UI.

The custom-gate modal shows the sender and notes or verified preview, one icon-led
button per terminal choice, checkboxes for that choice's independently selectable add-on
commands, and a feedback input. Required feedback blocks submission until non-empty text
is present; optional and disabled modes adjust the affordance accordingly. Unsupported
future actions produce a warning instead of silently doing nothing.

Custom gates and neutral HITL gates execute through the shared hash-verifying gate
executor. ACE schedules the terminal command and each selected add-on through the
tracked proc queue, streams live stdout/stderr to the proc, shows each command as a
reporter phase, and refreshes the inbox when the proc completes. Legacy HITL bundles
retain the direct response-file fallback.

### Toast Notifications

Each newly-arrived notification produces a short toast in the TUI. The toast text is
derived per-action type (plan, question, HITL, axe error, Patch sync, agent update) so
the message previews the actual event rather than a generic "N new notification(s)"
line. Severity is also picked per type: plans, questions, and HITL render as warnings;
axe errors (and sync failures) render as errors; everything else renders as information.

A genuinely new tale or epic plan review rings the terminal once on arrival and remains
visually prominent as a warning toast and priority inbox row. Already-answered plan
reviews discovered during polling and the post-approval coder or epic handoff stay
silent. Questions, other audible notification classes, and explicit snooze-expiry
reminders retain their existing bell behavior; snoozing a plan review therefore still
produces the requested reminder bell when it expires.

When more than 3 notifications arrive in the same poll tick, per-notification toasts are
consolidated into one grouped toast per severity bucket (e.g.,
`2 warnings: 1 plan, 1 question`). Ordering is urgency-first: errors, then warnings,
then information. Silent notifications are excluded from this pipeline entirely.

Agent completion and failure toasts include the `%id`-set agent name with an `@` prefix
when present (e.g., `CLAUDE(opus) @sase-q.land completed: ace(run)-...`); anonymous
agents (no `agent_name`) keep the prior format.

## XPrompt Browser

Press `#` on any tab to open **SASE Admin Center**, then press `7` or switch to the
**XPrompts** tab with `Tab` / `Shift+Tab` or the tab strip. The XPrompts tab displays
all discovered xprompts in a two-panel layout: a filterable list on the left and a
syntax-highlighted preview on the right. Markdown xprompts with leading YAML frontmatter
render the frontmatter and body with their respective syntax styles.

Xprompts are grouped by source (project `sase/xprompts/`, home `~/sase/xprompts/`,
project-specific home, config `sase.yml`, plugins, built-in, plus labeled legacy
compatibility sources). Workflow xprompts (multi-step YAML) are marked with a gear icon;
standalone workflows are displayed with the `#!name` insertion syntax. Project-local
xprompts defined in each project's `sase.yml` file are also included, even though the
TUI's normal config loading does not read project-local config files.

The list rows and preview metadata show the same insertion form and visible input
metadata used by `Ctrl+T` completion. Step-only inputs are hidden from this user-facing
surface because they are supplied by workflow execution rather than typed by the user.

### Keybindings

| Key       | Action                                                                       |
| --------- | ---------------------------------------------------------------------------- |
| `j` / `↓` | Navigate to next xprompt                                                     |
| `k` / `↑` | Navigate to previous xprompt                                                 |
| `Ctrl+N`  | Navigate to next xprompt                                                     |
| `Ctrl+P`  | Navigate to previous xprompt                                                 |
| `'`       | Jump to a non-header row via adaptive hints                                  |
| `Ctrl+D`  | Scroll preview panel down                                                    |
| `Ctrl+U`  | Scroll preview panel up / clear input                                        |
| `Enter`   | Target the highlighted xprompt: load it into the home prompt bar for editing |
| `E`       | Open the highlighted definition in `$EDITOR`                                 |
| `Ctrl+O`  | Add a new xprompt                                                            |
| `Ctrl+I`  | Inline-expand the highlighted xprompt into the home prompt bar               |
| `Esc`     | Close SASE Admin Center                                                      |

Type in the filter input to narrow the list in real time. The filter input is focused by
default, so two keys are reserved while it is **empty**: digits `1`–`9`/`0` jump to an
Admin Center tab, and `'` arms entry-jump over the list's non-header rows instead of
being typed. Once the filter holds text, both keys fall through to ordinary editing, so
values such as `bug2` or a filter ending in a literal apostrophe can be typed normally.

### Editing XPrompts

Press `Enter` on any xprompt to load its definition into the home prompt bar and target
it for editing — see
[Editing an Existing XPrompt from the TUI](#editing-an-existing-xprompt-from-the-tui)
for the full targeting loop, including the visual chip states, the target-aware `Enter`
save menu, and the chezmoi-aware write path. Project, home, and config sources are
editable and bind the bar to their source file. Read-only sources (legacy, plugin, and
built-in) load without a target: the bar shows a persistent read-only marker instead,
and `gw` falls through to the save-as flow so your edits land in a new, editable copy
rather than being silently discarded. Press `E` to open an editable definition directly
in `$EDITOR` instead; after saving, the browser offers the applicable follow-up actions
(commit/push, a scoped chezmoi apply, or `sase memory init` / `sase skill init`).

### Creating XPrompts

Press `Ctrl+O` to start the guided creation flow:

1. **Location modal** — Choose where to save the new xprompt (project `sase/xprompts/`,
   home `~/sase/xprompts/`, project `sase/sase.yml`, or a global config file). Legacy
   sources remain browseable but are never new-write destinations. Press `Ctrl+G` to
   open the selected config file in `$EDITOR` instead of proceeding with creation.
2. **Filename modal** — Enter a filename (`.md` for prompt parts, `.yml` for workflows).
   Workflow files are pre-filled with a YAML template containing the workflow scaffold.
3. **Editor** — The file opens in `$EDITOR` for editing.
4. **Follow-up actions** — After saving, the browser offers the actions that apply to
   the new file: commit/push, and — when `use_chezmoi` redirected the write to the
   chezmoi source — a scoped `chezmoi apply` of just that file.

## Jump All Modal

Press `` ` `` (backtick) on any tab to open the Jump All Modal. It displays all entries
across Agents, Artifacts, and Axe tabs with the same adaptive one- or two-character
hints used by current-tab entry jump. Completing an entry's hint switches to the
appropriate tab and focuses it.

Up to 62 entries use `0`–`9`, `a`–`z`, `A`–`Z`. Larger result sets use fixed-width pairs
from `00` through `ZZ`; a first character is consumed without closing the modal, and
uppercase characters remain case-sensitive.

| Key         | Action                          |
| ----------- | ------------------------------- |
| Hint        | Jump to the corresponding entry |
| `Esc` / `q` | Close modal                     |

The modal groups entries by tab (Agents, Artifacts, Axe) and shows contextual
information for each: PR names and statuses, agent names with running indicators, and
Axe lumberjack/command labels.

### Jump Back

Both jump modals support a jump-back feature for toggling between two entries:

- **Backtick jump-back**: Pressing `` ` `` inside the Jump All Modal returns to the
  previous position, enabling quick toggling between two entries across tabs.
- **Apostrophe jump-back**: Pressing `'` twice (`''`) in the single-tab entry jump mode
  jumps back to the previously jumped-from entry. The footer shows a "JUMP" mode
  indicator with `' back` when a target exists.
- **Fast jump**: `Ctrl+O` runs the same current-tab jump-back path without painting
  hints first; when no jump-back target exists, it selects the first current-tab hint.
- **Forward jump**: After walking backward, `Ctrl+Shift+O` walks forward through that
  current tab's jump stack. Agents, Artifacts/Patches, and Axe keep independent back and
  forward positions.

The single-tab variant (`'` apostrophe) shows entries only from the current tab with the
same hint-character navigation.

## Mentor Comment Stats in PR List

When a Patch has completed mentor reviews with comments, its Patches sub-tab list entry
shows inline stats:

- **checkmark + count** (e.g., `✓3`) — number of accepted comments
- **dot + count** (e.g., `●2`) — number of unread comments

These stats are computed from the latest stitch's finished mentors. They update as you
accept or read comments in the Mentor Review modal.

## PR Origin Chip

A Patch with a `pr_url` shows a `PR_ORIGIN` chip next to its PR badge in the Patches
sub-tab list and in the detail panel: nothing for the default `sase` origin (a PR SASE
created through the tracked PR workflow), `external` for a PR SASE adopted but did not
create, and `origin?` for `unknown` (no evidence either way). The detail panel adds a
one-line note for `external` Patches, since AXE excludes external-origin Patches from
its candidate selection entirely (see [AXE](axe.md)). Press `!o` on a PR row (see
[PR Actions](#pr-actions) above) to open the Mark PR Origin modal and set it explicitly,
or run `sase patch set-origin <name> <sase|external|unknown>` (see
[CLI Reference](cli.md#work-tracking-and-planning)). See
[PR_ORIGIN](change_spec.md#pr_origin) and
[Origin Matching](query_language.md#origin-matching) for the underlying Patch field and
the `origin:` query property.

## Tab Bar Display

The tab bar renders plain tab labels (`Agents`, `Artifacts`, `AXE`). Per-bucket counts
live inside each tab's body — for example the per-panel count summaries on the Agents
tab — rather than as suffixes on the tab title itself.

### Proc Indicator

A blue gear icon (⚙) with a count appears in the top bar when ACE's own procs are
running (e.g., sync, mail, accept, and notification-gate operations). It excludes
monitor shells — see [Monitor Indicator](#monitor-indicator) below. The indicator
automatically hides when all procs complete.

### Monitor Indicator

An amber gear icon (⚙), immediately right of the [Proc Indicator](#proc-indicator),
shows a count of currently running monitor shells (`sase monitor start` supervised
commands). It hides at zero. A monitor is a detached supervisor that survives ACE exit,
so it is counted separately from — and never blocks — ACE's own procs.

### Runners Modal

Press `,R` (leader + `R`) to open the runners modal. It shows concurrency information
including hook runners, agent runners, and a **Procs** section listing active and
recently completed TUI procs from the current ACE session. These include Patch actions,
agent launch and cleanup work, `monitor-stop`, and notification updates. Each row shows
the target, proc type and status, and elapsed or total duration; a failed row also shows
its error message. This modal does not show proc output. Use the Admin Center's
[Procs tab](#procs-tab) or `sase proc show ID` for durable records and captured output.

## File Panel Rendering

Agent files render in full and scroll natively in the file panel. Syntax highlighting
falls back to plain text for large content. Pathological outputs above the file-panel
safety limit show the first 5,000 lines and an explicit editor notice; press `E` to open
the complete content.

## Agents Zoom Panel

Press `Z` on an agent row in the Agents tab to open a near-fullscreen view of the active
detail panel. With a whole tribe panel selected, `Z` opens that tribe's metadata
document instead. Press `=` to isolate the focused tribe panel or restore the previously
remembered panel layout (see [Tribe Side Panels](#tribe-side-panels) above). In the
detail modal, the header shows the available panel tabs (`METADATA`, `FILE`, `TOOLS`)
with the active panel highlighted; use `]` / `[` to cycle those panels with wrap-around.
A tribe zoom exposes only the `METADATA` target, so panel cycling and file paging are
inert there while search, copy, edit, and refresh continue to work.

When the zoom modal shows files, the file list is fixed for the life of that modal so
refreshes cannot add, remove, reorder, or jump the selected file. Use `Ctrl+N` /
`Ctrl+P` to cycle files with first-to-last wrap-around. Multi-file views show a left
rail listing every frozen file entry and marking the active one; single-file views use
the full width for content.

Inside the zoom modal, `/` starts forward search, `?` starts backward search, and typed
queries jump to the first match as you type. Press `Enter` to keep the highlighted
matches, then use `n` / `N` to move to the next / previous match with wrap-around
feedback.

Search covers the complete text behind the zoomed panel, including content beyond the
pathological render cap. `Esc` or `Ctrl+C` cancels an in-progress search; after a search
is committed, `Esc` leaves search and returns to the normal zoomed panel.

## Image Preview Foundation

ACE renders PNG, JPEG, WebP, and GIF attachments with a Pillow-backed Rich cell preview.
The renderer decodes the first image frame, preserves aspect ratio within the visible
panel bounds, composites transparency, and paints colored half-block cells using
truecolor when the terminal advertises it and 256-color approximations otherwise.

Generated images are already attached to successful agent completion notifications and
recorded in `done.json` as `image_paths`. The Agents tab file panel and notification
modal route supported raster image attachments through this preview layer before
attempting text decoding. See [`agent_images.md`](agent_images.md) for supported image
extensions, guardrails, and current preview behavior.

## Agent Auto-Naming

Prompts with no `%id` directive, or with a bare `%id`, use the plain auto-name template
`@`. SASE reserves the lowest available token from the sequence `0`, `1`, ..., `9`, `a`,
..., `z`, `00`, `01`, ...; with no reserved names, plain auto-naming yields concrete
names such as `0`, then `1`.

An explicit `%id` value containing exactly one marker is an agent-name template. The
legacy marker is bare `@`, so the first allocation for `%id:@.cld` becomes `0.cld`,
`%id:build-@` becomes `build-0`, and `%id:research.@.final` becomes `research.0.final`.
Keyed markers such as `%id:research.{@1}.final` are preferred for xprompt swarms: SASE
resolves every matching key in `%id`, `%clan`, `clan=`, waits, fork/resume references,
and prose before any spawned member can start. Bare `@` still works, but template
references use latest-wins lookup and can be unsafe when a swarm member starts after a
newer overlapping launch. See [XPrompt template directives](xprompt.md#directives) for
`{@<id>}` and `{@<id>!}` qualification rules.

Names are permanent IDs: a name used by any existing agent state remains reserved until
that agent is explicitly wiped or deleted. This enables the fork-by-name workflow: press
`f` on a running named agent to queue a follow-up that waits for it to finish and then
loads its conversation history.

### Provider/Model Suffixes

When the same base name is shared by multiple co-launched agents (e.g. multi-model
fan-out via the `%model:` directive), the rendered display name carries a short
`.<provider>` or `.<provider>(<model>)` suffix so each row is distinguishable. Provider
suffixes are supplied by the LLM provider plugins via the `llm_provider_short_name` hook
(built-in defaults: `cld` for Claude, `cdx` for Codex, `agy` for Antigravity).
Additional provider plugins can contribute their own short names. Model-name shorthands
come from the `llm_model_short_aliases` hook (e.g. `fable` for `claude-fable-5`,
`gpt56sol` for `gpt-5.6-sol`; see [Model Short Aliases](llms.md#model-short-aliases))
and are resolved against the configured model so the suffix stays compact regardless of
how the model was spelled in the prompt or config. Single-runtime spawns omit the
suffix.

An explicit `%id:<name>` launch fails before spawning if `<name>` is already reserved.
The prompt is saved as a cancelled history entry and the error suggests the lowest free
numeric suffix, such as `<name>1`. To deliberately reuse a reserved name from the TUI,
launch with `%id:!<name>`; the `!` form confirms that SASE should wipe the previous
owner and then claim the name for the new agent. Reviving and dismissing agents preserve
their stored names.

The durable registry lives at `~/.sase/agent_name_registry.json` and is rebuilt from
visible artifacts plus dismissed bundles when missing or stale. Use
`sase agent names migrate-auto` to run the historical auto-name migration that moves
older generated names into the permanent namespace; pass `--force` to rerun after the
migration marker is present or `--json` for machine-readable output.

### Per-Step Naming for Multi-Agent Workflows

Sequential plan-family workflows have a stable family container plus member suffixes.
When the first follow-up attaches, the original agent is renamed and the bare family
name becomes a pure container. Generated follow-up rows and phase metadata use canonical
double-dash suffixes. For example, if the initial agent was named `a`:

1. The first attachment creates family container `a` and gives the original its
   persisted role suffix (`a--plan` for a plan proposer or `a--0` for a generic agent).
2. The planner phase uses a canonical `--plan` role suffix.
3. Feedback and question-continuation rounds become `a--2`, `a--3`, etc.
4. Terminal follow-ups use the phase suffix, such as `a--code`, `a--epic`, or
   `a--commit`.

The base name (`a`) is reserved for the family as a whole, so `%wait:a` or `@a`
references resolve through the family container. In ACE, the aggregate family row
displays that bare container name, while expanded concrete member rows keep their exact
suffixed names (`a--0`, `a--plan`, `a--code`, and so on). New plan-family metadata
stores double-dash `role_suffix` values (`--plan`, `--2`, `--code`, ...). ACE still
canonicalizes older dotted suffixes (`.plan`, `.2`, `.code`, etc.) and legacy
single-dash suffixes (`-plan`, `-2`, `-code`, etc.) when reading legacy artifacts.

## Agent Statuses

Each agent in the Agents tab displays a status label indicating its current state.
Statuses fall into two categories: active (the agent is still running or awaiting input)
and completed (the agent has finished).

### Active Statuses

| Status             | Color           | Description                                                            |
| ------------------ | --------------- | ---------------------------------------------------------------------- |
| **RUNNING**        | Gold            | Agent subprocess is executing                                          |
| **QUEUED**         | Cornflower blue | Cleared dependency, bead, and time waits; parked for runner capacity   |
| **WAITING**        | Amethyst/purple | Paused on a dependency, bead, or time wait; `?` marks a missing target |
| **WAITING INPUT**  | Amber/orange    | Workflow is paused at a human-in-the-loop (HITL) step                  |
| **TALE**           | Pink/magenta    | An authored tale is waiting for user review                            |
| **EPIC**           | Orchid          | An authored epic is waiting for user review                            |
| **PLAN**           | Pink/magenta    | A legacy or unreadable-tier plan is waiting for user review            |
| **PLAN APPROVED**  | Cyan            | Plan was approved; follow-up agent has been spawned                    |
| **EPIC APPROVED**  | Cyan            | Epic was approved, but no created epic ID has been back-filled yet     |
| **PLAN COMMITTED** | Cyan            | Plan was approved with auto-commit; `--commit` follow-up is running    |
| **QUESTION**       | Amber           | Agent is asking the user a question (via `/sase_questions`)            |
| **RETRYING**       | Orange          | Agent hit a retryable error and is in a countdown before retrying      |

`QUESTION` status survives notification dismissal. While an agent is waiting for an
answer it writes a `pending_question.json` marker into its run directory and temporarily
yields its root runner slot. The marker remains until the agent reacquires capacity
after an answer, or until the agent is killed or crashes. If capacity is full after the
answer, the row becomes a normal runner-slot `QUEUED` row before follow-up work resumes.
Any otherwise-active row whose own run directory contains an unanswered marker is shown
as `QUESTION`, so the "waiting on you" status keeps appearing even after you dismiss the
matching question notification from the inbox. The `,n` shortcut (jump to the open
question) reads the marker directly when no unread notification is left, so it can still
reopen the question modal.

`QUESTION` also propagates up agent families. When a completed row recorded a question
(`questions_times` is non-empty) but has neither a persisted `question_response_path`
nor a later follow-up child, the parent workflow row inherits `QUESTION` so the family
still shows as waiting on you. Once the user response is persisted, the continued work
usually appears as the next numeric phase (`--2`, `--3`, ...); `--q` identifies the
question phase in metadata and phase labels. On the next status pass, the parent is
re-evaluated without the stale question override. If the parent has several active
children, the most recently started one wins, so a newer `RUNNING` child can overtake
the `QUESTION` override on the parent.

The keybinding footer renders available conditional actions as non-breaking key/label
chips. When the chips do not fit on one line, the footer switches to a deterministic
grid so narrow terminals and leader-mode action sets do not wrap in the middle of a
binding. Mode labels such as `LEADER` are pinned on the left, and the axe/status
indicator remains pinned on the right. The status is a segmented badge with a neutral
`AXE` label chip before the colored state chip, so the indicator always identifies the
daemon it describes.

The footer also shows axe daemon status indicators:

| Status         | Color         | Description                                                  |
| -------------- | ------------- | ------------------------------------------------------------ |
| **RUNNING**    | Green         | Axe daemon is running normally                               |
| **STOPPED**    | Red           | Axe daemon is not running                                    |
| **STARTING**   | Yellow        | Axe daemon is starting up                                    |
| **STOPPING**   | Yellow        | Axe daemon is shutting down                                  |
| **RESTARTING** | Deep sky blue | Axe daemon is restarting (triggered by `--restart-axe` flag) |

During TUI startup the footer slot shows a live **starting** stopwatch with a rotating
glyph in place of the daemon status, ticking at ~10 Hz until the TUI finishes mounting
and the real axe status resolves. The background color turns from its normal tone to a
slow-startup tone once the elapsed time crosses the slow threshold, giving immediate
visual feedback on cold-start latency. A safety timeout forcibly retires the stopwatch
if the mount signal never fires.

### Completed Statuses

| Status           | Color | Description                                                      |
| ---------------- | ----- | ---------------------------------------------------------------- |
| **DONE**         | Green | Agent completed successfully                                     |
| **PLAN DONE**    | Green | Plan workflow fully completed (all steps)                        |
| **TALE DONE**    | Green | Tale plan workflow fully completed (all follow-ups)              |
| **EPIC CREATED** | Green | A created epic ID is known, or a legacy epic follow-up completed |
| **FAILED**       | Red   | Agent exited with an error                                       |

Monitor shells are the exception to this status table's success-oriented labels: a
gate-approved epic monitor uses `EPIC APPROVED` as its start label and `EPIC CREATED` as
its stop label for every terminal state. A failed, timed-out, stopped, or lost monitor
can therefore display `EPIC CREATED` in its state-dependent color. Inspect the monitor
state, bucket, exit code, and output; on the planner row itself, `EPIC CREATED` means
the created epic ID was successfully back-filled.

Completed agents can be dismissed with `x` on a single row, or through the `X` cleanup
panel for focused-panel, global, tribe, clan, marked, group, and custom planner-backed
selections. `DONE`, `PLAN DONE`, and `TALE DONE` rows with a saved response path are
resumable from the Agents tab.

When a terminal agent becomes unread, ACE marks it with the completed-agent indicator
and includes it in the Agents header unread count. Selecting that row, jumping to it
with `,j`, or toggling it back to read with `U` acknowledges the row and dismisses the
matching user-agent completion notification. Manually marking a row unread with `U` arms
it for normal acknowledgement after you move away and return, so the marker can be used
as a short-lived reminder without leaving stale inbox entries.

If the currently focused row finishes while you are already on the Agents tab, ACE still
marks it unread and keeps the completion notification active until a real navigation or
selection event acknowledges it. A refresh that merely preserves focus does not silently
consume the unread marker.

The `unread` count in the Agents header is drawn as black text on a gold pill so the
"you still have unseen completed work" signal stands out from the rest of the colored
metrics. It uses the same gold tone as the top-bar notification indicator, giving you a
single color to scan for.

Switching to the Agents tab does not bulk-dismiss completion notifications. ACE projects
active completion notifications onto unread rows, then acknowledges rows one at a time
when you select or navigate into a terminal unread row. Bulk acknowledgement is explicit
through `,u`, which marks loaded unread completed agents read. Plan approvals and user
questions are never auto-dismissed by this flow; they always require explicit `y` / `n`
confirmation from their respective modals.

### Agent Revival

Press `!R` on the Agents tab to revive previously dismissed work. ACE opens the
saved-group revival modal first, showing newest saved groups with a right-hand preview
of included agents, projects, PRs, statuses, provider/model labels, and revival count.
Select a group and press Enter to revive it, choose **Load more saved groups...** to
page older groups, or choose **Custom revival search...** to open the older
dismissed-agent search where you choose all, home, project, or PR scope manually.

Use `m` to mark related Agents-tab rows and then `s` to save and dismiss them as a
group. The save modal accepts an optional human name. Leaving it blank keeps the
generated display title, such as "3 agents from @review" or "2 agents in auth_retry".
Saving a marked group hides the selected rows from the normal Agents tab without killing
running processes. When a marked top-level workflow row has child rows, ACE also
includes the children in the saved group so revival can restore the original tree.

Dismissed agents are saved as individual bundle files under month shards in
`~/.sase/dismissed_bundles/YYYYMM/` and can be restored later. Saved group metadata
lives under `~/.sase/dismissed_agent_groups/` and stores stable references to those
bundle files plus the optional group name, status counts, projects, PRs, model/provider
metadata, and tribes. There is no limit on the number of dismissed agents or saved
groups that can be stored.

Dismiss operations are O(1) per agent: each agent is saved to its own JSON file rather
than a monolithic store. Parent workflow rows use `<raw_suffix>.json`; workflow children
use `<raw_suffix>__c<step_index>.json`. ACE keeps a SQLite summary index in the
dismissed-bundle directory so the revive modal and internal lookups can list dismissed
agents without opening every bundle. Use `sase agent archive verify` to check that
maintenance index, or `sase agent archive rebuild-index` to rebuild it from bundle
files. The index stores metadata such as status, name, project, model, provider,
workflow, and Patch metadata; it is not a full-text copy of agent chat contents.

Revival removes the agent identity from the dismissed set, restores enough artifact
files for ACE to rediscover the agent, and preserves the dismissed bundle as historical
recovery data. Saved-group revival skips missing bundle references with a warning and
restores the remaining agents. Group metadata is not deleted after revival; ACE marks
the group with `revived_at` and increments `times_revived` so the modal can show
previous use. The reload path forces a full-history scan and can hydrate the
just-revived row directly from the bundle, so agents still appear after revive even if
the persistent artifact index was empty or stale.

Every revival also writes structured events to `~/.sase/logs/events.jsonl` (start,
per-agent success, per-agent failure). Read them back with `sase revive-log` — see
[Agent revival audit log](troubleshooting/agent-revival.md) for the record schema and
CLI flags.

#### Legacy Dismissed-Name Prefix

Current dismiss and revive operations preserve stored agent names, per-agent tribes, and
top-level/workflow-child identity. Older dismissed bundles may still contain
`YYmmdd.<base>` names from the previous dismissal model, and ACE keeps compatibility
helpers for reading those bundles. Bare `%wait` (no target) intentionally skips legacy
dismissal-prefixed candidates so it anchors on a live, visible agent.

## Agents Tab Metadata Panel

The Agents tab metadata panel (cycled to via `]`/`[`) shows structured information about
the selected agent:

`Ctrl+J` and `Ctrl+K` cycle forward and backward through the rendered titled sections in
this pane, with the true top of the metadata document as a waypoint before the first
title. On a fresh agent document, the first forward jump selects the first title and the
first reverse jump selects the final title. From the final title, `Ctrl+J` jumps to the
document top and another press selects the first title; from the first title, `Ctrl+K`
jumps to the document top and another press selects the final title. Both directions
share one cursor. Each selected title is aligned with the first visible metadata row,
including a short final section, while the top waypoint reveals any ordinary header
fields before the first title. Only rendered section titles participate; matching text
inside prompts or replies does not. The shortcuts continue to target the metadata pane
when a file or tools pane is also visible, and changing agents or entering/leaving a
pinned attempt view resets the cursor.

- **Agent details**: Name, status, model, provider, Patch association, and
  chronologically sorted timestamps:
  - `Bead` — shown for agents launched by `sase bead work`; modern phase and task rows
    use explicit bead launch metadata, phase rows also use epic/plan metadata and
    validated plan frontmatter, and exact epic plus legacy phase/`.land` rows retain
    compatibility inference
  - `WAIT` — when the agent was spawned (waiting for a slot)
  - `BEGIN` — when runner admission completed, before workspace preparation for
    slot-participating user agents
  - `PLAN` — each plan proposal round (multiple entries when re-planning occurs)
  - `FBACK` — each time the agent requested feedback from the user
  - `QUEST` — each time the agent asked the user a question
  - `RETRY` — each time the agent entered retry state (retryable error)
  - `CODE` — when the agent began writing code
  - `EPIC` — when an epic follow-up agent was launched after plan approval
  - `DONE` — when execution completed
- **CLAN / MEMBERS**: Shown when a synthetic clan row is selected. The orchid heading
  and orchid `Name:` value match the clan row's identity block; the header also shows
  `@tribes`, rolled-up status counts, wall-clock runtime, and agent/family totals.
  Direct member rows use chronological launch order (earliest first), which keeps their
  numbers stable while statuses change. Each numbered row shows the hood-relative
  suffix, kind, status, model, and duration; members of a nested sequential family are
  indented under its aggregate row. `Ctrl+J` / `Ctrl+K` navigate the rendered section
  headings, and pressing the row's number jumps to that member in the Agents list. At
  most 100 members receive numbers.
- **SASE CONTEXT / BEAD**: Shown for epic phase workers and task workers. For an epic
  phase worker, the lane is limited to its selected phase. Its fields are `Phase Title`,
  `Description`, `Size`, `Epic Plan`, and `Epic Title`, in that order. The phase title
  comes from the same validated, frontmatter-ordered phase entry, is normalized to one
  line, wraps losslessly, and renders a quiet `unavailable` for missing, unreadable,
  damaged, or out-of-range entries. Exact validated sizes use literal blue `small`, gold
  `medium`, or rose `large` chips; missing/unreadable/damaged plans, explicit invalid
  sizes, and out-of-range phase ordinals also show a quiet `unavailable` size. Modern
  explicit phase metadata avoids bead-store reads. The parent goal, dependencies, and
  peer phases are never rendered, and the parent plan does not become a generic
  artifact. For a task worker, the fields are `Task Title`, `Description`, optional
  `Notes`, `Size`, optional `+1 Reports` / `+1 Evidence`, and `Created`. A multi-line
  `Notes` value (both bead types) or `+1 Evidence` value (task only) collapses to a
  one-line `N lines (zz to show)` digest at metadata fold level 1 and renders in full at
  levels 2-3; single-line values never fold.
- **SASE CONTEXT / PLAN**: Shown for the epic-authoring planner, epic lander, and task
  workers with a distinct authored plan when direct metadata or a confirmed legacy epic
  association resolves a plan. Phase workers deliberately omit the parent epic lane; no
  goal or peer roadmap phase is rendered. A task bead's own `design` field is never
  rendered as the task worker's `PLAN` lane. For plan-bearing roles, the body rows are
  `Title`, `Goal`, and canonical `Path`, in that order; a tale additionally gets a
  `Size` row between `Goal` and `Path` (the authored `xsmall`/`small`/`medium` chip, or
  a defaulted `medium` chip when the tale's `size` was missing or an over-sized legacy
  `large`/`xlarge` normalized at launch). The lane header carries the effective tier
  (`plan`, `tale`, or `epic`) and an epic's phase count. An `approve` action displays
  `plan`, `tale` and legacy commit-only actions display `tale`, and an `epic` action
  displays `epic`, even when the corresponding commit or launch later fails. Without
  action metadata, a valid authored tale or epic supplies the tier; legacy committed
  plans without a readable authored tier display `tale`, and unresolved values display
  `tier unavailable`. Canonical path selection remains separate: committed paths are
  workspace-relative, while pending or explicitly uncommitted paths use the
  home-shortened machine-local archive. Valid authored epics then show every phase in
  authored order with its title, fixed-width literal size chip, ID, dependency IDs,
  optional model, and optional description; these are static roadmap ordinals, not
  progress indicators. Launch-consumption validation normalizes only an omitted
  historical size to `small`; explicit invalid sizes remain unavailable. The chip stays
  visible while the title and every other value wrap without truncation in the normal
  panel and metadata zoom view, and logical text exposes the same labels to metadata
  search and copy. Only the path participates in file hint mode. Invalid known epics
  show `phases unavailable` in the lane header without leaking partial entries; tales do
  not show a phase roadmap. A plan alone renders `SASE CONTEXT`; across every
  combination of present lanes, the full order is `PLAN`, `BEAD`, `ARTIFACTS`, `MEMORY`,
  `GLOSSARY`, `SKILLS`, then `WORKSPACES`, with absent lanes omitted once they resolve
  and still-resolving lanes holding their slot with a dim `resolving…` row.
- **SASE CONTEXT / GLOSSARY**: Shown directly after `MEMORY` whenever the selected agent
  or family has at least one audited `sase glossary read`. The lane header counts reads
  and distinct requested terms, adding the agent count for a multi-agent family. Each
  row shows the read's requested terms (truncated the same way `MEMORY` truncates
  paths), with a `+N related` suffix when the closure expanded past the requested terms,
  and the recorded reason on its own indented line. A numbered file hint targets the
  term's recorded `source_path` in `sase/sase.yml`. Loading, attribution, and the
  mtime/size snapshot cache mirror `MEMORY`'s reference implementation; the lane is
  skipped rather than rendered empty when there are no reads to show.
- **SASE CONTEXT / ARTIFACTS**: The plan-adjacent output lane groups `Commits`,
  `Deltas`, and `Files` as compact fields, preserves that internal order, and summarizes
  only the present fields in its header. Commits persisted by the selected agent's
  post-run steps are grouped by repository; primary workspace, linked-repo, sidecar, and
  external-repo commits retain their repository identity. Deltas preserve their green
  `+`, gold `~`, and red `-` change glyphs and group linked or external files by
  repository. Artifact type remains visible through its icon shape, while every artifact
  icon and path uses the shared blue output-lane/file-path palette. This lane starts
  painting on the very first navigation frame: `Commits` is derived from the selected
  agent's in-memory step metadata and needs no disk reads, so it renders immediately,
  while `Deltas` and `Files` — which do need store reads — fill in when the debounced
  enrichment resolves the lane. The immediate commit-only view is deliberately not
  cached, so the full lane still resolves on its normal schedule.
- **Slow tool calls**: The metadata header lists tool calls that took 20 seconds or
  longer, ordered by start time and capped at 8 rows (an overflow line points to the
  full [Tools panel](#agents-tab-tools-panel) timeline via `]`). Level 1 is a compact
  triage table: every row keeps its timestamp, state, tool, duration, and a short path-,
  query-, or command-aware digest, while a dim tail reports that full commands are
  hidden. From position 2 upward, each row adds the complete command or target in an
  indented block that wraps with a hanging indent, plus start/end and outcome facts and
  any error. The lane's last position also adds output previews, subagent tool/token
  statistics, and each call's rank and share of selected slow time. These tiers are
  positional: an ordinary agent uses compact/detail/full across its three levels, while
  a family uses compact/full across its two. `za` and `zA` can change only this section.
  For a root agent the list aggregates calls across its children while attributing each
  call to the child that made it.
- **Wait state**: For a `WAITING` agent gated by `%wait`, a duration wait, or an
  absolute-time wait, the detail view shows a tagged `Wait:` block with one lane per
  active dimension: `[agents]`, `[beads]`, `[time]`, then `[runners]`. Present tags
  occupy a padded gutter, so every value begins in one aligned column and long
  dependency lists wrap with a hanging indent beneath that value column. The `[agents]`
  lane lists the dependency names recorded on the waiting agent, adds per-name status
  badges for currently known agents, clan containers, or family containers, and marks
  unknown names with `?` so typos and stale references are obvious. A WAITING list row
  also shows one amber `?` when any named dependency is absent from the current agent
  status snapshot; bead-only, timed-only, and runner-only waits do not receive that
  marker. Timed waits add compact duration, target time, and countdown text when
  available. An explicit runner threshold on a `QUEUED` row shows the live running
  count, threshold, and its `queue #N of M` capacity-aware display rank; `runners=0` is
  labeled as a drain barrier. A `QUEUED` detail uses a separate `Queue:` line led by its
  rank and elapsed time since `slot_requested_at`, followed by cap context. It
  deliberately suppresses the marker's stale dependency, bead, and time-wait fields.
- **OUTPUT VARIABLES**: Small JSON-shaped values written by the selected agent family
  with `sase var set`. Strings, numbers, booleans, null, lists, and nested maps retain
  their types. A single contributing agent renders as a flat sorted key/value block;
  multiple family members render with compact role labels so root, planner, coder,
  tester, and follow-up values stay attributable. Lists, maps, and multi-line strings
  use an indented YAML-shaped block with type-specific colors. The section is omitted
  when the family has not published variables. These values are stored in
  `agent_meta.json`, so they are visible metadata rather than secret storage.
- **AGENT REPLY**: The agent's live or completed reply content, streamed from
  `live_reply.md` during execution and read from the artifacts directory after
  completion. When per-turn reply timestamps are available (recorded in
  `live_reply_timestamps.jsonl`), the reply is displayed with timestamp dividers between
  each agent turn. For agents with follow-up phases (planner, feedback rounds, coder),
  the AGENT REPLY section consolidates replies from all phases into a single view with
  phase dividers showing each phase's label and start time. Agent-shell members follow
  one rule, `AGENT (<role>)`, derived from the member's family role: `--plan` renders as
  `AGENT (plan)`, `--code` as `AGENT (code)`, `--q` as `AGENT (q)`, `--epic` as
  `AGENT (epic)`, `--commit` as `AGENT (commit)`, and numeric feedback suffixes such as
  `--2` as `AGENT (plan round 2)`. Custom family members render the same way with their
  suffix token, e.g. `AGENT (bar)`. A monitor member is a proc shell, so its phase
  renders as an amber `⚙ MONITOR` divider followed by the monitor's command, its
  recorded detail fields, and its full captured output — the same block the monitor's
  own panel shows. Legacy dotted and single-dash suffixes render the same way.
- **WORKFLOW VARIABLES**: xprompt workflow output variables from step outputs with
  additional `meta_*` keys are grouped under a dedicated header. The special routing
  keys `meta_project`, `meta_patch`, and `meta_workspace` are promoted into the normal
  header fields; `meta_changespec` remains accepted as a legacy alias for `meta_patch`.
  Other metadata keys are title-cased and shown in this section.
- **PROMPT**: For agents launched from a multi-agent (`---`-separated) prompt, the
  final, planner, and question transcripts include a `PROMPT:` row linking the saved
  original launch prompt (stored under `~/.sase/.../multi_prompts/`), so the exact text
  that fanned out into every segment stays recoverable.

When the file or tools panel is empty, the `g`/`G` keys automatically fall back to
scrolling the metadata panel.

## Agents Tab Tools Panel

The tools panel sits between the file panel and the metadata panel in the Agents-tab
cycle (`]` advances forward, `[` goes back). It shows a chronological timeline of the
LLM tool calls the selected agent has made — file reads, edits, bash invocations, web
fetches, sub-agent launches, and so on.

Entries are read from the `tool_calls.jsonl` artifact in the agent's run directory. Each
call renders as one timeline row:

- A status label colored by outcome — `ok` (success), `fail` (error), `stop`
  (interrupted), `agent` (sub-agent launch), or `wait` (the post-call record has not
  arrived yet).
- The tool name, optionally followed by a compact target (such as the file path the tool
  acted on) and the call's duration.
- A short preview of the call result on the next line, when the collector captured one.
  Command-output previews keep a marked suffix with at least the final 50 logical lines;
  the character budget is soft so unusually wide trailing lines remain complete. Other
  preview types remain head-oriented.

The panel header shows the total call count, the failure count, the interrupted count,
and a timestamp for the most recent reload. While a background reload is in flight
(because the artifact changed on disk), `(refreshing...)` appears next to that
timestamp. The body shows `No tools artifact available` when the file does not yet exist
for this agent and `No tool calls recorded` when the file exists but contains zero
records.

For retry chains and planner-to-coder follow-up families, the panel aggregates
`tool_calls.jsonl` from related artifact directories so the selected logical agent shows
one ordered tool timeline. Discovery uses the persistent artifact index when it is
available; if the index is missing or stale, ACE falls back to direct lineage pointers
plus a bounded scan of nearby legacy sibling artifacts.

Records are produced by writers that share one normalized on-disk format. Claude uses
the SASE tool-call hook collector as the preferred source and keeps its stream-derived
parser as a fallback when hooks are unavailable. Codex writes equivalent rows from its
`codex exec --json` stream with `runtime: "codex"` and `source: "stream"`; current Codex
start/completion events can show pending rows, result previews, failures, interruptions,
and durations, while older completed-only `function_call` rows remain readable with more
limited detail. Qwen writes stream-derived rows from its `--output-format stream-json`
output with `runtime: "qwen"` and `source: "stream"`; start/completion (and Qwen's
`tool_use` / `tool_result`) pairs collapse into single rows the same way Codex pairs do.
Muse Code writes stream-derived rows from its `muse exec --json` JSONL stream with
`runtime: "muse"` and `source: "stream"`; proposed/scheduled and `tool.result` pairs
collapse into single rows like the others. Muse's stream never carries tool _arguments_,
so a Muse row's input target comes from `edit_facts.path` for edits, the parsed command
for `bash`, and otherwise a bounded preview of the result text — SASE does not invent
arguments Muse did not emit. Antigravity (`agy`) runs in plain-stdout mode; SASE never
scrapes display prose, but supported Antigravity versions may contribute guarded
`source: "trajectory"` rows from the local trajectory DB. When that extractor is
unavailable, the panel simply shows nothing for `agy` runs. Grok Build writes
stream-derived rows from its `streaming-messages-json` output with `runtime: "grok"` and
`source: "stream"`; Grok's native tool names (`run_terminal_command`, `read_file`,
`search_replace`, and so on) are mapped onto the same canonical display names Claude
rows use, and its JSON-encoded `tool_result` envelopes are decoded for exit codes and
file paths rather than shown raw. See
[LLM Providers — Claude tool calls](llms.md#claude-tool-calls),
[LLM Providers — Codex tool-call capture](llms.md#codex-tool-call-capture),
[LLM Providers — Qwen tool-call capture](llms.md#qwen-tool-call-capture),
[LLM Providers — Muse tool-call capture](llms.md#muse-tool-call-capture),
[LLM Providers — Antigravity (`agy`) Integration](llms.md#antigravity-agy-integration),
and [LLM Providers — Grok Tool-Call Capture](llms.md#grok-tool-call-capture) for
provider integration details.

## Plan Workflows

When an agent submits a plan via `/sase_plan` (or `sase plan propose`, including the
`%auto:epic` path), it enters a planning phase before executing:

- **TALE** / **EPIC** — The agent has submitted an authored tale or epic and is waiting
  for user review. Tales are pink/magenta; epics are orchid. **PLAN** is the
  compatibility fallback when the authored tier cannot be resolved.
- **PLAN APPROVED** — The plan has been approved and the follow-up agent has been
  spawned. Shown in cyan/turquoise.
- **PLAN REJECTED** — The plan was rejected. A no-feedback rejection from ACE or
  `sase plan reject` writes the rejection response first, then attempts to dismiss the
  notification, user-kill the matching planner, and persist dismissed-agent state so the
  row is hidden on refresh. If the matching row is already gone, the plan is still
  rejected. Rejected archived plans can still appear in history-oriented views, and
  redundant completion notifications are suppressed.

Plan files generated by the agent are displayed in the file panel alongside other agent
artifacts. Plan approval notifications include the LLM provider and model name, so users
can see which model proposed the plan (visible in both the TUI notification modal and
Telegram delivery).

ACE's arrival toast names the authored tier — **Tale ready** or **Epic ready** — instead
of using a generic Plan label. An epic toast adds the validated phase count, dependency
wave count when available, and the non-zero per-size counts (`XS`, `S`, `M`, `L`, and
`XL`). Those values are captured when the approval gate is created, so a notification
that is snoozed and later resurfaces keeps its original summary even if the bundled plan
was edited meanwhile. Batched warning toasts likewise count tales and epics separately.

When `sase plan propose` writes the plan, it also touches `~/.sase/.ace_refresh_pulse`
to wake any running TUI immediately — the tier-aware `TALE` or `EPIC` status (or
fallback `PLAN`) appears without waiting for the next auto-refresh tick. The pulse file
is consumed by the inotify artifact watcher (see [Auto-Refresh](#auto-refresh)) and is
harmless if no TUI is open.

Root plan workflows also surface their tier-aware pending status when a re-proposed plan
is still awaiting review. Plan and feedback timestamps from feedback-round children
(`--2`, `--3`, ...; legacy `-2`, `.2`, etc.) propagate onto the root entry, and whenever
the root's latest plan timestamp is newer than its latest feedback timestamp the
override engine restores `TALE`, `EPIC`, or fallback `PLAN` over a `RUNNING` or `DONE`
label. This applies only to root plan workflows that have not yet spawned a terminal
follow-up (`--code`, `--epic`, ...); once a terminal follow-up is launched, the parent
moves on to `PLAN APPROVED` (or the matching follow-up status) instead.

The Plan Review modal title shows a provider-themed `PROVIDER(model)` badge between the
"Plan Review" label and the plan filename — orange for Claude, lime for Codex,
Antigravity indigo (`#6E5DE7`) for agy, neutral muted for other providers. The badge is
omitted when provider/model metadata is absent, leaving the legacy title shape
unchanged.

Whole-document Markdown previews in plan, launch, and custom-gate review modals
highlight leading YAML frontmatter as YAML and the remaining body as Markdown.
Highlighting does not alter validation or the reviewed file contents.

For tale plans, the modal's primary **Approve** decision includes two independently
selectable add-ons: **Commit plan file to the plans sidecar** and **Run coder
follow-up**. Both are selected by default. Press `enter` to approve with the current
checkbox selection; the existing `a`, `t`, `c`, `r`, `f`, and `E` bindings remain as
compatibility shortcuts for their common presets and alternate flows.

The same pending approvals are available from the CLI. Run `sase plan` to see pending
proposals, recent approvals, and inferred rejected archived plans; run
`sase plan approve <id-prefix> --kind approve|commit|epic|tale` or
`sase plan reject <id-prefix>` to write the same response protocol used by the TUI
modal. Use the `id_prefix` from a Proposed row; if the selector is omitted, the CLI acts
only when exactly one proposal is pending. Omitting `--kind` uses the plan's authored
tier. In the Plan Review modal, `enter` uses that same authored-tier default; `a`, `t`,
and `E` remain explicit overrides. `approve` starts the coder without committing an SDD
plan, `tale` commits the plan as an SDD tale and starts the coder, `epic` commits the
matching SDD tier and launches the bead follow-up, and `commit` records the approved
plan in SDD without launching a coder. `-m/--model` picks the follow-up agent's model,
while `-p/--prompt` adds extra coder instructions for the `approve` and `tale` paths.
Tale and epic choices validate the plan against the target schema before consuming the
approval; failures surface an error and keep the notification actionable. CLI rejection
also attempts the durable planner cleanup used by no-feedback TUI rejection.

For active Agents-tab rows, `A` opens the **Auto-Approve menu**, a single-key modal that
configures how the agent's _next_ submitted plan is auto-approved. The agent's current
state is marked with `▸`; pressing `p` (Plan — approve the plan as-is), `t` (Tale —
approve and commit as a tale), `e` (Epic — approve and commit as an epic), or `d`
(Disable — turn off auto-approval) applies the change immediately, while `esc`/`q`
cancels. The selected state shows on the agent row as a `⚡` (plan), `⚡T` (tale), or
`⚡E` (epic) icon. For plan submissions, these choices correspond to the plan-adapter
behavior of `%auto`, `%auto:tale`, and `%auto:epic` respectively — for example, epic
auto-approve accepts the next submitted plan as an epic, writes SDD epic artifacts,
initializes beads, and launches the epic follow-up agent. The menu only configures plan
auto-approval; unlike bare `%auto`, it does not automatically answer questions or
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

Pressing `c` in the plan approval modal opens a custom approval dialog. Choose the
approval outcome directly: Approve, Tale, or Epic. These choices map to the same
response protocol used by external approval transports: Approve runs the coder without
asking the runner to commit an SDD plan, while Tale and Epic commit the plan under the
matching tier in the resolved SDD plans root's `<YYYYMM>/` directory. The root may be
in-tree, a legacy `.sase/sdd/` clone, or the split `--plans` sidecar;
`sase repo path plans` prints it.

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

The dialog keeps the custom coder prompt and follow-up model controls for Approve and
Tale. Epic approval reads its land and phase models from structured plan frontmatter and
launches bead work directly, so those controls are hidden for Epic:

- **Additional prompt** — Optional extra instructions for the coder follow-up. It is
  used by Approve and Tale.
- **Coder model** — Select an LLM model for the next follow-up agent instead of using
  the role default. For Approve and Tale that agent is the coder. Shows all registered
  models grouped by provider (Claude, Codex, Antigravity, Qwen, OpenCode, Muse Code,
  Grok Build) with a "Custom..." option for freeform input. A model its provider flags
  with an advisory carries a warning-styled `⚠ <label>` suffix on its row (`ⓘ` for
  informational advisories), with the full advisory sentence in the row's secondary text
  — this is where somebody actually chooses a model, so the trade is impossible to miss.
  See [LLM Providers — Model advisories](llms.md#model-advisories). Type to filter by
  provider, model id, label, or short alias; use `j`/`k` or arrows to navigate, `Enter`
  to select, `Esc` to clear the filter or cancel, and `'` for jump hints over the
  visible selectable rows. The displayed default resolves to the model the handoff will
  actually use: for Approve and Tale, the validated tale size selects the corresponding
  `@<size>` alias directly, with legacy sizeless tales using `@medium`. Selecting a
  specific model and then re-opening the picker and choosing "Follow-up default" resets
  the follow-up back to that role default (distinct from pressing `Esc`, which keeps the
  current selection).

The custom approval dialog no longer exposes separate commit/run switches because the
selected outcome determines the commit location and follow-up behavior. Additional
family members are launched explicitly with `%i(suffix, family=parent)`; they are not
selected at the plan gate.

## Launch Approval

Launches requested by a running agent (see
[Agent-initiated launches](agent_families.md#agent-initiated-family-launches)) arrive as
priority notifications with a `LaunchApproval` action. Selecting one opens the launch
approval modal, which renders the request's human-readable preview
(`launch_preview.md`). Clan slots identify their rootless clan alongside the model,
kind, and planned member name. Press `a` to approve, `r` to reject, and `q` or `Esc` to
cancel. ACE resolves the same hash-verified command bundle used by mobile and remote
callbacks, while retaining legacy launch-request fallback. The CLI equivalents are
`sase launch approve <selector>` and `sase launch reject <selector>`.

## Linked Chats in Multi-Step Workflows

When a workflow spawns multiple agents (e.g., a planner step followed by a coder step),
the chat history files for each step are cross-linked via a `## Linked Chats` markdown
section. This section is inserted near the top of each chat file and lists all related
agents with their roles and file paths, making it easy to trace the full workflow from
any individual agent's chat history.

For example, a plan-then-code workflow produces chat files with:

```markdown
## Linked Chats

- **1. planner** — `/path/to/planner_chat.md`
- 2. coder — `/path/to/coder_chat.md`
```

The current agent's entry is bolded for quick identification.

## Retry/Fallback Display

When an agent encounters a retryable error (configured via `llm_provider.retry`), the
Agents tab shows retry state:

- **RETRYING** — Shown in bold orange when waiting before the next retry attempt.
  Includes a countdown timer: `RETRYING (45s)`.
- **↻N** — Shown after the status for running agents that have retried. The number
  indicates how many retries have occurred (e.g., `↻2` means two retries so far).
- **▸Model** — Appended to the retry annotation when the agent has fallen back to an
  alternate model (e.g., `↻3▸flash`).

### Prior Agent Attempts

Every time the axe retry loop retries an agent — context-limit retry, provider/API-error
retry, user-configured retry, or fallback-model switch — the failed attempt's partial
reply, error text, timestamps, and model are snapshotted under
`<artifacts_dir>/attempts/<N>/`. The AGENT REPLY area in the Agents tab renders these
prior attempts inline with styled dividers before the current/final attempt, so the full
arc of the agent's work stays visible in one scroll.

ACE hydrates prior-attempt history lazily. Normal Agents-tab refreshes do not enumerate
every `attempts/<N>/` directory; the selected detail panel, `D` attempt-view toggle, and
content search hydrate the needed attempt records on demand.

Press `D` to collapse the view to the current attempt only; press `D` again to
re-expand. The binding only appears in the keybinding footer when the selected agent has
one or more prior attempts.

## Custom Keymaps

All TUI keybindings are configurable via the `ace.keymaps` section in `sase.yml`. You
can remap app-level, gate-modal, Glossary-panel, and focused Statistics-pane keys and
define entirely new prefix-key modes.

### Remapping Built-in Keys

Override any app-level keybinding under `ace.keymaps.app`:

```yaml
ace:
  keymaps:
    app:
      next_patch: "n" # Remap j -> n
      prev_patch: "p" # Remap k -> p
      edit_query: "f5" # Every Artifacts query pane
      show_notifications: "N" # Remap i → N
```

The Agents structured-query shortcut is independent: remap
`ace.keymaps.modes.leader_mode.keys.edit_query` to change the subkey after the
configured leader prefix. Bare Agents metadata search remains under
`ace.keymaps.app.search_forward`.

### Remapping Statistics Pane Keys

Override focused Statistics bindings under `ace.keymaps.statistics`:

```yaml
ace:
  keymaps:
    statistics:
      prev_view: "left_square_bracket"
      next_view: "right_square_bracket"
      select_view: "0"
      jump_to_entry: "apostrophe"
      cycle_range: "f11"
      cycle_range_reverse: "shift+f11"
      custom_range: "c"
      cycle_group: "g"
      cycle_project_filter: "p"
      cycle_project_filter_reverse: "P"
      focus_xprompt: "x"
      clear_xprompt_focus: "X"
      scroll_down: "ctrl+d"
      scroll_up: "ctrl+u"
      refresh: "f10"
      help: "f9"
```

The example above names every Statistics binding, but only some are remapped: it shows
`cycle_range`, `cycle_range_reverse`, `refresh`, and `help` moved off their `t`, `T`,
`r`, and `?` defaults, and repeats the defaults for the rest. Override only the keys you
want to change.

These keys dispatch only while the Admin Center Statistics pane is focused. They may
overlap app-level bindings without creating a global conflict, and the pane's hint bar
always shows the effective keys. Press the configured `select_view` prefix and then
`1`–`8` to select the matching numbered view; bare digits continue to switch the Admin
Center's top-level tabs. `jump_to_entry` arms that same numbered-view selection, which
is how the Admin Center-wide `'` behaves on a pane that has no row cursor to jump
between — the visible strip numbers serve as its hints. The group control is visible and
active only in Projects, XPrompts, and Perf. On the XPrompts view, the focus key opens a
filterable picker and the clear-focus key restores **All xprompts**. Project filtering
cycles through **All projects** and the latest cached unfiltered ranking: the configured
forward key moves toward the first ranked project, the reverse key moves toward the
last, and both wrap. Either key clears an active project filter directly when its loaded
result is empty.

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

These bindings dispatch only while a branch-driven gate modal is open, and its footer
shows the effective keys. The retired `activate_control` setting is accepted as a
deprecated alias for `submit_primary`.

### Remapping Glossary Panel Keys

Override [Glossary panel](#glossary-panel) bindings under `ace.keymaps.glossary`. A
value may list more than one key, separated by commas:

```yaml
ace:
  keymaps:
    glossary:
      follow_relation: "enter,l"
      travel_back: "backspace,h"
      filter_terms: "slash"
      toggle_definition_filter: "full_stop"
      add_term: "a"
      delete_term: "d"
```

These bindings dispatch only while the panel is open. The full action list and defaults
are in the [`ace.keymaps` configuration reference](configuration.md#acekeymaps).

### Custom Modes

Define user-defined prefix-key modes under `ace.keymaps.modes`. Each custom mode has a
`prefix` key and a `keys` dict where each sub-key specifies either a `shell` command or
a built-in `action`:

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

Pressing `;` activates the mode, then pressing `t` runs `just test`, `l` shows the git
log, etc.

### Validation

The keymap loader validates all configuration:

- **Invalid keys** are reverted to their defaults with a warning
- **Duplicate keys within one binding scope** are detected and the conflicting override
  is reverted
- The contextual Agents `search_forward` and non-Agents `edit_query` actions may
  intentionally share a key
- **Prefix conflicts** between custom mode prefixes and existing app bindings are warned

See [`docs/configuration.md`](configuration.md) for the full `ace.keymaps` configuration
reference.

## Prompt Input Widget

The prompt input is a multiline TextArea widget with vim-style INSERT, NORMAL, VISUAL,
and V-LINE modes. The widget provides markdown syntax highlighting for prompt content
(headings, bold, italic, code blocks, lists, etc.). The first dash of an unindented or
space-indented `- ` bullet, and the digits plus delimiter of an unindented or
space-indented `<N>.` / `<N>)` ordered marker, are additionally bolded with the same
theme-aware accent, including inside fenced code; this presentation does not change the
prompt text. A tab-indented dash or ordered marker is not treated as a list marker.

When loaded prompt text contains literal top-level `---` multi-agent separators, ACE
renders the text as a prompt stack: one pane per agent segment. YAML frontmatter at the
start stays prompt-level metadata, and `---` lines inside fenced code blocks are left
alone. A `#name` xprompt swarm invocation stays a single pane and expands only when it
is launched. During live editing, typed `---` lines stay literal text; add prompt panes
with `g-` in prompt NORMAL mode. The detailed multi-agent parsing rules live in the
[XPrompt reference](xprompt.md#multi-agent-prompts).

### Cursor Readout

Every mounted pane advertises its cursor position as `Ln <line>, Col <column>`, both
1-based and counted in document columns (the character index within the logical line,
not the soft-wrapped screen column). The active pane's readout sits flush right on the
bar's bottom border, next to the mode hints; each parked pane's readout sits on the
right end of its own `─── ▍ agent N ───` separator rule. The digits are painted the
color of that pane's own vim-mode cursor -- gold for NORMAL, cyan for INSERT, magenta
for VISUAL / V-LINE -- so the readout and the cursor it describes always match. On a
narrow terminal the active-pane readout always wins over the mode hints (which truncate
first); a parked pane's readout is dropped entirely rather than abbreviated if its
separator cannot fit both the readout and the `agent N` label.

### INSERT Mode (Default)

| Key                          | Action                                                                                                                                   |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `Enter`                      | Submit; in a prompt stack, open the submit chooser                                                                                       |
| `Ctrl+S`                     | Stash the active pane; from an empty prompt, open the stashed-prompt picker                                                              |
| `Ctrl+G Enter`               | Submit only the selected pane                                                                                                            |
| `Ctrl+C`                     | Cancel the prompt; in a prompt stack, cancel only the selected pane                                                                      |
| `Ctrl+J`                     | Insert a newline; continue a containing `- ` bullet or `<N>.` item (renumbered), or leave the list from an empty marker                  |
| `Ctrl+A`                     | Move to start of line (jumps to previous line start if already at col 0)                                                                 |
| `Ctrl+E`                     | Move to end of line (jumps to next line end if already at end)                                                                           |
| `Ctrl+G`                     | Start the prompt-local prefix; press `g` or `Ctrl+G` again to open `$EDITOR`                                                             |
| `Ctrl+G Enter`               | Submit only the selected pane                                                                                                            |
| `Ctrl+G j/k`                 | Focus the next / previous pane and leave the target pane in INSERT mode                                                                  |
| `Ctrl+G J/K`                 | Move the active pane down / up and leave it in INSERT mode                                                                               |
| `Ctrl+G -`                   | Add an empty bottom pane                                                                                                                 |
| `Ctrl+G G`                   | Open the Glossary panel; seeds from the glossary term under the cursor when there is one                                                 |
| `Ctrl+G d`                   | Edit the xprompt definition under the cursor in the prompt bar                                                                           |
| `Ctrl+G f`                   | Reformat the active prompt pane's Markdown with Prettier                                                                                 |
| `Ctrl+G w`                   | Write a bound xprompt definition; unbound drafts fall through to save-as                                                                 |
| `Ctrl+G =`                   | Show/focus the xprompt frontmatter panel; its rows-mode `g=` returns to the originating pane                                             |
| `Ctrl+G s`                   | Bundle every non-empty pane into one stash row                                                                                           |
| `Ctrl+G S`                   | Overwrite a pinned stashed prompt with the current stack                                                                                 |
| `Ctrl+G x` / `Ctrl+G Ctrl+X` | Save as reusable xprompt/snippet; xprompt mode converts raw `<tags>`                                                                     |
| `Ctrl+G t`                   | Open a new/rename-in-place snippet target pane (see [Authoring a snippet from the prompt bar](#authoring-a-snippet-from-the-prompt-bar)) |
| `Ctrl+G X`                   | Convert the active pane into a frontmatter-local xprompt; raw `<tags>` become inputs                                                     |
| `Ctrl+G Ctrl+C`              | Cancel every pane in the prompt stack at once                                                                                            |
| `Ctrl+G p`                   | Open the stashed-prompt picker                                                                                                           |
| `Ctrl+Y`                     | Open the workflow YAML editor                                                                                                            |
| `Ctrl+K`                     | Open prompt history from a single-line prompt, pre-filtered by that text                                                                 |
| `Ctrl+P`                     | Cycle toward older workspace MRU prefixes, including a no-prefix stop before wrapping                                                    |
| `Ctrl+N`                     | Cycle toward newer workspace MRU prefixes, including a no-prefix stop before wrapping                                                    |
| `Ctrl+T`                     | Completion (structured tokens, paths, prompt-local words, or history words; see [Completion](#completion))                               |
| `Ctrl+R`                     | Recursive fuzzy file finder using the same prompt-aware path root as file completion                                                     |
| `Tab`                        | Expand a snippet or advance its tabstop; otherwise indent a bullet or nest an ordered item under a preceding marker                      |
| `Shift+Tab`                  | Retreat to the previous snippet tabstop; otherwise dedent a bullet or unnest an ordered item into its enclosing run                      |
| `#@`                         | Open XPrompt snippet picker (type `#` then `@`)                                                                                          |
| `Escape`                     | Switch to vim NORMAL mode                                                                                                                |

In prompt INSERT mode, ACE auto-pairs safe openers for `()`, `[]`, `{}`, `<>`, single
quotes, double quotes, and backticks. Typing the matching closer over an auto-inserted
closer moves the cursor across it instead of duplicating it, and backspace or delete
removes both sides of an empty pair. Pairing is conservative: it is suppressed before
token characters, when text is selected (the typed character replaces the selection
literally), for contractions or possessives, and for repeated quotes/backticks needed to
type Markdown fences or code spans.

INSERT-mode `Ctrl+J` and prompt NORMAL-mode `o` / `O` continue a containing
space-indented `- ` bullet using that bullet's indentation. Prompt NORMAL-mode `J` is
the inverse operation: when it folds the next line into a nonblank current line, it
drops that line's supported `- ` marker. Bullet continuation also works from physical
continuation lines, including Prettier-wrapped nested bullets; non-bullet lines keep the
ordinary bare newline or open-line behavior. In INSERT mode, when there is no selection,
pressing `Ctrl+J` anywhere on a line containing only zero or more leading spaces
followed by `- ` replaces that marker with a bare newline and moves the cursor to column
zero, ending the list -- but only when the line above that marker is itself part of a
hyphen bullet. The common sequence is therefore `Ctrl+J` once to create the next sibling
marker and `Ctrl+J` again to exit the list. A marker-only line whose preceding line is
not part of a bullet -- a freshly typed `- ` on the first line, or one following a blank
line or plain prose -- grows a sibling marker on the next line instead, so the exit
still happens on the following press. Those two edits are separate undo checkpoints. A
selection uses the normal replacement path instead. Extra spaces after the marker, tab
indentation, other Markdown markers, and markers containing text do not trigger either
path.

Ordered items (`<N>.` or `<N>)`, one to nine digits) mirror every one of those hyphen
rules for `Ctrl+J`, `o`, `O`, and `J`, and add the one thing ordered lists need: after
each structural edit, ACE renumbers the surrounding _run_ -- the maximal sequence of
same-indent, same-delimiter siblings, joined across blank lines and each item's own
owned continuation lines -- so the live numbers agree with what `gf` (Prettier
formatting) would produce. When a run's second item repeats the first item's number,
every item in the run keeps that number (the `1. / 1. / 1.` convention Prettier
preserves); otherwise later items are numbered sequentially from the first item's start.
`Ctrl+J`, `o`, and `O` give a newly inserted item the number after its nearest preceding
sibling, or the run's first number when there is none. `J` drops the pulled-up marker
and renumbers the run it left behind. A renumber that changes a marker's width (`9.` ->
`10.`) shifts every line that item owns by the same amount so indentation stays correct,
and leading zeros (`007. `) are recognized as a marker but always renumber to plain
decimal.

In INSERT mode, `Tab` and `Shift+Tab` do snippet work before list shifting. `Tab` first
expands a trigger word immediately before the cursor, then advances to the next live
snippet tabstop. `Shift+Tab` first retreats to a previous live tabstop. When that
snippet action reports no movement or expansion, the selection is collapsed, and the
cursor is anywhere on a direct marker line beginning with zero or more spaces followed
by `- `, ACE indents or dedents that bullet. Each press shifts only that logical line by
the same two-space unit as vim `>>` / `<<`; dedent removes up to one unit, and the
cursor follows the shifted content. Physical continuation lines, tab indentation, and
other Markdown marker styles are excluded.

The same fallback applies to ordered items from anywhere on the direct `<N>.` / `<N>)`
marker line. Ordered `Tab` nests at the _content column_ of the nearest preceding marker
line (either family, same or lower indent) instead of a fixed two-space unit, because an
ordered item can only interrupt its parent's paragraph when numbered `1`: `Tab` with no
preceding marker line to nest under is a no-op, `Tab` landing under an existing nested
run continues that run at its next number, and `Tab` that starts a new nested list
numbers the moved item `1`. `Shift+Tab` moves the item back out to its parent's indent
and gives it the next number in that outer run; at the outermost level it is a no-op.
Both carry the item's owned block along and renumber the source and destination runs as
one undo checkpoint.

Text automatically wraps at the terminal width, breaking at spaces (never mid-word).
Line numbers appear in cyan when the text exceeds one line. The native cursor cell is
color-coded by prompt Vim mode: INSERT uses cyan, NORMAL uses gold, and VISUAL or V-LINE
uses magenta.

Uppercase `TODO` at identifier boundaries is a visual draft marker. ACE gives `TODO`,
`TODO:`, `TODO(owner)`, and `TODO(owner):` headers the exact `#FFD700` gold used by the
Agents-tab `RUNNING` status with explicit deep navy `#00005F` text. The deep navy stays
legible on gold without relying on the terminal's customizable ANSI black palette entry.
Only a header ending in `:` activates the quiet, theme-aware warm italic annotation
style for the rest of that line; punctuation and prose after bare `TODO` or
`TODO(owner)` retain their ordinary prompt syntax. When the first content in a dash-list
item is the exact `TODO:` header, the body style continues through lazy and indented
continuation lines, nested list content, and later paragraphs that Markdown assigns to
that item. It stops at the sibling-item or outside-content boundary, and structural list
dashes keep their bullet color. Checklist prefixes, `TODO(owner):`, and a `TODO:` later
in item prose retain the same-line behavior.

Inline backtick spans and closed or live unclosed backtick/tilde fenced code blocks are
literal zones: TODO-shaped text inside them receives no marker or body treatment and is
omitted from the count. Ordinary quotation marks are not code delimiters. Lowercase
`todo` and identifiers such as `TODOS`, `TODO2`, and `preTODO` remain ordinary text.
When markers exist, the prompt border shows a matching deep-navy-on-gold `TODO N` count
pill for every non-literal match across the full prompt stack, including compact
inactive panes and markers outside the active viewport. The pill disappears immediately
when the last marker is edited away.

TODO treatment does not move the cursor during history or stash restoration, and ACE
stashes and opens the literal prompt text in `$EDITOR` unchanged. Submitting an agent
prompt with one or more visible TODO markers opens a neutral y/n confirmation with
**Keep editing** focused by default. Keeping the draft preserves the exact prompt or
prompt stack without launching or writing history; approving launches the same literal
prompt text unchanged. The warning uses the same detector as the gold marker and count
pill, so TODO-shaped text in inline or fenced code, lowercase `todo`, and non-boundary
identifiers such as `TODOS`, `TODO2`, and `preTODO` do not trigger it. Feedback and
coder-prompt submission keep their existing unguarded behavior. Only the
colon-terminated body-note color follows the active dark or light theme, while the
shared deep-navy-on-gold header and count pill remain fixed; search matches, selections,
yank feedback, and the cursor retain their higher-priority treatments.

### Raw Placeholder Inputs

Raw `<placeholder>` tags in the ACE prompt bar act like ad hoc prompt inputs. When you
submit a prompt containing one or more highlighted raw tags, ACE opens the **Prompt
Inputs** panel before launch. The panel lists each unique tag once, shows a one-line
context snippet and an occurrence count, and collects values on the same page as any
required frontmatter-declared `input:` arguments. After confirmation, ACE substitutes
the collected values into the prompt and records history for the resolved prompt that
the agents actually received.

Inline backtick spans, fenced code blocks, and `%xprompts_enabled:false` regions are
literal zones. Tags inside those zones are not highlighted as raw placeholders, recorded
in the saved common-placeholder store, or collected on submit. Their text is still
offered as a current-prompt completion candidate, ranked after live tags. Use backticks
when a tag-like value is meant to survive literally, for example
``keep `<div>` unchanged``.

Each raw placeholder row must be filled before launch unless it is marked literal. Press
`Ctrl+L` in the Prompt Inputs panel to toggle **keep literal** for the focused
placeholder row; when focus is outside the field list, `Ctrl+L` marks all still-empty
placeholder rows literal. A literal row counts as filled and leaves its original
`<placeholder>` text in the launched prompt.

Set `ace.prompt_inputs.collect_raw_placeholders: false` to stop collecting raw tags on
submit; declared frontmatter inputs are still collected. Set
`ace.prompt_inputs.xprompt_placeholder_args: false` to keep live raw tags literal when
using `gx` or `gX` and mint no placeholder-derived `text` inputs; Jinja-variable
inference for `gX` still runs. See
[Raw Prompt Placeholders](xprompt.md#raw-prompt-placeholders) for the exact conversion
and naming rules.

### Prompt Stacks

Prompt stacks are the ACE editing surface for literal `---` multi-agent prompts. Loading
multi-agent prompt text from history, a whole-bar editor session, or an editor buffer
that returned with a ` @` review marker splits top-level `---` segment separators into
panes labeled `agent 1`, `agent 2`, and so on; the border title shows
`Prompt · N agents`. Restoring stashed prompts and using marked-agent `,x` can also open
a stack, but those paths load one pane per selected draft or agent instead of re-parsing
each pane's text. Panes are ordered top-to-bottom for whole-stack submission. The bottom
pane is active by default so you can keep drafting the newest segment; it is not a
priority marker, and pressing `Enter` immediately opens the submit chooser.

Inactive panes stay compact, and the active pane takes the available height; each parked
pane's separator rule also carries a live [cursor readout](#cursor-readout) of that
pane's own position. A `---` line typed while INSERT mode is active stays literal prompt
text; use `Ctrl+G -` while drafting, or `g-` from prompt NORMAL mode, to add a new
bottom pane. `Ctrl+G g` and `Ctrl+G Ctrl+G` open the whole stack in `$EDITOR` when the
bar already has multiple panes (a single-pane bar opens just the current prompt).
Returning from a whole-bar editor session, or from a single-pane editor buffer with a
` @` review marker, reloads xprompt-style Markdown and parses `---` separators into
fresh panes. History loads parse only real multi-agent prompts; a single history item
with leading YAML frontmatter stays one verbatim pane instead of auto-opening the
Frontmatter Panel.

A single-pane editor session normally launches the moment you close `$EDITOR`. To review
it in the prompt bar first, end any line of the buffer with the exact suffix ` @` (a
space followed by `@`). On return, that marker is stripped from every matching line and
the cleaned text reloads with editor-file semantics: leading xprompt frontmatter is
lifted into the Frontmatter Panel and real `---` separators split into one pane per
agent, so a marked multi-agent buffer comes back as a reviewable stack instead of
launching. The marker is editor-return-only — typing ` @` in the prompt bar and
submitting carries no special meaning. (This replaces the removed `%edit` directive.)

In prompt INSERT mode, pressing `Ctrl+G` opens the same context-aware hint row as prompt
NORMAL mode's `g` prefix, plus the editor continuation. Press `Esc` while the prefix is
pending to cancel it and stay in INSERT mode.

In prompt NORMAL mode, pressing `g` opens a small hint row for the prompt-local `g`
prefix actions currently available.

| Key         | Action                                                                                                                                   |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `Enter`     | Open the submit chooser when stacked or targeted; an untargeted single pane sends normally                                               |
| `Ctrl+S`    | Stash the active pane; from an empty prompt, open the stashed-prompt picker                                                              |
| `g<enter>`  | Launch the selected pane and remove it from the stack                                                                                    |
| `Ctrl+C`    | Record the selected pane as cancelled history and remove it; the final remaining pane cancels normally                                   |
| `Escape`    | Enter NORMAL mode for stack navigation                                                                                                   |
| `gj` / `gk` | Focus the next / previous pane in NORMAL mode; inside the panel, jump to the top / bottom prompt pane                                    |
| `gJ` / `gK` | Move the active pane down / up in NORMAL mode; reorder cycles at the stack edges                                                         |
| `g-`        | Add an empty bottom pane in NORMAL mode and switch it to INSERT mode                                                                     |
| `gG`        | Open the Glossary panel; seeds from the glossary term under the cursor when there is one                                                 |
| `g=`        | Show/focus the xprompt frontmatter panel; in panel rows mode, return to the originating prompt pane                                      |
| `gs`        | Bundle every non-empty pane into one stash row and dismiss the prompt bar                                                                |
| `gS`        | Overwrite a pinned stashed prompt with the current stack, leaving the bar open                                                           |
| `gw`        | Write a bound xprompt definition; unbound drafts fall through to save-as                                                                 |
| `gd`        | Edit the xprompt definition under the cursor in the prompt bar                                                                           |
| `gf`        | Reformat the active prompt pane's Markdown with Prettier                                                                                 |
| `gx`        | Save as reusable xprompt/snippet; xprompt mode converts raw `<tags>` and leaves the bar open                                             |
| `gt`        | Open a new/rename-in-place snippet target pane (see [Authoring a snippet from the prompt bar](#authoring-a-snippet-from-the-prompt-bar)) |
| `gX`        | Convert the active pane into a frontmatter-local xprompt; raw `<tags>` become inputs                                                     |

Submitting one pane at a time re-attaches prompt-level frontmatter to the launched pane
so local xprompts and metadata continue to resolve. Empty selected panes are dropped
without launching. Whole-stack submission joins panes in top-to-bottom order and then
uses the usual multi-agent launch path, including `%wait`, `%id`, `%model`, and other
segment-local directives. A selected-pane TODO warning counts only that pane; a
whole-stack warning counts visible markers across all non-empty submitted panes.
Choosing **Keep editing**, `n`, `Escape`, or `q` leaves pane order, selection,
frontmatter, and source binding intact. Segment order alone does not make later agents
wait; add `%wait` to the later pane when it must start after an earlier agent succeeds.

The `Enter` submit chooser accepts `a` or `Ctrl+S` for all panes, `c` for the current
pane, and `Esc`/`q` to cancel without changing the stack. Outside that chooser, `Ctrl+S`
is always an active-pane stash shortcut.

Prompt stashes are a per-user draft pile stored outside prompt history. `Ctrl+S`
captures the selected non-empty pane plus the shared prompt frontmatter; when other
panes remain the bar stays open, and when the last pane is stashed the bar closes
without also recording the draft as cancelled history. If the active pane is empty,
`Ctrl+S` opens the stashed-prompt picker instead. `gs` captures all non-empty panes in
their current order as one bundled stash row and dismisses the bar. `gS` opens an update
flow for an existing pinned stash and overwrites the chosen row with the current
non-empty panes. `gx`, `Ctrl+G x`, and `Ctrl+G Ctrl+X` open one save screen containing
the name, storage location, resolved path, and a live preview when the name collides.
Inside that screen, `Ctrl+X` switches between xprompt and snippet mode, so
`Ctrl+G Ctrl+X Ctrl+X` goes directly from a prompt draft to snippet mode. `Ctrl+T`
remains manual completion in the prompt input and does not toggle this save screen. A
successful save binds the prompt stack to that source. `gw` then performs atomic
write-back, and if the source changed since load it offers overwrite, reload, or save-as
instead of clobbering it. `gd` loads the simple xprompt under the cursor for the same
bound editing loop. `gX` instead converts the active pane through a prefilled
frontmatter ghost row and rewrites the pane to invoke the committed helper. Before `gx`
opens the save preview, its xprompt version converts live `<label>` tags into required
Jinja `text` inputs; switching that screen to snippet mode shows and saves the original
active-pane body instead. `gX` performs the same raw-placeholder conversion when it
creates a frontmatter-local helper. Set
`ace.prompt_inputs.xprompt_placeholder_args: false` to disable both conversions while
preserving `gX` Jinja-variable inference. `gw` only writes the currently bound
definition—it does not reinterpret newly typed raw placeholders. Tags in inline code,
fenced code, and disabled xprompt regions stay literal throughout. See
[Raw Prompt Placeholders](xprompt.md#raw-prompt-placeholders) for the exact launch,
conversion, and naming rules.

`Ctrl+G p` opens the unified stashed-prompt picker from the prompt bar, and `@` opens
the same picker from the main ACE tabs even when the prompt bar is not active. In the
picker, `space` toggles a row's persistent pin, `Tab` marks a row to restore and remove
from the stash, `d` marks one row for deletion, `D` marks every row for deletion, `a`
toggles all rows for restore-and-remove, and `Enter` confirms the marked set. Delete
marks are staged until confirmation, replace restore marks for the same rows, and do not
alter pin state; `Escape` or `q` cancels without deleting anything. With no explicit
marks, `Enter` restores the highlighted row; pinned rows stay stashed when restored,
while unpinned rows are popped. Number keys `1`-`9` and `0` restore rows 1-10 directly
with the same pin-aware behavior. A small top-bar badge shows how many restorable drafts
are currently stashed.

### Editing an Existing XPrompt from the TUI

Loading a definition into the prompt bar for editing puts the bar into a **targeting**
state instead of a plain draft: the bar tracks the exact source file your edits will
write to, and everything below applies whenever the bar shows a target. Every surface
that loads an editable definition enters this state the same way:

- The Admin Center XPrompts tab's `Enter` (see [Editing XPrompts](#editing-xprompts)).
- The Select XPrompt `#` picker's `Ctrl+O` ("edit here"), alongside its existing
  `Ctrl+E` (open in `$EDITOR`) and `Ctrl+I` (inline-expand) keys.
- The jump panel (`Ctrl+]`, `gd`) and `gd` under the cursor in the prompt bar.
- Returning from a whole-bar `$EDITOR` round trip (`Ctrl+G g`) preserves whatever target
  the bar already had — your edits stay bound to the same file.

A read-only source (legacy, plugin, built-in) loads without a target: the bar shows a
persistent read-only marker instead of binding, and `gw` falls through to the save-as
flow rather than clobbering the original.

**Visual state.** A targeted bar's border switches from a solid to a **double** rule so
the state reads at a glance in any theme: `$secondary` when clean, `$warning` when dirty
or when the source changed on disk underneath you, and a dim `$foreground` when
read-only. The border title shows a `✎ <reference>` chip using the canonical reference
you'd actually type (`#foo`, `#memory/foo`, `/skill-name`) — not the file stem —
followed by a state marker: dim `✓` (clean), gold `●` (dirty), `🔒 read-only`, or
`⚠ changed on disk` (another process edited the file since you loaded it). The
frontmatter panel's border tints to match and auto-shows on a targeted load, even before
you add any frontmatter fields.

**Saving.** `Enter` opens the submit chooser whenever the bar is targeted or has more
than one pane; an untargeted single-pane draft still sends immediately, unchanged from
before. The chooser's rows are target- and pane-count-aware: `s` sends a single targeted
pane, `a`/`c` submit all/current in a multi-pane stack, `w` saves to the targeted
reference (its subtitle names the destination when dirty, or says there's nothing to
save when clean), and `X` forks the definition to a new location. `gw` / `Ctrl+G w`
performs the same save directly, and the bar's subtitle shows a
`[^G w] save <reference>` hint whenever a target is active. If the source changed on
disk since you loaded it, the save opens a conflict prompt offering overwrite, reload,
or save-as instead of silently clobbering the external edit.

**Chezmoi-managed homes.** With `use_chezmoi: true`, editing a definition under `$HOME`
whose chezmoi source already exists writes to that chezmoi **source** file, not the
applied copy — the applied copy is regenerated by `chezmoi apply` and would otherwise
silently discard your edit on the next apply. The border title and the follow-up actions
modal both surface this redirect so it's never a surprise.

**Follow-up actions.** After a save (or an `E` / `$EDITOR` edit), a follow-up modal
offers only the actions that apply to the file you just wrote, each toggleable and run
through the tracked proc queue in order:

- **Commit & push** — offered when the write path is inside a git repo with changes.
- **Apply chezmoi** — offered when the write redirected to a chezmoi source; scoped to
  just the one home target, never a whole-home apply.
- **`sase memory init`** — offered instead of the two above when you edited a
  [SASE memory note](memory.md), since it already commits and pushes for you while
  regenerating `AGENTS.md` and the provider instruction shims.
- **`sase skill init`** — offered instead of the two above when you edited a canonical
  [skill source](xprompt.md#skill-field), since it already commits, pushes, and deploys
  the generated skill files for you.

With a single offered action, `Enter` runs it and `Esc` skips, matching the previous
plain commit/push confirmation. With more than one, each row's key toggles it and
`Enter` runs everything still selected.

### Completion

Press `Ctrl+T` to activate token completion. The completion kind is determined by the
token under the cursor:

- **XPrompt completion**: When the cursor is on a `#`-prefixed token (e.g., `#my_pro`),
  completion shows matching xprompt names from all discovery sources, including
  registered workspace workflow xprompts. Completion rows include the xprompt kind and
  visible typed inputs, with required arguments shown as `name: type` and optional
  arguments shown as `name?: type` plus a default when the default is a simple scalar.
  Standalone workflow references use the `#!name` insertion form; typing `#!` filters
  completion to entries whose canonical insertion starts with `#!`.
- **Project/Patch completion**: When the cursor is on a `+query` token whose plus is at
  absolute prompt offset zero or immediately after a literal ASCII space, completion
  opens a project/Patch picker. A plus directly after a newline or tab, a plus glued to
  other text, and `#+query` are not project triggers. The picker contains enabled
  launchable projects plus active PR-sized Patches in `WIP`, `Draft`, `Ready`, or
  `Mailed` status; system-managed `home`, disabled projects, internal sibling backing
  records, and non-launchable projects are excluded. Typing after the trigger filters by
  project name, project alias, or Patch name prefix. Accepting a row inserts the
  canonical workspace tag such as `#gh:sase` or `#gh:my_change`, replacing existing
  line-start VCS tags when present or placing the tag after leading
  frontmatter/directives when no tag exists.
- **VCS ref completion**: When the cursor is inside the root segment of a registered VCS
  workflow ref, such as `#gh:`, `#gh:sa`, or `#git(`, completion lists that provider's
  projects and active PR-sized Patches. Providers can add namespace rows, such as GitHub
  organization rows, from local project/config data. Accepting a project or Patch
  completes only the current ref token, producing `#gh:sase ` in colon form or
  `#gh(sase)` in parenthesized form. Accepting a namespace inserts a trailing slash such
  as `#gh:sase-org/` and immediately hands off to repository completion.
- **VCS repository completion**: When the cursor is inside a registered VCS workflow ref
  that already contains an owner or namespace plus `/`, completion lists repositories
  for that namespace through the owning workspace plugin. For example, `#gh:bbugyi200/`
  opens GitHub repositories for `bbugyi200`, and `#gh:bbugyi200/sa` narrows locally or
  through the LSP client's filtering. Accepting a row replaces only the current ref
  value, producing `#gh:bbugyi200/sase ` in colon form or `#gh(bbugyi200/sase)` in
  parenthesized form. Failed or empty lookups show a placeholder row in ACE; stale
  cached results are reused when a refresh fails.
- **Slash-skill completion**: When the cursor is on a slash-skill token such as `/` or
  `/sase_`, completion filters the same catalog to skill sources and inserts
  `/<skill_name>` — the provider name, not the `#` reference. The same source completes
  as `#skill/sase_plan` after a `#`, and both forms resolve one definition, so argument
  hints, previews, and jumps agree. Packaged built-in skills are included, so
  `/sase_plan`, `/sase_questions`, and other bundled SASE skills are available without a
  project-local skill file.
- **XPrompt argument completion**: When the cursor is inside a known xprompt argument
  position, `Ctrl+T` completes the active argument instead of the xprompt name. For
  `path` inputs it delegates to file path completion, for `bool` inputs it offers `true`
  and `false`, and inside parenthesized syntax it completes missing `name=` arguments
  without repeating names already present in the argument list. Agent inputs such as
  `#fork` offer agent, family, clan, and `@tribe` targets with kind and member context.
  Family rows also show the associated plan or bead when SASE can resolve one: the row
  reads `<kind> · <phases/waves> · <title>` (for example
  `Epic · 5 phases · 2 waves · Bead review hardening`), and its plan title is
  searchable, so typing part of the title filters to that family. Selecting the row
  fills the panel subtitle with more of the same artifact — phase titles for an epic,
  the goal for a tale or plain plan, the parent title for a phase or task bead. When
  nothing resolves, the row falls back to a snippet of the family's launch prompt and
  the subtitle falls back to member names; completion is never blocked either way.
  Numeric inputs keep the type hint visible but do not invent values.
- **Directive completion**: When the cursor is on a `%`-prefixed directive token (e.g.,
  `%m`), completion lists user-facing prompt directives and accepts aliases into their
  canonical forms. For example, `%m` completes to `%model` and `%w` completes to
  `%wait`. Inside `%wait`, completion keeps `time=` and `runners=` first, followed by
  matching tribes, clans, families, and agents. The panel shows each directive's aliases
  and whether it takes an argument or is a flag.
- **`@` reference completion**: A bare `@` opens the artifact-kind menu before a `:`
  appears. Local file rows such as `@src/` and `@Justfile` from the prompt-selected base
  directory stay hidden while the typed text prefix-matches an artifact kind; the panel
  advertises `[^T] files`, and the first `Ctrl+T` reveals those rows without accepting
  or extending the kind. A second `Ctrl+T` behaves as normal completion. The reveal
  stays active while that menu remains open and the query is narrowed. When no kind
  prefix-matches, file rows appear automatically, so path-shaped tokens such as `@src/`
  naturally show only files. Matching is fuzzy, so a payload is reachable by any
  memorable fragment of its path or title — `@research:site` finds
  `@research:202607/sase_sites_hub_and_pages/sase_sites_hub_and_pages.md` — and `@rsch`
  finds the `research` kind. Rows are tiered so a fuzzy hit never outranks a literal one
  (prefix, then basename prefix, then contiguous substring, then ordered subsequence),
  then ranked by score, shorter text, and case-insensitive text; see
  [Artifact references](editor.md#lsp-features) for the shared tier table. An empty
  query is not ranked at all, so opening a menu keeps each group's provider order. After
  any file reveal, `Ctrl+T` extends the token to the shared prefix only while every
  leading row is a literal prefix match; once the query is fuzzy-only there is no shared
  prefix to insert, so a single remaining row is accepted outright instead. Directory
  navigation stays exact — only the trailing path segment is fuzzy. Accepting an
  artifact kind inserts `@kind:` and immediately opens its payload rows; accepting a
  directory inserts the `@`-prefixed directory and drills down; accepting a file inserts
  the `@`-prefixed path. Dotfiles are hidden unless the typed path segment starts with
  `.`. Documents, explicit artifact files, chats, beads, and agents come from bounded
  project-scoped catalogs warmed off-thread. Bead rows are loaded from an mtime-cached
  bead-store snapshot, and agent rows come from a bounded scan of the project's agents
  sidecar. Agent rows display the readable local name when possible but insert the
  durable global `@agent:<username>.<machine>.<name>` spelling. Commit and bug rows
  appear only from snapshots the mounted Artifacts panes have already loaded, so typing
  never launches Git, contacts a tracker, or performs unbounded filesystem scans.
  Payload acceptance replaces the complete `@kind:payload` context, including when the
  cursor is in the middle of it. On an un-narrowed bare-`@` menu, `Enter` submits and
  dismisses the menu until you type a query character or move the selection; `Ctrl+L`
  always accepts the highlighted row. Payload rows are rendered path-first — the source
  badge, then the reference path with dim directories and a bright basename, then a dim
  `title · detail · age` tail truncated to the remaining panel width — so what you see
  is what gets inserted. Matched characters are highlighted in gold wherever they
  landed, in the path, in the title, in a kind name, or in a local file row, so every
  row shows why it is there. The panel subtitle reports the same context: `~ fuzzy` when
  any visible row matched below the literal tiers, `N of M` for matching rows out of
  that kind's known payloads, and a `⚠ K not scanned` warning when a catalog cap
  truncated the candidate set, so a bounded search never reads as an exhaustive one.
- **Placeholder completion**: When the cursor is inside an incomplete `<foobar>` tag,
  completion suggests matching placeholders from the current prompt first, then saved
  common placeholders learned from tags you have written before. Within the
  current-prompt group, live tags keep document order and literal-zone tags follow in
  document order. Current-prompt rows use the cyan `<>` badge; saved rows use the gold
  `◆` badge. ACE retains up to `ace.prompt_completion.common_placeholder_count` saved
  placeholders. Automatic completion stays quiet for a bare `<` and adds saved
  placeholders only after you type at least one prefix character; manual `Ctrl+T` on a
  bare `<` shows the saved list explicitly. A lone match in the highest-priority group
  is inserted outright, so saved tags never suppress direct insertion of a lone
  current-prompt match. Set `common_placeholder_count: 0` to disable saving and display
  of common placeholders. In the completion panel, `Ctrl+D` deletes the highlighted
  saved (`◆`) placeholder from the store; current-prompt (`<>`) rows are not deletable.
  By default, submitting from ACE opens **Fill in this prompt** and asks once for each
  distinct live tag before launch; `Ctrl+L` can keep a tag literal. Saving a new xprompt
  converts the same live tags to typed inputs. Inline-code, fenced-code, and
  disabled-region tags stay literal in both paths; see
  [Raw Prompt Placeholders](xprompt.md#raw-prompt-placeholders).

  By default (`ace.prompt_completion.placeholder_ranking: smart`) saved rows are ranked
  by the same weighted composite the history-word menu uses: how strongly a tag relates
  to the words and tags already in the prompt (weight `0.50`), how recently it was used
  (`0.30`), and how often it has been used (`0.20`). Each saved row shows the same
  5-cell stacked score meter and dominant-reason chip as history words —
  `⇄ <tag or word>` for relation, `◷ <age>` for recency, or `✦ <count>×` for frequency —
  with the current-prompt and saved groups aligned on one shared label column. The
  panel's border subtitle adds a matching `⇄ related · ◷ recent · ✦ frequent` legend
  alongside the `<> prompt   ◆ saved` source legend when both are visible; a narrowing
  panel drops the source legend first (the badges are already visible in the rows), then
  the signal legend, leaving today's subtitle, and finally just the `[^D] delete` hint.
  The meter and chip degrade the same way on individual rows too narrow to fit them —
  the chip is dropped first, then the meter. Set `placeholder_ranking: recent` to
  restore the previous most-recent-use ordering with no signal column, or
  `placeholder_ranking_signals: false` to keep smart ranking but hide the meter, chip,
  and legend.

- **File path completion**: When the cursor is on a path-like token (starting with `/`,
  `./`, `../`, `~/`, or containing `/`), completion shows matching filesystem entries.
  Tokens starting with `@` are also recognized — the `@` prefix is preserved in the
  completed path (useful for file-reference arguments). Relative paths use the
  prompt-selected base directory: registered workspace-provider refs and known-project
  refs such as `#git:<project>` or `#gh:<owner>/<repo>` can root completion in that
  project checkout. If no prompt workspace ref resolves, ACE uses the TUI process
  directory.
- **File-history completion**: When the cursor is in whitespace (or at an empty prompt
  prefix), `Ctrl+T` opens a list of recently referenced files and well-formed
  `@kind:payload` artifact references drawn from prompt history, ranked by recency.
  Project-local `.sase/` paths are filtered out so internal bead/plan artifacts don't
  pollute the suggestions. Artifact references retain their leading `@`. Press `Ctrl+D`
  in the completion panel to delete the highlighted entry from the on-disk history.
- **Prompt-local word completion**: As the first fallback for a plain prose token,
  `Ctrl+T` filters words already in the active prompt by the word prefix immediately
  left of the cursor. Candidates are drawn only from complete words earlier in the
  prompt, before that prefix; words later in the prompt (including any suffix already
  sitting to the right of the cursor) are never candidates. Identifier-like candidates
  may include ASCII hyphens, so `bob-mac-capture` is matched and replaced as one word;
  Unicode dash punctuation still acts as a boundary. Matching is case-insensitive, but
  each candidate keeps its original spelling. Accepting a candidate replaces only the
  typed prefix, so completion works safely in the middle of a word: `foo<cursor>baz`
  completing to `foobar` becomes `foobar<cursor> baz` — a single space is inserted to
  separate the completed word from a preserved right-hand suffix, and the cursor lands
  immediately after the completed word, before that space. An exact-prefix spelling is
  only offered when accepting it would have this separating effect; at a plain word
  boundary with no suffix to separate, that exact match is suppressed as a no-op. While
  multiple candidates share a longer common prefix, `Ctrl+T` only narrows the typed
  prefix and keeps the menu open; it never inserts the separator until a candidate is
  actually committed. Candidates shorter than `ace.prompt_completion.word_min_length`
  are skipped before history fallback is considered; the default is `5`, and the
  threshold applies to the complete candidate rather than the typed prefix. This
  provider scans only the current prompt pane and takes precedence over history words
  when it has an eligible match. Candidates are ordered nearest-first: the word you just
  wrote is the one you are most likely repeating.
- **History-word completion**: When prompt-local words have no match, `Ctrl+T` filters
  recently used words derived from recorded prompt history using that same
  left-of-cursor prefix; any suffix under the cursor is never consulted to include or
  exclude candidates, only to decide whether accepting inserts the same separating space
  described above. Hyphenated identifier-like spellings are indexed, matched,
  length-filtered, and replaced as one word, with only the typed prefix replaced so a
  preserved suffix survives acceptance. Matching remains case-insensitive and keeps
  exact spelling. ACE retains up to `ace.prompt_completion.history_word_count` unique
  words that meet the shared `ace.prompt_completion.word_min_length` (defaults: `10000`
  and `5`); set `history_word_count: 0` to disable only this final fallback. History is
  loaded off-thread, so a cold cache briefly shows `loading history words…` without
  blocking input. `Ctrl+D` deletes the highlighted word instantly, without rebuilding
  the index, and records it in `~/.sase/prompt_word_deletions.json`, so future history
  derivations continue to filter it out; remove that file to reset all history-word
  deletions. The former `history_word_min_length` configuration key has been replaced by
  `word_min_length`.

  By default (`ace.prompt_completion.word_ranking: smart`) rows are ranked by a weighted
  composite of three signals rather than plain recency: how strongly a word relates to
  the words already in the prompt (weight `0.50`), how recently it was used (`0.30`),
  and how often it has been used (`0.20`). Each row shows a 5-cell stacked meter whose
  filled length is the composite score and whose cell colors show each signal's share,
  plus a dominant-reason chip — `⇄ <word>` for the context word it relates to, `◷ <age>`
  for recency, or `✦ <count>×` for frequency — and the panel's border subtitle carries a
  matching `⇄ related · ◷ recent · ✦ frequent` color legend. The meter and chip are
  dropped (leaving the word alone) on panels too narrow to fit them, and the legend
  falls back to the plain `[^L] accept  [^D] delete` hint under the same width pressure.
  Set `word_ranking: recent` to restore the previous most-recent-use ordering with no
  signal column, or `word_ranking_signals: false` to keep smart ranking but hide the
  meter, chip, and legend.

| Key                | Action                                                               |
| ------------------ | -------------------------------------------------------------------- |
| `Ctrl+T`           | Start completion or insert shared prefix                             |
| `Ctrl+N` / `Down`  | Next candidate                                                       |
| `Ctrl+P` / `Up`    | Previous candidate                                                   |
| `Enter` / `Ctrl+L` | Accept highlighted candidate                                         |
| `Ctrl+D`           | Delete a highlighted recent file, saved placeholder, or history word |
| `Escape`           | Cancel completion                                                    |

Press `Ctrl+R` to open the recursive fuzzy file finder. With a token such as `src/alp`,
`src/` becomes the search root and `alp` pre-seeds the fuzzy query; with no token, the
finder starts at the prompt-selected base directory described above. If a `Ctrl+T` file,
recent-file, or path-argument candidate is highlighted, that highlighted path seeds the
recursive root instead. The finder uses
`git ls-files --cached --others --exclude-standard` from the search root when possible,
falls back to a bounded filesystem walk, and inserts the selected path into the prompt
position captured when the finder opened. Inside the finder, type to filter, use
`Ctrl+N` / `Ctrl+P` or arrows to move, `Ctrl+U` to clear the query, `Enter` to insert,
and `Esc` to cancel.

In prompt NORMAL mode, `K` previews the xprompt, slash skill, or file under the cursor.
Inside `#name: ` / `#name:: ` argument text, `K` and `Ctrl+]` prefer a nested reference,
file path, glossary term, or plain word under the cursor, and fall back to the xprompt
that owns the argument text only when nothing else matches. On ordinary prompt text, ACE
checks the warm project glossary before falling back to plain word lookup or spelling
fixes. `Ctrl+]` jumps to an xprompt, skill, file, or glossary definition, or opens an
action picker when several jump targets are available. Glossary terms come from the
project selected by a leading VCS workflow reference, or from the active workspace
project when the prompt does not select one.

#### Glossary terms

Project glossary entries are authored in `sase/sase.yml`; see
[glossary configuration](configuration.md#memoryglossary). ACE highlights matched
glossary phrases in the prompt after the catalog is warm, rendering them bold,
underlined, and in a muted blue so they read apart from the lavender repo-name highlight
— the same "you can preview this with `K` or jump to it with `Ctrl+]`" affordance, a
different hue. Matching skips inline code and fenced code and uses the shared
longest-match rules from the xprompt LSP. Loading, validation, and matcher compilation
run off the render path and are cached per project/config signature. Config edits,
project changes, and watched `sase.yml` changes invalidate the cache.

`K` on a glossary phrase opens a compact definition card. The title shows the canonical
term and discloses the matched phrase only when you opened an alias. The body renders
the definition as prose, followed by display-alias chips, numbered `SEE ALSO` chips for
glossary terms mentioned by the definition, and a property grid for project, source, and
match count. Press `1`-`9` to follow a `SEE ALSO` term in place and `Backspace` to walk
back through the card history. `y` copies the definition, while `Y`, `o`, and `Z` copy
the source path, open the owning `sase.yml` definition line in `$EDITOR`, or hand the
file to the artifact viewer when a source path is available. `Ctrl+]` opens the
project-local `sase/sase.yml` definition range through the normal editor/tmux jump flow.
If the catalog is still loading, ACE schedules a warm and asks you to retry rather than
falling through to word lookup or an unrelated jump target.

The card's `SEE ALSO` chips are the depth-1 case of the same closure resolver behind
`sase glossary show`/`read` (see [Glossary](memory.md#glossary)): both walk outgoing
reference spans from the shared `sase.glossary.resolution` module, so the preview card
and the CLI can never disagree about which terms a definition references.

<a id="glossary-panel"></a>

#### Glossary panel

`K` previews one highlighted phrase. The **Glossary panel** is the browse-and-edit
surface for a whole project's terms. From a prompt pane, press `gG` in NORMAL mode or
`Ctrl+G G` in INSERT or NORMAL. The which-key hint row lists `glossary…` on both
prefixes. If the cursor sits inside a highlighted glossary term, that term is selected;
otherwise the panel opens on the first term. Closing with `Esc` or `q` restores the
prompt pane and the vim mode you left.

The header reads `GLOSSARY · <project> · N terms · project i/N` and always uses the
configured `PROJECT_NAME:`, never a `ProjectSpec` key. A single-project setup still
shows `project 1/1`.

Two navigation axes stay synchronized:

- **Alphabetical.** `j`/`k` (or arrows / `Ctrl+N` / `Ctrl+P`) move the term-list cursor;
  the definition card follows. `g`/`G` jump to the first and last term. `/` filters
  terms and aliases with the same predicate as `sase glossary list`; `.` extends the
  match into definition bodies, matching `--definitions`. `Esc` closes the filter and
  keeps the selection when it is still visible. An empty result reads
  `no terms matched: <pattern>`.
- **Relational.** The definition card carries numbered `SEE ALSO` chips (outbound
  references from this definition) and `REFERENCED BY` chips (inbound terms that mention
  this one). Numbering is continuous across both rows so `1`–`9` is never ambiguous.
  `Tab` / `Shift+Tab` move a chip cursor; `Enter` or `l` follows the focused chip, or ①
  when none is focused. Following moves the term-list cursor to the target, pushes the
  previous term onto a trail bounded at 32 entries, and clears an active filter when the
  target is hidden. `h` or `Backspace` walks back. A non-empty trail renders as
  `TRAIL  A › B › C` above the footer.

`p` and `P` cycle the enabled-project ring. The ring is every enabled project that has a
glossary configured, plus the project you opened from even when it has none — so `a` can
add that project's first term. Order is by display name. Switching projects clears the
trail and the filter and restores that project's last-selected term for the life of the
panel.

`a` opens an add form (term, optional comma-separated aliases, definition) with live
validation against the Rust glossary validator. `d` confirms a delete and shows the
inbound blast radius before anything is written. Both writes use the same engine as
`sase glossary add` and `sase glossary del` (see [Glossary](memory.md#glossary)), run as
tracked procs, refresh the panel, invalidate prompt highlighting, and offer a config
commit for the written `sase.yml`. A delete toasts the exact restore command. The panel
does not run `sase memory init`; the success toast names that follow-up.

A project with no glossary shows a centered invitation that names the project and points
at `a`. A project whose glossary failed to load shows the diagnostics and the config
path. `?` opens a panel-scoped help overlay. `y` copies the definition, `Y` copies the
source path, `o` opens the definition line in `$EDITOR`, `Z` hands the file to the
artifact viewer, and `r` re-reads the current project.

The panel footer lists only conditional keys: `d` when a term is selected, relation keys
when chips exist, `p`/`P` when the ring has more than one project, and back when a trail
exists. Always-available keys live in `?` and in this guide.

Every key named above is remappable under
[`ace.keymaps.glossary`](configuration.md#acekeymaps); see
[Remapping Glossary Panel Keys](#remapping-glossary-panel-keys).

#### Repo names

ACE highlights the unambiguous identifier of every non-primary repo in the active
project — linked names (`sase-core`), sidecar slugs (`sase--beads`), and external names
(`gh:owner/repo`) — after the catalog is warm. Matches are bold, underlined, and
lavender. The project's own primary name, sidecar role words (`beads`, `plans`), and any
name the project glossary already claims are left as ordinary text so the two overlays
never fight over the same characters.

Matching skips inline and fenced code, ignores path-adjacent hits (`../sase-core`,
`sase-core/crates`), and drops the matcher's derived plurals so the highlighted
characters always equal a real identifier. Loading and compilation run off the render
path and are cached per project. Config edits, project changes, and watched `sase.yml`
changes invalidate the cache. A repo opened with `sase repo open` during a live ACE
session does not appear until the next config-driven invalidation.

`K` on a repo mention opens a compact repo card: kind, description, checkout path, clone
coverage, remote URL, and where the repo is declared. The title shows the repo
identifier and discloses the matched text only when it differs in case from the
identifier — the exact-identifier filter above rules out any other difference. Chips
mark the kind, plus `AUTO-CLONE` and/or `AUTO-SYNC` when set, and `ENV <name>` when the
record has one. `Checkout` prefers the clone registered for the active workspace, else
the record's own path; when that path does not exist locally it is suffixed
` (not cloned)` and the card prints the exact `sase repo open <name>` command as a hint
— ACE never runs that command itself. `Clones` shows
`<existing> of <registered> workspaces` when the repo has clone records, and rows whose
value is unknown (no remote, no declaration site) are omitted rather than shown empty.
`y` copies the description, `p` copies the checkout path, and `Y`, `o`, and `Z` copy the
declaration path, open the owning `sase.yml` line in `$EDITOR`, or hand the file to the
artifact viewer — all three warn cleanly for an external repo, which has no declaration
site. If the catalog is still loading, ACE schedules a warm and asks you to retry rather
than falling through to word lookup or an unrelated jump target.

`Ctrl+]` on a repo mention opens the resolved checkout — the clone registered for the
active workspace, else the record's own path — in `$EDITOR` or a new tmux pane through
the normal jump action chooser, which gains a `c` — Open declaration choice whenever the
repo has one (external repos do not). When the checkout is not cloned in the active
workspace, `Ctrl+]` notifies that the repo is not cloned and prints the exact
`sase repo open <name>` command to run instead of offering to open a path that does not
exist: it opens the declaration directly when one exists, or just notifies with no
chooser at all for an external repo. ACE never runs `sase repo open` itself.

#### Word definitions & spellcheck

When no xprompt, slash skill, workflow, or file target matches, `K` treats a plain
natural-language word that is not a glossary match as a lookup target. Correctly spelled
words open a scrollable definition panel; use `j` / `k`, `Ctrl+D` / `Ctrl+U`, and `g` /
`G` to navigate it. Misspelled words open a compact correction panel: press `1`–`9` to
apply a suggestion immediately, or move with `j` / `k` and press `Enter`. The
replacement is an ordinary undoable prompt edit.

Definitions require the optional `dict` command. Spell checking requires GNU `aspell`
with an English dictionary (`aspell-en` on Debian; Homebrew's package bundles English).
If either tool is absent, ACE explains the unavailable feature without affecting the
rest of prompt preview. Run `sase doctor -D` to see the exact optional-tool status and
installation hint.

Every word `K` proves misspelled is remembered durably and gets a red underline in every
prompt input from that moment on, in every `sase ace` session -- no live spell-checking
runs on every keystroke; only what `K` has already checked is ever squiggled. This is
distinct from the bold blue glossary underline and the bold lavender repo-name
underline, which mark a definable project term or repo rather than a spelling issue. The
correction panel offers two ways to stop fighting a word, at two different scopes. Press
`a` to accept a word for SASE only: it is recorded in `prompt_misspellings.json`, `K` on
it no longer opens the panel, but `aspell` itself -- and every other consumer of it on
the machine -- still rejects the word. Press `d` to add the word to your `aspell`
personal dictionary instead (usually `~/.aspell.en.pws`, though `aspell` configuration
can relocate it), so it stops being flagged everywhere on the machine, not just in ACE;
this is reversible by editing that file directly. The add is verified by re-checking the
word in a fresh `aspell` process afterwards, so the squiggle clears only once `aspell`
genuinely accepts it -- a failure leaves the word flagged and reports `aspell`'s own
explanation. Case follows `aspell`: a word added capitalized (`Bugyi`) stays flagged in
lowercase (`bugyi`). Hyphenated words cannot be added with `d` -- `aspell` does not
permit `-` inside a personal-dictionary entry -- and the panel reports that explicitly
rather than pretending the add worked. A `K` press on a now-correctly-spelled remembered
word clears its squiggle automatically. The remembered words are stored at
`sase_home()/prompt_misspellings.json`; see
[`ace.prompt_spellcheck`](configuration.md#aceprompt_spellcheck) to disable the
highlight or change how many words are retained.

ACE also computes a non-disruptive live suggestion after a short debounce while the
prompt input is in INSERT mode. The suggestion appears in the prompt bar subtitle as
`[^L] accept ...`; press `Ctrl+L` to accept it. `Enter` still submits the prompt as
typed, so live suggestions cannot accidentally replace text on send.

Live soft completion covers directives, xprompt names, xprompt argument names, and bool
argument values. File-path soft completion is disabled by default because it can scan
the filesystem while typing; enable it with
`ace.prompt_completion.auto_file_paths: true`. The xprompt/skill menu also opens
automatically while typing matching `#name`, `#!name`, or `/skill` tokens; disable that
xprompt auto-open behavior with `ace.prompt_completion.auto_xprompt_menu: false`. The
directive menu likewise opens automatically while typing matching `%id` tokens; disable
it with `ace.prompt_completion.auto_directive_menu: false`. Both auto-menus open only
once at least one identifier character follows the marker (bare `#`, `/`, and `%` stay
quiet) and never auto-accept a single match. The grouped `@` reference menu opens from a
bare `@`, narrowed artifact/file queries such as `@pl` or `@src/`, and syntactically
valid `@kind:` payload contexts; disable automatic opening with
`ace.prompt_completion.auto_artifact_menu: false`. On an un-narrowed bare-`@` menu,
`Enter` still submits the prompt and dismisses the menu until you type a query character
or move the selection. The project/Patch picker opens when `+` completes a token at
prompt offset zero or immediately after a literal ASCII space and is also available
through manual `Ctrl+T`. The VCS ref-root menu opens when `:` or `(` completes a known
workflow ref trigger such as `#gh:` and local candidates exist. The VCS repository menu
opens when `/` completes a known workflow ref trigger such as `#gh:owner/`; cached rows
appear immediately and uncached namespaces fetch in a background worker. Placeholder
auto-completion opens only for an incomplete `<...` context; saved common placeholders
join automatic results after the prefix is non-empty, while manual `Ctrl+T` can show
them from a bare `<`. Manual `Ctrl+T` inserts a lone match in the highest-priority
placeholder source group outright; automatic completion only opens the menu, even for
one match. Manual `Ctrl+T` completion still supports file paths, xprompt names,
directives, skills, `@` references, project/Patch tags, VCS ref roots, VCS repository
refs, prompt-local prose words, placeholders, and enabled history words regardless of
the automatic settings. Live suggestions pause while the manual completion panel is
open, while snippet tabstops are active, in NORMAL mode, and during feedback prompts.

For file completion, directories appear before files in the candidate list. Dotfiles are
hidden unless the partial prefix starts with `.`. Accepting a directory automatically
re-opens completion for the next level (drill-down). The completion panel shows up to
eight candidates at a time — seven when more candidates remain, so the `↓ N more…` line
always fits, and one fewer again when the grouped `@` reference menu draws its
`── files · <base-dir>` rule — and scrolls to keep the highlight visible. When exactly
one xprompt or file candidate matches, accepting completion inserts the canonical
reference immediately.

Accepting an xprompt completion, or selecting an xprompt from the `#@` picker, opens an
`xprompt args` hint panel when the xprompt has required user-facing inputs. The panel
shows the supported arguments and highlights the active one. Press `:` while the
accepted reference is still current to switch to colon syntax, or press `(` to insert a
required-argument named snippet and use `Tab` to advance through the snippet fields.

The same smart insertion rules apply to `#@` selections and `Ctrl+T` completions. A
selected xprompt with no required inputs inserts a trailing space, a single required
non-text input inserts colon syntax, a single required text input inserts double-colon
shorthand, and multiple required inputs insert a parenthesized named-argument snippet.
When that trailing space sits at a live snippet tabstop and the next keystroke is `Tab`
or `Shift+Tab`, the jump removes the space on its way to the next tabstop; when the jump
has nowhere to go, the space is kept and ordinary snippet/list fallback continues.

The same hint panel appears while typing narrow, known argument forms such as `#name:`,
`#!name:`, `#ns/name:`, `#ns__name:`, `#name!!:`, `#name??:`, `#name(`, and
`#name(arg=`. The hint is advisory; the backend xprompt parser still owns expansion
semantics when the prompt is submitted. Detection intentionally stays conservative, so
prose shorthand, URLs, unknown xprompt names, `#name+`, and completed colon text such as
`#name: value` do not keep the prompt-bar hint open.

### Alt Brace Syntax (`%{...}`)

The prompt input has dedicated highlighting and editing help for the `%{A | B}` alt
fan-out shorthand (see the [Alt Directive reference](xprompt.md#alt-directive)). It
distinguishes the alt delimiters from the branch separators so a fan-out is easy to read
at a glance:

- The `%{` opener and `}` closer are styled as **delimiters** (bold accent).
- Top-level `|` branch **separators** use a dimmed accent so they read differently from
  the delimiters.
- A branch name before a top-level `=` (e.g. `sec=` in `%{sec=... | perf=...}`) is
  highlighted as a **branch name**.
- An unmatched `%{` (or stray closer) is flagged as an **error** span.

The alt overlay layers on top of the existing Jinja and search highlighting rather than
replacing it, and it uses the same size guards, so highlighting stays responsive on
large prompts.

Editing help in the ACE prompt input mirrors the Jinja auto-pair behavior and only fires
for the `%{...}` shorthand:

- **Auto-pair** — typing `{` immediately after a directive-valid `%` inserts `%{  }` and
  parks the cursor between the two padding spaces. The expansion fires at end of line,
  before whitespace, before a bracket closer (`)`, `]`, `}`, `>`), and before trailing
  punctuation (`.`, `,`, `;`, `:`, `!`, `?`), so a fan-out can be inserted before the
  existing `?` in `Which is better %{ A | B }?`. It remains suppressed before word
  characters and other token-opening characters.
- **Paired delete** — backspacing the `{` in `%{|}` also removes the auto-inserted `}`;
  a forward delete on `%|{}` removes both braces.
- **`|` separator normalization** — typing `|` inside a live `%{...}` span inserts a
  padded `|` separator, keeps the cursor after the trailing space and before the closing
  `}`, and normalizes comma spacing in the current branch. For example, typing `|` at
  the end of `%{foo ,bar, and baz` yields `%{foo, bar, and baz | }` with the cursor
  before `}`.

These edits are suppressed when there is an active selection or when the cursor is not
inside a directive-valid `%{...}` context, so ordinary `{` and `|` typing elsewhere is
unaffected. External editor integrations do not own `%{}` auto-pairing or paired delete;
editor-local brace-pair plugins own that lifecycle there. The
[Neovim plugin](https://github.com/sase-org/sase-nvim) still provides the same
separator-normalization behavior for prompt buffers.

### NORMAL Mode

Press `Escape` in INSERT mode to enter vim-style NORMAL mode. The border title shows
`[NORMAL]` and line numbers switch to relative numbering (current line shows absolute,
others show offset).

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
| `Y`   | Yank from the cursor to end of line (charwise, like `y$`)                                    |
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

Vim-surround commands are also available in NORMAL mode: `ys{motion}{delimiter}` wraps a
motion or text object, `yss{delimiter}` wraps the current line, `ds{delimiter}` removes
the nearest matching surround, and `cs{old}{new}` replaces it. Quotes and backticks pair
with themselves; either side of `()`, `[]`, `{}`, or `<>` selects the matching pair,
with `b` aliasing parentheses and `B` aliasing braces. Other single characters pair with
themselves. For example, `ysiw)` changes `word` to `(word)`, and `cs)]` changes the
parentheses around the cursor to brackets. A count on the `ys` motion expands its
target; a count before `ds` or `cs` selects a farther enclosing pair. Successful edits
are repeatable with `.`.

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

| Key         | Action                                                                                                |
| ----------- | ----------------------------------------------------------------------------------------------------- |
| `i`         | Enter INSERT mode; inserted text is repeatable with `.`                                               |
| `v`         | Enter charwise VISUAL mode                                                                            |
| `V`         | Enter linewise V-LINE mode                                                                            |
| `a`         | Append after cursor; inserted text is repeatable with `.`                                             |
| `A`         | Append at end of line; inserted text is repeatable with `.`                                           |
| `I`         | Insert at line start; inserted text is repeatable with `.`                                            |
| `o`         | Open below; prompt bullets and ordered items auto-continue, and inserted text repeats with `.`        |
| `O`         | Open above; prompt bullets and ordered items auto-continue, and inserted text repeats with `.`        |
| `[<Space>`  | Insert blank line(s) above current line without leaving NORMAL mode                                   |
| `]<Space>`  | Insert blank line(s) below current line without leaving NORMAL mode                                   |
| `u`         | Undo                                                                                                  |
| `Ctrl+R`    | Redo                                                                                                  |
| `Ctrl+A`    | Increment the number at/after cursor, wrapping to the prompt top (supports count and `.`)             |
| `Ctrl+X`    | Decrement the number at/after cursor, wrapping to the prompt top (supports count and `.`)             |
| `x`         | Delete character                                                                                      |
| `X`         | Delete character before cursor                                                                        |
| `r{c}`      | Replace character(s) at cursor (supports count: `3rx`)                                                |
| `p`         | Paste after cursor / below line from the internal register                                            |
| `P`         | Paste before cursor / above line from the internal register                                           |
| `~`         | Toggle case of character(s) at cursor (supports count: `5~`)                                          |
| `.`         | Repeat last mutation, including inserted text; a count replaces the recorded count                    |
| `J`         | Join current line with next, removing a pulled-up prompt `- ` or `<N>.` marker (supports count: `5J`) |
| `K`         | Preview the xprompt, workflow, skill, file, glossary term, repo name, or plain word under the cursor  |
| `Ctrl+]`    | Jump to the xprompt/workflow/skill/glossary definition, file, or repo checkout under the cursor       |
| `/` / `?`   | Search forward / backward in the current prompt pane                                                  |
| `n` / `N`   | Repeat the last confirmed search in its original / opposite direction                                 |
| `*` / `#`   | Search forward / backward for the whole word under the cursor                                         |
| `g*` / `g#` | Like `*` / `#`, but also matches the word as a substring                                              |

In prompt panes, `o` and `O` continue the containing hyphen bullet or ordered item below
or above at the same indentation, including when the cursor is on a physical
continuation line produced by Prettier wrapping. Non-list lines retain ordinary bare
open-line behavior. For an ordered item, `O` on the marker row takes that item's own
number, `O` on a line the item owns takes the next number (the new marker lands after
that item's marker), and `o` always takes the next number; the surrounding run is
renumbered either way. Prompt `J` removes a supported `- ` or `<N>.` marker when joining
onto a nonblank current line, renumbering the run an ordered item left behind; a blank
current line keeps the marker, and non-prompt editors retain vanilla `J` behavior.

For `Ctrl+]`, ACE opens the target directly in `$EDITOR` when there is only one
available action. Inside tmux, or for loadable Markdown xprompt definitions, it can show
a small chooser for editor, tmux-pane, or load-into-prompt actions. Glossary jumps use
the same flow, targeting the owning project's `sase/sase.yml` `definition` scalar.

The border subtitle shows pending operators and counts (e.g., `2d` when a delete with
count 2 is pending).

Search previews matching text as you type. `Enter` confirms the query, while `Esc` or
`Ctrl+C` cancels and restores the original cursor. The last confirmed search is shared
by every pane in the current `---`-separated prompt stack and survives a stack rebuild,
so switching panes and pressing `n` or `N` reuses the same query against the newly
active pane.

`*` and `#` resolve the keyword run under (or, failing that, forward of) the cursor on
the current line and search for it as a whole word (`g*` / `g#` match it as a substring
instead), landing on the start of the destination match. Unlike `/` and `?`, these are
always case-sensitive, matching vim's exemption of `*` / `#` from smartcase. `n` and `N`
afterward repeat with the same whole-word and case-sensitivity rules, not a plain
smartcase substring search. When no keyword character follows the cursor on the line,
ACE reports "no string under cursor" and leaves the cursor and any existing search state
untouched.

### Visual Mode

Press `v` in NORMAL mode for charwise VISUAL mode, or `V` for linewise V-LINE mode. The
border title shows `[VISUAL]` or `[V-LINE]`. `Escape` returns to NORMAL mode, and `o`
swaps the active selection end.

Visual mode supports the NORMAL-mode motions and counts listed above, including word
motions, paragraph motions, line motions, `f`/`F`/`t`/`T` with `;`/`,` repeats, `%`,
`gg`/`G`, `Ctrl+D`/`Ctrl+U`, and the NORMAL-mode text objects. `v` exits charwise VISUAL
mode; `V` exits V-LINE mode; pressing the other visual key switches selection kind.

Visual changes (`d`, `c`, `>`/`<`, `u`/`U`, `~`) are dot-repeatable over a same-sized
range from the current cursor; visual `c` repeats the replacement text typed before
`Escape`.

| Key       | Action                                                       |
| --------- | ------------------------------------------------------------ |
| `d` / `x` | Delete selection and copy it to the internal register        |
| `c` / `s` | Change selection and enter INSERT mode                       |
| `S{char}` | Surround the exact selection with a delimiter pair           |
| `y`       | Yank selection to the internal register and system clipboard |
| `p`       | Replace selection with the internal register                 |
| `>` / `<` | Indent / dedent selected lines by two spaces                 |
| `u` / `U` | Lowercase / uppercase the selection                          |
| `~`       | Toggle case in the selection                                 |
| `*` / `#` | Search forward / backward for the selected text, literally   |

Visual `*` / `#` search for the exact selected text (including embedded newlines in a
multi-line or V-LINE selection) rather than a resolved keyword, are always
case-sensitive, and return to NORMAL mode at the search destination.

Visual `S` uses the same delimiter pairs as NORMAL-mode surround, preserves an exact
charwise selection, and leaves the unnamed register unchanged. In V-LINE mode the
delimiters go inside the neighboring newlines, so the lines outside the selection do not
join the surrounded text. The edit is one undo step and `.` repeats the saved charwise
length or V-LINE row count from the current cursor; a count before `.` scales that saved
shape. `Escape` or `Ctrl+X` cancels a pending delimiter without replacing the previous
dot-repeat action. Lowercase `s` keeps its change-selection behavior. V-LINE operators
always apply to whole selected lines regardless of the cursor column.

## Prompt History Modal

Press `Ctrl+K` from the prompt input to open the prompt history modal. That shortcut is
available when the current prompt is a single logical line; that line pre-fills the
modal filter. Press `,.` (leader + `.`) to open the same modal from the main ACE UI. The
modal loads prompts previously launched from ACE or `sase run` in 250-row recency pages.
Normal launch writes skip trivial one-token prompts (e.g. `y`, `ok`) so they do not
clutter the list, while failed-launch recovery can still preserve a short submitted
prompt.

Bare prompts are stored after launch normalization, so a prompt without an explicit
workspace reference appears with the default `#git:home` prefix. Explicit workspace
prefixes also feed the prompt-input MRU controls. In the prompt input, the MRU ring is
ordered from most recent to oldest: `Ctrl+P` moves toward older launchable workspace
prefixes, while `Ctrl+N` moves toward newer prefixes. Each edge has a no-prefix stop
that removes the first launchable workspace tag from the prompt without touching the
remaining prompt text, then wraps. When no workspace tag is present, `Ctrl+P` starts at
the most recent entry and `Ctrl+N` starts at the oldest one.

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

Type in the search box to filter the prompts that have already been loaded by text.
Press `Ctrl+K` to load older pages, and press `Ctrl+X` to toggle cancelled prompts on or
off — when enabled, cancelled prompts appear in the results with an `x` marker.

Prompt-history rows are compact single-line entries: cancelled marker, last-used
timestamp (`MM-DD HH:MM` when parseable), and a first-line prompt preview. The preview
panel still shows the full prompt and timestamp metadata. History writes use a sidecar
lock plus atomic tempfile replacement of monthly shard files under
`~/.sase/prompt_history/`, so concurrent agent launches do not truncate prompt history.
A legacy `~/.sase/prompt_history.json` store is migrated into shards before normal reads
and writes when the shard directory has not already been created.

## Procs Tab

Open the SASE Admin Center with `#`, then press `3` (or switch tabs until you reach
**Procs**). You can also run the keyless **Open procs panel** command from the command
palette. The tab shows procs (hook runs, mentor executions, agent launches, plugin
operations, etc.) with live output for running procs and completed output for finished
ones.

### Durability and Scope

Procs the TUI runs itself are **mirrored** into the durable proc store
(`~/.sase/procs/procs.jsonl`, with one combined output log per proc under
`~/.sase/procs/logs/`), so their outcome survives the session that produced them and is
visible from `sase proc list` / `sase proc show`. Supervisor-backed procs — commands
submitted with `sase proc run`, programmatic submissions, and the unattributed command
fallback for an epic approval whose planner agent family cannot be resolved — are read
back out of that store and rendered here, so work that this process never owned still
shows up on the tab.

The pane defaults to **this session** plus unattributed procs; press `a` to widen it to
every session. Historical `detached` rows remain visible in both modes. The pane title
names the active scope and the two running-lane counts, e.g.
`Procs · this session   ⚙ 2  ⚙ 1   [3 running · 5 done]`. The blue gear is running plain
procs (excluding monitors); the orange gear is running monitors. Both counts follow the
tab's current scope, so `a` moves them with the list. A zero lane still renders as a dim
`⚙ 0` so a missing chip cannot be read as "unknown". The bracketed totals keep their
current meaning: blue plus orange equals the running count. Rows read from the store
carry a colored session chip (`ace·sase#14 4f2a`) that matches the one `sase proc list`
prints; a session that has since exited renders dim with a `†`. An ordinary unattributed
proc renders a dim `—`; a historical detached proc carries a cyan `◆ detached` marker
that makes the legacy row kind explicit.

Store reads happen on a worker thread and are revalidated by store mtime about once a
second, so the tab never stats, reads, or locks the store from a render or keystroke
path. Retention is governed by `procs.history_limit` (see
[configuration](configuration.md#procs)): finished rows and their logs age out
oldest-first, and running procs are never pruned. Because the store owns that retention,
`d` / `D` only dismiss this session's in-memory rows.

The top-bar proc indicator counts this session's active `command` procs plus **every
active unattributed proc globally**, including an approved epic that had to use the
unattributed command fallback.

### Layout

The tab uses a two-panel layout: a proc list on the left and an output pane on the
right. Running procs refresh their output on the pane's 0.25 s tick while the Procs tab
is visible.

### Proc Status Icons

| Icon | Color  | Meaning                                                     |
| ---- | ------ | ----------------------------------------------------------- |
| `◌`  | Dim    | Pending (supervisor starting)                               |
| `●`  | Green  | Running                                                     |
| `✓`  | Cyan   | Success                                                     |
| `✗`  | Red    | Error                                                       |
| `⊘`  | Yellow | Killed                                                      |
| `?`  | Dim    | Unknown                                                     |
| `⚙`  | Orange | Monitor shell (same mark as the Agents tab and the top bar) |

### Monitors on this tab

A `sase monitor start` supervisor is a durable proc like any other, but this tab marks
it the same way the rest of ACE does. See [Monitors](monitors.md).

- **Orange `⚙`.** Monitor rows carry the orange gear between the status icon and the
  label (`● ⚙ just check-full`), matching the Agents tab and the top-bar monitor
  indicator. The same mark prefixes the output header.
- **Agent name.** Each monitor names its member agent (`acme--mon`) on the list's
  secondary line (`acme--mon · Working...`) and on an `agent` line in the output header.
- **Live `live_reply.md`.** The output pane streams the monitor's artifacts-owned log
  (`<artifacts_dir>/live_reply.md`) the same way the agent metadata panel does, so a
  running monitor is not an empty `Working...`.
- **`<enter>` jumps to the agent.** On a monitor whose agent row is loaded, `<enter>`
  (or a click) closes Admin Center and reveals that agent on the Agents tab. The hints
  line shows `⏎: agent` only when that jump is possible. If the agent is not on the
  Agents tab, ACE says so and stays put.
- **Visible in both scopes.** Monitor procs are unattributed, so they appear in both
  **this session** and **all sessions**.
- **`K` stops the supervisor.** Kill uses the proc-shell stop path: it stops the
  supervisor, settles the family, and runs any `--next` action.

### Durable Procs

Procs are durable records shared by every SASE surface, not just rows in this pane. They
live in `~/.sase/procs/procs.jsonl`, with one combined stdout/stderr log per proc under
`~/.sase/procs/logs/<proc_id>.log`. Because the records outlive the process that
produced them, `sase proc` can list and inspect work started anywhere — including a
TaskTriage launch or unattributed command submitted from another client.

Each proc carries a 12-character id resolvable by unique prefix (three characters
minimum, like a git short SHA), so `sase proc show k7m2` works. Statuses are `pending`,
`running`, `success`, `error`, and `killed`; terminal states are final, and a proc whose
supervisor died without reporting is reconciled to `error` rather than left running
forever. `sase proc list` reuses the icons above and adds `◌` for pending and `⊘` for
killed.

A proc may also carry a **named proc shell**: `sase proc run -N/--shell NAME` (bare
names resolve beneath the calling sase-agent; `agent/name` is fully qualified) names the
proc so `sase proc show`, `sase proc list -N`, and `sase proc kill` can address it by
name instead of id. Resolution tries an exact fully qualified name, then an exact proc
id, then a unique id prefix. Active uniqueness is scoped per project — starting a proc
under a name already held by an active proc in the same project is a conflict — and a
name is only reusable once the proc holding it settles. A monitor's member agent name
(for example `acme--mon`) is its own named proc shell.

**Kinds and ownership.**

| Kind       | Typical producer                                          | Owner and scope                                                     |
| ---------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| `tui`      | Work run and mirrored by ACE                              | The ACE process; scoped to its session                              |
| `command`  | `sase proc run` or `sase.procs.submit_proc()`             | The proc supervisor; attributed to one session or left unattributed |
| `detached` | Historical rows from retired CLI/API detached submissions | The legacy proc supervisor; global because no session owns the row  |

The programmatic submission API is `sase.procs.submit_proc()`. Pass `session_id=None`
when no interactive session should own the row; it still writes a `command` proc. The
legacy `sase.procs.submit_detached_proc()` wrapper remains for old callers but now
records the same unattributed command row. The public `read_procs()` and
`filter_procs()` helpers accept `kind=` as either one kind or a collection, including
`detached` when a caller needs historical rows. A `command` or historical `detached` row
that remains `pending` without a supervisor PID for 60 seconds is reconciled to `error`;
a mirrored `tui` row is left to its owning TUI. Epic launches record the approving
surface as `ace`, `telegram`, `cli`, or `axe`, with `api` retained as the fallback for
direct or unrecognized API callers.

Session attribution is not delegation: a `command` proc always executes under its own
supervisor, while its session id decides which TUI includes it by default. `--session`
accepts a full session id, a unique id prefix or short handle, or `current`, `latest`,
and `none`; the default is this process's ACE session, then the newest live one, then no
session. `sase proc run --session none` creates an unattributed command row.
`sase proc list` scopes work to the resolved session plus unattributed rows by default,
and widens to every session with `--all`. Rows from a session that has since exited
render dim with a `†` marker.

**Retention.** [`procs.history_limit`](configuration.md#procs) caps how many _finished_
procs are kept; pending and running work is never pruned for being old. Lowering the
limit removes the oldest finished rows and their log files. The legacy
`tasks.history_limit` key is still honored as a deprecated alias.

The CLI equivalents are `sase proc list`, `sase proc show ID` (`--follow` to stream),
`sase proc run [--session SESSION|none] -- COMMAND` (`--wait` to stream and inherit the
exit code), and `sase proc kill ID`. A hidden legacy `--kind` filter remains for
historical kind rows. Approved epics normally launch as [monitor shells](monitors.md);
only an unresolvable planner agent family uses an unattributed command proc. See the
[CLI reference](cli.md#daily-operation).

### Keybindings

| Key                 | Action                                       |
| ------------------- | -------------------------------------------- |
| `j` / `k`           | Navigate proc list                           |
| `'`                 | Jump to a proc row via adaptive hints        |
| `a`                 | Toggle scope: this session / all sessions    |
| `K`                 | Kill selected running proc (durable or live) |
| `Enter`             | Open the selected monitor's agent            |
| `d`                 | Dismiss selected completed proc              |
| `D`                 | Dismiss all completed procs                  |
| `e`                 | Open proc output in `$EDITOR`                |
| `y`                 | Copy proc output to clipboard                |
| `Ctrl+D` / `Ctrl+U` | Scroll output pane down / up                 |
| `g` / `G`           | Jump output pane to top/bottom               |
| `Tab` / `Shift+Tab` | Switch Admin Center tabs                     |
| `q` / `Esc`         | Close SASE Admin Center                      |

## Updates Tab

Open the SASE Admin Center with `#`, then press `6`. The Updates tab has **Core**,
**Plugins**, and **Agent CLIs** sub-tabs; cycle them with `]` / `[`. Core shows SASE
package versions and incoming commits. Plugins hosts the catalog browser and its
install/update/uninstall/mode-switch actions. Agent CLIs shows provider-colored
installed → latest rows, exact update or manual commands, vendor docs links, update
marks, and durable update history. Providers that opt out of independent CLI management,
including the bundled internal Fakey provider, are omitted from this sub-tab. On Plugins
and Agent CLIs, `'` jumps to an item row via adaptive hints; Core has no list, so `'` is
a silent no-op there.

Every sase-managed agent-CLI update run from `,U`, `A`, or `sase agent-cli update` is
appended to `~/.sase/logs/agent_cli_updates.jsonl`. Runs where no command reaches a
terminal outcome are not recorded. The Agent CLIs sub-tab renders that journal below the
selected CLI's details; `H` toggles between this CLI's executed update rows and a
run-grouped timeline across all CLIs. Configure the panel with
`ace.updates.agent_cli_history` and `agent_cli_history_max_rows`.

Automatic checks publish one composite snapshot after first paint. Ten-minute session
ticks only revalidate cached SASE/plugin rows and provider names already known outdated;
full discovery waits for the longer configured recompute cadence, and provider registry
lookups retain their own cache. The top bar renders purple/amber SASE and cyan `CLI`
segments with separate counts.

Every mutation opens a confirmation preview first, and `Ctrl+D` / `Ctrl+U` scroll long
preview panes. When commit previews are enabled and a comparable range is available,
core and installed-plugin **update** confirmations load incoming commits by repository
in the background; install confirmations do not. The global `,U` comprehensive
confirmation additionally groups SASE, Agent CLI, and agents-repository work into
labeled sections with update/current/skipped glyphs, counts, and commands. Its **Agents
repos** section uses a captured no-network status snapshot from the enabled-project
inventory. Every represented project remains runnable even when its cached status is
current; lifecycle-disabled projects are absent rather than shown as skipped. The
tracked proc runs Agent CLI commands first, the SASE/core/plugin leg second, and one
all-enabled-project agent sync last. A failure in the final leg is reported alongside
the independent earlier results. After a changed core/plugin update restarts ACE, the
one-shot result toast can show applied commits grouped by repository as well as
file/line statistics. Configure the toast with `ace.updates.post_update_toast_commits`,
`post_update_toast_max_commits`, and `post_update_toast_diffstat`.

Global `,U` captures the agent-CLI candidates from the latest completed automatic
result, revalidates exactly those names, and previews one comprehensive tracked update;
the Updates-pane load cannot broaden the captured set. Manual-only providers remain in
the preview with their suggested command or docs. A real SASE/core/plugin code change
restarts ACE and axe only after provider and agents-repository work finishes, while
provider-only updates refresh in place.

`u` remains pane-wide and updates SASE core plus installed plugins. `A` is the separate
pane-wide agent-CLI action: on the Agent CLIs sub-tab it updates the marked `Space`
selection, and elsewhere it targets every safely updatable installed CLI. See the
[Updates tab reference](configuration.md#updates-tab) for the full keymap and behavior,
[Plugins](plugins.md) for the equivalent `sase plugin` CLI, and
[Agent providers](agent_providers.md#inventory-and-updates) for the equivalent
`sase agent-cli` CLI.

Separately, ACE fetches and checks enabled agents repositories after first paint and on
the remote cadence configured by `ace.agents_sync`; cheaper checks between fetches only
reconcile cached entries and receipts. A green `⇅ N` top-bar badge appears only when
incoming hoods from other owners are already captured in the cache and not covered by
import receipts. Its tooltip lists the exact projects and hoods; clicking it imports
only those cached hoods without fetching, pulling, pushing, exporting, or mutating the
sidecar checkout. See [Agent Hood Synchronization](agents_sidecar.md) for privacy,
import, status, and recovery behavior.

## Snippets

The prompt input supports expandable text snippets triggered by pressing `Tab`. Snippets
are configured in the `ace.snippets` section of `sase.yml` as a mapping of trigger words
to template strings:

```yaml
ace:
  snippets:
    fix: "Please fix the following issue:\n$0"
    review: "Review this code for correctness, performance, and style."
    bug: "Bug in $1:\n\nExpected: $2\nActual: $3\n\nPlease fix.$0"
```

### Usage

1. Type a trigger word (e.g., `fix`) in the prompt input.
2. Press `Tab`. If the word before the cursor matches a snippet, it is replaced with the
   template text.
3. If the template contains tabstop markers (`$1`, `$2`, ...), the cursor jumps to `$1`
   first. Press `Tab` again to advance to `$2`, then `$3`, and so on. `Shift+Tab`
   retreats through already visited tabstops. `$0` marks the final cursor position after
   all tabstops are visited. If there are no tabstop markers, the cursor moves to the
   end of the expanded text.

**Tab priority:** Snippet expansion always takes priority over tabstop advancement. If
you type a trigger word at an active tabstop and press `Tab`, the snippet expands rather
than jumping to the next tabstop. Expanding inside the live snippet nests the new
snippet session: ACE visits the nested snippet's tabstops first, then resumes the
enclosing snippet at the next outer stop. Expanding outside the current snippet resets
the tabstop session.

**Multi-line indentation:** When a multi-line snippet is expanded on an indented line,
continuation lines automatically inherit the leading whitespace of the trigger line.
Tabstop positions are adjusted accordingly.

Trigger words are matched against the alphanumeric/underscore word immediately before
the cursor. If no snippet matches, `Tab` advances to the next tabstop (if any are
remaining from a previous expansion), and `Shift+Tab` retreats to a previously visited
tabstop. If neither snippet action succeeds, the key falls back to INSERT-mode list
shifting when the cursor is on a supported marker line. Advancing from the final tabstop
clears the session before that same fallback check runs.

XPrompt-derived snippets compose normal xprompt references before they enter the snippet
registry. After xprompt-derived snippets and `ace.snippets` are merged, any snippet can
splice another snippet by trigger with `#[trigger]`. `#[trigger(value)]` and
`#[trigger:value]` fill the referenced snippet's `$1`, `$2`, ... tabstops before
splicing. The final template is renumbered so tabstops from the caller and referenced
snippets do not collide.

### Capitalized aliases

Every effective snippet also gains a generated initial-capital alias. For each explicit
trigger, SASE uppercases only its first character — the rest of the trigger is preserved
byte-for-byte — to form a companion trigger, and uppercases only the first character of
the resolved template to form the companion expansion. So authoring only

```yaml
ace:
  snippets:
    foo: "foo bar baz"
```

exposes both `foo` → `foo bar baz` and `Foo` → `Foo bar baz`.

- Only the first character changes. Triggers that are already capitalized,
  digit-leading, or underscore-leading produce no extra entry, and a template whose
  first character has no uppercase form expands unchanged (its distinct trigger alias is
  still created).
- An explicitly authored capitalized trigger always wins. If both `foo` and `Foo` are
  defined, each keeps its own template, and no alias is generated over the authored
  `Foo`.
- Aliases are runtime-only. They are never written back to `sase.yml`, xprompt front
  matter, or chezmoi source files, and they never prevent you from later defining the
  capitalized name yourself.
- Both spellings participate in `#[trigger]` composition, so `#[foo]` and `#[Foo]` both
  resolve, and generated templates preserve tabstop and escape behavior.

The rule applies uniformly to xprompt-derived snippets, merged `ace.snippets`, and
snippets saved into the current ACE session — including a second save that updates an
already-pending trigger. The same pairs appear through ACE,
`sase editor helper-bridge snippet-catalog`, normal LSP completion, and the native Rust
fallback.

You can also create a snippet on the fly from the prompt save panel, opened with `gx`,
`Ctrl+G x`, or `Ctrl+G Ctrl+X`. Press `Ctrl+X` in that panel to switch to snippet mode
and choose which config file should store the new `ace.snippets` entry;
`Ctrl+G Ctrl+X Ctrl+X` performs that sequence directly from the draft. In snippet mode,
rows are grouped by source and sorted alphabetically by trigger; snippet completions
elsewhere are listed in trigger order, too, for stable display. As soon as ACE reports
the snippet as created or saved, it is available to every prompt input already open in
the current TUI; no prompt remount or restart is needed. When
[`ace.snippet_config_path`](configuration.md#acesnippet_config_path) is configured, this
panel's row list always offers it, pre-selected, as a synthetic destination row — even
when it points outside the standard discovered locations — and shows why if it falls
back to a discovered location instead (for example
`configured path unusable: read-only`).

When `use_chezmoi` is enabled, the save panel writes the chezmoi source file first. ACE
keeps that successfully written snippet live as session state even before deployment.
Skipping or failing the optional commit/push/apply step does not remove it from the
running TUI, but another SASE process will not see the source-only change until chezmoi
is applied. SASE applies chezmoi from this flow only after the user confirms the
optional commit-and-push action.

Editors using `sase lsp` can receive the same registry as LSP snippet completions after
bare trigger words when the client advertises `completionItem.snippetSupport`. The
server uses the editor helper operation `sase editor helper-bridge snippet-catalog` as
the authoritative source and falls back to native Rust loading only for simple snippets
if the helper is unavailable. Clients without snippet support do not receive these
entries, because raw `$1` / `$0` markers would not behave like ACE tabstops.

### Authoring a snippet from the prompt bar

`gt` (NORMAL) or `Ctrl+G t` (INSERT) opens a dedicated snippet pane at the bottom of the
prompt input stack, a faster loop than the general save panel above when you already
know you're authoring a trigger:

1. **Name it.** `gt` opens the trigger-name panel: type a trigger and it validates live,
   lists up to six existing triggers that share your typed prefix (`Tab` completes to
   the highlighted one), and shows the destination file the entry will be written to.
   `↑`/`↓` (or `Ctrl+P`/`Ctrl+N`) cycle the destination among the other discovered
   config files for this invocation only — it never rewrites `ace.snippet_config_path`.
   The verdict line reports one of: an invalid trigger; `✓ Create` for a fresh trigger;
   a warning that the trigger already exists in the destination (`Enter` will load it
   for editing); a warning that it's defined in a different config file (saving here
   will shadow or be shadowed by that file, per your project's precedence); or a warning
   that the trigger is derived from an xprompt and this entry will override it.
2. **Open the pane.** `Enter` opens the snippet pane — empty for a new trigger, or
   pre-filled with the current definition (from the destination, the shadowing file, or
   the derived xprompt template) when the trigger already exists. The pane always opens
   in INSERT mode and is unmistakably not a prompt pane: its own separator rule names
   the `⇥ <trigger>` and destination, with a state marker (`✓` clean, `●` dirty, `new`
   for an unsaved trigger), and its own accent color and subtitle. It is never included
   in a launch, a stash, or a save-as — `Enter` in it means "save the snippet", not
   "submit the stack".
3. **Save it.** `Enter` in the pane opens the save confirmation, showing `[Draft]` for a
   brand-new trigger or opening straight on `Diff` — a real `difflib` unified diff
   against the existing entry — for an overwrite (`Ctrl+O` cycles Draft / Existing /
   Diff, `Ctrl+D`/`Ctrl+U` scroll). An empty body refuses to save; a byte-identical
   overwrite reports `✓ No changes` and closes without writing; a destination that
   changed on disk since the pane opened warns and offers `r` to reload the current
   definition instead of overwriting blindly. `Enter` writes the file, publishes the new
   template to every open prompt input in the session immediately (no restart needed),
   and closes the pane only once the write succeeds — a failed write leaves the draft in
   place to retry.
4. **Follow-ups.** A successful save runs the same post-write chooser as the general
   save panel: an optional commit & push, and — for a chezmoi-managed destination — a
   scoped `chezmoi apply` limited to the deployed snippet file.
5. **Discard or rename.** `Ctrl+C` discards the pane; if you've typed anything different
   from the loaded body, a confirmation guards against losing it. `Esc` returns to
   NORMAL mode without discarding. `gt` again while the pane is open re-opens the
   trigger-name panel prefilled with the current trigger to rename or re-target it
   without touching the body you've written. On close (saved or discarded), focus and
   the cursor return to exactly the pane and position you were at before `gt`.

### XPrompt Picker (`#@`)

Typing `#@` (the `#` character followed by `@`) opens the XPrompt snippet picker modal.
This lists all available xprompts (including project-local xprompts from `sase/sase.yml`
files) and inserts the selected reference at the cursor position. Inline-capable
xprompts and workflows insert as `#name`; standalone workflows insert as `#!name`. The
picker uses the same argument-aware skeletons as xprompt completion, so typed inputs can
be filled immediately after selection. Markdown xprompt swarms are inline-capable and
insert as `#name`. This is separate from the `ace.snippets` mechanism — it provides
quick access to xprompt references rather than expanding static templates.

## Auto-Refresh

ACE auto-refreshes data at a configurable interval (default: 10 seconds). The remaining
time until the next refresh is shown in the info panel. Set `--refresh-interval 0` to
disable.

Tab switches are instant: cached data is shown immediately while a background refresh
runs asynchronously, so moving between tabs never blocks on disk I/O.

When the inotify-based artifact watcher is active, the periodic tick is
**event-driven**: it consults per-surface dirty flags (`_dirty_changespecs`,
`_dirty_agents`, `_dirty_axe`) and short-circuits the whole tick when nothing has
changed. A 60-second `FULL_SANITY_REFRESH_SECONDS` floor still triggers a full reconcile
to recover from missed inotify events, so a quiet TUI does ~zero work between real
changes without going stale.

### Performance Tracing

For diagnosing TUI latency, set `SASE_TUI_TRACE=1` before launching `sase ace`. Tracing
is near-zero-cost when the env var is unset; with it enabled, each instrumented hot path
emits one JSONL line per span to `~/.sase/perf/tui_trace.jsonl` (override via
`SASE_TUI_TRACE_PATH=…`). See [`docs/perf_runbook.md`](perf_runbook.md) for the full
span catalog, benchmark harness, and per-phase performance targets.
