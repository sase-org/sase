---
title: Global controls
description: Global keys, custom keymaps, the command palette, the command line, and auto-refresh.
---

# Global controls

This page lists global TUI keys, custom keymaps, the command palette, the command line,
and auto-refresh.

## Global Keybindings

Default configurable actions are listed in the generated
[TUI keymaps reference](keymaps.md). This page keeps behavior details and
fixed widget keys.

These work on all tabs:

| Key                     | Action                                                                        |
| ----------------------- | ----------------------------------------------------------------------------- |
| `$$` / `$1`-`$9` / `$0` | Follow the first / numbered contextual artifact link, or open the links panel |

The generic **Open SASE Admin Center** action and the first `#` always open a
lightweight landing page without mounting a working pane. Press `#` again while home is
visible to resume the last section that was successfully active. With no prior visit,
the repeated key stays on home and loads nothing. Inside a working section, the same key
takes on a second meaning: it jumps to the section you were in immediately before the
current one, and pressing it again toggles back — exactly two sections remembered, like
a two-slot alternate. A color-coded, clickable footer along the bottom of the working
section names the jump target (or explains that none exists yet). The numbered strip
remains clickable: `1` Config, `2` Logs, `3` Machines, `4` Procs, `5` Projects, `6`
Statistics, `7` Tools, and `8` Updates. `Tab` enters Config, and `Shift+Tab` enters
Updates. Each working pane and its data are loaded only on first entry, then cached
while the modal remains open. Command-palette actions such as **Open logs panel**,
**Open procs panel**, and **Open statistics**, plus update shortcuts and indicators,
enter their requested pane directly and make a successful entry the next resume target.
Closing from home does not clear an older target.

Both the top-level resume target and the alternate are persisted machine-locally and
survive across sase's TUI process restarts. Within one running sase's TUI process,
closing and reopening Admin Center also remembers each selectable pane's last logical
entry by stable identity, plus the minimal scope or sub-tab needed to show it again.
Filters, marks, scroll position, loaded data, pane instances, Statistics controls, and
other pane-local state still end with the modal. If `ace.keymaps.app.open_config_center`
is rebound, repeat that configured key instead; the footer and landing page display the
effective binding and destination.

Inside every working section, `'` is an Admin Center-wide entry-jump key: it paints
adaptive hints over that section's selectable rows using the same hint alphabet
described under
[Navigation in Agent, Commits, Beads, Provider Documents, and Files](tabs-and-panes.md#navigation-in-agent-commits-beads-provider-documents-and-files),
a hint character moves the selection there, `'` again returns to the previous position
(or the first hint with an empty back stack), and `Esc` cancels. Each working section's
own keybindings table names its jump targets; two are deliberate exceptions. The
Statistics tab has no row cursor, so `'` there arms the same numbered-view selection the
`0` prefix already arms, using the visible strip numbers as hints. Config's nested
catalog is ordered **01 All · 02 Flags · 03 Holds · 04 Launch · 05 Memory · 06 Snippets
· 07 Macros**; `0` then the matching digits selects those children, while bare digits
continue to belong to the active child or the Admin Center's top-level tabs. The Updates
tab's single merged list jumps normally across every section — SASE, Plugins, and Agent
CLIs alike.

### Quit / Restart Menu

Pressing `Q` opens the **quit / restart menu**. When this TUI instance has in-process
work, the menu warns inline (`N TUI tasks will be interrupted`) and it offers three
actions:

- `1` / `s` — quit sase's TUI and stop the `scheduler` service proc (best effort: the
  TUI still quits if the stop fails); the service host and its other service procs keep
  running
- `2` / `r` — restart the TUI, leaving the service host running
- `3` / `a` — restart the TUI and restart the service host

Press `esc` (or `q`) to cancel and return to the TUI.

Durable procs, `!` background commands, monitor turns, and service procs survive
quitting and restarting; the menu says nothing about them because they keep running.

A plain `q` quits sase's TUI directly when nothing would be interrupted. Otherwise `q`
shows a y/n confirmation (default No) listing the in-process TUI work that would be
lost; confirming quits, declining (or `esc`/`q`) stays in the TUI.

