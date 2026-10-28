---
title: "SASE Admin Center"
description: "Navigation, sections, and editor behavior in the SASE Admin Center."
---

# SASE Admin Center

Navigation, sections, and editor behavior in the SASE Admin Center.

## SASE Admin Center (interactive editor)

Press `#` in the `sase tui` TUI to open **SASE Admin Center**. The first press always
starts on its lightweight home page, where the working sections—**Config**, **Logs**,
**Machines**, **Procs**, **Projects**, **Statistics**, **Tools**, and **Updates**—are
introduced without loading their data. Config's nested catalog is alphabetized: **All**,
**Flags**, **Holds**, **Launch**, **Memory**, **Snippets**, and **Macros**, labeled `01`
through `07`. While home is visible, press `#` again to resume the last section that was
successfully active in this sase's TUI process. Before the first section visit, the
repeated key leaves home unchanged and constructs no pane. Press `1`–`8` or click the
numbered tab strip to enter a section: `1` Config, `2` Logs, `3` Machines, `4` Procs,
`5` Projects, `6` Statistics, `7` Tools, and `8` Updates. From home, `Tab` enters Config
and `Shift+Tab` enters Updates; within a working section they wrap across the same tabs.
Pane-local `[` / `]` keys switch sub-tabs or views where the active pane provides them,
including Config's nested catalog.

Inside a working section, the same opener key takes on a second meaning: it jumps to the
section you were in immediately before the current one, and pressing it again toggles
back—exactly two sections remembered, like a two-slot alternate rather than an unbounded
history stack. A color-coded footer along the bottom of each working section names the
jump target (or explains that none exists yet) and is itself clickable.

Each pane is constructed only on first entry and is then reused until the Admin Center
closes, preserving filters, selection, and scroll state while avoiding unrelated config,
project, machine, log, statistics, proc, update, and macro work on open. Direct commands
such as **Open logs panel**, **Open procs panel**, **Open statistics**, and update
actions still open their requested pane immediately and make that successfully mounted
section the next resume target. Closing and reopening with one `#` still returns to
home; only a second press while home is visible resumes. The top-level resume target and
alternate are persisted machine-locally and survive sase's TUI process restarts. Entry
bookmarks for Config, Logs, Machines, Projects, Procs, Tools, and Updates last only for
the current sase's TUI process. They restore by stable identity, along with minimal
scope or sub-tab context when needed, but reset when sase's TUI restarts. Filters,
marks, scroll positions, loaded data, pane instances, Statistics controls, and other
pane-local state are never carried between modal lifetimes.

### Config tab

The Config tab answers four questions for every field — what value is effective, why
(its provenance), where an edit will go, and whether it validates:

The nested Config catalog is alphabetized: **01 All**, **02 Flags**, **03 Holds**, **04
Launch**, **05 Memory**, **06 Snippets**, and **07 Macros**. With the bundled prefix,
press `0` and then `1`-`7` to open those children. Remap the prefix with
`ace.keymaps.config.select_subtab` without changing the visible default badges.

