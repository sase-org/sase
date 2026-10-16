---
title: Services tab
description: Services tab sidebar, description panel, job results, and control keys.
---

# Services tab

This page lists Services tab rows, the description panel, job results, and control keys.

## Keybindings: Services Tab

Default configurable actions are listed in the generated
[TUI keymaps reference](keymaps.md). This page keeps behavior details and
fixed widget keys.

The visible tab is **Services**. Its sidebar is four stacked panels. The top **Service
Procs** panel holds every service proc assembled from built-in, plugin, user, and
machine-overlay configuration — daemon rows plus background commands (oneshot service
procs) in a separate `── oneshots ──` section below the daemon procs. Below it, one
panel per routine declaring source holds that source's routines with their job rows
nested under each parent: **User Routines**, then **Plugin Routines**, then **Builtin
Routines**. Source means the first config layer that declared the routine, not the layer
that last changed one of its fields — a builtin routine with a user interval override
stays Builtin, and jobs always render in their parent routine's panel. Each panel border
title carries at-a-glance metadata (counts, status chips, and badges such as hidden
oneshots or a non-running scheduler). `J` jumps to the first row of the next panel and
`K` to the last row of the previous panel, wrapping around and skipping empty panels;
`Ctrl+O` returns to where you jumped from. `j` / `k` cross panel boundaries on the
underlying global list without selecting chrome. Service proc rows show their lifecycle,
enablement provenance, restart state, and bounded output. The dashboard status line
reports the service host state (`Host: <state>`). Project-local `sase.yml` service
entries are intentionally ignored.

Builtin routine rows start folded on first sight so the dense builtin list stays calm; a
folded row still carries its jobs' health as a red `!N` badge (failed, timed-out, or
missing-script jobs, counted from the same cached snapshots as the panel title). Folding
applies only once those snapshots have arrived, so a header-only pre-load never hides
rows behind a misleading fold. `h` / `l` fold and expand the focused routine, and an
explicit fold persists for the session. `ace.services.fold_builtin_routines` (default
`true`) controls the first-sight behavior permanently.

Once service status has loaded, the info panel leads with a host clause:
`Services · host ● running 4d · sase.service` while the host runs (uptime in its largest
unit when known, then the installed native service unit or `detached`),
`Services · host ○ starting` while the host is still starting (not a failure),
`Services · host ○ stale · press !x to start` when the heartbeat is stale, or
`Services · host ○ stopped · press !x to start` when the host is down. A host config
error renders inline (`! <error>`), and an unreadable snapshot renders its short reason
in the header. Disabled rows carry an inline provenance chip (`disabled here` for a
local override, `disabled by <layer>` otherwise), unavailable rows show
`unavailable: <reason>`, and other non-running rows carry the core's human summary (for
example `crash-looping (3)`) plus the restart count (`· 5r`) whatever the state.

