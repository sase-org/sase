---
title: Files and preview
description: The Files pane, Preview reader, and Agents tab Archive in the sase TUI.
---

# Files and preview

This page lists the Files pane, Preview reader, and Agents tab Archive in the sase TUI.
Default configurable actions are listed in the generated
[TUI keymaps reference](keymaps.md).

## Archive (Agents Tab)

Agent history lives in the Agents tab's **Archive** view. See
[TUI migration notes](../upgrading/tui.md#artifacts-agent-pane).
Press `,a` to toggle between the Inbox and the Archive; the tab label reads `Agents ◷`
while the Archive is active. The Inbox holds undismissed agents, including completed
runs; dismissing an agent moves it to this machine's Archive. Selecting an archived run
shows its retained content in the decks (Main, Files, Tools, FINAL, Record) without
restoring it, marking it read, or starting another run.

The Archive's committed query always contains `in:archive`, shown as a chip, so `^`
history, saved slots, and
[`sase agent search`](../cli/agent.md#sase-agent-search) all agree on what is on
screen. Each view parks its own query, selection, folds, and deck state, and `,a` always
returns each view exactly as left. Pane-era saved slots and history were migrated once
to free `agents-live` slots with `in:archive` prepended.

Day banners group the list by default; `o` switches grouping between day, project,
outcome, and model. `j` / `k` move across rows, banners, containers, and `⋮ more` rows,
while `J` / `K` move between the Inbox pulse and the list. Selecting a row hydrates the
real decks from the retained bundle: the full prompt, the reply, diffs, tool calls, and
the Record deck's Lifecycle, Provenance, Relations, and Links cards.

The Jump panel shows the archived agent's relations, and the `linked:`, `relation:`, and
`artifact:` facets expose the same graph as query terms.

`Enter` opens the action chooser. Its ARCHIVE section lists Restore first:
`Restore to inbox`, `Restore N marked` when Archive marks exist, or
`Restore clan|session <name> (N members)` on a container. Marks take precedence over the
highlighted row. A container, collapsed or expanded and highlighted or marked, restores
every member that matches the current query, and the label's count is exactly the set
Restore acts on. Restore shows the existing agent in the Inbox again and starts no new
run.

Choose Restore with `r` **inside the chooser** to stay in the Archive. Successfully
restored rows dim and gain a `⌂ restored` suffix until the query changes or you leave
the Archive. A toast reports the outcome; mixed sets report restored, skipped, and
failed counts. The saved Inbox view keeps its selection, agent tab, folds, and jump
anchors. `Restore and show in inbox` (`s`, chooser only) switches to the Inbox when
exactly one agent is successfully restored; a larger restored set stays in the Archive
with a count summary. If the Inbox query hides the single restored agent, SASE replaces
it with an exact `name:"…"` query and saves the old query in history (`^`).

Fork (`F`, in the chooser and on the list) is offered for one named archived agent with
a recorded chat path or retained reply. It opens a prompt prefilled with that agent's
fork reference; submit the prompt to start a new run. Clan and session containers do not
offer fork. For an individual readable entry, the READ section offers Open chat in
`$EDITOR` (`e`), Copy `@agent` reference (`y`), and More copy targets (`%`). These also
work from the list. Opening chat does not restore the agent, but the editor opens the
file in its normal mode; SASE does not enforce read-only editing.

For a readable entry that cannot be restored, the chooser initially selects Open chat.
If its bundle cannot be read, the detail title reads
`Archive entry unreadable — Record only`, and the Record deck still shows the available
index facts. That entry cannot open the chooser unless other runs are marked for
restore.

Live Inbox actions stay in the Inbox. `x`, `X`, `s`, `S`, `w`, `W`, `A`, `R`, `n`, and
`U` toast that the key acts on inbox agents and name `,a` to get back. Agent-tab `[` /
`]` and the tab picker say agent tabs live in the Inbox; `N` says tribes do. List `s` is
that blocked save action; it is not the chooser's restore-and-show key.

| Key       | Action                                                             |
| --------- | ------------------------------------------------------------------ |
| `,a`      | Toggle between the Inbox and the Archive                           |
| `Enter`   | Open the chooser (Restore first; Open chat when restore is absent) |
| `j` / `k` | Select the next / previous archive row, banner, or `⋮ more` row    |
| `J` / `K` | Move between the Inbox pulse and the Archive list                  |
| `o`       | Archive grouping picker: day · project · outcome · model           |
| `l` / `h` | Expand / collapse a container row                                  |
| `m` / `u` | Mark / clear Archive rows (separate from Inbox marks)              |
| `y`       | Copy the `@agent:` reference                                       |
| `%`       | Open the **Copy as…** palette                                      |
| `e`       | Open the retained chat file in `$EDITOR`                           |
| `F`       | Open a fork prompt for a named run with chat metadata or content   |

## Preview Reader

Press `Enter` on a Beads entry, provider document, or Files row to open its full
contents in the preview reader. Prompt-normal-mode `K` opens the same reader for a
previewable macro, skill, or file. When sase's TUI knows a canonical artifact reference,
the title shows that logical reference beside the resolved local path.

The reader opens at its normal size when the content fits and grows toward a
near-full-screen maximum (a thin backdrop margin remains) for long or wide content.
Width follows the 95th-percentile line width, so one very long line does not force full
width. Switching views with `R` or `p` only ever grows the panel; resizing the terminal
recomputes it.

| Key                 | Action                                                     |
| ------------------- | ---------------------------------------------------------- |
| `j` / `k`           | Scroll down / up one line                                  |
| `Ctrl+D` / `Ctrl+U` | Scroll down / up half a page                               |
| `g` / `G`           | Jump to the top / bottom                                   |
| `y`                 | Copy the complete preview contents                         |
| `Y`                 | Copy the local source path, when available                 |
| `%`                 | Open the active Artifacts sub-tab's **Copy as…** palette   |
| `R`                 | Toggle Markdown previews between rendered and source views |
| `p`                 | Toggle the full macro properties view                      |
| `/`                 | Open source search (smartcase substring matching)          |
| `n` / `N`           | Jump to the next / previous match with wraparound          |
| `o`                 | Open the source path in `$EDITOR` (falling back to `nvim`) |
| `Z`                 | Hand the source path to the rich terminal artifact viewer  |
| `Esc`               | Cancel input, clear active search, then close the reader   |
| `q`                 | Close the reader                                           |

Path-only actions are omitted from the footer when the preview has no local source path;
invoking one still produces a specific warning instead of failing. Clipboard operations
run in the background and report when no clipboard tool is available. Plans open in
rendered Markdown by default when they fit the reader's bounded render budget; macros,
skills, files, and oversized documents open as source.

For a macro or skill preview with declared properties (inputs, tags, skill/snippet/
memory flags, local macros, or steps), a compact band appears above the source pane
showing its description, an inputs table, and a dim chips summary of everything else it
declares. `p` opens a full, scrollable properties view — the same projection
`sase macro show` renders — with the band hidden while that view is active; `p` again
restores whichever mode was showing before. A preview with no declared properties (a
bare-body macro, a plain file, a bead, and so on) shows no band, no `p` row in the
footer, and `p` emits a warning toast instead of switching views.

Search is commit-on-enter: `/` opens a one-line input prefilled with the last committed
query, and `Enter` highlights every matching source line before jumping to the first
match at or below the current viewport. Queries containing an uppercase character are
case-sensitive; other queries are case-insensitive. Starting search from rendered
Markdown switches to source view. `Esc` in the input cancels the edit, while `Esc` after
a committed search first clears the matches and only closes the reader on the next
press.

Prompt `K` on a supported image path (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`) opens
the reader with an inline cell preview sized to the near-full-screen panel. It
re-renders on terminal resize. The footer shows
`Y path | % copy | Z viewer | esc close`, and `Z` opens the full-fidelity artifact
viewer. `y`, `/`, and `o` warn instead of acting on image previews.

## Files Pane

Files browses the artifact-file index that backs
[`sase artifact list`](../cli/artifact.md#sase-artifact-list). It is a beta pane, off by
default. Enable it with `sase flag enable artifacts_files_pane` or
`feature_flags: {artifacts_files_pane: true}`, then restart sase's TUI. While it is
hidden, following a `file:` link shows an enablement hint instead of opening the pane;
[`sase artifact list`](../cli/artifact.md#sase-artifact-list) still covers the same
index. See [TUI migration notes](../upgrading/tui.md#artifacts-files-pane). The Agent
pane is also off by default (`artifacts_agent_pane_retired`) and shows only with the
opt-out. See [its migration notes](../upgrading/tui.md#artifacts-agent-pane).
Configured document-provider panes appear between Beads and Files when Files is enabled.
Rows are grouped by logical file identity, so repeated captures of
`@file:~/bob/gtd.md` or repeated `sase artifact create` rows for the same logical
artifact appear as one selectable row with versions.

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

| Key                 | Action                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------ |
| `j` / `k`           | Select the next / previous file, skipping day headings                                     |
| `Enter`             | View the file: preview reader for Markdown and text, rich viewer for media                 |
| `Z`                 | Hand the marked visible rows — or the selection — to the rich terminal viewer              |
| `E`                 | Open text in `$EDITOR` (falling back to `nvim`); open media with `xdg-open`                |
| `a`                 | Jump to the producing agent on the Agents tab, reviving it first when dismissed            |
| `f`                 | Edit the pane's filter query                                                               |
| `Ctrl+J` / `Ctrl+K` | Load more matching files / unload one page (rewrites `limit:`)                             |
| `z`                 | Cycle the kind filter through All and the stored kinds present in the snapshot             |
| `o` / `O`           | Cycle grouping (**Source**, **Kind**, **Project**) forward / backward                      |
| `(` / `)`           | Select previous / next version for the current logical file                                |
| `y`                 | Copy the row's `@file:<id>` reference                                                      |
| `Y`                 | Copy the row's anchored stored path                                                        |
| `m` / `u`           | Mark / unmark the selected file · clear this pane's marks                                  |
| `%`                 | Open the Files **Copy as…** palette                                                        |
| `R`                 | Refresh the index (through the [Refresh panel](agents-tab.md#refresh-panel)) |
| `p`                 | Change the shared Artifacts project scope (first-open seeds current project)               |

These are the default keymap values; the Files-pane actions retain their `files_*`
configuration names and are remappable under
[`ace.keymaps.app`](../config/ace-keymap-configuration.md#acekeymaps) as
`files_next`, `files_prev`, `files_view_selected`, `files_open_viewer`,
`files_open_external`, `files_open_agent`, `files_filters`, `files_cycle_kind`, and
`files_copy_path`. `y`/`R` are the shared `artifacts_copy_reference`/`refresh` actions
every Artifacts pane binds. `Ctrl+J` / `Ctrl+K` are the shared
`artifacts_load_more`/`artifacts_unload` actions. Version cycling uses the old
nested-files sub-tab keys. The pane also shares the navigation and jump keys described
in
[Navigation in Agent, Commits, Beads, Provider Documents, and Files](tabs-and-panes.md#navigation-in-agent-commits-beads-provider-documents-and-files).

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

### Filtering Files

Files keeps its committed query visible in a persistent filter row, the same idle chrome
Agent, Patches, Stitches, Beads, and Plans use. Press `f` or `/` to edit it. Filtering
is purely in-memory over the loaded snapshot, so a query narrows thousands of rows
without a re-query. Files accepts `id:`, `kind:`, `project:`, `agent:`, `workflow:`,
`origin:`, `since:`, `until:`, and host-owned `limit:`, plus free text matched against
the label, logical path, stored path, source path, digest, and artifact id. `id:` is the
pane's identity field: it matches a logical file id exactly and stays free-text
searchable too. Tokens from different facets combine with AND semantics, while
comma-separated or repeated values within `id:`, `kind:`, `project:`, `agent:`,
`workflow:`, and `origin:` combine with OR semantics. `kind:` accepts the stored kinds
`chat`, `plan`, `image`, `markdown`, `pdf`, and `file`; `origin:` accepts `ref`,
`created`, and `capture`; `since:` and `until:` accept `YYYY-MM-DD`, `YYYY-MM`,
`YYYYMM`, or a relative `Nd` / `Nw` / `Nm` offset and may each appear once.

`z` and the `kind:` token drive the same filter state: cycling with `z` closes an open
edit session and sets `kind:` to the next stored kind actually present in the snapshot,
wrapping back to All. A query listing several kinds is treated like All, so the next
press selects the first present kind. When a filter hides every row, the pane says so
and names the key that focuses the query row.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Tabs and panes](tabs-and-panes.md) — tab system and Artifacts panes.
- [SASE Pager](pager.md) — artifact and file pager.
- [TUI keymaps](keymaps.md) — generated keymap defaults.
- [TUI migration notes](../upgrading/tui.md) — Archive and Agent-pane moves.