An unsent agent prompt does not, by itself, ask you to confirm. After any required
confirmation — and immediately when none is required — plain `q` and menu quit (`1` /
`s`) write that prompt to Stash before exiting. The save is one Stash row: every
non-empty pane, in order, or the frontmatter alone when every pane is empty but
frontmatter is present. Plan Feedback and Coder Prompt bars are not saved. If the write
fails, the exit stops, the TUI stays open, and the error is
`Failed to stash prompt draft — staying so no text is lost`. Choosing `1` / `s` also
leaves the scheduler running when that save fails.

Restart (`2` / `r`, or `3` / `a`) tries the same save. When it succeeds, the TUI says
`Prompt draft stashed; press @ to restore after restart`. When it fails, the restart
still exits and the draft is not written.

A submitted prompt that is still waiting to launch does not, by itself, ask you to
confirm. The scheduler batches in the next paragraph are separate: they are chop
launches that have not all been started. When a quit or restart actually exits, each
waiting prompt is recorded in prompt history as cancelled and copied to Stash so `@` can
bring the Stash copy back. The exit still completes if that copy fails or does not
finish within 3 seconds. When a confirmation is shown for other in-process work, its
summary adds `Your unsent prompt draft will be stashed` when a draft is open, and a
count such as `1 pending launch will be stashed for @` when prompts are waiting.
Declining the confirmation writes nothing.

Options `1` and `3` also check for in-flight scheduler launch batches (a chop run that
has proposed launches but has not launched them all yet). When quitting would drop the
remaining launches — or when in-process TUI work would be lost — a y/n confirmation
(default No) lists exactly what would be lost. Option `2` confirms only for in-process
TUI work. Declining returns to the TUI without exiting or stopping anything; when
nothing would be lost, `q` and all three `Q` options behave exactly as before with no
extra prompt.

## Command Palette

Press `;` from any tab to open the **Command Palette** — a context-aware modal listing
every keymapped action that is currently runnable. The palette is the discovery surface
for the TUI: rather than memorizing every chord, you can search by command label, key
sequence (e.g. `%n`, `,A`, `zc`), category, or alias.

**Behavior:**

- Only commands applicable to the current tab and selected entry are shown by default.
  For example, PR diff appears only when a PR is selected; service start/stop appears
  only on the Services tab; agent-specific actions appear only when an agent row (not a
  group banner) is focused.
- Each row shows the keybinding, the command label, and a category badge such as
  `Navigation`, `PR Actions`, `Agent Actions`, `Copy`, or `Leader`.