**Holds** lists the active [agent holds](../macros/directive-launch.md#hold-directive) with their selectors
and expiry. `j` / `k` move, `d` releases the highlighted hold immediately, and `r`
reloads the list. See [agent hold limits](../config/agents-and-runners.md#agent-hold-limits) for the TTL settings.

**Flags** is a keyboard-first control surface for every code-owned SASE feature flag. It
does not edit `~/.config/sase/sase.yml`, overlays, project-local `sase.yml`, or chezmoi
source. Enable and disable write a SASE-owned machine-state file under `SASE_HOME`
(normally `~/.sase/feature_flags.json`) and then restart sase's TUI and the service host
so new processes see the saved value. See [feature_flags](../config/feature-flags.md#featureflags) for
precedence, corruption behavior, and the CLI equivalent, and the
[Config Flags pane](machines-and-tools.md#config-flags-pane) for layout, keys, confirmation, and
self-disable recovery.

- **Browse / inspect** (read-only): a source rail lists each config layer with
  loaded/missing/invalid/read-only badges; the field tree is generated from the schema
  (`/` filters, `:` jumps to a dotted path, `m` shows only modified fields, `r`
  refreshes). In the tree, `j` / `k` move through visible rows and wrap at the ends,
  while Down / Up use clamped navigation. `'` paints entry hints over the currently
  visible rows, and a hint key moves the cursor exactly as `j` / `k` would, detail panel
  and selection bookmark included. Hints label nodes in place, so entering and leaving
  jump mode preserves whatever you collapsed; collapsed children are not hinted and
  cannot be jumped to. While hints are up they own the keyboard: `Esc` — or any key that
  is neither a hint nor the first character of one — leaves jump mode without moving the
  cursor, so reach for `/`, `m`, `r`, or `:` after exiting rather than during a jump (in
  a tree large enough for those letters to be hints, they jump instead). A rebuild of
  the tree that changes which fields are listed drops the hints and the jump-back
  history with them. `'` stays typable while the filter or path input holds focus. The
  detail pane shows the type, default, effective value, and the full provenance stack
  with the winning layer marked. Structured values (object maps and arrays of objects,
  such as `axe.routines` or [`repos`](../config/repositories-behavior.md#repos)) render as a multi-line,
  syntax-highlighted YAML block instead of a one-line JSON blob, while scalars and short
  flat lists keep their compact inline form.
- **Edit** (`↵` or `e` on a field): a typed editor is generated from the schema — a
  toggle for booleans, an option cycle for enums, validated inputs for numbers and
  strings, a line editor for string lists, and a raw-YAML escape hatch for complex
  shapes. Pick the write **scope** (`ctrl+t` cycles user base / overlays / a selected
  local file; `ctrl+n` creates a new overlay), or reset a field to its default
  (`ctrl+r`, which deletes the key from the chosen scope). A banner states the
  list-merge consequence (replace vs. append) for the chosen scope.
- **Preview / write** (`ctrl+s`): before anything is written you see the exact per-file
  text diff, the resulting effective merged value, and schema validation of the
  candidate config. The write is source-preserving (comments, key order, and quoting are
  kept) and is remapped to the chezmoi source tree when `use_chezmoi` is enabled.

For a chezmoi-remapped write, sase's TUI first applies the changed target; an apply
failure leaves the source edit in place and keeps the editor open. After a successful
write and any targeted apply, sase's TUI checks the file that was actually changed. If
that file is dirty inside a git repository, it offers to **commit and push** the change
as a tracked proc. Confirming stages that config file, commits the repository's current
index, pulls with rebase, and pushes; pre-existing staged changes are therefore included
in the same commit. The repository is discovered from the written file, so a remapped
edit uses the chezmoi source repository. When `use_chezmoi` is enabled, a successful
push is followed by a full `chezmoi apply`. Each failure stops the sequence at that
step, without undoing the written config change. Skipping the offer—or editing a file
outside git—also leaves the successful write in place. The
[Launch Control](launch-control-overrides.md#persistent-edits) uses the same workflow for persistent alias
edits, while its fixed `Ctrl+E` binding previews and writes
`llm_provider.default_effort` specifically to the user-base layer. `Ctrl+E` is local to
Launch Control modal (including bucket rows), not a configurable leader-key entry.
Choosing Provider default writes the empty schema sentinel; a currently active temporary
effort override remains effective until expiry or clear.

The Config tab edits the canonical [`repos.linked`](../config/repositories-behavior.md#repos)
mapping; its editor has no one-key migration action. Hand-edited config can still use the
`linked_repos` and `sibling_repos` aliases. See
[Configuration migration notes](../upgrading/configuration.md#repository-configuration).

SASE Admin Center never writes without showing the diff and validation first, and never
edits a built-in or plugin default (those layers are read-only).

### Logs tab

The Logs tab lists each log source and a colorized tail of the selected file. After a
launch or job failure, sase's TUI toasts a leader chord (`,L` by default) that opens
this tab on that failure's source, highlights the matching header line, and scrolls the
detail pane to it. The jump target is session-scoped: it is the most recent error toast
in this sase's TUI process, not a durable pointer, and it degrades to the ordinary tail
with an in-pane notice if the entry has rotated out of the log.

### Machines tab

The Machines tab is the controller's local fleet inventory. It always includes the local
controller and adds every enrolled remote alias, with columns for enrollment state,
health, capacity, last observation, and endpoint. The local row shows configured runner
capacity; every remote row shows **not reported** because the status response does not
include capacity. Opening or reloading the tab reads local inventory only; it never
contacts every gateway implicitly. A remote therefore starts with state **not checked**
and health **unknown** until you press `s` for one bounded, authenticated hello.

Use `/` to filter, `j` / `k` to move, `U` to reload inventory, and `Enter` to close
Admin Center and open Agents filtered to `machine:<alias>` (`machine:local` for the
local row, whose Alias column instead shows the configured machine name). `c` shows the
persistent enrollment flow. For a selected remote, `r`, `R`, and `x` show repair,
rename, and removal guidance, while `y` copies the displayed command; these guidance
actions do not mutate machine state by themselves. See the
[Remote Dispatch Runbook](../integrations/remote-dispatch.md) for enrollment and credential handling.

### Projects tab

The Projects tab is an inventory and lifecycle surface with three clickable sub-tabs:
**Projects · Repos · Workspaces**. `[` / `]` cycle those sub-tabs, while `Tab` /
`Shift+Tab` switch the Admin Center's main tabs.

- **Projects** lists true projects—projects backed by their own main ProjectSpec,
  excluding `home` and internal linked-repo backing records. Enabled and disabled rows
  appear together with VCS kind, claim, workspace, repo, and warning counts. Press `n`
  to open the New Project wizard, or choose **Projects: New project…** from the command
  palette. `a` / `d` enable or disable, `i` / `I` initialize the marked or highlighted
  set or every enabled project, `r` / `w` cross-navigate to the selected project's
  inventories, and the established mark, alias, edit, force, and confirmed-delete
  actions remain available.
- **Repos** lists primary, sidecar, linked, and opened external repos for enabled
  projects by default. It reports checkout presence, source/config metadata,
  `auto_clone`, environment names, and SDD storage mode.
- **Workspaces** joins registry entries with active claims, PID liveness, pins,
  last-used timestamps, TTL staleness, and checkout presence. Missing checkouts point to
  `sase workspace repair`.

On Repos and Workspaces, `p` opens a shared project picker. Choosing a disabled project
explicitly reveals its rows; `Esc` clears the project scope, `/` text-filters within it,
and `R` refreshes the off-thread cached inventory.

### Statistics tab

The Statistics tab aggregates durable agent run and activity records over a selectable
time range. Its nine numbered views are **01 Overview**, **02 Runners**, **03
Projects**, **04 Providers**, **05 Activity**, **06 Macros**, **07 Plans & Questions**,
**08 Perf**, and **09 Footprint**. The Runners view uses today's effective global limit—including a
temporary override—as present-day context, never as historical configuration. The
Projects view reports default-branch output, committed plans, lifetime code, and this
machine's runs. Press `g` to group by project, repo, language, model, or Project →
Patch; several projects default to project grouping, while a one-project scope defaults
to model and skips project while cycling. Macros can group by usage, model, project, or co-usage.
Perf combines TUI startup and responsiveness logs with telemetry latency and
reliability; its grouping cycles through subsystem, provider, and workflow. A pane-wide
project filter lets you apply the same scope to the run-backed views, but Perf is global
and marks the project chip **not applied**. Footprint is the local usage census of
which sase surfaces you actually use; see the
[Footprint reference](../footprint.md) for its lenses, evidence states, and review flow.

The pane loads only while visible, refreshes every 30 seconds, and performs its queries
off the UI thread. Use `[` / `]` to change views or press `0` followed by `1`–`9` to
select the view displayed as `01` through `09`. Use `t`/`T` or `c` to choose a preset or
custom range, `g` to change the Projects, Macros, Perf, or Footprint lens grouping, `a`
to cycle the Footprint actor scope, `p`/`P` to cycle the
project filter forward or backward, and `r` to refresh immediately. On the Footprint
view, `enter` drills into an area, `backspace` returns, `/` finds a feature, `y` copies
its ID, `k` / `l` / `x` / `u` record keep / later / cut / clear decisions, and `F`
launches the `#footprint_review` flow. Keyed scope chips
keep the effective range, grouping, and project visible; the **Group** chip appears only
in those three groupable views and names the selected dimension there. Project scopes
use configured display names while retaining canonical keys internally. First open seeds
the current project when `ace.current_project.seed_filters` is on; `p` / `P` can always
cycle away from that seed. The cycle order is **All projects**, followed by projects
ranked by run count in the most recently loaded unfiltered result, and then wraps: `p`
moves forward and `P` backward. Return to **All** after changing the range to rebuild
that list for the new range. If a selected project produces an empty result, either
project-cycle key clears directly to **All projects**. Every populated view includes a
compact metric legend, `?` opens the complete glossary and current scope, and
empty/error states show the effective keys for widening, clearing, or retrying. The
Overview Agents Run, Success Rate, and **Run commits (this machine)** tiles open
Projects, while Plans Proposed and Questions open Plans & Questions. The plan and question tiles remain all-project
values even when a project is selected; see
[Telemetry: Admin Center Statistics tab](../../contribute/telemetry.md#admin-center-statistics-tab) for
the view contents, range syntax, and project-filter caveats, and
[Reading the Admin Center Perf view](../../contribute/perf-runbook.md#reading-the-admin-center-perf-view)
for Perf data sources and retention.

### Tools tab

Press `7` in Admin Center to inspect recorded command runs, grouped failure signatures,
and the configured tool catalog. The pane has **Runs**, **Failures**, and **Catalog**
views, with project filters and links to output and diagnostics. See the
[Tools tab guide](machines-and-tools.md#tools-tab) and [Named Tools and ToolRuns](../automation/tools.md).

### Updates tab

The Updates tab keeps SASE, its plugins, and its supported agent CLIs current without
leaving the TUI, as one master/detail inventory rather than separate tabs per source.
Every SASE core package, plugin, and registered agent CLI is a row, grouped into
**SASE**, **Plugins · Built-in**, **Plugins · Community**, and **Agent CLIs** sections.
The list always shows every row (installed or not), with updatable rows first in each
section.

- **SASE** rows show the installed and latest versions of `sase` and `sase-core`; the
  highlighted row's detail includes its incoming commits.
- **Plugins** rows bring the full
  [`sase plugin`](../integrations/plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show)
  experience into the TUI: filter the catalog, inspect a plugin, and install, update,
  uninstall, or switch install mode. A plugin that declares commands shows a
  `❯ sase <name>` chip on the row and in the detail panel. Install, update, and
  uninstall confirmations can preview declarations that would be added or removed, when
  the metadata is known. Update comparisons cover single-plugin managed updates;
  collision warnings appear on single-plugin install confirmations. The completion toast
  labels net command-name additions `new command` and removals `removed`. See
  [Where a command shows up](../integrations/plugins-commands.md#where-a-command-shows-up).
- **Agent CLIs** rows are a provider-colored master/detail browser for Claude Code,
  Codex CLI, OpenCode, Qwen Code, Antigravity, Muse Code, and Grok Build. Rows show
  installed → latest versions, install method, `↑` availability, and update marks.
  Missing CLIs that SASE can install show `latest v…` with an `[npm]` or `[script]`
  badge (others show `[manual]`) and install with `i` (or `Space` / `I` marks for a bulk
  set, mixed with plugin marks in one combined flow). Details show the resolved
  executable, exact automatic or manual update command, skip reason, canonical vendor
  docs URL, and the last result; missing CLIs instead show the install route, exact
  command or script URL, target, and the
  `↓ i install now · Space mark · * mark all missing` call to action. Every install
  previews first — exact command, target, and PATH status, plus the full SHA-256 for a
  script — runs without a shell (a script CLI runs the previewed bytes; an npm CLI runs
  `npm install -g <package>`), and stays visible afterwards (row, detail, toast, and
  history), including "installed but not on PATH" with the exact `export` line. `H`
  toggles the agent-CLI run history between the highlighted CLI and every CLI.

The always-visible header above the list shows either the all-current banner or a digest
(update counts per source, cache age, install mode, and an offline badge) plus a line
per failed source; it never renders "all current" while any enabled source is unknown or
failed.

Opening the tab never refreshes from the network. The first open in an ACE session
builds the inventory from local caches the automatic update check maintains (plugin
catalog, latest-version caches, editable checkouts' last-fetched upstream refs), without
PyPI/GitHub/npm or `git fetch`. Later opens reuse the in-memory inventory instantly;
when the automatic check has published newer results, the open re-reads those caches
instead. `r` refreshes everything from the network, and `checked … ago` is the age of
the last network check.

The Plugins rows stay visually consistent with the CLI by reusing the same catalog
loader and Rich renderables. They are split into **Built-in** and **Community**
(third-party, shown with a warning) sections; status glyphs match the CLI exactly: `●`
installed, `○` available, `↑` update available. Editable / dev installs (both core
packages and plugins) carry a lowercase `dev` marker and are compared against their git
upstream instead of PyPI. Update actions route editable packages through the
[dev-update](../integrations/plugins-update.md#dev-editable-installs) planner and managed packages through the
`uv` path. Blocked editable states appear as dim reasons such as `dev · local changes`,
`dev · diverged`, `dev · detached HEAD`, `dev · no upstream`, or `dev · offline`.

sase's TUI computes one composite SASE/plugin/agent-CLI snapshot after first paint. The
existing ten-minute session tick only revalidates that cached snapshot and locally
probes provider names already present in it. A full inventory/network recompute is
eligible on the longer `ace.updates.recompute_interval_minutes` cadence (one hour by
default), while npm latest-version lookups retain their separate six-hour cache. Source
failures remain independent, so a provider lookup failure does not erase known
SASE/plugin results and vice versa.

The persistent `updates:` top-bar group is the top bar's only dark chip (a deep moss
surface), so it never blends with its neighbors: lime `⬆ N` for SASE/plugin updates,
with a bright lime `core` tag when `sase-core-rs` requires a Rust rebuild, and a sage
`CLI ⬆ N` segment for supported agent CLIs. While SASE is updating, a green `⚙` gear
inset leads the badge. Mixed states join the SASE and CLI segments, and the tooltip
spells out both counts plus any manual-only CLI updates. Clicking the badge opens this
tab without mutating anything, or the Procs tab on the running update while one runs.

The global `,U` action opens the **Update panel** from already-fetched SASE and provider
snapshots (no Admin Center, no live inventory load). The providers row lists each
captured provider with its installed-to-latest version transition and marks manual-only
providers by name, and the Everything row summarizes both legs on one line. When the
SASE leg needs a `sase-core-rs` Rust rebuild, the SASE and Everything rows carry the
same `core` tag as the top-bar badge. Lowercase `e` / `s` / `p` (or `⏎` / mouse on the
highlighted row) choose Everything, SASE, or providers and still require the final
`y`/`n` confirmation. Capital `E` / `S` / `P` plan the same scopes and skip only that
confirmation after a runnable preview succeeds; failed or already-current previews still
do not mutate. Global `,E` is equivalent to `,U` then capital `E`: it submits the same
Everything preview from cached snapshots and only the runnable preview continues to the
tracked update proc. The providers leg still captures provider names from the latest
completed automatic snapshot and never adds a newly discovered provider to that
invocation. Safe commands run sequentially; Homebrew, non-writable npm, and
unknown-provenance installs remain visible with manual guidance. The pane-wide `u`
remains SASE/core/plugins-only, pane-wide `A` remains the deliberate action for the
current agent-CLI inventory, and pane-wide `a` runs a tracked agents-sidecar publication
sync: it publishes and reconciles this machine's own agent hoods for every enabled
project and is not part of the comprehensive update. See
[Agent Hood Synchronization](../agents/hood-sync.md#commands-and-status) for that command's
behavior.

Admin Center mutations **preview first**, and long confirmation panes scroll with
`Ctrl+D` / `Ctrl+U`. The Update panel's capital shortcuts are the documented exception:
they skip only the final `y`/`n` after that same preview succeeds. Plugin and core
actions show the exact `uv` command or editable-checkout plan. When commit previews are
enabled and a comparable range is available, confirmations for core and installed-plugin
**updates** load incoming commits by repository in the background; install, uninstall,
and mode-switch confirmations do not claim a commit range. An Everything confirmation
from `,U` groups SASE and Agent CLI work into labeled sections with update/current/
skipped glyphs, counts, and commands (home paths display as `~/`). The tracked proc runs
Agent CLI commands first and the SASE/core/plugin leg second, reporting independent
partial failures. `A` previews every exact agent-CLI command and every skip with its
reason and docs URL; it uses the marked subset from anywhere in the pane, otherwise it
targets every safely updatable installed CLI. Agent-CLI commands execute sequentially as
one tracked proc and refresh the browser without restarting sase's TUI; new agent
launches naturally use the updated binaries. `Space` (or its alias `I`) marks any
markable row — installable plugins, installable agent CLIs, and updatable agent CLIs —
in one shared mark set whose aggregate line counts plugin installs, CLI installs, and
CLI updates separately; `Esc` clears every mark, of any kind and regardless of the
active filter, before closing. All slow work runs off the event loop. Core/plugin code
changes retain the existing automatic sase's TUI and service host restart behavior after
the other legs finish. The Tools pane bindings are listed in the generated
[TUI keymap reference](keymaps.md).

From home, `Tab` enters Config and `Shift+Tab` enters Updates; within a working section
they switch tabs. `1`–`8` select a section directly. Pressing `#` from home resumes the
last section; within a section it toggles between the current and previous section.
`Esc` clears every mark before closing, and `q` closes the Admin Center.

The Admin Center opener uses the effective `ace.keymaps.app.open_config_center` binding
(`number_sign` / `#` by default), which is shown in the generated keymap reference and
the landing-page hint. Section navigation is pane-local and cannot be configured.

## Related

- [TUI keymaps](keymaps.md) — generated keymap defaults.
- [Configuration reference](../config/index.md) — generated configuration keys.