On a selected top-level service proc, `x` starts or stops it, `r` restarts it, and `!e`
enables or disables it on this machine. Those actions are no-ops when no service proc is
selected; in particular, `x` does not toggle the host from a routine or job row in any
of the routine panels. Use `!x` to start or stop the service host itself. The `SVC`
footer pill shows the running/desired service-proc count (`N/M`), or a red `!` when the
host or a service proc is unhealthy (see
[Service Health Pill](agent-statuses.md#service-health-pill)). The
right-hand panel shows the selected proc's effective command, current and desired state,
restart policy, dependencies, last exit, restart decision reason, stop provenance, any
pending start/restart request, and output tail, plus the host config error when one is
set. The description sits in the sticky [description panel](#description-panel) above
it.

The canonical tab id is `services` (`axe` is still accepted as an alias, for
example `sase tui -t axe`; see
[TUI migration notes](../upgrading/tui.md#model-size-and-tab-aliases)). Configuration
keys such as `ace.axe_description_expanded` and many internal row names keep the `axe`
spelling, which is why the detailed scheduler reference below still uses “Axe.”

### Sidebar Row Taxonomy

The Services sidebar renders four row types across its four panels so the operational
tree reads at a glance:

- **Service proc** rows live in the Service Procs panel with a solid left accent bar
  (`▌`) in the service teal, a `[*]` / `[!]` / `[~]` / `[?]` / `[-]` / `[·]` status
  marker, the proc name, and an optional state chip (restart count, disablement
  provenance, or the core's human summary).
- **Routine** rows live in their declaring-source panel (**User**, **Plugin**, or
  **Builtin Routines**) as top-level sections with a solid left accent bar (`▌`) in the
  routine hue, a `[*]` / `[!]` / `[·]` running/error/idle marker, the routine name, an
  optional overrun roll-up (`⚠N`), a red health badge (`!N`) counting failed, timed-out,
  or missing-script jobs even when the row is folded, and an optional compact `Nc / Ne`
  cycles/errors chip at the end.
- **Job** rows are child rows indented under their parent with a `  └─` tree connector,
  a per-run status icon (`✓` success, `!` failure/timeout, `?` missing script, `●`
  running, `*` agent-launched, `·` no runs), and the job name in a dim-gold child hue.
  Disabled jobs remain visible with a quiet `disabled` chip but cannot be run manually.
- **Oneshot** rows (background commands run via `!!`) live in the Service Procs panel
  below the daemon procs under a dim `── oneshots ──` divider when both groups are
  present. Each row leads with a state glyph (`▷` running, `✓` exit 0, `✗` failed or
  killed), a muted `#N` index, and the command, and ends with a chip carrying the
  recorded exit code and age (for example `exit 0 · 4m ago`), so they cannot be mistaken
  for scheduled AXE work. Commands started before oneshots existed remain readable from
  their old slot directories (no exit code) until those directories age out.

### Description Panel

The right-hand dashboard keeps the selected service proc, routine, or job description in
a dedicated panel between the status line and scrolling output. Every row of the panel
carries a solid left accent gutter (`▌ `) in the row's own hue — service teal for
service procs, routine gold and job copper otherwise — so the block reads as a
blockquote and stays visually distinct from the output pane below. Generated `for_each`
job instances also show their target key on the summary row. The panel stays fixed while
output scrolls and disappears for background-command and empty Services views. It shares
one session state across the Services tab: `d` on a service proc row also collapses
routine and job panels, and the reverse is true too. A service proc with no configured
description shows the dim-italic `No description configured` fallback, while a proc
missing from the snapshot hides the panel entirely. Oneshot rows get no panel.

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
See
[Description Grammar](../automation/scheduler-description-grammar.md#description-grammar)
for the authored form.

`ace.axe_description_expanded` (default `true`) sets the state each `sase tui` session
starts in. `d` flips an in-memory session state and repaints from cached snapshot data —
it never reloads config, reads disk, or writes the toggle back.

An expanded panel never crowds out the job output it exists to explain. The dashboard
budgets `max(3, min(16, floor(pane_height * 0.45)))` rows for the panel, falling back to
10 rows before its height is known. If the rendered block exceeds that budget, the last
row becomes a dim `… +N more · e` marker on routine and job rows — service proc rows
read `… +N more` with no `· e`, because `e` does nothing there: nothing is silently
dropped, and `e` opens the AXE entry editor, whose first field is the full description
in a multi-line text area.

Because `d` belongs to the Services tab, `show_diff` is scoped to the Patches sub-tab.
Pressing `d` outside Patches does not open a diff for an unrelated Patch.

### Dynamic Sidebar Width and No-Wrap Rows

Every sidebar row is rendered as single-line Rich `Text` with `no_wrap=True` and
`overflow="ellipsis"`. After each refresh each panel computes its widest formatted row
and its border title, and the widest of the visible panels decides the sidebar width:
the AXE container resizes between a 35-cell minimum and an 80-cell maximum, clamped
further so the right-hand dashboard always keeps at least 40 cells. On terminals too
narrow to fit a label even at the clamped width, the row ellipsizes rather than wrapping
onto a second line, and a long panel title truncates with Textual's border-title
ellipsis.

### Controlled-Output Highlighting and ANSI Fallback

Output in the dashboard right panel uses a semantic highlighter for sources whose shape
is controlled by sase, and falls back to ANSI rendering for everything else:

- **Routine aggregate logs** (`[YYYY-MM-DD HH:MM:SS] [routine] message`) get timestamp,
  routine name, status words (`success`, `failure`, `timeout`, `running`, `error`, …),
  PIDs, durations, exit codes, and counts colored by severity and consistent with the
  sidebar taxonomy.
- **Controlled job output** — runner lifecycle lines such as
  `Launched proposal 1 as <name> (PID <pid>)` use the same status-word, PID, duration,
  and count highlighting as other routine messages.
- **External job scripts** and **background command output** are arbitrary text and stay
  on the ANSI fallback (`Text.from_ansi`) with the existing capping and tail-biased
  caching behavior.

Render cache slots are keyed on `(source_id, source_type)` so the semantic and ANSI
paths cannot collide for the same numerical identity.

### Job Result Documents

Selecting a recorded job run composes three sections inside the existing scroll region:

1. **RESULT** is always present and is derived entirely from the cached run entry. It
   includes the status, structured summary and reason, counters, proposal and launch
   rosters, evidence, dry-run/source markers, and any error or traceback.
2. A job-authored structured **report** follows when the result document supplies one.
   Semantic tones map to the AXE palette, tables elide cells at wide widths and stack at
   widths below 60 cells, and all job strings are rendered literally rather than parsed
   as Rich markup or ANSI.
3. **OUTPUT** contains the existing ANSI-rendered log tail and retains the waiting,
   failure, reason, and no-output fallbacks for runs with an empty log.

The card and report are cached by run identity, lifecycle state, completion timestamp,
and rendered width. They paint only from the in-memory job snapshot; navigation does not
read, stat, or glob the run files. Auto-scroll continues to follow active `running` and
`launched` output, but terminal runs open at the RESULT card so the report is not
scrolled off screen on selection.

### Navigation {#navigation-2}

| Key                     | Action                                                                 |
| ----------------------- | ---------------------------------------------------------------------- |
| `$$` / `$1`-`$9` / `$0` | Follow the first / numbered job link, or open the complete links panel |
| `` ` ``                 | Jump to an entry across all tabs                                       |

### Commands

The `a` flow discovers installed `sase_job_*` executables and also accepts a custom
executable. Both add and edit open a single-page property sheet showing every schema
field, including unset and inherited fields. The active row's detail dock shows its
schema help plus effective, target-layer, and inherited values. Edits remain sparse: an
inherited field is not copied into the selected writable scope unless you touch it.
Compound and advanced fields expand in place as raw YAML, with inherit/reset available
for removing a target-layer override.

Editing a generated job row edits its immutable base job and warns that every generated
instance is affected. Before writing, the panel shows an exact effective before/after
preview plus a source-file diff. When the scheduler is running, the preview makes
restart explicit: save and restart the scheduler to reconcile it immediately, or save
only and leave the current scheduler configuration active until the next restart. `E`
remains reserved for opening recorded job output.

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

| Preview key                     | Action                                            |
| ------------------------------- | ------------------------------------------------- |
| `↑` / `↓` / `Ctrl+D` / `Ctrl+U` | Scroll by line or page                            |
| `g` / `G`                       | Scroll to the top / bottom                        |
| `Enter`                         | Save, restarting the scheduler when it is running |
| `Ctrl+O`                        | Save without restarting the scheduler             |
| `q`                             | Close the panel directly                          |
| `Esc`                           | Return to the property sheet                      |

### Leader Mode (`,` prefix) {#leader-mode-prefix-2}

Help is not a leader command: press the app-level `?` on any tab to open the Help modal.

### Bang Mode (`!` prefix) {#bang-mode-prefix-2}

### Copy Mode (`%` prefix) {#copy-mode-prefix-2}

Press `%` to open the **Copy as…** palette for the selected AXE row. Choose with the
mouse, arrows or `j`/`k` plus `Enter`, or use a configured direct accelerator. `q`/`Esc`
cancels, with configured target keys taking precedence.

### Services Control

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Procs tab](procs-tab.md) — durable procs, monitors, and filtering.
- [Global controls](global-controls.md) — keys, palette, command line, refresh.
