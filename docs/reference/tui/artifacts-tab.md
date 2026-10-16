---
title: Artifacts tab
description: Artifact links, Patches keybindings, mentor comment stats, and the PR origin chip.
---

# Artifacts tab

This page lists Artifacts-tab links, Patches keys, mentor comment stats, and the PR
origin chip.

## Contextual Artifact Links

sase's TUI owns one link rail across the three top-level tabs. It appears when the
current selection has artifact links: an Artifacts-pane entry, a named agent or session
turn, or an AXE job. Synthetic clan containers, routines, and background-command rows do
not provide a link subject. The rail includes a breadcrumb while a link-follow trail is
active.

Press `$` to arm the rail. Then press `$` again to follow its first entry, `1`-`9` for a
numbered entry, or `0` to open the complete links panel. The rail always advertises
`$0 all` or `$0 +N more`, so links beyond the first nine remain discoverable. Several
projected links produced by the same rule may collapse into one entry; following that
entry opens the panel already scoped to the group.

In the panel, `a`-`z` follow the first 26 entries directly, Enter follows the
highlighted entry, arrows or `Ctrl+N`/`Ctrl+P` move, and Esc closes it. `-` removes a
writable durable link and `+` creates a link from marked rows where that action is
available. Projected links are read-only. Rows show relation direction, rationale,
provenance, and missing targets; the panel shows a separate notice when the aggregate is
stale. Two glyphs pre-flag a row before you follow it, using the same resolution the
follow path itself uses: `⊘` means the ref is dangling — no pane resolves it at all —
and `↻` means the target exists but is not selectable in place, so following it will
rewrite the destination pane's query. A destination pane that is still loading is not
flagged, because "not in the result set yet" there is a loading artifact rather than a
real reveal need. The `?` help modal lists both glyphs beside the link-follow keys.