- A title-bar badge (`Agents`, `Artifacts`, or `Services`) reflects the current tab.
- Typing `:` into an empty filter hops to the [Command Line](#command-line).
- When the filter has no match, a fallback row offers `Run `sase
  <query>` in Command Line`, which opens the Command Line pre-filled with the filter
  text (without running it).

**Keybindings inside the palette:**

| Key                 | Action                                       |
| ------------------- | -------------------------------------------- |
| `Type`              | Filter commands (case-insensitive substring) |
| `:` on empty filter | Hop to the Command Line                      |
| `↑` / `↓`           | Move highlight                               |
| `Ctrl+P` / `Ctrl+N` | Move highlight                               |
| `Enter`             | Run the highlighted command                  |
| `Esc`               | Close without running anything               |

The palette delegates execution to the same handlers that the keybindings use, so
behavior matches pressing the chord directly. Selecting a built-in mode subcommand (e.g.
`%n` to copy an agent name) runs the action without forcing you through the transient
prefix mode. Custom modes defined in `sase.yml` are also represented per-command.

The `;` binding follows your configured keymap. To rebind it, set
`ace.keymaps.app.open_command_palette` in `~/.config/sase/sase.yml`; comma-separated
keys in that setting are treated as alternate bindings for the same action.

## Command Line

Press `:` from any tab to open the **Command Line** — a centered panel where you type
`sase` commands (the `sase` prefix is implicit) and run them without leaving the TUI.

**Behavior:**

- Selection-aware, fuzzy completion with a live signature line: the panel knows the
  current selection, ranks the selected entity first, and shows advisory grammar
  diagnostics. `Tab` completes, `Ctrl+F` accepts an active completion, `Ctrl+R` searches
  history, and `;` on an empty line hops back to the Command Palette.
- The frame's borders carry the chrome: `❯ Command Line` and the working-context chip
  (`⌂ +<project> · <path>`) on the top border, the key hints for the current context and
  the `N running` count on the bottom one. Both borders recompose when the terminal
  resizes, so their ends stay aligned: the chip is middle-truncated first, and the hints
  give way to the running count. The frame is 96% of the terminal wide (at most 200
  columns) and 80% of its height, centered; `Ctrl+T` toggles full height.
- The completion popup (and, on terminals at least 140 columns wide, the doc peek) sits
  in a completion tray beneath the input and signature line. It never covers command
  output. The tray keeps a fixed height (up to 13 rows), so the input never moves as
  candidates change. The candidate text still lines up under the slot being completed.
- The transcript follows new output. `Ctrl+D` / `Ctrl+U` scroll it by half a page from
  the input in INSERT or NORMAL mode, taking over the input's delete-char /
  delete-to-line-start keys in this panel. Scrolling back to the bottom (or running a
  command) resumes following.
- The completion popup shows an 8-row window that scrolls through every candidate; its
  footer counts the highlighted row (`N of M`) and shows the one key that fits the menu
  state. An empty line offers `RECENT` history and `FOR <selection>` suggestions under
  section headings. A slot whose provider failed reads `⚠ <kind> unavailable`, and one
  with nothing to offer reads `no <kind>`; the note never carries over to another slot.
  Provider results are cached briefly (pending plans for 5 seconds, everything else 15)
  and forgotten when a command finishes; the next fetch then skips the providers' own
  disk cache, so a plan you just approved is not offered again. A result that arrives
  after you edited the line or moved the cursor is dropped. Project slots always merge
  the provider behind the projects the TUI already knows, and a path slot lists dotfiles
  once the name you type starts with `.`.
- Every command runs as an ordinary durable proc (tagged `command-line`, visible by
  default in Admin Center → Procs), so hiding the panel never interrupts anything.
  Finished command-line procs keep their own retention bucket of 50.
- Running blocks show a spinner and live elapsed seconds even when the command produces
  no output. Reopening the panel restores the duration from the proc's start time;
  finished blocks keep their final duration.
- Run policies: most commands run as procs, some (editors, pagers, interactive tools)
  run in the real terminal with the TUI suspended, and a few refuse with an alternative.
  Declined confirmation commands render an explicit `R` rerun with `-y`; `R` does
  nothing for other blocks.
- Built-ins: `cd` (pin a working directory), `clear`, `help`, and `history`. They run
  instantly with no proc. `cd` takes a path, `+<project>` (the project's label as
  completion shows it, or `+home`), or `-` to unpin.
- Block keys (`NORMAL` mode): `o` expand, `v` pager, `K` kill, `r`/`R` rerun, `e` edit,
  `y`/`Y` copy output/command, `p` open in Procs, `x` remove, `i` back to input.

Panel keys are configurable under `ace.keymaps.command_line` in
`~/.config/sase/sase.yml`: history (`up`/`down`, `Ctrl+R`), the `;` palette hop,
`scroll_transcript_down` / `scroll_transcript_up` (`Ctrl+D` / `Ctrl+U`), and every Block
key above. Set an action to `unbound` to disable it; it also leaves the key hints. The
completion-menu keys follow the zsh menu-select contract and stay fixed: `Tab` /
`Shift+Tab` / `Ctrl+N` / `Ctrl+P` / `↑` / `↓` to move, `Enter` or `Ctrl+F` to accept,
`Esc` to leave the menu, `→` to accept ghost text at the end of the line.

The `:` binding follows your configured keymap. To rebind it, set
`ace.keymaps.app.open_command_line` in `~/.config/sase/sase.yml`.

## Custom Keymaps

Configurable TUI actions use the `ace.keymaps` section in `sase.yml`; their bundled
defaults are listed in the generated [TUI keymaps reference](keymaps.md).
You can remap app-level, gate-modal, Memory-panel, and focused Statistics-pane keys and
define entirely new prefix-key modes.

### Remapping Built-in Keys

Override any app-level keybinding under `ace.keymaps.app`:

```yaml
ace:
  keymaps:
    app:
      next_patch: "n" # Remap j -> n
      prev_patch: "p" # Remap k -> p
      edit_query: "f5" # Structured query on Artifacts and Agents
      show_notifications: "N" # Remap i → N
```

Agents deck search is independent: remap
`ace.keymaps.modes.leader_mode.keys.search_forward` to change the subkey after the
configured leader prefix. Structured query editing on every query-capable surface,
including Agents, is `ace.keymaps.app.edit_query`. Stale `app.search_forward` and `leader_mode.keys.edit_query` overrides are ignored
with a warning pointing at those replacements. See
[TUI migration notes](../upgrading/tui.md#config-and-keymap-aliases).

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
      focus_macro: "x"
      clear_macro_focus: "X"
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
`1`–`8` to select the matching view displayed as `01` through `08`; bare digits continue
to switch the Admin Center's top-level tabs. `jump_to_entry` arms that same
numbered-view selection, which is how the Admin Center-wide `'` behaves on a pane that
has no row cursor to jump between — the visible strip numbers serve as its hints. The
group control is visible and active only in Projects, Macros, and Perf. On the Macros
view, the focus key opens a filterable picker and the clear-focus key restores **All
macros**. Project filtering cycles through **All projects** and the latest cached
unfiltered ranking: the configured forward key moves toward the first ranked project,
the reverse key moves toward the last, and both wrap. First open seeds the current
project when `ace.current_project.seed_filters` is on; either key can cycle away from
that seed. Either key clears an active project filter directly when its loaded result is
empty.

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
      open_inputs: "o"
      next_input: "ctrl+n"
      previous_input: "ctrl+p"
      decision_next: "l,right"
      decision_prev: "h,left"
      decision_reset: "r"
      decision_reset_all: "R"
      decision_zoom: "z"
```

These bindings dispatch only while a branch-driven gate modal is open, and its footer
shows the effective keys. The example remaps navigation, `submit_branch`, and the input
panel keys, and repeats the defaults for `toggle_option` and `submit_primary`.
`open_inputs` (default `i`) opens the input panel for the focused option's note or
declared fields, including an optional note that would otherwise skip the panel.
`next_input` and `previous_input` (defaults `tab` and `shift+tab`) walk the panel's
fields and buttons; they are inactive on the gate modal itself. Confirming the panel
submits the branch; cancelling it returns to the gate without answering. The `activate_control` setting is accepted as an alias for `submit_primary`. See
[TUI migration notes](../upgrading/tui.md#config-and-keymap-aliases).

### Remapping Memory Panel Keys

Override [Memory panel](prompt-completion-panels.md#memory-panel) bindings
under `ace.keymaps.memory`. A value may list more than one key, separated by commas:

```yaml
ace:
  keymaps:
    memory:
      follow_link: "enter,l"
      travel_back: "backspace,h"
      filter_notes: "slash"
      toggle_body_filter: "greater_than_sign"
      toggle_web: "space"
      next_strand: "s"
      prev_strand: "S"
      add_note: "a"
      edit_note: "e"
      delete_note: "d"
      publish: "I"
```

These bindings dispatch only while the panel is open. The full action list and defaults
are in the
[`ace.keymaps` configuration reference](../config/ace-keymap-configuration.md#acekeymaps).
`.` (`full_stop`) is reserved for the fixed `.` then `1`–`9` numbered-chip prefix; a
config that assigns it to a Memory action is warned and reverted to that action's
default. `>` (`greater_than_sign`) remains a valid configurable key and is the default
for `toggle_body_filter`.

`add_note`/`delete_note` branch on the selected row (a web row adds a strand, a strand
row deletes one), and `next_link`/`prev_link`/`follow_link` follow a glossary strand's
mention-relation chips the same way they follow a note's `PARENT`/`CHILDREN` chips. See
[TUI migration notes](../upgrading/tui.md#keymap-moves) for the older
`ace.keymaps.glossary` key.

### Remapping Snippets Panel Keys

Override [Snippets panel](prompt-completion-panels.md#snippets-panel)
bindings under `ace.keymaps.snippets`. A value may list more than one key, separated by
commas:

```yaml
ace:
  keymaps:
    snippets:
      follow_relation: "enter,l"
      travel_back: "backspace,h"
      filter_snippets: "slash"
      toggle_body_filter: "full_stop"
      add_snippet: "a"
      edit_snippet: "e"
      delete_snippet: "d"
```

These bindings dispatch only while the panel is open. The full action list and defaults
are in the
[`ace.keymaps` configuration reference](../config/ace-keymap-configuration.md#acekeymaps).

### Custom Modes

Define user-defined prefix-key modes under `ace.keymaps.modes`. Each custom mode has a
`prefix` key and a `keys` dict where each sub-key specifies either a `shell` command or
a built-in `action`:

```yaml
ace:
  keymaps:
    modes:
      my_mode:
        prefix: "B"
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

Pressing `B` activates the mode, then pressing `t` runs `just test`, `l` shows the git
log, etc.

### Validation

The keymap loader validates all configuration:

- **Invalid keys** are reverted to their defaults with a warning
- **Duplicate keys within one binding scope** are detected and the conflicting override
  is reverted
- Stale `app.search_forward` and `leader_mode.keys.edit_query` overrides are ignored
  with a warning; they are not translated into a second live shortcut
- **Prefix conflicts** between custom mode prefixes and existing app bindings are warned
- Key names follow Textual's spelling (`slash`, `dollar_sign`, `backslash`,
  `vertical_line`, …); the raw glyphs `+`, `-`, `$`, `_`, `\`, and `|` are also
  accepted, and key hints display the glyph

See the
[ACE keymap configuration](../config/ace-keymap-configuration.md#acekeymaps) for
the full `ace.keymaps` reference.

## Auto-Refresh

sase's TUI auto-refreshes data at a configurable interval (default: 10 seconds). The
remaining time until the next refresh is shown in the info panel. Set
`--refresh-interval 0` to disable. Press `R` on Artifacts or Services, or `r` on Agents,
to open the [Refresh panel](agents-tab.md#refresh-panel) and choose a
manual refresh without waiting for the next tick.

Tab switches are instant: cached data is shown immediately while a background refresh
runs asynchronously, so moving between tabs never blocks on disk I/O.

When the inotify-based artifact watcher is active, the periodic tick is
**event-driven**: it consults per-surface dirty flags (`_dirty_patches`,
`_dirty_agents`, `_dirty_axe`) and short-circuits the whole tick when nothing has
changed. Cheap stat-only change tokens also skip unchanged surfaces when no watcher is
available. A 300-second `--sanity-refresh-interval` floor still triggers a full
reconcile to recover from missed events, so a quiet TUI does ~zero work between real
changes without going stale.

Until the initially visible tab is ready — or a 45-second safety timeout fires —
auto-refresh ticks keep probing change tokens but do not collect axe, run a sanity or
broad Agents load, or reload Patches. That hold keeps the first tick from racing the
startup axe init (auto-start / `--restart-axe`) and from competing with the Agents
loader. Hidden-surface loads, the app-wide link index, and other CPU-heavy maintenance
wait for the same release and then run one job at a time.

### Performance Tracing

For diagnosing TUI latency, set `SASE_TUI_TRACE=1` before launching `sase tui`. Tracing
is near-zero-cost when the env var is unset; with it enabled, each instrumented hot path
emits one JSONL line per span to `~/.sase/perf/tui_trace.jsonl` (override via
`SASE_TUI_TRACE_PATH=…`). See
[`docs/contribute/perf-runbook.md`](../../contribute/perf-runbook.md) for the full span
catalog, benchmark harness, and per-phase performance targets.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Launching](launching.md) — start the TUI and CLI options.
- [TUI keymaps](keymaps.md) — generated keymap defaults.
- [TUI migration notes](../upgrading/tui.md) — keymap aliases and Memory-panel keys.
