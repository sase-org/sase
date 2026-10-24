---
title: Tabs and panes
description: Top-level TUI tabs, Artifacts panes, navigation, copy mode, marks, and Beads.
---

# Tabs and panes

This page lists the sase TUI tab system, Artifacts panes, navigation, copy mode, marks,
and the Beads pane.

## Tab System

sase's TUI has three tabs, cycled with `Tab` and `Shift+Tab`:

While a prompt input bar is open, `Tab`/`Shift+Tab` belong to the prompt (snippet
expansion, tabstops, list indent) and never switch tabs.

| Tab           | Description                                                                                                                                                                                                                                                                                                                                                                              |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Agents**    | View running and completed agents, their files and prompts                                                                                                                                                                                                                                                                                                                               |
| **Artifacts** | Browse Commits, Patches, Beads, configured document providers, and the optional Files beta pane. Agent history lives in the Agents tab Archive (`,a`); the Artifacts ▸ Agent sub-tab is off by default (`sase flag disable artifacts_agent_pane_retired` restores it). See [TUI migration notes](../upgrading/tui.md#artifacts-agent-pane) and [Files pane migration notes](../upgrading/tui.md#artifacts-files-pane), the [Artifacts pane contract](../../contribute/artifacts-pane-contract.md), and [visual grammar](../../contribute/artifacts-pane-visual-grammar.md). |
| **Services**  | Monitor the service host, configured service procs, scheduler work, and background commands                                                                                                                                                                                                                                                                                              |

Agents is the first tab and the startup default. Each tab has contextual help: press `?`
to open the Help modal on its **Keymaps** view, then `]` to switch to the tab's
**Guide** view. While Help is open, the configured tab-switch keys still switch sase's
TUI tabs and refresh both views in place. By default those keys are `Tab` and
`Shift+Tab`; if you remap them, the modal follows the configured keys.

Press `/` in the Keymaps view to open a live filter bar. Typing splits the query into
whitespace-separated tokens that must **all** match — each token is checked against a
row's section name, key display, or description, so a token that matches a section name
(e.g. `beads`) pulls in every keymap in that section. Matched text is highlighted and a
counter shows how many keymaps and sections matched. The filter follows you across
sase's TUI tab switches while Help stays open, but resets whenever the panel is closed
and reopened. `Esc` clears an active filter before it closes the Help modal.

On first use, empty tabs render onboarding states instead of blank panels: the Patches
view shows a getting-started card when no Patches or saved queries exist yet, and the
Agents tab walks through launching a first agent — the project/Patch launch hint appears
only when a launchable target exists — and can recommend installing plugins from the
Admin Center when no third-party plugins are installed. Onboarding cards carry "learn
more" links into the published docs. An empty Beads pane points agents to
`/sase_new_task`, calls out sized draft tasks, and explains how ready tasks enter
TaskTriage.

Within Artifacts, number keys follow the visible left-to-right order of the strip:
Commits, Patches, and Beads are always **1**, **2**, **3**; configured document-provider
tabs such as Plans and Research take the next digits; and Files, when enabled, renders
last with the highest digit — **4** with no provider tabs configured, **6** with two.
With Files hidden, remaining panes use positional numbering. Digits stop at `9`, and the
Files pane keeps `9` when the runtime strip grows past nine panes; middle overflow panes
may then have no digit. Use `[` / `]` to cycle through
the complete runtime strip. As horizontal space tightens, the strip chooses the widest
tier that fits from a full → compact → micro ladder and re-renders only when the tier
changes. Compact removes outer padding; micro also tightens the separators and hides
inactive labels, leaving their digits and icons visible. If even micro is wider than the
available space, micro remains selected. Every Artifacts tab has an icon, including
provider tabs whose missing or invalid `ref.icon` falls back to the generic `◆`, so the
micro tier never leaves an inactive tab unidentified. Hovering a tab shows that pane's
one-sentence description. These keys act only while Artifacts is visible. Press `p` on
any Artifacts pane to change the shared project scope — first-open seeds from the
[current project](projects-tab.md#current-project) — or use the command palette to jump directly to a
top-level view. Patches remains query-scoped: choosing a project there rewrites the
Patches query's `project:` token. The strip order does not change the entry point:
opening Artifacts still selects Commits by default.

<a id="contextual-artifact-links"></a>
<a id="link-jumps"></a>
Moved to [Artifacts tab](artifacts-tab.md#contextual-artifact-links).

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

The Patches pane remains content-sized instead of reserving empty list space. Its mode
sets the maximum list width for the available terminal width, while the existing 43-cell
readability floor and 80-cell upper bound still apply.

### Pane Description Brief

Every Artifacts pane — the five built-ins, the Plans pane, and every pane a sidecar ref
creates — carries a resolved, never-empty description, shown as a host-owned brief
directly under the sub-tab strip. Press `D` to cycle it through three modes:

| Mode      | What you see                                                     |
| --------- | ---------------------------------------------------------------- |
| `off`     | Nothing; the row disappears entirely.                            |
| `summary` | One line: an icon and a one-sentence summary, ellipsized to fit. |
| `full`    | The summary plus a longer body, capped at 6 rows.                |

`ace.artifacts.description_mode` seeds which mode a session starts in (default
`summary`); `D` changes it in memory for the current session only. Clicking the brief
cycles it the same way. An unconfigured document-provider pane shows, in `full` mode
only, a dim italic hint naming both places its description can be configured:
`ref.pane.description` in the sidecar's ref config, or
`ace.artifacts.panes."<pane_id>".description` in `sase.yml`. See
[`ace.artifacts`](../config/ace-behavior.md#aceartifacts) for the config surface
and
[Artifacts pane visual grammar](../../contribute/artifacts-pane-visual-grammar.md#pane-brief)
for the full rendering rules.

### Navigation in Agent, Commits, Beads, Provider Documents, and Files

The Agent pane is off by default (`artifacts_agent_pane_retired`) and shows only
with the opt-out. See [TUI migration notes](../upgrading/tui.md#artifacts-agent-pane). The non-Patches panes share fast navigation over their selectable
left-panel entries. Commits and Files skip day headings; Agent, Beads, and provider
document panes skip group, section, and empty-state rows as applicable. Movement clamps
at the first or last entry and silently does nothing when a list is empty.

| Key                       | Action                                                                                 |
| ------------------------- | -------------------------------------------------------------------------------------- |
| `g` / `G`                 | Select the first / last agent, commit, issue, bead, document, or file                  |
| `Enter`                   | Open the selected commit, document, bead, or file in its full-screen reader            |
| `Ctrl+F` / `Ctrl+B`       | Move down / up 10 selectable entries                                                   |
| `Ctrl+D` / `Ctrl+U`       | Scroll the active right-hand detail pane down / up (half page)                         |
| `'`                       | Show adaptive entry hints; press `'` again for the first entry or the last jump origin |
| `Ctrl+O` / `Ctrl+Shift+O` | Walk the link trail first, then the pane jump stack; back falls through to first hint  |
| `$$` / `$1`-`$9` / `$0`   | Follow the first / numbered artifact link, or open the complete links panel            |
| `Ctrl+J` / `Ctrl+K`       | Load `ace.page_size` more rows / unload that page (rewrites the host `limit:` cap)     |

Hint keys select an entry without activating it. Jump-back history is kept separately
for each non-Patches pane, and stale origins disappear automatically after filtering,
changing project scope, refreshing data, or collapsing an expanded bead tree. Escape or
an invalid hint exits jump mode. These actions use the configured keymap values; the
keys above are the defaults.

On the Agents tab Archive, `Enter` opens the [Archive chooser](files-and-preview.md#archive-agents-tab). `l`
/ `h` expand and collapse containers.

When the selected entry has declared relationships, a relation panel appears at the
bottom of the list column, starting collapsed into a one-line rail that names its own
expand key (`.` by default) so it is never hidden knowledge. Press `.`
(`toggle_relation_panel`) or click the rail to expand it; the expanded panel's border
carries the reverse affordance (`{key} collapse`, bottom-right) so it can be collapsed
the same way. Its section names come from the pane contract, so examples include parents
and children, document lifecycle stages, dependencies, linked beads or plans, and
file-version families. Navigation is two keystrokes: first a relation mode, then the key
printed in square brackets beside the target row. The modes are `<` for ancestors, `>`
for descendants, and `~` for session or siblings, and the footer lists only the ones the
current entry actually has; these keys stay live even while the panel is collapsed. A
section header ending in `(N hidden)` means the query is filtering out that many
targets, a row ending in `(missing)` points at an entry that no longer exists, and a row
ending in `→ <pane>` crosses to another Artifacts pane.

On Patches, choosing a hidden same-pane target rewrites the query to reveal it rather
than failing. Patches saves the query and selection you started from first and pushes
the old query onto the same history stack `^` walks, so `^` returns to the exact view
you came from. Other panes run relation jumps through the same engine as `$` link
follows (see [Link Jumps](artifacts-tab.md#link-jumps)): a filtered-out target is unfolded, fetched, or
revealed by one reversible query rewrite, and each jump adds a link-trail hop that
`Ctrl+O` walks back.

Shared entry-jump surfaces allocate hints from the zero-based alphabet `0`–`9`, `a`–`z`,
`A`–`Z`. A session with at most 62 targets uses one character (`0` through `Z`). A
larger session uses two characters for every target, beginning `00`, `01`, …, `0Z`, `10`
and ending at the fixed `ZZ` capacity. The first character of a two-character hint keeps
jump mode open; the second completes the jump. Hints remain case-sensitive.

Outside the Artifacts panes above, a single shared implementation backs `'` everywhere
it appears: each Admin Center working section (see
[Global Keybindings](global-controls.md#global-keybindings)) and four modals — the notification options
modal, the model picker, the saved-group revival modal, and
[Launch Control](launch-control.md#launch-control-1). In all of them,
pressing `'` a second time while the hints are painted is the **jump back** key: it pops
the most recent origin off a bounded stack of the last ten pre-jump positions, rather
than toggling between one saved target and the current row. With an empty stack it falls
through to the first hinted row instead. The footer shows which of the two the next `'`
will do — `JUMP ' back` while the stack holds an origin, `JUMP ' first` when it does
not. Changes that shift which row is where — refiltering the model picker, paging or
deleting in the revival modal, drilling into or out of a Launch Control bucket, or an
async provider-snapshot reload — discard the stored origins instead of leaving them
pointing at whatever row inherited the index.

### Copy Mode in Agent, Commits, Beads, Provider Documents, and Files

Press `%` on any non-Patches Artifacts pane to open the context-aware **Copy as…**
palette for the visible entry. Rows are grouped by representation, show their configured
accelerator and a warm preview, and can be selected with the mouse, arrow keys or
`j`/`k` plus `Enter`, or the accelerator directly. `q`/`Esc` cancels. If an accelerator
is configured as `j`, `k`, or `q`, the configured copy target wins over navigation or
cancellation.

| Pane            | Keys                                                                                                                                                                             |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent           | `%@` artifact ref · `%!` ref in agent prompt · `%n` name · `%l` Markdown link · `%p` artifacts path · `%c` chat path · `%P` prompt · `%j` metadata JSON                          |
| Commits         | `%@` artifact ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` full SHA · `%m` message · `%r` `repo@sha` · `%p` plan                              |
| Beads           | `%@` artifact ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` id · `%t` title · `%b` description and notes · `%d` design · `%u` linked issue ref |
| Plans           | `%@` artifact ref · `%d` bead design ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%%` bead id · `%p` path · `%t` title · `%b` body                |
| Other providers | `%@` artifact ref · `%l` Markdown link · `%J` metadata JSON · `%!` ref in agent prompt · `%p` path · `%t` title · `%b` body                                                      |
| Files           | `%%` contents · `%@` artifact ref · `%L` Markdown link · `%p` stored path · `%o` source path · `%l` label · `%j` metadata JSON · `%!` ref in agent prompt                        |

`%s` captures the current `sase tui` tmux pane on every view.

The palette and copied value follow the active pane. After selection or cancellation,
the footer returns to the active pane's normal bindings. An unknown printable key warns
but leaves the palette open so another choice can be made.

When entries are marked, the reference choice copies newline-separated prompt
references, the Markdown-link choice copies a bullet list, the metadata-JSON choice
copies one array, and the handoff choice seeds one prompt with the marked set. Entries
that cannot produce the selected representation are skipped; the completion toast
reports both the copied and skipped counts. The palette title reports the visible marked
count and applicable rows use plural labels such as **commit SHAs**.

The same `%` prefix opens the palette above copy-forwarding readers and modals,
including the preview panel. Dismissing the palette returns to the underlying modal.
Snapshot choices dismiss the palette before capture, so the palette itself is not
included in the copied pane.

### Marks in Agent, Commits, Beads, Provider Documents, and Files

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

<a id="filtering-agent-patches-commits-beads-and-plans"></a>
Moved to [Filtering](filtering.md#filtering-agent-patches-commits-beads-and-plans).

### Beads Pane

The top-level Beads view (`3`) is the work-item home for standalone tasks, epic plan
beads, and their phase beads. Every bead appears once: tasks occupy their own section,
while epics expand with `l` and collapse with `h` to reveal phases. Rows show stored
status and ownership metadata, `✦` when a task has a pending TaskTriage decision, and
`▤` when the bead links a plan document. Linked issue chips use `○` for open, `●` for
closed, and `?` for a stale issue absent from the complete cached listing; stale or
drifted links are highlighted, and `+N` summarizes additional links. Closed beads are
loaded but hidden by the visible `-status:closed limit:<page_size>` default; press `f`
to edit or clear that query. Section headings report matched and total counts while a
filter is active.

`n` collects a standalone task for the selected project. Title, filing reason, size, and
task type are required. The reason is one or two sentences, at most 2000 characters, and
is stored separately from the title and description. `Ctrl+S` creates the bead and `Esc`
cancels. See [Creation Reason](../work-units/beads.md#creation-reason).

The pane supports the full bead workflow:

| Key                 | Action                                                                          |
| ------------------- | ------------------------------------------------------------------------------- |
| `j` / `k`           | Select the next / previous bead                                                 |
| `Enter`             | Open the complete bead detail in the preview reader                             |
| `f`                 | Edit the bead filter query                                                      |
| `Ctrl+J` / `Ctrl+K` | Load more matching beads / unload one page (rewrites `limit:`)                  |
| `l` / `h`           | Expand / collapse the selected epic                                             |
| `s`                 | Cycle the selected bead's status using the type-aware sequence below            |
| `z`                 | Snooze the selected task bead (or edit/cancel an existing snooze)               |
| `e`                 | Edit the bead's valid fields                                                    |
| `N`                 | Append a note; `@path` attaches a snapshot and `Ctrl+T` cycles its audience     |
| `n`                 | Create a task bead in the selected project (filing reason required)             |
| `c`                 | Close with a required reason and optional note, or reopen a closed bead         |
| `w`                 | Launch an epic or launchable task; phase work launches with its epic            |
| `E`                 | Open a linked external issue                                                    |
| `y`                 | Copy the bead's `@bead:` reference                                              |
| `% u`               | Copy a linked issue reference (copy mode)                                       |
| `b`                 | Enter issue-action prefix mode                                                  |
| `$`                 | Arm the [link rail](artifacts-tab.md#contextual-artifact-links), e.g. to follow the linked plan |
| `R`                 | Open the [Refresh panel](agents-tab.md#refresh-panel)             |

`N` opens a modal for appending a note and leaves earlier notes in place. Add `@<path>`
to capture a file snapshot when you save with `Ctrl+S`: `Tab` completes paths, pasting a
single existing file path inserts an attachment reference, and `@@` inserts a literal
`@`. `Ctrl+T` cycles the attachment audience through automatic, private, and public.
Public asks you to confirm on save; policy can still reject the note and return you to
the editor. The bead detail lists each attachment's `🌐` or `🔒` chip from the stored
descriptor and leaves availability badges and thumbnails to the attachment viewer. See
[From the Beads pane](../work-units/bead-attachments.md#from-the-beads-pane).

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
[Snoozing a Task Bead](../work-units/bead-triage.md#snoozing-a-task-bead)) and an
optional reason field. Pressing `z` on an already-snoozed task opens the same modal in
re-snooze mode, showing the current wake time and offering a cancel-snooze choice. A
snoozed row in the list shows the `snoozed` status glyph and a dim relative wake time.

When that worker appears on the Agents tab, its bead badge points directly to the task,
and its **SASE CONTEXT / BEAD** lane shows the task title and description, plus size
when one is stored, without trying to resolve an epic plan.

<a id="archive-agents-tab"></a>
Moved to [Files and preview](files-and-preview.md#archive-agents-tab).

### Document Provider Panes

Artifacts includes one document pane per configured artifact-reference provider. The
fixed tabs are Commits, Patches, and Beads, with the Files beta pane shown when enabled;
provider-backed document tabs such as Plans and Research appear between Beads and Files
when an enabled project configures the matching sidecar `ref:` policy. Persisted selections use stable ids such as `ref:plan`
and `ref:research`, so a missing provider falls back to Commits instead of crashing
startup. Each pane renders an icon before its label — the four fixed marks (`◉` Commits,
`⎇` Patches, `◈` Beads, `▤` Files) are built in, and a provider pane's mark comes from
its sidecar `ref.icon`. The active tab's icon takes that pane's accent color; inactive
icons render dim. A missing `ref.icon`, one that fails validation, or one wider than two
terminal cells uses the generic `◆` provider icon instead.

Plans is the built-in provider-backed document pane for the plans sidecar. It keeps the
existing plan actions: `A` and `X` approve or reject pending proposals. A plan's owning
bead (and a bead's linked plan) is an artifact link, so follow it from the
[link rail](artifacts-tab.md#contextual-artifact-links) with `$`. Plans groups its list by **Kind**,
**Status**, or **Project** (`o` / `O`). Other document providers reuse the same list,
filter, detail, preview, copy, and refresh behavior from their declared properties and
detail fields, and group only when they declare `ref.grouping` (or `ref.pane.group_by`);
see
[Grouping declarations](../../contribute/artifacts-pane-contract.md#grouping-declarations).

### Commit Detail and Linked Plans

Press `Enter` on a Commits entry to open its full message and syntax-highlighted diff.
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
known project workspace and its plans store. sase's TUI does not clone or materialize a
missing store. A missing tag, invalid reference, unavailable path, non-file path, or
unreadable file produces a specific toast and leaves the commit visible. Moving to
another commit always returns the modal to commit mode.

<a id="preview-reader"></a>
Moved to [Files and preview](files-and-preview.md#preview-reader).

<a id="files-pane"></a>
<a id="filtering-files"></a>
Moved to [Files and preview](files-and-preview.md#files-pane).

### Epic phase sizes across plan surfaces

sase's TUI uses the literal scope labels `xsmall`, `small`, `medium`, `large`, and
`xlarge`, with mint, sky, gold, rose, and violet chips whose text remains the primary
signal. Valid older plans and phase beads with an omitted size use the stable `small`
fallback, while an invalid authored value never produces a confident chip or count. The
Plans pane also uses that shared display fallback for a legacy standalone task with no
stored size; launch routing uses the same `@small` fallback.

| Surface                                                                  | Size contract                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Agents author and lander                                                 | Shows every normalized authored size in roadmap order.                                                                                                                                                                                                                                                 |
| Agents phase worker                                                      | Shows only that worker's normalized authored size, preserving phase isolation.                                                                                                                                                                                                                         |
| Artifacts / Beads epic, phase, and task beads                            | Shows current persisted bead sizes in rows and details; the epic detail summarizes direct children in `xsmall`, `small`, `medium`, `large`, `xlarge` order. Standalone tasks appear in their own section. A legacy task with no stored size displays and launches through the shared `small` fallback. |
| Artifacts proposals, linked plans, and archives                          | Retains the authored `phases` property exactly once instead of adding a competing roadmap.                                                                                                                                                                                                             |
| Telegram epic review                                                     | Adds a validated textual size breakdown while retaining the detailed Properties card and source/PDF attachment.                                                                                                                                                                                        |
| Epic clan summary, `sase bead show`, and epic work preview               | Continues using persisted bead sizes, which these execution surfaces already exposed.                                                                                                                                                                                                                  |
| Raw approval, validation/schema, source/PDF, and mobile attachment paths | Remains a lossless generic/source view; authored phase metadata is preserved without a second summary.                                                                                                                                                                                                 |

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Filtering](filtering.md) — Agents, Patches, Commits, Beads, and Plans.
- [Files and preview](files-and-preview.md) — Files pane, Preview reader, Archive.
- [Artifacts tab](artifacts-tab.md) — links, Patches keys, and PR chips.