Link follows can cross tabs and keep a bounded 32-hop trail. `Ctrl+O` walks backward and
`Ctrl+Shift+O` walks forward, restoring the tab, pane, project scope, query, selection,
and supported AXE fold state. If no link-trail hop is available, those keys retain the
current pane's normal jump-stack behavior. Ordinary navigation clears the link trail.
See [Artifact Links](../artifact-links.md#browsing-links-in-sases-tui) for
relation and projection details.

### Link Jumps

Following a link whose target is outside the destination pane's current result set does
not fail. Every jump — the `$` link rail, the `$0` links panel, and relation jumps
outside Patches — runs one engine: it plans a single verified rewrite, then commits it
once. The query bar always truthfully describes what is shown, and query history records
exactly one `^` entry, which restores the original query and selection. While the
destination pane is still loading, the jump waits for it rather than reporting a miss.
Starting a new jump cancels one still in flight.

| Step          | When                                          | What happens                                                                                                                                  |
| ------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Resolve       | Always                                        | Find the target through the destination pane's own row identity, re-resolved once the pane has loaded.                                        |
| Scope         | The current project scope excludes the target | Switch to the target's project, or to All projects if its project is unknown and the current scope cannot resolve it. Never narrows from All. |
| Select        | The target is visible                         | Select it. No toast.                                                                                                                          |
| Fold          | A collapsed fold hides it                     | Expand the minimum fold, then select. No query change, no toast.                                                                              |
| Acquire       | The row is not in the pane's loaded inventory | Fetch it directly from its source in the background, then continue.                                                                           |
| Context       | The query or limit hides it                   | Rewrite to the context query below, verified against the target's row before committing.                                                      |
| Identity      | No context, or the context still misses       | Rewrite to the tightest query that names the row (`id:`, `sha:`, …), keeping the limit.                                                       |
| Neutral       | Still missing, where allowed (never Stitches) | Replace the query with a blunt `limit:all`.                                                                                                   |
| Honest report | Everything missed                             | Say so: a dangling ref, a load failure, an unconfigured provider pane, or "not in `<Pane>`".                                                  |

The rewrite lands the target inside its natural session — never an isolated row — and
keeps the current `limit:`, raising it only when the session would not fit:

| Target                              | The query becomes                                                                                  | Lens label                             |
| ----------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Bead phase `sase-16n.7`             | `id:sase-16n.*`                                                                                    | `epic sase-16n`                        |
| Bead epic `sase-16n`                | `id:sase-16n id:sase-16n.*`, epic fold expands                                                     | `epic sase-16n`                        |
| Bead task or flag `sase-abc`        | `id:sase-abc`                                                                                      | `bead sase-abc`                        |
| Agent hood member `sase-16n.7`      | `name:sase-16n.*`, or `(name:sase-16n OR name:sase-16n.*)` when the root exists                    | `sase-16n hood`                        |
| Lone agent `x`                      | `name:x`                                                                                           | `agent x`                              |
| Agent session turn `x--y`           | `session:x`                                                                                        | `session x`                            |
| File                                | `agent:<creating agent>`, else `id:<file>`                                                         | `files from <agent>`, else `file <id>` |
| Plan or provider doc                | `path:<doc path>`                                                                                  | `plan <name>` or `<provider> <name>`   |
| Stitch `repo@sha`                   | `repo:<repo> since:<day> until:<day>`, plus `project:`, `sidecar:true`, or `merges:show` as needed | `<repo> · <day>`                       |
| Patch in a stack                    | `ancestor:<stack root>`                                                                            | `stack <root>`                         |
| Submitted, reverted, archived patch | `name:<patch>`                                                                                     | `patch <name>`                         |

The `*` above is the [wildcard filter](../query-language.md#wildcards):
`id:sase-16n.*` matches every phase of epic `sase-16n` but not the epic itself.

An `agent:` link climbs a four-step ladder, stopping at the first step that holds.
Loaded on the Agents tab, it reveals in place, switching agent tabs and opening any
collapsed fold, group banner, or tribe panel around it. Hidden only by the Inbox filter,
the filter is rewritten to an exact `name:"…"` query, with the old query waiting on `^`.
Dismissed from the Inbox, it opens read-only in Agents ▸ Archive with
`in:archive name:"…"`, selecting the row and recording one `Ctrl+O` hop. With no record
on this machine, a toast says so and nothing changes: the current tab, query, selection,
and pages stay exactly as they were. A `job:` link lands on the Services tab and expands
the job's routine fold.

Each rewrite explains itself in one toast naming the new query, what hid the target, any
scope change, and the real keys that restore (`^`) and walk back (`Ctrl+O`):

```text
↪ Bead sase-16n.7
query  id:sase-16n.* limit:100
was    -status:closed limit:100 · hidden by -status:closed
epic sase-16n · ^ restore · Ctrl+O back
```

Extra lines appear only when they apply: `scope  <old> → <new>` (project display names,
or `All projects`) and `fetched  outside the loaded rows` after an Acquire. The agent
ladder reports in its own words instead:
`The inbox filter hid it — showing name:"…" · ^ restores your filter` after a filter
rewrite, `<source> — dismissed … · ⏎ restore · ctrl+o back` on an Archive arrival, and
`agent:… has no record on this machine` when nothing changes. The `was` line names the
terms that hid the target (`hidden by your query` in a Boolean-dialect pane, or
`hidden by the project scope`), or `past limit:N` when only the limit did. The key names
follow the live keymap, and the toast stays for about 8 seconds. Selecting,
fold-expanding, switching scope, or fetching without a rewrite shows no toast.

While a rewrite is live, the pane's info header shows a reversible **lens chip** —
`↩ sase-16n.7 · epic sase-16n` in the pane's accent color, followed by a dim
`^ to return` naming the configured `prev_query` key rather than introducing a new
binding. The lens is derived from the live query rather than stored as a flag: it is
active only while the pane's canonical query is still exactly the query the reveal wrote
and the pane's dialect has not changed. Editing the query yourself, walking query
history with `^` / `_`, loading a saved query, or triggering a fresh reveal all end it
with no separate clear step.

## Keybindings: Artifacts / Patches

Default configurable actions are listed in the generated
[TUI keymaps reference](keymaps.md). This page keeps behavior details and
fixed widget keys.

### Navigation

| Key                     | Action                                                                      |
| ----------------------- | --------------------------------------------------------------------------- |
| `$$` / `$1`-`$9` / `$0` | Follow the first / numbered artifact link, or open the complete links panel |
| `` ` ``                 | Jump to entry across all tabs (see [Jump All Modal](finders.md#jump-all-modal))       |

> **Note:** `o` opens a direct grouping picker on the Agents tab. `o`/`O` cycle the L0
> grouping bucket forward / reverse on Artifacts panes that have a grouping mode (each
> surface keeps its own in-session mode). Beads has no grouping modes, and a provider
> document pane has them only when it declares `ref.grouping`, so the keys are a silent
> no-op on panes without modes; the same is true on the Services tab. The Artifacts
> open-externally verb moved to `E`; bang-mode `!o` still marks PR origin. See
> [PR Grouping and Folding](#pr-grouping-and-folding) and the Agents-tab
> [Grouping Modes](agents-tab-grouping.md#grouping-modes) below.

### PR Actions

| Key             | Action                                |
| --------------- | ------------------------------------- |
| `C` / `c1`-`c9` | Checkout PR (primary / workspace 1-9) |

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

Collapsed banner rows are first-class navigation stops: `j`/`k` step through them just
like Patch rows, and `'` jump-hints land on them too. After a fold change that hides the
focused PR, focus snaps to the deepest collapsed ancestor banner so the cursor always
sits on a row the user can see.

### Fold Mode (`z` prefix)

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

The DELTAS section uses the same three levels with its own meaning. When **collapsed**,
the section renders a one-line file and line-count summary such as
`DELTAS:  +3 (+428) ~6 (+91 ~37 -14) -1 (-22) (10 files)`. When **expanded**, the
alphabetical entry list is shown with colored glyphs (green `+`, gold `~`, red `-`);
**fully expanded** adds inline line-count tokens to each entry. Binary files display
`binary`; zero-count entries display `0 lines`. `z` `D` jumps between the summary and
the full list. The section is omitted entirely when the Patch has no deltas.

### Workflows and Agents

| Key        | Action                                             |
| ---------- | -------------------------------------------------- |
| `,<space>` | Run an agent from the current PR (skips selection) |

If sase's TUI cannot detect a workspace provider for the selected Patch or agent, the
quick-launch actions show an error toast instead of opening a prompt with a broken VCS
prefix.

### Bang Mode (`!` prefix)

`!!` ends in a **Run Command** picker over previously run background commands: type to
filter the history or enter a new command, move with `Ctrl+N` / `Ctrl+P` or the arrow
keys, press `Enter` to run it, and `Esc` to cancel. `,!` skips the project and uses the
current PR's project.

A background command is a **oneshot service proc**: a durable proc-store row with a
recorded exit code, a store-owned log, and a stable `#1`–`#9` index, shown in the
Services tab's `── oneshots ──` section. It runs outside the TUI and the service host,
so quitting or restarting either does not kill it, and a rerun (`r`) works after a TUI
restart. At most nine oneshots can be _running_ at once; finished commands never block a
new one (the oldest finished index is reused once all nine are taken).
`sase service proc run` submits through the same path.

### Hook History Modal

Type `.` into the `F` edit-hooks input to open the hook history modal, which lists
previously added hook commands:

| Key         | Action                 |
| ----------- | ---------------------- |
| `Esc` / `q` | Cancel and close modal |

The modal supports live filtering as you type in the search box and displays last-used
timestamps for each hook.

### Leader Mode (`,` prefix)

Help is not a leader command: press the app-level `?` on any tab to open the Help modal.

The `,h` shortcut opens a home-context prompt directly. Project and PR launch pickers
use lifecycle-aware discovery: project entries, including `home` when it appears in
picker lists, must have enabled and launchable ProjectSpecs; PR choices come from
enabled ProjectSpecs. Disabled projects do not appear in normal launch pickers until
they are enabled with `sase project enable <project>`. You can also type a known-project
VCS ref explicitly; launch preparation treats that as intent to resume work and
re-enables the project before claiming a workspace. When the current project appears in
the list, the `+` picker highlights that row on mount; typing in the filter box still
resets the highlight to the first match.

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
command has been run yet, sase's TUI shows a toast and does nothing.

> **Note:** `,x` (kill & edit) and `,X` (kill & edit last launched agent) are only
> available on the Agents tab — see [Agents Tab Leader Mode](agents-tab-modes.md#leader-mode-prefix-1).

### Mentor Review Modal

Press `,C` to open the Mentor Review modal, which lets you navigate mentor comments,
accept or reject suggestions, and apply accepted changes. See
[Mentors](../automation/mentors.md) for the full mentor system reference.

| Key         | Action      |
| ----------- | ----------- |
| `Esc` / `q` | Close modal |

### Copy Mode (`%` prefix)

Press `%` to open the **Copy as…** palette for the selected Patch. Select a row with the
mouse, arrows or `j`/`k` and `Enter`, or complete any configured two-key accelerator
directly. `q`/`Esc` cancels; configured target keys take precedence if rebound to `j`,
`k`, or `q`.

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
its candidate selection entirely (see [AXE](../automation/scheduler.md)). Press
`!o` on a PR row (see [PR Actions](#pr-actions) above) to open the Mark PR Origin modal
and set it explicitly, or run `sase patch set-origin <name> <sase|external|unknown>`
(see [CLI Reference](../work-units/cli-workflows.md#work-tracking-and-planning)). See
[PR_ORIGIN](../work-units/patches.md#pr_origin) and
[Origin Matching](../query-language.md#origin-matching) for the underlying Patch
field and the `origin:` query property.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Tabs and panes](tabs-and-panes.md) — tab system and Artifacts panes.
- [Files and preview](files-and-preview.md) — Files pane, Preview reader, Archive.
