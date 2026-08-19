# Configuration Reference

This document is the central reference for all sase configuration: config files, YAML
sections, environment variables, and CLI flags.

## Table of Contents

- [Config File Location](#config-file-location)
- [Owner Identity](#owner-identity)
- [SASE Admin Center (interactive editor)](#sase-admin-center-interactive-editor)
  - [Config tab](#config-tab)
  - [Projects tab](#projects-tab)
  - [Updates tab](#updates-tab)
- [Deep-Merge System](#deep-merge-system)
- [Configuration Sections](#configuration-sections)
  - [memory.h1_title](#memoryh1_title)
  - [memory.glossary](#memoryglossary)
  - [generated templates](#generated-templates)
  - [is_sase_managed](#is_sase_managed)
  - [id](#id)
  - [machine_name (deprecated)](#machine_name-deprecated)
  - [ace](#ace)
  - [artifacts](#artifacts)
  - [artifact_refs](#artifact_refs)
  - [llm_provider](#llm_provider)
  - [commit](#commit)
  - [repos](#repos)
  - [vcs_provider](#vcs_provider)
  - [vcs_repo_completion](#vcs_repo_completion)
  - [vcs_ref_completion](#vcs_ref_completion)
  - [axe](#axe)
  - [file_hooks](#file_hooks)
  - [plugins](#plugins)
  - [mentor_profiles](#mentor_profiles)
  - [metahooks](#metahooks)
  - [xprompts](#xprompts)
  - [xprompt_aliases](#xprompt_aliases)
  - [use_chezmoi](#use_chezmoi)
  - [commit_hooks](#commit_hooks)
  - [max_running_agents](#max_running_agents)
  - [max_agent_pipe_chain](#max_agent_pipe_chain)
  - [runner_slots](#runner_slots)
  - [procs](#procs)
  - [markdown](#markdown)
  - [timezone](#timezone)
  - [chat_install](#chat_install)
  - [telegram](#telegram)
  - [tmux_agent](#tmux_agent)
  - [mobile_gateway](#mobile_gateway)
  - [sdd](#sdd)
  - [bead](#bead)
  - [external_mirror](#external_mirror)
  - [feature_flags](#feature_flags)
  - [workspace](#workspace)
  - [telemetry](#telemetry)
  - [update](#update)
- [Environment Variables](#environment-variables)
- [CLI Flags](#cli-flags)
- [Directory Sharding](#directory-sharding)

## Config File Location

All sase configuration lives under `~/.config/sase/`. The base config file is:

```
~/.config/sase/sase.yml
```

Overlay files matching the glob `~/.config/sase/sase_*.yml` are merged on top of the
base file. In the SASE Admin Center new-overlay prompt, enter a single local overlay
name rather than a path: `extra`, `sase_extra`, and `sase_extra.yml` all resolve to
`~/.config/sase/sase_extra.yml`. SASE trims surrounding whitespace and rejects empty
names, `.` / `..`, or names containing `/` or `\`, so the create-overlay flow cannot
escape the user config directory. A project-local `sase/sase.yml` at the detected
project root usually takes highest priority. A root-level `sase.yml` remains an
exclusive read fallback during the
[layout compatibility window](content_layout.md#compatibility-and-collisions); if both
files exist, SASE reports a collision instead of merging them. The ACE TUI deliberately
disables project-local config loading for its own process so opening `sase ace` inside a
repo does not inherit that repo's agent-run settings. See
[Deep-Merge System](#deep-merge-system) below.

## Owner Identity

SASE has one explicit owner identity selected for the current machine. Initialize or
migrate it interactively with either equivalent command:

```bash
sase config init
sase init config
```

The selected overlay owns both parts of the identity:

```yaml
id:
  username: alice
  machine_name: athena
```

`id.username` is a path-safe, dot-free SASE username. It must be globally unique, should
be identical on every machine owned by the same user, and should normally be the user's
GitHub username. SASE validates its syntax and reserved names but cannot prove global
uniqueness. `id.machine_name` matches `^[a-z_]+$` and is unique among that user's
machines.

The bounded local state file `~/.sase/machine_name` (or `$SASE_HOME/machine_name`) is
only a selector. It contains one machine name and is deliberately not portable
configuration; it is not the owner identity and cannot supply a missing username. SASE
discovers machine overlays by nested `id.machine_name` first, with deprecated top-level
`machine_name` accepted only as migration input. Foreign machine overlays do not
contribute runtime settings, Config inventory layers, or config-defined xprompts.
Ordinary overlays still participate.

Only the selected raw machine overlay can own provenance. An `id` value in bundled
defaults, plugins, `~/.config/sase/sase.yml`, ordinary overlays, or project-local config
is ignored by runtime merging and cannot change the owner for one project. The selected
raw `id` object remains visible in merged configuration for inspection.

The initializer lists declared machines, suggests a schema-safe hostname when a machine
must be chosen, and requires an explicit valid username unless exactly one existing
username is clearly confirmed for reuse. It never chooses among conflicting usernames.
Creation and migration minimally set `id.username` and `id.machine_name` in the same
overlay, remove its deprecated top-level key, preserve unrelated YAML/comments, and then
write the selector. With `use_chezmoi: true`, the overlay edit is made in the chezmoi
source tree. Direct `sase config init` uses the normal commit/push/apply deployment;
bare `sase init` combines the edit with deferred chezmoi deployment. The initializer
also adds a hostname guard to the chezmoi source `.chezmoiignore`, staging it in the
same commit as the new overlay:

```text
{{ if ne .chezmoi.hostname "<chezmoi-hostname>" }}
.config/sase/sase_<machine>.yml
{{ end }}
```

The guard uses chezmoi's hostname, which may differ from the SASE machine name, so the
overlay is applied only on the machine where it was initialized. If `.chezmoiignore`
already contains an entry for that overlay, the existing guard is left unchanged.

Prompting requires a TTY. `sase config init --check`, bare `sase init --check`, and
`sase doctor` report missing usernames, legacy migration, invalid values, selector
mismatches, duplicate overlays, and identity conflicts without writing. Config
inspection, help, initialization, doctor, and legacy history remain available while
identity is incomplete. Actual agent process creation, new commit provenance, and
agents-sidecar mutations require both identity fields and fail with the actionable
`sase config init` instruction.

There is intentionally no bundled identity default.

Machine hoods also provide stable ownership for the hidden agents sidecar. See
[Agent Hood Synchronization](agents_sidecar.md) for privacy controls, package contents,
import/publication commands, and recovery.

## SASE Admin Center (interactive editor)

Press `#` in the `sase ace` TUI to open **SASE Admin Center**. The first press always
starts on its lightweight home page, where the seven working sections—**Config**,
**Logs**, **Projects**, **Statistics**, **Procs**, **Updates**, and **XPrompts**—are
introduced without loading their data. While home is visible, press `#` again to resume
the last section that was successfully active in this ACE process. Before the first
section visit, the repeated key leaves home unchanged and constructs no pane. Press
`1`–`7` or click the numbered tab strip to enter a section. From home, `Tab` enters
Config and `Shift+Tab` enters XPrompts; within a working section they wrap across the
same seven tabs. Pane-local `[` / `]` keys switch sub-tabs or views where the active
pane provides them.

Inside a working section, the same opener key takes on a second meaning: it jumps to the
section you were in immediately before the current one, and pressing it again toggles
back—exactly two sections remembered, like a two-slot alternate rather than an unbounded
history stack. A color-coded footer along the bottom of each working section names the
jump target (or explains that none exists yet) and is itself clickable.

Each pane is constructed only on first entry and is then reused until the Admin Center
closes, preserving filters, selection, and scroll state while avoiding unrelated config,
project, log, statistics, proc, update, and xprompt work on open. Direct commands such
as **Open logs panel**, **Open procs panel**, **Open statistics**, and update actions
still open their requested pane immediately and make that successfully mounted section
the next resume target. Closing and reopening with one `#` still returns to home; only a
second press while home is visible resumes. The top-level resume target and alternate
are persisted machine-locally and survive across ACE processes. Entry bookmarks for
Config, Logs, Projects, Procs, Updates, and XPrompts last only for the current ACE
process and restore by stable identity, along with minimal scope or sub-tab context when
needed. Filters, marks, scroll positions, loaded data, pane instances, Statistics
controls, and other pane-local state are never carried between modal lifetimes.

### Config tab

The Config tab answers four questions for every field — what value is effective, why
(its provenance), where an edit will go, and whether it validates:

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
  such as `ace.lumberjack` or [`repos`](#repos)) render as a multi-line,
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

For a chezmoi-remapped write, ACE first applies the changed target; an apply failure
leaves the source edit in place and keeps the editor open. After a successful write and
any targeted apply, ACE checks the file that was actually changed. If that file is dirty
inside a git repository, it offers to **commit and push** the change as a tracked proc.
Confirming stages that config file, commits the repository's current index, pulls with
rebase, and pushes; pre-existing staged changes are therefore included in the same
commit. The repository is discovered from the written file, so a remapped edit uses the
chezmoi source repository. When `use_chezmoi` is enabled, a successful push is followed
by a full `chezmoi apply`. Each failure stops the sequence at that step, without undoing
the written config change. Skipping the offer—or editing a file outside git—also leaves
the successful write in place. The [Launch Control](ace.md#persistent-edits) uses the
same workflow for persistent alias edits, while its fixed `Ctrl+E` binding previews and
writes `llm_provider.default_effort` specifically to the user-base layer. `Ctrl+E` is
local to Launch Control modal (including bucket rows), not a configurable leader-key
entry. Choosing Provider default writes the empty schema sentinel; a currently active
temporary effort override remains effective until expiry or clear.

The deprecated `linked_repos` and `sibling_repos` keys remain readable as compatibility
aliases for [`repos.linked`](#repos), but the Config tab no longer offers a one-key
migration action. Prefer editing the config to use `repos.linked` directly.

SASE Admin Center never writes without showing the diff and validation first, and never
edits a built-in or plugin default (those layers are read-only).

### Logs tab

The Logs tab lists each log source and a colorized tail of the selected file. After a
launch or chop failure, ACE toasts a leader chord (`,L` by default) that opens this tab
on that failure's source, highlights the matching header line, and scrolls the detail
pane to it. The jump target is session-scoped: it is the most recent error toast in this
ACE process, not a durable pointer, and it degrades to the ordinary tail with an in-pane
notice if the entry has rotated out of the log.

### Projects tab

The Projects tab is an inventory and lifecycle surface with three clickable sub-tabs:
**Projects · Repos · Workspaces**. `[` / `]` cycle those sub-tabs, while `Tab` /
`Shift+Tab` switch the Admin Center's main tabs.

- **Projects** lists true projects—projects backed by their own main ProjectSpec,
  excluding `home` and internal linked-repo backing records. Enabled and disabled rows
  appear together with VCS kind, claim, workspace, repo, and warning counts. `a` / `d`
  enable or disable, `r` / `w` cross-navigate to the selected project's inventories, and
  the established mark, alias, edit, force, and confirmed-delete actions remain
  available.
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
time range. Its eight numbered views are **1 Overview**, **2 Runners**, **3 Projects**,
**4 Providers**, **5 Activity**, **6 XPrompts**, **7 Plans & Questions**, and **8
Perf**. The Runners view uses today's effective global limit—including a temporary
override—as present-day context, never as historical configuration. The Projects view
can group by project, by Patch, or as a project-to-Patch drilldown. XPrompts can group
by usage, model, project, or co-usage. Perf combines TUI startup and responsiveness logs
with telemetry latency and reliability; its grouping cycles through subsystem, provider,
and workflow. A pane-wide project filter lets you apply the same scope to the run-backed
views, but Perf is global and marks the project chip **not applied**.

The pane loads only while visible, refreshes every 30 seconds, and performs its queries
off the UI thread. Use `[` / `]` to change views or press `0` followed by `1`–`8` to
select one directly. Use `t`/`T` or `c` to choose a preset or custom range, `g` to
change the Projects, XPrompts, or Perf grouping, `p`/`P` to cycle the project filter
forward or backward, and `r` to refresh immediately. Keyed scope chips keep the
effective range, grouping, and project visible; the **Group** chip appears only in those
three groupable views and names the selected dimension there. Project scopes use
configured display names while retaining canonical keys internally. First open seeds the
current project when `ace.current_project.seed_filters` is on; `p` / `P` can always
cycle away from that seed. The cycle order is **All projects**, followed by projects
ranked by run count in the most recently loaded unfiltered result, and then wraps: `p`
moves forward and `P` backward. Return to **All** after changing the range to rebuild
that list for the new range. If a selected project produces an empty result, either
project-cycle key clears directly to **All projects**. Every populated view includes a
compact metric legend, `?` opens the complete glossary and current scope, and
empty/error states show the effective keys for widening, clearing, or retrying. The
Overview Agents Run, Success Rate, and Commits tiles open Projects, while Plans Proposed
and Questions open Plans & Questions. The plan and question tiles remain all-project
values even when a project is selected; see
[Telemetry: Admin Center Statistics tab](telemetry.md#admin-center-statistics-tab) for
the view contents, range syntax, and project-filter caveats, and
[Reading the Admin Center Perf view](perf_runbook.md#reading-the-admin-center-perf-view)
for Perf data sources and retention.

### Updates tab

The Updates tab keeps SASE, its plugins, and its supported agent CLIs current without
leaving the TUI. Use `]` / `[` to cycle its three pane-local sub-tabs:

- **Core** (the default) shows the installed and latest versions of `sase` and
  `sase-core`, incoming commits, and the all-current banner.
- **Plugins** brings the full
  [`sase plugin`](plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show)
  experience into the TUI: filter the catalog, inspect a plugin, and install, update,
  uninstall, or switch install mode.
- **Agent CLIs** is a provider-colored master/detail browser for Claude Code, Codex CLI,
  OpenCode, Qwen Code, Antigravity, Muse Code, and Grok Build. Rows show installed →
  latest versions, install method, `↑` availability, and update marks. Details show the
  resolved executable, exact automatic or manual update command, skip reason, canonical
  vendor docs URL, and the last result.

The Plugins browser stays visually consistent with the CLI by reusing the same catalog
loader and Rich renderables. Its list is split into **Built-in** and **Community**
(third-party, shown with a warning) sections; status glyphs match the CLI exactly: `●`
installed, `○` available, `↑` update available. Editable / dev installs (both core
packages and plugins) carry a lowercase `dev` marker and are compared against their git
upstream instead of PyPI. Update actions route editable packages through the
[dev-update](plugins.md#dev-editable-installs) planner and managed packages through the
`uv` path. Blocked editable states appear as dim reasons such as `dev · local changes`,
`dev · diverged`, `dev · detached HEAD`, `dev · no upstream`, or `dev · offline`.

ACE computes one composite SASE/plugin/agent-CLI snapshot after first paint. The
existing ten-minute session tick only revalidates that cached snapshot and locally
probes provider names already present in it. A full inventory/network recompute is
eligible on the longer `ace.updates.recompute_interval_minutes` cadence (one hour by
default), while npm latest-version lookups retain their separate six-hour cache. Source
failures remain independent, so a provider lookup failure does not erase known
SASE/plugin results and vice versa.

The persistent top-bar badge uses separate joined segments: purple `↑ N` for routine
SASE/plugin updates, amber `↑ N *` when `sase-core-rs` requires a Rust rebuild, and cyan
`CLI ↑ N` for supported agent CLIs. Mixed states join the SASE and CLI segments, and the
tooltip spells out both counts plus any manual-only CLI updates. Clicking the badge
opens this tab without mutating anything.

The global `,U` action opens the **Update panel** from already-fetched update and
agents-sync snapshots (no Admin Center, no live inventory load). Choosing Everything,
SASE, providers, or agents plans only that scope; the providers and agents legs still
capture provider names and pending incoming hood cache items from the latest completed
automatic snapshots and never add a newly discovered provider or a subsequently fetched
hood to that invocation. Safe commands run sequentially; Homebrew, non-writable npm, and
unknown-provenance installs remain visible with manual guidance. The pane-wide `u`
remains SASE/core/plugins-only, pane-wide `A` remains the deliberate action for the
current agent-CLI inventory, and pane-wide `a` performs an explicit full-network sync of
all enabled agents repositories.

Every mutation **previews first**, and long confirmation panes scroll with `Ctrl+D` /
`Ctrl+U`. Plugin and core actions show the exact `uv` command or editable-checkout plan.
When commit previews are enabled and a comparable range is available, confirmations for
core and installed-plugin **updates** load incoming commits by repository in the
background; install, uninstall, and mode-switch confirmations do not claim a commit
range. An Everything confirmation from `,U` groups SASE, Agent CLI, and **Cached agent
hoods** work into labeled sections with update/current/skipped glyphs, counts, and
commands (home paths display as `~/`). The cached-hood section is runnable only when
captured incoming hoods from other owners exist, and it lists their exact projects and
hood counts. The tracked proc runs Agent CLI commands first, the SASE/core/plugin leg
second, and cached agents integration last, reporting independent partial failures. `A`
previews every exact agent-CLI command and every skip with its reason and docs URL; on
the Agent CLIs sub-tab it uses the marked subset, otherwise it targets every safely
updatable installed CLI. Agent-CLI commands execute sequentially as one tracked proc and
refresh the browser without restarting ACE; new agent launches naturally use the updated
binaries. Installable plugins use `I` / `Space` marks, while updatable agent CLIs use
`Space`; `Esc` clears marks in the active sub-tab before closing. All slow work runs off
the event loop. Core/plugin code changes retain the existing automatic ACE/axe restart
behavior after the other legs finish. The context-sensitive keymaps are:

| Key                 | Action                                                                                                      |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| `]` / `[`           | Cycle Core / Plugins / Agent CLIs sub-tabs                                                                  |
| `j` / `k`           | Move the highlight down / up in Plugins or Agent CLIs                                                       |
| `'`                 | Jump to an item row via adaptive hints in Plugins or Agent CLIs; no-op on Core                              |
| `I` / `Space`       | Mark / unmark an installable plugin; `Space` marks an updatable agent CLI on that sub-tab                   |
| `i`                 | Open the install preview for the marked set, or for the highlighted plugin when no install marks are active |
| `x`                 | Uninstall the highlighted plugin (only when installed)                                                      |
| `u`                 | Run `sase update` for SASE core plus all installed plugins                                                  |
| `A`                 | Update marked agent CLIs on that sub-tab, or every safely updatable installed agent CLI otherwise           |
| `a`                 | Full-network sync every enabled agents repository and drain publication retries                             |
| `U`                 | Update the highlighted installed plugin when that row has an update available                               |
| `m`                 | Switch install mode (PyPI managed ↔ dev editable; the `sase update --to` analog)                            |
| `r`                 | Refresh — refetch the catalog and latest versions (the `-r/--refresh` analog)                               |
| `Ctrl+D`            | Scroll the detail panel down                                                                                |
| `Ctrl+U`            | Scroll the detail panel up                                                                                  |
| `g`                 | Scroll the detail panel to the top                                                                          |
| `G`                 | Scroll the detail panel to the bottom                                                                       |
| `o`                 | Toggle offline (cache-only) mode, with a header badge (the `-o/--offline` analog)                           |
| `v`                 | Toggle verbose list columns — stars / last-updated (the `-v/--verbose` analog)                              |
| `/`                 | Focus the filter input (matches name / description / topics)                                                |
| `#` (default)       | From home, resume the last section used; in a section, jump to the previous one, press again to toggle      |
| `Tab` / `Shift+Tab` | From home enter Config / XPrompts; otherwise switch SASE Admin Center tabs (`1`–`7` jump directly)          |
| `Esc`               | Clear active plugin/agent-CLI marks first; close when no marks are active                                   |
| `q`                 | Close SASE Admin Center                                                                                     |

The Admin Center opener is the effective `ace.keymaps.app.open_config_center` binding
(`number_sign` / `#` by default), so a custom binding is repeated in the same way and
appears in the landing-page hint. The remaining section-navigation keymaps above are
widget-local and are not configurable through `default_config.yml`.

## Deep-Merge System

Sase builds a merged configuration through five layers, each merged on top of the
previous:

1. **`default_config.yml`** — bundled package defaults
2. **Plugin `default_config.yml` files** — from installed plugin packages (via
   `sase_config` entry points), sorted by entry-point name; lists concatenate
3. **`sase.yml`** — user config (`~/.config/sase/sase.yml`); lists **replace** defaults
   (not concatenate)
4. **Selected `sase_*.yml` overlays** — ordinary overlays plus only the machine overlay
   whose nested `id.machine_name` (or deprecated top-level fallback) matches
   `~/.sase/machine_name`, sorted alphabetically; lists **concatenate**
5. **Local `sase.yml`** — project-level config in the current working directory; lists
   **concatenate** (highest priority)

This allows splitting shared configuration across ordinary files (e.g., `sase_work.yml`,
`sase_personal.yml`) without duplication and keeping machine-specific settings in
selector-safe overlays. Plugins can provide sensible defaults that users can override,
and individual projects can customize behavior without changing global config.

Merge semantics:

| Type        | Behavior                                                                   |
| ----------- | -------------------------------------------------------------------------- |
| **Dicts**   | Merged recursively (overlay keys override base keys).                      |
| **Lists**   | Concatenated in layers 2, 4, and 5; **replaced** in layer 3 (user config). |
| **Scalars** | Override (overlay value replaces base value).                              |

For example, given a base file with two mentor profiles and an overlay or local project
config that adds a third, the merged result contains all three profiles. A user
`~/.config/sase/sase.yml` list replaces earlier defaults instead. If two files define
the same scalar key (e.g., `axe.max_hook_runners`), the later layer wins.

Source: `src/sase/config/core.py`

## Configuration Sections

### memory.h1_title

Optionally customizes the Markdown H1 title of a generated managed `AGENTS.md`.

```yaml
memory:
  h1_title: "Structured Agentic Software Engineering (SASE) - Agent Instructions" # default: null
```

| Field             | Type           | Default | Description                                                                             |
| ----------------- | -------------- | ------- | --------------------------------------------------------------------------------------- |
| `memory.h1_title` | string \| null | `null`  | H1 title used by the `sase memory init` `AGENTS.md` generator when enabled for a scope. |

For ordinary project roots, `is_sase_managed: true` in that root's own `sase/sase.yml`
is the authorization switch. A managed project with no title derives
`<project> - Agent Instructions`; `memory.h1_title` alone does not opt a project in. The
legacy top-level `amd_h1_title` key has been removed; it is now reported as an
unsupported key by `sase config layers` instead of being silently ignored.

Home roots are the exception. For the live home root, user config from
`~/.config/sase/sase.yml` and `~/.config/sase/sase_*.yml` can provide the home
`AGENTS.md` title. For the chezmoi home source root, source-side config under
`dot_config/sase/` is used instead. With `use_chezmoi: true`, `sase memory init`
initializes the chezmoi home source root rather than writing a live-home `AGENTS.md`.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`

### generated templates

SASE packages default Jinja templates for managed agent instructions and generated
memory Markdown. Managed projects can replace them with root-relative files named in
their own `sase/sase.yml`:

```yaml
memory:
  agents_template: templates/AGENTS.template.md
  agents_minimal_template: templates/AGENTS.minimal.template.md
  sase_template: templates/memory-sase.template.md
  readme_template: templates/memory-README.template.md
```

| Field                            | Required Jinja variables                                                                  | Generated target or use               |
| -------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------- |
| `memory.agents_template`         | `title`, `tier1_sections`, `tier2_entries`                                                | Managed root `AGENTS.md`              |
| `memory.agents_minimal_template` | `title`, `tier1_sections`                                                                 | Create-if-missing minimal `AGENTS.md` |
| `memory.sase_template`           | `project_name`, `linked_repo_entries`                                                     | Generated `sase/memory/sase.md`       |
| `memory.readme_template`         | `memory_notes`, `total_notes`, `short_notes`, `long_notes`, `total_lines`, `total_tokens` | Generated `sase/memory/README.md`     |

`{{ tier2_entries }}` renders the entire Tier 2 body: the long-memory instruction
paragraph plus one H3 subsection per top-level long note. A custom `agents_template`
must not repeat that prose above `{{ tier2_entries }}`. When a root has no top-level
long notes, `{{ tier2_entries }}` is empty.

The legacy top-level `amd_agents_template`, `amd_agents_minimal_template`,
`memory_sase_template`, and `memory_readme_template` keys are deprecated but still read
as aliases; when both paths appear in one file, the nested `memory.*` form wins.

Every configured path must remain inside the project root. Rendering uses strict
variables: required placeholders must appear, unknown placeholders are rejected, and the
rendered instruction/memory structure is validated before any file is written. Generated
agent documents are numbered automatically, so custom `AGENTS.template.md` headings
should not carry their own numbers.

Home initialization uses convention-based files instead of the project-local path keys.
Put `AGENTS.template.md`, `AGENTS.minimal.template.md`, `memory-sase.template.md`, or
`memory-README.template.md` directly in `~/.config/sase/`; with `use_chezmoi: true`, put
them in the corresponding source-side `dot_config/sase/` directory. See
[Memory initialization](init.md#memory-initialization) for ownership, preview, and
deployment behavior.

Source: `src/sase/amd/_template.py`, `src/sase/main/init_memory/root_rendering.py`

### memory.glossary

Defines project-local domain terms in the repository's canonical `sase/sase.yml`.
Defaults, plugin config, user config, and overlays cannot provide glossary entries; the
config inventory reports those scopes as invalid so a global glossary cannot leak into
another project.

```yaml
memory:
  glossary:
    Agent Clan:
      definition: >-
        A named, rootless container for agents that run in parallel.
```

| Field             | Type              | Default | Description                                                                                                 |
| ----------------- | ----------------- | ------- | ----------------------------------------------------------------------------------------------------------- |
| `memory.glossary` | object \| omitted | omitted | Mapping from canonical displayed term to one glossary entry.                                                |
| `definition`      | string            | n/a     | Required nonblank Markdown definition, generated into project memory.                                       |
| `aliases`         | string[]          | `[]`    | Optional single-line aliases matched after the canonical term itself; derivable plurals need not be listed. |

The legacy top-level `glossary` key has been removed; it is now reported as an
unsupported key by `sase config layers` instead of being silently ignored. Run
`sase memory init` after editing glossary entries. A nonempty glossary generates a
short-term `sase/memory/glossary.md` note (frontmatter `sase_generated: glossary`) that
is inlined into Tier 1 of `AGENTS.md` and the provider instruction copies as
`Glossary Terms (glossary)`. The note ends with a single semicolon-separated
`**GLOSSARY TERMS:**` paragraph that names every displayed term and alias and points
agents at `sase glossary read <term> [<term> ...] -r "<why>"` — see
[Glossary](memory.md#glossary) — to fetch those definitions plus the terms they depend
on in one command, instead of loading every definition into every agent's context. The
plural of the term and of each alias is matched automatically; derivable plurals are
omitted from the rendered term list, and an empty glossary writes no note.
`sase memory init --check` verifies the note is current. A previously generated
`sase/memory/glossary.md` (marked `sase_generated: glossary`) is overwritten when terms
are configured and deleted when they are not; an unmarked, hand-authored
`sase/memory/glossary.md` plus configured terms is a blocker.

The canonical term is always the first effective alias, followed by configured aliases
and accepted derived plurals. Matching is case-insensitive, Unicode-aware, bounded by
word-like edges, and separates words in multiword phrases with horizontal whitespace
runs or one line break plus its surrounding indentation. A blank line or any
non-whitespace continuation prefix, such as a list marker, blockquote marker, heading,
or separator, ends the phrase. Inline and fenced code are skipped. Overlapping phrases
are allowed; the longest match wins, with authored order breaking ties. Blank terms,
blank definitions, multiline aliases, duplicate normalized terms, and one alias claimed
by more than one term fail validation consistently for config loading, memory
generation, ACE, and the xprompt LSP.

ACE highlights warm glossary matches in prompt text as bold, theme-accent, underlined
terms you can preview with `K` or jump to with `Ctrl+]`; wrapped matches are underlined
per line with continuation indentation excluded. In NORMAL mode, `K` previews the
matching project's definition after xprompt, skill, and file targets; `Ctrl+]` jumps to
the entry's `definition` range in that project's `sase/sase.yml`. The xprompt LSP uses
the same project selection and matcher for semantic tokens, hover Markdown, and
go-to-definition. A leading VCS workflow reference selects the glossary project;
otherwise the active workspace project is used. Unknown, disabled, home, or unreadable
project contexts produce no glossary semantics.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`,
`src/sase/main/init_memory/glossary.py`, `src/sase/xprompt/glossary_catalog.py`

### is_sase_managed

Controls whether SASE owns repository resources such as project memory, the root
`AGENTS.md`, and explicit SDD initialization.

```yaml
is_sase_managed: false # default
```

| Field             | Type    | Default | Description                                                              |
| ----------------- | ------- | ------- | ------------------------------------------------------------------------ |
| `is_sase_managed` | boolean | `false` | Explicitly authorize SASE to manage resources in the current repository. |

Only the target repository's own checked-in `sase/sase.yml` is consulted for this
authorization. A legacy root `sase.yml` remains readable only when the canonical file is
absent. Defaults, user config, and merged overlays cannot opt repositories in globally.
When false or absent, memory init does not create, refresh, or validate project memory
and does not create or alter the root `AGENTS.md`; it still propagates every existing
project `AGENTS.md` to provider files beside it. Explicit `sase repo init` and its
`sase init repo` alias become successful no-ops before provider and storage work.
Invalid local YAML or a non-boolean marker fails safely.

This is a direct migration: `memory.enabled` is retired and does not authorize
repository management. Existing managed projects must replace it with top-level
`is_sase_managed: true`.

Home and chezmoi-home memory initialization does not use this project-local switch, and
provider instruction copies for existing project `AGENTS.md` files remain independent of
it.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`

### id

Declares the explicit owner in the selected machine overlay:

```yaml
id:
  username: alice
  machine_name: athena
```

| Field             | Type   | Default | Description                                                                                           |
| ----------------- | ------ | ------- | ----------------------------------------------------------------------------------------------------- |
| `id.username`     | string | none    | Stable per-user identity shared across that user's machines; syntax and reserved names are validated. |
| `id.machine_name` | string | none    | Per-user machine name matching `^[a-z_]+$` and the local selector.                                    |

The schema permits partial objects so `sase config init` can diagnose and repair
interrupted or legacy migrations, but provenance requires both valid fields.

### machine_name (deprecated)

Top-level `machine_name` remains schema-valid only as read-only migration input for
legacy overlays:

```yaml
machine_name: athena
```

New writers never emit this form. Run `sase config init` to move it under `id`, add the
required username, and preserve the rest of the overlay. See
[Owner Identity](#owner-identity) for selection, authority, and deployment behavior.

Source: `src/sase/config/core.py`, `src/sase/config/sase.schema.json`,
`src/sase/core/paths.py`

### ace

Configures the ACE TUI behavior. Defaults are provided by `src/sase/default_config.yml`.

```yaml
ace:
  axe_description_expanded: true # Axe-tab description panel starts expanded
  artifacts:
    relations_expanded: false # Relation panel starts collapsed as a rail; . expands it
    commits:
      default_query: "sidecar:false since:24h"
  tribes:
    default:
      icon: "⌂"
      color: "#87D7FF"
      description: "Agents with no assigned tribe."
    chop:
      icon: "†"
      color: "#FFAF5F"
      initially_expanded: false
      description: "Scheduled AXE chop automation."
  updates:
    startup_toast: true # show SASE/plugin/agent-CLI updates on startup
    startup_toast_max_commits: 20 # total incoming subjects across repositories
    post_update_toast: true # confirm the version transition after self-update restart
    post_update_toast_diffstat: true # show applied file and line counts
    post_update_toast_commits: true # show applied commits grouped by repository
    post_update_toast_max_commits: 5 # applied subjects shown per repository
    agent_cli_history: true # show Agent CLIs update history in the Updates tab
    agent_cli_history_max_rows: 8 # history rows/runs shown; 0 shows all
    indicator: true # show the segmented SASE + agent-CLI update badge
    prebuild_rust: true # background-cache editable sase-core Rust artifacts
    incoming_commits:
      enabled: true # show incoming commit subjects in the Updates tab
      max_per_repo: 7 # cap subjects per repository
      confirm_max_per_repo: 250 # larger per-repository cap in confirmations
    check_interval_minutes: 10 # attempt a periodic check this often
    check_ttl_minutes: 10 # refresh latest-version checks at most this often
    recompute_interval_minutes: 60 # periodic full network recompute cadence
  agents_sync:
    check_interval_minutes: 10 # local/cached agents-repository status cadence
    recompute_interval_minutes: 30 # minimum remote-fetching status cadence
    indicator: true # show ⇅ N only for cached, unapplied hoods from other owners
  keymaps:
    statistics:
      prev_view: "left_square_bracket" # active only while Statistics is focused
      next_view: "right_square_bracket"
      select_view: "0"
      cycle_range: "t"
      cycle_range_reverse: "T"
      custom_range: "c"
      cycle_group: "g"
      cycle_project_filter: "p"
      cycle_project_filter_reverse: "P"
      scroll_down: "ctrl+d"
      scroll_up: "ctrl+u"
      refresh: "r"
      help: "question_mark"
    app:
      next_patch: "j"
      prev_patch: "k"
      edit_query: "slash" # defaults render as `/` outside Agents
      show_help: "question_mark" # app-level Help; defaults render as bare `?`
      # ... all app-level keybindings are configurable
    modes:
      # Built-in modes (fold, copy, leader, bang) are configurable
      leader_mode:
        prefix: "comma"
        keys:
          repeat_last: "comma" # press the leader prefix, then this key; defaults render as `,,`
          edit_query: "slash" # Agents structured query; defaults render as `,/`
          models_panel: "m"
          update_sase: "U"
          full_history_refresh: "y"
      fold_mode:
        prefix: "z"
        keys:
          set_level_1: "1" # PR detail: set every section to level 1
          set_level_2: "2"
          set_level_3: "3"
          cycle_stitches: "c" # `cycle_commits` is still accepted as a legacy alias
          cycle_hooks: "h"
          agents:
            set_level_1: "1" # family 1-2; clan/session 1-3; tribe 1-4
            set_level_2: "2"
            set_level_3: "3"
            set_level_4: "4"
      # Custom modes can be added here
      my_mode:
        prefix: ";"
        keys:
          run_tests:
            key: "t"
            shell: "just test"
```

| Field                      | Type         | Default   | Description                                                                                                                                                |
| -------------------------- | ------------ | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agents_sync`              | dict         | see below | Periodic agents-repository status checks and the top-bar synchronization indicator.                                                                        |
| `artifacts`                | dict         | see below | Per-pane settings for ACE's Artifacts tab.                                                                                                                 |
| `axe_description_expanded` | bool         | `true`    | State the Axe-tab [description panel](ace.md#description-panel) starts each session in; `d` toggles it in memory.                                          |
| `current_project`          | dict         | see below | Top-bar `+<project>` chip and session seeds for project filters.                                                                                           |
| `keymaps`                  | dict         | -         | Configurable keybindings (see below).                                                                                                                      |
| `page_size`                | int          | `100`     | Ctrl+J / Ctrl+K step and the default Artifacts `limit:` value. Must be at least 1.                                                                         |
| `prompt_completion`        | dict         | see below | Live soft-completion settings for the ACE prompt input.                                                                                                    |
| `prompt_inputs`            | dict         | see below | Prompt input collection settings for raw `<placeholder>` tags and xprompt-save conversion.                                                                 |
| `prompt_spellcheck`        | dict         | see below | Sticky misspelling highlight settings for the ACE prompt input.                                                                                            |
| `repro_output_dir`         | str          | `""`      | Base directory for [Agents-tab reproduction bundles](ace.md#agents-tab-reproduction-bundles). Empty means `<SASE_HOME>/repros` (default `~/.sase/repros`). |
| `snippet_config_path`      | str          | `""`      | Config file that receives new `ace.snippets` entries written from the prompt bar (see below).                                                              |
| `snippets`                 | dict[string] | `{}`      | Trigger-word → template mappings for prompt input snippet expansion.                                                                                       |
| `tribes`                   | dict         | see below | Per-tribe ACE TUI icons and identity colors, plus Agents-tab panel initial expansion.                                                                      |
| `updates`                  | dict         | see below | Startup update checks, the top-bar update badge, and the one-shot post-update restart confirmation toast.                                                  |

#### `ace.artifacts`

| Field                | Type | Default | Description                                                                                                                                                                                                |
| -------------------- | ---- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `relations_expanded` | bool | `false` | Whether the [Artifacts relation panel](ace.md#navigation-in-stitches-beads-provider-documents-and-files) starts expanded; `.` (`toggle_relation_panel`) toggles it in memory for the current session only. |

#### `ace.artifacts.stitches`

`ace.artifacts.commits` is a deprecated alias for this block; it still loads and warns.

| Field           | Type | Default                               | Description                                                                                                                                                                                                                                                                                                                                          |
| --------------- | ---- | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `default_query` | str  | `sidecar:false merges:hide since:24h` | Initial persistent Stitches query. Supports one configured project name, directory key, or alias in `project:`; startup may add the current registered project. Accepts `origin:stitch`, `origin:auto`, or `origin:manual`, plus `merges:hide`, `merges:show`, or `merges:only`. Relative windows re-anchor on refresh; changes apply on next start. |

The Stitches pane validates this value with its live query parser. Invalid runtime
configuration produces a warning and falls back to the bundled query. An empty
configured query is valid and includes sidecars; the visible canonical row renders that
state as `sidecar:true merges:hide`. At startup, an explicit project from the ACE query
takes precedence over a `project:` in this setting, which takes precedence over
read-only current registered-project inference. The selected project is merged into the
query before the pane is composed. `project:` is singular and cannot be negated or
contain an unquoted comma list. It accepts a configured project name, ProjectSpec
directory key, or alias, and known committed values are rewritten to the configured
name. Once startup merging is complete, no `project:` token always means a true
all-project collection. The Stitches project picker replaces only that token, and **All
projects** removes it while preserving the rest of the query.

Stitches queries are uncapped unless they contain an explicit positive `limit:N`, so the
bundled 24-hour query has no row cap. When an explicit cap clips the result, ACE keeps
the token visible and shows a lower-bound total such as `[1/40+]` in the repository
legend while the filter row says `capped`. The legend's `[P/N]` form means selected
one-based position over displayed matched entries. `limit:all` is accepted as an
unlimited synonym but is omitted from canonical query text. Day-granular `until:` values
include the full named day. This setting is independent of the `sase stitch list` CLI's
sidecar opt-in and limit contract.

#### `ace.axe_description_expanded`

Sets whether the Axe-tab description panel starts expanded (`true`, the default) or
collapsed to its summary line in each `sase ace` session. The `toggle_axe_description`
keymap action — `d` by default, configurable under `ace.keymaps.app` — flips the state
in memory for the rest of the session; it never writes the toggle back to configuration,
so this key is the only durable setting. Descriptions themselves follow the
[AXE description grammar](axe.md#description-grammar), and the panel's layout, height
budget, and overflow row are described in
[ACE — Description Panel](ace.md#description-panel).

Because the Axe tab claims `d`, the `show_diff` action is active only on the Patches
sub-tab.

#### `ace.agents_sync`

| Field                        | Type   | Default | Description                                                                                   |
| ---------------------------- | ------ | ------- | --------------------------------------------------------------------------------------------- |
| `check_interval_minutes`     | number | `10`    | Interval between cache-and-receipt status reconciliations in a running ACE session.           |
| `recompute_interval_minutes` | number | `30`    | Minimum cadence between status checks that fetch remote refs before recomputing the snapshot. |
| `indicator`                  | bool   | `true`  | Show the top-bar `⇅ N` badge for cached incoming hoods and publication queue diagnostics.     |

Both intervals must be greater than zero. ACE schedules the first check after its
initial paint, coalesces overlapping checks, and keeps the network-fetch cadence
separate from the cheaper cache/receipt reconciliation cadence. Only a remote
recomputation runs Git and refreshes ahead and behind counts; the cheaper pass carries
those diagnostic values forward. Neither value controls the badge. The badge counts
validated incoming hoods from other owners in the immutable incoming cache whose digests
are not covered by import receipts, plus publication queue diagnostics from the same
no-network snapshot. Clicking it imports exactly the displayed cache items without any
fetch, pull, push, export, or sidecar-checkout mutation; publication diagnostics remain
informational. Hiding the indicator also disables the periodic ACE status scheduler, but
it does not disable `sase agent sync`, Updates-pane `a`, commit-triggered publication
queueing, or the `,U` cached-integration leg. See
[Agent Hood Synchronization](agents_sidecar.md).

#### `ace.current_project`

The current project is derived from the head of the VCS xprompt MRU store — the project
you last launched an agent on. `sase project set-current` and the Projects tab perform
the same MRU promotion without a launch.

| Field               | Type | Default | Description                                                                                                                                                                                                                           |
| ------------------- | ---- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `indicator`         | bool | `true`  | Show the `+<project>` chip in the ACE top bar, right of the default-model indicator. Governs the top-bar chip only; the Admin Center [Projects tab](ace.md#projects-tab) always shows the current project regardless of this setting. |
| `seed_filters`      | bool | `true`  | Seed project filters that have no value yet. Never overrides an explicit choice or an already-open surface.                                                                                                                           |
| `seed_agents_query` | bool | `false` | Also seed the Agents-tab search query with the current project's `project:` term.                                                                                                                                                     |

`seed_agents_query` is **off by default** on purpose. The Agents tab is the primary
at-a-glance view, and its search query is also read by unread-jump candidates and
prospective-clan selection — not just the visible list. Turning this on silently
re-scopes those surfaces. The capability is fully built; one line of config enables it.

When `seed_filters` is on, a filter that already has a value — an explicit `project:` /
`+name` query term, or a pick made this session — is left alone. The Patches query is
one of those seeded surfaces: the seed appends a visible `project:<name>` term for the
session only and does not write it to `last_query.txt`. A mid-session MRU change moves
the chip but does not re-scope surfaces that are already open.

#### `ace.tribes`

`ace.tribes` is keyed by bare tribe name (without `@`). The special `default` key
configures the reserved `@default` panel. Every configured tribe entry is **required**
to carry a `description`; the other fields are optional:

| Field                | Type | Default    | Description                                                                                                                                                                                               |
| -------------------- | ---- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `icon`               | str  | `""`       | Short glyph on structured identity surfaces that already include an icon. Set `""` to remove an icon inherited from defaults.                                                                             |
| `color`              | str  | `""`       | `#RRGGBB` foreground for structured tribe icons and names throughout the TUI. Set `""` to restore ACE's gold fallback.                                                                                    |
| `initially_expanded` | bool | `true`     | State applied every time the Agents-tab panel comes into existence.                                                                                                                                       |
| `description`        | str  | _required_ | One-line explanation of the tribe, 1-160 characters. Shown as an unlabeled row beneath the header fields (`Name`/`Status`/`Composition`/`Runtime`/`Fold`) when that tribe's Agents-tab panel is selected. |

The bundled defaults use ⌂ in sky blue for `default`, ▲ in lavender-purple for `epic`,
and † in amber-orange for `chop`. They also use ◆ for `pinned` and ◉ for `review`, whose
identities retain ACE's gold fallback; `chop` starts collapsed. Because config entries
merge deeply, setting `color: ""` explicitly clears an inherited color without replacing
that tribe's other defaults — overriding only `icon` or `color` on a bundled tribe still
inherits its bundled `description`. A manual panel expand/collapse lasts only while that
panel remains live in the current ACE session. On restart, or when a tribe panel
disappears and later returns, `initially_expanded` is applied again.

SASE bundles display config only for the tribes its own source assigns (`default`,
`epic`, `chop`, `pinned`, `review`); a tribe your own xprompts assign with `%tribe:` has
no bundled entry, renders with ACE's gold fallback and no icon until you configure it
under `ace.tribes`, and — once configured — requires a `description` like any other
entry.

A missing or blank `description` on any configured tribe is an error-severity config
diagnostic: the ACE Config Center refuses to write _any_ change while it is present, not
just an edit to that tribe. Run `sase doctor -C config.tribes` to list every tribe
missing a description and the exact `ace.tribes.<name>.description` key to set.

Identity colors apply only where ACE already has a structured tribe value. They do not
scan free-form `@...` text or recolor selection markers, fold controls, counts,
statuses, headings, or explanatory copy. Icons likewise appear only on identity surfaces
that already include them; configuring an icon does not add one to compact name-only
rows.

ACE reads this TUI setting from the user-level `~/.config/sase/sase.yml` (and user
overlays), not project-local `sase/sase.yml`.

#### `ace.notification_tabs`

`ace.notification_tabs` colors, iconifies, and reorders the per-tab counts the top-bar
notification indicator renders, keyed by notification-panel tab key. Keys use the
user-facing tab names: the synthetic `hitl`, `errors`, `general`, `snoozed`, and `muted`
tabs (never the internal `__snoozed__` / `__muted__` spellings), a gate-declared panel
name such as `beads`, or a notification tag.

| Field      | Type | Default | Description                                                                                                                          |
| ---------- | ---- | ------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `color`    | str  | `""`    | `#RRGGBB` foreground for that tab's count chip and its tooltip label. Set `""` to restore the built-in default for the tab.          |
| `icon`     | str  | `""`    | One emoji or display glyph for that tab's chip and tab-strip icon. Set `""` to restore the built-in default for the tab.             |
| `priority` | int  | inherit | Sort weight for that tab in the panel strip and the indicator; higher sorts earlier. Omit to inherit the default for the tab's kind. |

Colors resolve by precedence, highest first: this setting, then a color the sending gate
declared through `presentation.color`, then the built-in default for a tab ACE ships
knowing about, and finally a stable auto-palette entry derived from the tab key. The
last rung means a brand-new tag tab is never colorless and keeps the same color across
restarts. The bundled defaults are amber-orange `hitl`, red `errors`, lavender-purple
`beads`, gold `general`, grey `snoozed`, and teal `muted`.

Icons resolve through the same shape, with one deliberate difference at the last rung:
this setting, then an icon the sending gate declared through `presentation.panel_icon`,
then the built-in default for a tab ACE ships knowing about, then a default keyed by the
tab's own kind (`panel` or `tag`, so an unrecognized panel or tag tab still gets a glyph
that means something about what kind of tab it is), and finally `•` for a tab with no
kind at all. Unlike color, an icon never falls back to a hashed auto-palette entry — an
arbitrary glyph would teach the reader something false, so the chain always bottoms out
at a meaningful or honestly generic mark instead. The bundled defaults are `⚑` `hitl`,
`✖` `errors`, `◈` `beads`, `✉` `general`, `☾` `snoozed`, and `⊘` `muted`.

Configured icons are explicit choices and are never overridden. ACE guarantees
distinctness only for SASE-chosen generic icons from the kind and last-resort rungs: on
collision it derives an unused ASCII letter or digit from the tab key, and if the key is
exhausted it keeps the generic mark rather than inventing one. Run
`sase doctor -C config.notification_tabs` to report two configured tabs that use the
same glyph.

Priority is an integer in `-1000..1000`. Omit the field to inherit the default for the
tab's kind; there is no empty-string reset, because `0` is a legitimate value. Writing
the number you want at a lower config layer is how an override is cancelled. The
defaults restated from the core's tab order are `Gates` (`hitl`) `60`, any declared
panel `50`, `Errors` `40`, `General` `30`, `Done` (a `done` tag) `20`, any other tag
`10`, `Snoozed` `-10`, and `Muted` `-20`. The shipped `beads` default is `0`, which
drops `Beads` below every ordinary tab and above the two put-away tabs. A tab whose
effective priority differs from its default renders a compact `▴` (raised) or `▾`
(lowered) mark in the panel strip and the indicator tooltip.

#### `ace.notification_indicator_max_counts`

Maximum number of per-tab counts the top-bar notification indicator renders before the
remaining tabs collapse into a single dim `+N` chip. Must be at least 1; defaults to
`4`. Suppressed tabs are still described in the indicator's hover tooltip.

#### `ace.page_size`

Integer step used by Ctrl+J (load more) and Ctrl+K (unload) on ACE lists, and the
default Artifacts `limit:` value when a pane has no explicit cap. Must be at least 1;
defaults to `100`. Invalid or missing values fall back to 100. Changing this changes the
chord step and any default query that had no explicit `limit:`; it does not rewrite a
user-authored `limit:40`.

#### `ace.updates`

| Field                                   | Type   | Default | Description                                                                                                                       |
| --------------------------------------- | ------ | ------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `startup_toast`                         | bool   | `true`  | Show the startup toast when cached status reports SASE, plugin, or supported agent-CLI updates.                                   |
| `startup_toast_max_commits`             | int    | `20`    | Maximum total incoming commit subjects shown across all repositories in the startup toast.                                        |
| `post_update_toast`                     | bool   | `true`  | Show a one-shot combined result after an update changes SASE code and restarts ACE.                                               |
| `post_update_toast_diffstat`            | bool   | `true`  | Show per-repository applied file and line-change statistics when available.                                                       |
| `post_update_toast_commits`             | bool   | `true`  | Show applied commits grouped by repository when available.                                                                        |
| `post_update_toast_max_commits`         | int    | `5`     | Maximum applied commit subjects shown per repository; `0` keeps totals but hides subjects.                                        |
| `agent_cli_history`                     | bool   | `true`  | Show the durable update-history panel beneath the selected CLI's details on the Agent CLIs sub-tab.                               |
| `agent_cli_history_max_rows`            | int    | `8`     | Maximum rows in the this-CLI view or runs in the all-CLIs view; `0` shows all history loaded for the pane.                        |
| `indicator`                             | bool   | `true`  | Show the segmented SASE and agent-CLI badge when cached status reports available updates.                                         |
| `prebuild_rust`                         | bool   | `true`  | Prebuild exact-match editable `sase-core` Rust artifacts in the background; update confirmation falls back on every cache miss.   |
| `incoming_commits.enabled`              | bool   | `true`  | Fetch and show incoming commit subjects for SASE core and plugin repositories.                                                    |
| `incoming_commits.max_per_repo`         | int    | `7`     | Maximum incoming commit subjects to show per repository in Updates-tab details.                                                   |
| `incoming_commits.confirm_max_per_repo` | int    | `250`   | Maximum subjects fetched per repository in update confirmations; larger ranges show an explicit `+N more` marker.                 |
| `check_interval_minutes`                | number | `10`    | Interval between local cached-snapshot revalidation attempts in a running ACE session.                                            |
| `check_ttl_minutes`                     | number | `10`    | Minimum age before a startup update check recomputes cached status; this bundled default always wins over the legacy hours key.   |
| `check_ttl_hours`                       | number | unset   | Deprecated and schema-valid, but currently has no effect in a normal merged config because `check_ttl_minutes` is always present. |
| `recompute_interval_minutes`            | number | `60`    | Minimum snapshot age before a full SASE/plugin/agent-CLI network recompute; intervening checks only revalidate locally.           |

Set `check_ttl_minutes` to change the startup cache TTL. Although `check_ttl_hours`
remains accepted for compatibility, ACE resolves the merged `check_ttl_minutes` value
first; the bundled 10-minute default therefore prevents an hours-only override from
taking effect.

#### `ace.keymaps`

All TUI keybindings are configurable. The `keymaps` section has six scopes:

**`gate`** — Bindings active in the shared branch controls used by plan and custom gate
modals, plus the input panel those modals open when a selection needs typed input:

| Field              | Default     | Description                                                            |
| ------------------ | ----------- | ---------------------------------------------------------------------- |
| `next_control`     | `j`         | Focus the next branch control.                                         |
| `previous_control` | `k`         | Focus the previous branch control.                                     |
| `toggle_option`    | `space`     | Toggle the focused option in an AND group.                             |
| `submit_primary`   | `enter`     | Submit the gate's declared primary branch.                             |
| `submit_branch`    | `ctrl+s`    | Submit the currently active branch and feedback.                       |
| `open_inputs`      | `i`         | Open the input panel for the focused option's note or declared fields. |
| `next_input`       | `tab`       | Focus the next field in the gate input panel.                          |
| `previous_input`   | `shift+tab` | Focus the previous field in the gate input panel.                      |

Gate keys are scoped to the active modal and may overlap app-level bindings.
`open_inputs` is bound on the gate modal and opens the panel even when the selection
would otherwise submit immediately, unless the option takes no input. `next_input` and
`previous_input` dispatch only while that panel is open. `activate_control` remains
accepted as a deprecated alias for `submit_primary`.

**`statistics`** — Bindings active only while the Admin Center Statistics pane is
focused. The available actions are:

| Field                          | Default                | Description                                                           |
| ------------------------------ | ---------------------- | --------------------------------------------------------------------- |
| `prev_view`                    | `left_square_bracket`  | Select the previous Statistics view.                                  |
| `next_view`                    | `right_square_bracket` | Select the next Statistics view.                                      |
| `select_view`                  | `0`                    | Arm `1`–`8` selection for a numbered Statistics view.                 |
| `jump_to_entry`                | `apostrophe`           | Arm the same numbered-view selection used by `select_view`.           |
| `cycle_range`                  | `t`                    | Cycle to the next statistics time range.                              |
| `cycle_range_reverse`          | `T`                    | Cycle to the previous statistics time range.                          |
| `custom_range`                 | `c`                    | Enter a custom statistics time range.                                 |
| `cycle_group`                  | `g`                    | Cycle grouping in the Projects, XPrompts, or Perf view.               |
| `cycle_project_filter`         | `p`                    | Cycle forward through All and the latest unfiltered project ranking.  |
| `cycle_project_filter_reverse` | `P`                    | Cycle backward through All and the latest unfiltered project ranking. |
| `focus_xprompt`                | `x`                    | Focus one XPrompt in the XPrompts Statistics view.                    |
| `clear_xprompt_focus`          | `X`                    | Return the XPrompts Statistics view to all XPrompts.                  |
| `scroll_down`                  | `ctrl+d`               | Scroll the Statistics body down by half a page.                       |
| `scroll_up`                    | `ctrl+u`               | Scroll the Statistics body up by half a page.                         |
| `refresh`                      | `r`                    | Refresh the active view from its durable data sources.                |
| `help`                         | `question_mark`        | Open contextual Statistics help; the same key closes it.              |

Statistics keys may overlap app-level bindings because they are registered on the
focused pane, not globally.

**`glossary`** — Bindings active only inside the
[Glossary panel](ace.md#glossary-panel), the browse-and-edit surface opened from a
prompt pane with `gG` or `Ctrl+G G`. A value may list more than one key, separated by
commas:

| Field                      | Default         | Description                                                      |
| -------------------------- | --------------- | ---------------------------------------------------------------- |
| `next_term`                | `j`             | Move the term-list cursor to the next term.                      |
| `prev_term`                | `k`             | Move the term-list cursor to the previous term.                  |
| `first_term`               | `g`             | Jump to the first term.                                          |
| `last_term`                | `G`             | Jump to the last term.                                           |
| `scroll_definition_down`   | `ctrl+d`        | Scroll the definition card down by half a page.                  |
| `scroll_definition_up`     | `ctrl+u`        | Scroll the definition card up by half a page.                    |
| `filter_terms`             | `slash`         | Filter terms and aliases.                                        |
| `toggle_definition_filter` | `full_stop`     | Extend the active filter into definition bodies.                 |
| `next_relation`            | `tab`           | Focus the next `SEE ALSO` / `REFERENCED BY` chip.                |
| `prev_relation`            | `shift+tab`     | Focus the previous relation chip.                                |
| `follow_relation`          | `enter,l`       | Travel to the focused chip's term (or chip ① when none focused). |
| `travel_back`              | `backspace,h`   | Walk back one step along the travel trail.                       |
| `next_project`             | `p`             | Cycle forward through the enabled-project ring.                  |
| `prev_project`             | `P`             | Cycle backward through the enabled-project ring.                 |
| `add_term`                 | `a`             | Open the add-term form.                                          |
| `delete_term`              | `d`             | Confirm and delete the selected term.                            |
| `open_source`              | `o`             | Open the definition's source line in `$EDITOR`.                  |
| `open_viewer`              | `Z`             | Hand the source file to the artifact viewer.                     |
| `copy_definition`          | `y`             | Copy the definition to the clipboard.                            |
| `copy_source_path`         | `Y`             | Copy the source path to the clipboard.                           |
| `refresh`                  | `r`             | Re-read the current project's glossary.                          |
| `help`                     | `question_mark` | Open the panel-scoped help overlay.                              |

Like gate and statistics keys, glossary keys are scoped to the panel and may overlap
app-level bindings.

**`memory`** — Bindings active only inside the [Memory panel](ace.md#memory-panel), the
browse-and-edit surface opened from a prompt pane with `gm` or `Ctrl+G m`. A value may
list more than one key, separated by commas:

| Field                | Default         | Description                                                         |
| -------------------- | --------------- | ------------------------------------------------------------------- |
| `next_note`          | `j`             | Move the note rail cursor to the next note.                         |
| `prev_note`          | `k`             | Move the note rail cursor to the previous note.                     |
| `first_note`         | `g`             | Jump to the first note.                                             |
| `last_note`          | `G`             | Jump to the last note.                                              |
| `scroll_body_down`   | `ctrl+d`        | Scroll the note card down by half a page.                           |
| `scroll_body_up`     | `ctrl+u`        | Scroll the note card up by half a page.                             |
| `filter_notes`       | `slash`         | Filter notes by stem and description.                               |
| `toggle_body_filter` | `full_stop`     | Extend the active filter into note bodies.                          |
| `next_link`          | `tab`           | Focus the next `PARENT` / `CHILDREN` chip.                          |
| `prev_link`          | `shift+tab`     | Focus the previous link chip.                                       |
| `follow_link`        | `enter,l`       | Travel to the focused chip's note (or chip ① when none focused).    |
| `travel_back`        | `backspace,h`   | Walk back one step along the travel trail.                          |
| `next_scope`         | `p`             | Cycle forward through the memory scope ring.                        |
| `prev_scope`         | `P`             | Cycle backward through the memory scope ring.                       |
| `pick_scope`         | `ctrl+p`        | Open the filterable scope picker.                                   |
| `add_note`           | `a`             | Open the add-note form.                                             |
| `edit_note`          | `e`             | Open the edit form for the selected note's type/parent/description. |
| `delete_note`        | `d`             | Confirm and delete the selected note.                               |
| `publish`            | `I`             | Open the publish confirmation (`sase memory init`).                 |
| `open_source`        | `o`             | Open the note body in `$EDITOR`.                                    |
| `open_viewer`        | `Z`             | Hand the source file to the artifact viewer.                        |
| `copy_body`          | `y`             | Copy the note body to the clipboard.                                |
| `copy_source_path`   | `Y`             | Copy the source path to the clipboard.                              |
| `refresh`            | `r`             | Re-read the current scope.                                          |
| `help`               | `question_mark` | Open the panel-scoped help overlay.                                 |

Like gate, statistics, and glossary keys, memory keys are scoped to the panel and may
overlap app-level bindings.

**`projects`** — Bindings active on all three Admin Center
[Projects-tab](ace.md#projects-tab) sub-tabs (Projects, Repos, Workspaces), so
`focus_filter`, `jump_to_entry`, `reload`, and the sub-tab cycle keys stay identical
across the three rather than configuring the list separately from the inventories. A
value may list more than one key, separated by commas:

| Field                        | Default                | Description                                                        |
| ---------------------------- | ---------------------- | ------------------------------------------------------------------ |
| `next_option`                | `j,down,ctrl+n`        | Move selection to the next row.                                    |
| `prev_option`                | `k,up,ctrl+p`          | Move selection to the previous row.                                |
| `focus_filter`               | `slash`                | Filter the active sub-tab.                                         |
| `cycle_subtab`               | `right_square_bracket` | Cycle to the next sub-tab (Projects, Repos, Workspaces).           |
| `cycle_subtab_reverse`       | `left_square_bracket`  | Cycle to the previous sub-tab.                                     |
| `toggle_project_mark`        | `m`                    | Toggle the mark on the highlighted project.                        |
| `clear_project_marks`        | `u`                    | Clear all marks.                                                   |
| `edit_project_spec`          | `e`                    | Edit the highlighted project's ProjectSpec in `$EDITOR`.           |
| `edit_project_aliases`       | `A`                    | Edit the highlighted project's aliases.                            |
| `enable_project`             | `a`                    | Enable the highlighted project or marked set.                      |
| `disable_project`            | `d`                    | Disable the highlighted project or marked set.                     |
| `delete_project`             | `ctrl+d`               | Delete the highlighted or marked SASE project directories.         |
| `force_current_state_change` | `F`                    | Force the last blocked disable after confirming live-work checks.  |
| `default_project_action`     | `enter`                | Run the highlighted project's default lifecycle action.            |
| `reload`                     | `R`                    | Reload records or the current inventory.                           |
| `show_project_repos`         | `r`                    | Show repos pre-filtered to the highlighted project.                |
| `show_project_workspaces`    | `w`                    | Show workspaces pre-filtered to the highlighted project.           |
| `jump_to_entry`              | `apostrophe`           | Jump to a row via adaptive hints, within the active sub-tab only.  |
| `pick_project`               | `p`                    | Open the shared project picker on the Repos or Workspaces sub-tab. |
| `clear_project_filter`       | `escape`               | Clear an inventory project filter.                                 |
| `set_current_project`        | `c`                    | Make the highlighted project [current](ace.md#current-project).    |

Like gate, statistics, and glossary keys, Projects-tab keys are scoped to the pane and
may overlap app-level bindings.

**`app`** — App-level keybindings. Each key is an action name mapped to a key string.
See `src/sase/default_config.yml` for the full list of configurable actions and their
defaults. Rebinding `open_config_center` also changes the Admin Center's home-page
resume key; it does not add a second keymap action or setting.

The Artifacts split actions are remappable as `cycle_artifacts_split` and
`cycle_artifacts_split_reverse`. Their defaults use `right_curly_bracket` (`}`) and
`left_curly_bracket` (`{`); both curly-bracket key names are accepted anywhere an ACE
keybinding is configured.

**`modes`** — Prefix-key mode definitions. Built-in modes (`fold_mode`, `copy_mode`,
`leader_mode`, `bang_mode`) can be reconfigured, and custom modes can be added. Each
mode has:

| Field    | Type | Description                                                                                           |
| -------- | ---- | ----------------------------------------------------------------------------------------------------- |
| `prefix` | str  | The activation key for the mode.                                                                      |
| `keys`   | dict | Sub-key definitions. For custom modes, each entry needs a `key` field and either `shell` or `action`. |

The built-in `fold_mode` direct actions are `set_level_1` through `set_level_3` for PR
details and the nested `agents.set_level_1` through `agents.set_level_4` for Agents
metadata. Their defaults produce `z1`-`z3` on PRs; Agents accepts levels 1-2 for a
family, 1-3 for a clan or regular-agent session scope, and 1-4 for a selected whole
tribe panel. The configured prefix and subkeys are used by dispatch, the command
palette, footers, and help.

Query editing has two contextual scopes. `ace.keymaps.app.edit_query` controls Patches,
Stitches, Plans, and Axe and defaults to bare `/`.
`ace.keymaps.modes.leader_mode.keys.edit_query` independently controls the Agents
structured-query chord and defaults to `,/`; bare `/` on Agents starts inline metadata
search. Help is an app-level action controlled by `ace.keymaps.app.show_help` and
defaults to bare `?`; the retired `leader_mode.keys.show_help` override is dropped at
load time.

A small allowlist of app actions intentionally shares a key because the two actions can
never be available on the same surface. Validation permits exactly these pairs and
rejects every other duplicate app binding:

| Shared key (default) | Spelled in YAML as | Pair                                                   | Disjoint because                                       |
| -------------------- | ------------------ | ------------------------------------------------------ | ------------------------------------------------------ |
| `/`                  | `slash`            | `edit_query` / `search_forward`                        | query editing excludes Agents; search is Agents-only   |
| `a`                  | `a`                | `add_axe_item` / `open_artifact_files`                 | Axe vs Artifacts                                       |
| `d`                  | `d`                | `show_diff` / `toggle_axe_description`                 | Patches vs Axe                                         |
| `L`                  | `L`                | `beads_open_plan` / `plans_open_bead`                  | Beads vs Plans panes                                   |
| `E`                  | `E`                | `beads_open_bug` / `files_open_external`               | Beads vs Files panes (the shared open-externally verb) |
| `.`                  | `full_stop`        | `toggle_relation_panel` / `toggle_hide_reverted`       | Artifacts vs Agents/Axe                                |
| `X`                  | `X`                | `open_agent_cleanup_panel` / `patches_toggle_reverted` | Agents vs Patches                                      |

The first column is what the key looks like on your keyboard; the second is the name to
write in `sase.yml`, matching how `src/sase/default_config.yml` spells it. Punctuation
keys generally use their long name (`slash`, `full_stop`, `question_mark`), the same
convention as the curly-bracket names described above.

The allowlist is keyed by action pair, not by key, so moving one of these actions onto a
different key keeps the exemption, and pointing a third action at a shared key does not
gain it. Only actions you overrode are checked: an override that collides with any
action outside its allowed pair is logged as a duplicate and reverted to that action's
default, leaving the rest of your keymap in place.

`ace.keymaps.app.start_saved_query_mode` (default `0`) arms direct saved-PR-query slot
selection: press it, then a slot digit (`1`-`9`, then `0`) to load that slot. Its digit
sub-keys are not configurable -- they are the slot identifiers themselves, the same way
`start_checkout_mode`'s `1`-`9` workspace digits aren't. The prefix is scoped to the
Artifacts tab (any sub-tab); it does not arm on Agents or Axe.

Custom mode key fields:

| Field    | Type | Required | Description                            |
| -------- | ---- | -------- | -------------------------------------- |
| `key`    | str  | yes      | The sub-key to press after the prefix. |
| `shell`  | str  | no\*     | Shell command to execute.              |
| `action` | str  | no\*     | Built-in action name to invoke.        |

\*Exactly one of `shell` or `action` must be provided.

The keymap loader validates configuration: invalid keys are reverted to defaults,
duplicate bindings within a scope are warned, and prefix conflicts between custom modes
and app bindings are detected.

Source: `src/sase/default_config.yml`, `src/sase/ace/tui/keymaps/`

#### `ace.snippet_config_path`

Names the config file that receives new `ace.snippets` entries written from the prompt
bar — both the `gt` / `Ctrl+G t` snippet target pane and the `gx` / `Ctrl+G x` save
panel's snippet mode default to it.

An empty string (the default) resolves to the user's `sase.yml` — the chezmoi source
file under `dot_config/sase/` when [`use_chezmoi`](#use_chezmoi) is enabled, otherwise
`~/.config/sase/sase.yml`. A relative configured value resolves against
`~/.config/sase/`, so `sase_snippets.yml` means `~/.config/sase/sase_snippets.yml`. The
path's suffix must be `.yml` or `.yaml`; the file itself need not exist yet, but its
parent directory must be writable.

A configured value that is unusable — wrong suffix, unwritable parent, invalid YAML, or
a project `sase/sase.yml` that still needs its legacy migration — falls back to the
default and reports why: both the `gt` trigger-name panel and the `gx` save panel's
snippet mode append the reason to the destination line (e.g.
`configured path unusable: read-only`) rather than silently writing somewhere else. The
`gx` panel additionally always offers the resolved `ace.snippet_config_path` destination
as a selectable, pre-highlighted row — even when it is a custom filename or path that
falls outside the standard discovered locations (`sase.yml` / `sase_*.yml` under
`~/.config/sase/` or the chezmoi equivalent, and the project's `sase/sase.yml`) — so a
configured preference is never silently dropped from the picker.

```yaml
ace:
  snippet_config_path: "sase_snippets.yml"
```

See
[docs/ace.md — Authoring a snippet from the prompt bar](ace.md#authoring-a-snippet-from-the-prompt-bar).

Source: `src/sase/xprompt/snippet_targets.py`

#### `ace.snippets`

Defines expandable text snippets for the prompt input widget. Each entry maps a trigger
word to a template string. Press `Tab` in the prompt input to expand the trigger word
before the cursor.

```yaml
ace:
  snippets:
    fix: "Please fix the following issue:\n$0"
    review: "Review this code for correctness, performance, and style."
    plan: "#plan\n$0"
```

Templates can contain `$1`, `$2`, ... tabstops plus `$0` for the final cursor position.
In the ACE prompt input, `Tab` advances through those stops and `Shift+Tab` retreats
through stops already visited. Expanding a trigger inside an active snippet nests the
new snippet's tabstops before the remaining outer stops. Templates can also splice
another merged snippet with `#[trigger]`; use `#[trigger(value)]` or `#[trigger:value]`
to fill referenced `$1`, `$2`, ... tabstops before splicing.

Every effective snippet also gains a generated initial-capital alias: only the first
character of the trigger and of the resolved template is uppercased, so
`foo: "foo bar baz"` also exposes `Foo` → `Foo bar baz`. Already-capitalized,
digit-leading, and underscore-leading triggers produce no extra entry, and an explicitly
authored `Foo` is never replaced. These aliases are runtime-only and are never written
back into config. See [docs/ace.md — Capitalized aliases](ace.md#capitalized-aliases)
for the full rule.

See [docs/ace.md — Snippets](ace.md#snippets) for usage details.

Source: `src/sase/ace/tui/widgets/prompt_text_area.py`

#### `ace.prompt_completion`

Controls automatic non-disruptive suggestions and manual prompt-local and prompt-history
word completion in the ACE prompt input. Suggestions appear in the prompt-bar subtitle
and are accepted with `Ctrl+L`; `Enter` still submits the prompt as typed. Manual
structured/path `Ctrl+T` completion is independent of the automatic settings, and the
`Ctrl+R` recursive fuzzy file finder is always manual.

```yaml
ace:
  prompt_completion:
    auto: soft
    debounce_ms: 90
    auto_file_paths: false
    auto_xprompt_menu: true
    auto_directive_menu: true
    auto_artifact_menu: true
    max_auto_rows: 1
    history_word_count: 10000
    common_placeholder_count: 100
    word_min_length: 5
    word_ranking: smart
    word_ranking_signals: true
    placeholder_ranking: smart
    placeholder_ranking_signals: true
```

| Field                         | Type        | Default | Description                                                                                                                       |
| ----------------------------- | ----------- | ------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `auto`                        | bool/string | `soft`  | Automatic mode. `soft`, `true`, `on`, `yes`, or `1` enable subtitle suggestions; false/off disables them.                         |
| `debounce_ms`                 | int         | `90`    | Delay before computing a live suggestion after text or cursor changes.                                                            |
| `auto_file_paths`             | bool        | `false` | Allow live suggestions to scan file-path candidates. Manual `Ctrl+T` file completion still works when false.                      |
| `auto_xprompt_menu`           | bool        | `true`  | Automatically open the xprompt/skill completion menu while typing matching `#name`, `#!name`, or `/skill` tokens.                 |
| `auto_directive_menu`         | bool        | `true`  | Automatically open directive completion while typing `%id` tokens and fixed values such as `%model:`.                             |
| `auto_artifact_menu`          | bool        | `true`  | Automatically open the grouped `@` reference menu from bare `@`, narrowed path/kind queries, or `@kind:` payloads.                |
| `max_auto_rows`               | int         | `1`     | Reserved row limit for automatic completion modes; current soft mode shows one suggestion.                                        |
| `history_word_count`          | int         | `10000` | Maximum unique recent prompt-history words retained for manual completion; `0` disables the history fallback.                     |
| `common_placeholder_count`    | int         | `100`   | Maximum saved `<placeholder>` tags retained and offered after prompt-local placeholder matches; `0` disables them.                |
| `word_min_length`             | int         | `5`     | Shared minimum length for prompt-local and prompt-history word candidates; values below `1` clamp to `1`.                         |
| `word_ranking`                | string      | `smart` | History-word ordering. `smart` ranks by relation, recency, and frequency; `recent` restores plain most-recently-used order.       |
| `word_ranking_signals`        | bool        | `true`  | Whether smart-ranked history-word rows render the score meter, dominant-reason chip, and panel legend.                            |
| `placeholder_ranking`         | string      | `smart` | Saved-placeholder ordering. `smart` ranks by relation, recency, and frequency; `recent` restores stored count-then-recency order. |
| `placeholder_ranking_signals` | bool        | `true`  | Whether smart-ranked saved-placeholder rows render the score meter, dominant-reason chip, and panel legend.                       |

The minimum applies to the complete candidate, so a shorter typed prefix can still
complete an eligible word. Prompt-local words below the threshold are skipped before ACE
considers the prompt-history fallback. Candidates from history retain their original
spelling and, under the default `word_ranking: smart`, are ordered by a weighted
composite of how strongly each word relates to the words already in the prompt (`0.50`),
how recently it was used (`0.30`), and how often it was used (`0.20`). Setting
`word_ranking: recent` restores plain most-recently-used order. The warm cache holds the
prompt-word index off-thread and is rebuilt when history shards or the shared minimum
change, while `Ctrl+D` deletions apply at query time without a rebuild. Setting
`history_word_count: 0` disables only the history fallback; eligible prompt-local words
remain available. See the History-word completion bullet in `docs/ace.md` for the score
meter, reason chip, and legend that `word_ranking_signals` controls.

Common placeholders are stored at `sase_home()/prompt_placeholders.json` and are learned
from complete raw `<foobar>` tags outside literal zones in submitted, failed-launch, and
cancelled prompt drafts. When the store is first created, ACE seeds it once from bounded
prompt history so existing tags can appear immediately. Retention evicts
least-recently-used entries down to `common_placeholder_count`. By default
(`placeholder_ranking: smart`) the `<` menu ranks saved tags by relation to the prompt
being edited, recency, and frequency; `placeholder_ranking: recent` restores the stored
count-then-recency order. Setting `common_placeholder_count: 0` disables recording,
loading, and display of saved placeholders; prompt-local placeholder completion still
works.

The former `history_word_min_length` key has been replaced by `word_min_length`.
Existing overrides must rename the key to keep controlling word completion.

The `+query` project/Patch picker uses the same completion panel and opens when the plus
is at absolute prompt offset zero or immediately follows a literal ASCII space. It is
not disabled by `auto_xprompt_menu`. Manual `Ctrl+T` project/Patch completion uses the
same token rule and works regardless of these automatic-completion settings.

`@` reference completion uses a project-scoped artifact catalog and warm prompt path
inventory. `auto_artifact_menu` controls automatic opening of the grouped menu from bare
`@`, narrowed artifact-kind or local-path queries such as `@pl` and `@src/`, and
`@kind:` payload contexts; manual `Ctrl+T` remains available. Before a `:` appears,
local file rows stay hidden while the query prefix-matches an artifact kind (including
bare `@`). The panel's `[^T] files` hint marks that state; the first `Ctrl+T` reveals
files without completing the kind, and a later press completes normally. Queries with no
kind prefix match show file rows automatically. File rows preserve the `@` sigil on
insertion, directories drill down, and dotfiles are hidden unless the typed path segment
starts with `.`. A cold path inventory can briefly show a loading row while ACE
refreshes it off-thread. Document, chat, indexed-file, bead, and agent payloads use
bounded project-scoped catalogs; commit and bug candidates are projected only from
already-loaded Artifacts-pane snapshots.

The `%model:` / `%m:` value menu is also controlled by `auto_directive_menu`. It lists
inline-typable model names, the five built-in size aliases (`@xsmall`, `@small`,
`@medium`, `@large`, `@xlarge`), and configured model aliases; provider short aliases
are shown as filter/display hints but are not inserted.

File-path completion roots relative lookups in the prompt-selected workspace. Registered
workspace-provider refs and known-project refs such as `#git:<project>` or
`#gh:<owner>/<repo>` can root lookup in that project checkout. If no prompt workspace
ref resolves, lookups fall back to the TUI process directory. These root rules are
shared by live path suggestions, manual `Ctrl+T` path completion, and the manual
`Ctrl+R` recursive finder.

Source: `src/sase/ace/tui/widgets/prompt_completion.py`,
`src/sase/ace/tui/widgets/_prompt_soft_completion.py`,
`src/sase/ace/tui/widgets/history_word_completion.py`,
`src/sase/history/prompt_word_index.py`, `src/sase/history/prompt_word_ranking.py`,
`src/sase/history/prompt_placeholders.py`,
`src/sase/ace/tui/widgets/prompt_completion_root.py`,
`src/sase/ace/tui/widgets/recursive_file_finder.py`

#### `ace.prompt_spellcheck`

Controls the sticky misspelling highlight in the ACE prompt input. Every word `K` proves
misspelled (an aspell `misspelled` verdict) is remembered durably and underlined in
every prompt input from then on; `K` on a word already remembered is what teaches ACE
about it, not a background spell-checker.

```yaml
ace:
  prompt_spellcheck:
    highlight: true
    max_remembered_words: 5000
```

| Field                  | Type | Default | Description                                                                                                            |
| ---------------------- | ---- | ------- | ---------------------------------------------------------------------------------------------------------------------- |
| `highlight`            | bool | `true`  | Whether remembered misspellings are underlined in prompt inputs. `K` still records and clears misspellings when false. |
| `max_remembered_words` | int  | `5000`  | Maximum words retained in each of the misspelled and accepted-word lists; `0` disables remembering new misspellings.   |

Remembered words are stored at `sase_home()/prompt_misspellings.json`, casefolded for
matching but keeping the first-seen spelling. Pressing `a` in the correction panel
accepts a word instead of applying a suggestion, moving it into the accepted list so it
is never flagged again; `K` on an already-correct remembered word (for example, after
adding it to your `aspell` personal dictionary) clears it automatically. Retention
evicts the oldest entries once a list exceeds `max_remembered_words`.

Source: `src/sase/history/prompt_misspellings.py`, `src/sase/core/word_lookup.py`,
`src/sase/ace/tui/widgets/_misspelling_highlight.py`,
`src/sase/ace/tui/actions/_startup_misspellings.py`,
`src/sase/ace/tui/modals/spellcheck_panel_modal.py`

#### `ace.prompt_inputs`

Controls how ACE treats raw `<placeholder>` tags when a prompt is submitted or saved as
an xprompt.

```yaml
ace:
  prompt_inputs:
    collect_raw_placeholders: true
    xprompt_placeholder_args: true
```

| Field                      | Type | Default | Current behavior                                                                                                                                                                  |
| -------------------------- | ---- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `collect_raw_placeholders` | bool | `true`  | When true, submitting an ACE prompt opens **Fill in this prompt** for each live raw placeholder. When false, raw tags launch unchanged; declared `input:` collection still works. |
| `xprompt_placeholder_args` | bool | `true`  | When false, `gx` and `gX` keep live raw tags as literal text and mint no placeholder-derived `text` inputs. Jinja-variable input inference for `gX` is unaffected.                |

Raw placeholders in YAML frontmatter, inline code, fenced code, or
`%xprompts_enabled:false` regions are never collected. See
[Raw Prompt Placeholders](xprompt.md#raw-prompt-placeholders) for the submit panel,
literal-tag control, and xprompt conversion workflow.

Source: `src/sase/agent/prompt_placeholder_inputs.py`,
`src/sase/ace/tui/actions/agent_workflow/_launch_start.py`,
`src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py`,
`src/sase/ace/tui/widgets/_prompt_input_bar_local_xprompt_actions.py`,
`src/sase/ace/tui/widgets/_local_xprompt_conversion.py`

### artifacts

Bounds on automatic artifact capture at agent finalization, and the opt-in retention
policy that bounds the store afterwards. Capture keeps bytes only for files a run
authored that version control cannot reproduce; content already reachable from a durable
commit becomes a byte-free reference row. See
[VCS-Backed Artifact Files](agent_images.md#vcs-backed-artifact-files) for the decision
matrix and the `vcs-cache` directory, and
[Store Lifecycle](agent_images.md#store-lifecycle) for the report → dry run → opt-in
retention progression that `artifacts.retention` completes.

```yaml
artifacts:
  capture:
    max_stored_per_agent: 50
    max_history_scan: 20
    max_file_size_bytes: 104857600
    pool_max_bytes: 1073741824
```

| Field                                    | Type | Default      | Minimum | Description                                                                                                                  |
| ---------------------------------------- | ---- | ------------ | ------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `artifacts.capture.max_stored_per_agent` | int  | `50`         | `1`     | Maximum byte-copying automatic captures per agent run. Reference rows cost no bytes, are uncounted, and uncapped.            |
| `artifacts.capture.max_history_scan`     | int  | `20`         | `1`     | Durable commits searched per file when looking for one holding its exact content.                                            |
| `artifacts.capture.max_file_size_bytes`  | int  | `104857600`  | `1`     | Maximum size of one file copied into the workspace-local prompt-artifact pool; larger files are hashed and recorded instead. |
| `artifacts.capture.pool_max_bytes`       | int  | `1073741824` | `1`     | Workspace-local prompt-artifact pool budget before opportunistic garbage collection removes published terminal-run copies.   |

These fields are read fail-open: a missing, non-integer, or out-of-range value falls
back to the built-in default rather than failing capture. Once `max_stored_per_agent` is
reached, the remaining byte-copy candidates are skipped and finalization reports
`cap_fired=true` on its `[artifacts] default capture:` summary line. Raising
`max_history_scan` widens the bounded search that recovers content whose recorded commit
was squash-rewritten, at the cost of a longer walk per file.

`max_file_size_bytes` and `pool_max_bytes` apply to launch-time prompt-artifact staging
under the workspace-local `.sase/artifacts/` tree. The local manifest still records
oversized files, but SASE does not copy their bytes into `.sase/artifacts/pool/`. See
[Prompt Artifact Staging and Archive](agent_images.md#prompt-artifact-staging-and-archive)
for the layout and garbage-collection rules.

`artifacts.retention` is the opt-in policy that runs once after each agent finalization,
immediately after automatic capture. It ships disabled with generous values pre-filled,
so enabling it later is a flag flip rather than a policy design exercise.

```yaml
artifacts:
  retention:
    enabled: false
    keep_per_label: 3
    max_age_days: 90
    trash_grace_days: 14
```

| Field                                  | Type | Default | Minimum | Description                                                                                                |
| -------------------------------------- | ---- | ------- | ------- | ---------------------------------------------------------------------------------------------------------- |
| `artifacts.retention.enabled`          | bool | `false` | -       | Run the retention pass after agent finalization. While `false`, retention removes nothing at all.          |
| `artifacts.retention.keep_per_label`   | int  | `3`     | `0`     | Newest automatic captures kept per label; older generations are trashed first. `0` disables the predicate. |
| `artifacts.retention.max_age_days`     | int  | `90`    | `0`     | Trash automatic captures created more than this many days ago. `0` disables the predicate.                 |
| `artifacts.retention.trash_grace_days` | int  | `14`    | `0`     | Days a trashed artifact stays restorable before a purge removes it.                                        |

These fields are read fail-open the same way the capture fields are. The pass is bounded
and defensive: it never fails a run, and it removes nothing that retention's protection
contract keeps — explicit artifacts, artifacts referenced by a ProjectSpec, plan, bead,
or research document, artifacts recorded in the consumption ledger, and the newest
capture of every label. If any required protection source cannot be read, the whole pass
is skipped rather than under-protecting, and finalization prints
`[artifacts] retention skipped: protection sources unavailable: <sources>`. Otherwise it
prints one `[artifacts] retention:` line with rows trashed, bytes reclaimed, and trash
entries purged.

The same values drive the manual surfaces, so a dry run previews exactly what enabling
retention would do: `keep_per_label` is what `sase artifact prune` plans with when `-g`
is omitted, both predicates define the default-policy selection `sase artifact stats`
reports last, and `trash_grace_days` is the cutoff `sase artifact trash purge` honors
without `-a/--all` and the one `trash list` marks entries against. Setting both
predicates to `0` leaves a policy that selects nothing.

Source: `src/sase/config/core.py`, `src/sase/core/artifact_capture_policy.py`,
`src/sase/core/artifact_file_retention.py`, `src/sase/axe/run_agent_exec_finalize.py`

### artifact_refs

Allow-lists path-backed `@file:<path>` prompt references. Indexed
`@file:default:<digest>` and `@file:explicit:<digest>` references do not need these
roots; this section controls only references authored as absolute or `~/` paths.

```yaml
artifact_refs:
  file:
    roots:
      - name: notes
        path: ~/notes
        path_globs: ["**/*.md", "!private/**"]
      - name: reports
        path: /srv/reports
```

| Field                                   | Type         | Required | Description                                                 |
| --------------------------------------- | ------------ | -------- | ----------------------------------------------------------- |
| `artifact_refs.file.roots[].name`       | string       | yes      | Stable lowercase slug used in published logical identities. |
| `artifact_refs.file.roots[].path`       | string       | yes      | Absolute or `~/`-rooted allow-list directory.               |
| `artifact_refs.file.roots[].path_globs` | list[string] | no       | Root-relative POSIX includes and `!`-prefixed exclusions.   |

Root lists concatenate across ordinary config layers. A layer using the global
list-replacement merge strategy replaces the inherited list instead. When the same
`name` appears more than once, the later root overrides the earlier definition without
changing its position. Invalid entries are skipped with a warning rather than disabling
all usable roots.

Resolution accepts existing regular files only, requires the path to stay within an
effective root and its glob policy, and never interprets relative paths against the
current directory. At launch SASE snapshots accepted bytes into the workspace-local
artifact pool, so subsequent changes to the source file do not change the agent's
captured input. The normal `artifacts.capture.max_file_size_bytes` limit applies.

Run `sase doctor -C config.artifact_refs` to find malformed, missing, nested,
overlapping, or zero-usable-root configurations. See
[Artifact References](artifact_references.md) for prompt syntax and context rules.

### llm_provider

Configures which LLM backend sase uses and how model tiers map to concrete models. See
[docs/llms.md](llms.md) for the full LLM provider architecture, preprocessing pipeline,
and invocation lifecycle.

```yaml
llm_provider:
  provider: claude # or "codex", "qwen", "opencode", "agy", "muse", "grok", "fakey" (default: auto-detect)
  model_tier_map:
    large: opus
    small: sonnet
  # Scalar launch settings. Same grammar as %model; may reference a built-in
  # size alias.
  default_model: "@large" # used when a launch has no %model directive
  epic_lander_model: "@large" # epic land agents below bead.big_epic_phase_threshold
  big_epic_lander_model: "@xlarge" # epic land agents at/above that threshold
  model_alias_history_limit: 10 # runs shown per alias in Launch Control history
  # Override examples; shipped size-alias defaults are generated in docs/llms.md.
  model_aliases:
    builtin:
      medium: codex/gpt-5.6-sol # specialize the medium size alias
      large: claude/opus | codex/gpt-5.6-sol # custom large-phase pool
    custom:
      blogger:
        model: claude/opus
        description: Agents that draft and edit blog posts.
        bucket: writing # optional Launch Control grouping
    buckets:
      writing:
        description: Writing and editing roles.
```

| Field                                    | Type   | Default     | Description                                                                                                                                                                                                                       |
| ---------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm_provider.provider`                  | string | auto-detect | Which registered provider to use. Auto-detects by plugin-declared priority; built-ins default to claude → codex → qwen → opencode → agy. `muse` and `grok` declare no priority and are never auto-detected; name them explicitly. |
| `llm_provider.model_tier_map.large`      | string | -           | Model identifier for the `large` tier.                                                                                                                                                                                            |
| `llm_provider.model_tier_map.small`      | string | -           | Model identifier for the `small` tier.                                                                                                                                                                                            |
| `llm_provider.default_model`             | string | `@large`    | Model expression used when a launch has no explicit `%model` directive.                                                                                                                                                           |
| `llm_provider.epic_lander_model`         | string | `@large`    | Model expression used by epic land agents when the epic has fewer authored phases than `bead.big_epic_phase_threshold`.                                                                                                           |
| `llm_provider.big_epic_lander_model`     | string | `@xlarge`   | Model expression used by epic land agents when the epic has `bead.big_epic_phase_threshold` or more authored phases.                                                                                                              |
| `llm_provider.model_alias_history_limit` | int    | `10`        | Maximum prior runs returned per alias for the Launch Control agent-history panel. Must be at least `1`; malformed runtime values defensively fall back to `10`.                                                                   |
| `llm_provider.model_aliases.builtin`     | dict   | -           | Overrides for the five built-in size aliases (`xsmall`, `small`, `medium`, `large`, `xlarge`). Values use the single-target grammar, `\|` round-robin pools, `\|\|` ordered fallbacks, or `(A \| B) \|\| C` last-resort.          |
| `llm_provider.model_aliases.custom`      | dict   | -           | User-defined aliases usable from `%model:@<alias>` / `%m:@<alias>`. Each requires `model` (single target or selector) and `description`.                                                                                          |
| `llm_provider.model_aliases.buckets`     | dict   | -           | Optional display-only ACE Launch Control bucket descriptions.                                                                                                                                                                     |

Model aliases are resolved when an agent launches, so reusable xprompts can point at
names such as `%model:@medium` or `%model:@blogger` while each user's `sase.yml`
controls the concrete provider/model. Alias config keys stay bare; the `@` marker is
only used in `%model`/`%m` directive values. Alias values may reference another alias
with `@<alias>`; the reference may carry a trailing effort such as `@medium@high`, which
overrides the referenced alias's effort (chains are followed with cycle/depth
protection). Unknown non-alias model values keep the existing fallback behavior and run
on the default provider. Use `model_aliases.builtin` to override one of the five
built-in size aliases and `model_aliases.custom` for user-defined aliases with
descriptions. `A | B` round-robins across real launches, skips providers whose CLI is
unavailable, and stores its machine-global cursor in `~/.sase/llm_lb.json`; display and
preview surfaces only peek. `A || B` always selects the first installed provider CLI
that is not **hard**-disabled (a **soft**-disabled first candidate still wins) and never
reads or advances that cursor. `(A | B) || C` load-balances the parenthesized pool and
uses the `||` tail only when every pool member is unavailable (CLI missing or
**hard**-disabled); an all-**soft** pool still rotates and does not divert, and tail
selection does not consume the pool cursor. Unparenthesized mixing is still rejected.
Ordered fallback is based on CLI installation plus temporary provider-disable state, not
later model/runtime success, and preserves its first candidate for normal diagnostics
when none are available. Members may carry a trailing effort. Selectors cannot be
nested, and selectors are not accepted in `%model` directives or launch-scoped/temporary
overrides. In ACE Launch Control, the pool row reports the available/total count,
selector member lists mark the current selection with `→`, and active temporary
overrides label selection suspended unless their provider is **hard**-disabled; then the
override is paused and the underlying alias resolves. A **soft** disable does not pause
the override.

On top of any configured aliases, SASE ships a fixed set of **built-in size aliases**
that resolve even when unset: `@xsmall`, `@small`, `@medium`, `@large`, and `@xlarge`.
Each is a direct selector with no fallback chain to another alias — override one by
setting `model_aliases.builtin.<size>` to a concrete model, an `A | B` round-robin pool,
an `A || B` ordered fallback, or a parenthesized `(A | B) || C` last-resort. Phase and
task launches route directly to the size alias matching their size metadata; a legacy
phase or task with no size metadata routes through `@small`. New tasks require an
explicit size after `/sase_new_task` has ruled out a semantic duplicate and a causally
related in-progress epic. See [Built-in size aliases](llms.md#implicit-role-aliases) for
the full shipped-defaults table and
[Role Aliases for Delegated Work](llms.md#role-aliases-for-delegated-work) for how
delegated launches pick a model.

Three scalar `llm_provider` fields choose the model for launches that aren't driven by
phase/task/tale size routing: `default_model` (used when a launch has no explicit
`%model` directive), `epic_lander_model` (used by epic land agents below
`bead.big_epic_phase_threshold` authored phases), and `big_epic_lander_model` (used by
epic land agents at or above that threshold). Each accepts the same grammar as an alias
target — a concrete model, a provider-qualified model, an `@alias` reference (optionally
with a trailing effort such as `@large@high`), an `A | B` pool, an `A || B` fallback, or
a parenthesized `(A | B) || C` last-resort. Precedence is unchanged from before the
migration: an explicit prompt/plan/phase/task/approval-picker `%model` wins first, then
an active temporary override of the selected setting, then the config field resolves
through the normal alias/effort/selector/provider-disable machinery, and a missing or
malformed field falls back to its shipped default (`@large` / `@large` / `@xlarge`).

`model_alias_history_limit` bounds the number of prior runs requested for each alias in
Launch Control's agent-history panel. It defaults to `10`, must be at least `1`, and
falls back to `10` at runtime when a malformed value bypasses schema validation.

Accepted tale follow-ups without an approval-time model validate the actual handoff plan
and choose the matching size alias directly. Legacy tale plans without size metadata use
`@medium`. An approval-time model, a `%model` directive in a custom coder prompt, or an
outer effort suffix remains authoritative.

`model_aliases.builtin.epic_creator` is retired. SASE no longer launches an epic-creator
agent, resolves that alias implicitly, or treats it as a builtin override, so a stale
entry should be deleted rather than repointed. `sase doctor` reports a leftover entry
under the `model_aliases.builtin.epic_creator` key.

> The `llm_provider.worker_models` map and the reserved `@worker` / `@other` aliases
> were removed in epic sase-5d. Use a size alias (`@xsmall`, `@small`, `@medium`,
> `@large`, `@xlarge`) or an explicit model instead of `@worker`, and
> `llm_provider.default_model` instead of `@other`. The `phase_worker` bucket and its
> `<size>_phase_worker` aliases from that epic were themselves retired by the later
> size-alias simplification below. `sase doctor` reports configs that still reference
> removed keys or aliases, including retired `@coder` and registered `@<provider>_coder`
> builtin entries.

> The implicit role aliases (`@default`, `@epic_lander`, `@big_epic_lander`), the five
> `<size>_worker` aliases, the automatic `worker` bucket, and the capability/cost
> aliases (`@smart`, `@smarter`, `@smartest`, `@cheap`, `@cheaper`, `@cheapest`) were
> removed in favor of the five direct built-in size aliases above plus the three scalar
> `default_model` / `epic_lander_model` / `big_epic_lander_model` fields. A custom alias
> can still opt into a bucket of any name, including `worker` — it just has no special
> behavior anymore. Run `sase doctor -C config.model_aliases` for the exact destination
> of any retired name still present in your config or directives.

The TUI also supports **temporary**, per-alias session-level provider/model overrides
(set from [Launch Control](ace.md#launch-control), `,m`) that do **not** edit this
config. They are persisted to `~/.sase/llm_override.json` and expired entries are
deleted on next read. See [docs/llms.md](llms.md#temporary-model-overrides) for the
resolution order, state-file format, and precedence relative to
`SASE_MODEL_TIER_OVERRIDE`.

The same panel's `p=Providers` flow manages temporary provider disables in
`~/.sase/llm_provider_disables.json`. This is runtime state, not configuration: it does
not add a `disabled_providers` key, does not edit `llm_provider.provider`, and does not
rewrite any alias. A **hard** disable is fail-closed: alias selectors skip that member,
temporary alias overrides targeting it pause until the disable clears or expires, and
direct explicit provider/model requests fail with an actionable diagnostic instead of
silently switching providers. A **soft** disable is spared in `|` pools while another
member can cover, never diverts a `||` fallback, and does not pause overrides or fail
explicit requests. See
[Temporary Provider Disables](llms.md#temporary-provider-disables).

#### `llm_provider.usage_limit`

Automatic usage-limit detection temporarily disables a provider when that provider's own
error output positively matches its configured usage-limit patterns. This is separate
from `llm_provider.retry`: provider-scoped usage-limit classification wins before retry
policy, while a plain transient `429` or other retryable error that does not match a
usage-limit pattern still follows retry/fallback policy.

```yaml
llm_provider:
  usage_limit:
    enabled: true
    disable_seconds: 86400
    min_disable_seconds: 60
    max_disable_seconds: 604800
    honor_reset_hint: true
    notify: true
    providers:
      claude:
        patterns:
          - "you've hit your usage limit"
        exclude_patterns:
          - "usage limit approaching"
        replace_patterns: false
        disable_seconds: null
        honor_reset_hint: null
```

| Field                                                            | Type      | Default  | Description                                                                                                                                                                                                                                                                                                                                  |
| ---------------------------------------------------------------- | --------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm_provider.usage_limit.enabled`                               | bool      | `true`   | Enable usage-limit classification and automatic provider disables.                                                                                                                                                                                                                                                                           |
| `llm_provider.usage_limit.disable_seconds`                       | int       | `86400`  | Fallback disable duration in seconds when no provider reset hint is used.                                                                                                                                                                                                                                                                    |
| `llm_provider.usage_limit.min_disable_seconds`                   | int       | `60`     | Lower bound applied only to provider-reported reset-hint durations.                                                                                                                                                                                                                                                                          |
| `llm_provider.usage_limit.max_disable_seconds`                   | int       | `604800` | Upper bound applied only to provider-reported reset-hint durations.                                                                                                                                                                                                                                                                          |
| `llm_provider.usage_limit.honor_reset_hint`                      | bool      | `true`   | Parse a provider-reported reset time when present: a bare or zoned clock time ("resets at 8pm", "resets 6:38pm (America/New_York)"), an absolute date ("try again at Aug 20th, 2026 6:38 AM", "resets Aug 22, 8pm (America/New_York)", "resets 2026-08-20 06:38 UTC"), or a relative duration ("try again in 2 hours").                      |
| `llm_provider.usage_limit.notify`                                | bool      | `true`   | Send one notification for each newly-created automatic disable window.                                                                                                                                                                                                                                                                       |
| `llm_provider.usage_limit.providers.<provider>`                  | dict      | -        | Provider-specific detection and duration overrides.                                                                                                                                                                                                                                                                                          |
| `llm_provider.usage_limit.providers.<provider>.patterns`         | list[str] | `[]`     | Positive case-insensitive substring patterns. User patterns are additive with provider defaults unless replacement is set.                                                                                                                                                                                                                   |
| `llm_provider.usage_limit.providers.<provider>.exclude_patterns` | list[str] | `[]`     | Case-insensitive exclusions that suppress otherwise positive matches; exclusions are always additive.                                                                                                                                                                                                                                        |
| `llm_provider.usage_limit.providers.<provider>.replace_patterns` | bool      | `false`  | When true, the configured `patterns` list literally replaces built-ins; `patterns: []` intentionally disables that detector.                                                                                                                                                                                                                 |
| `llm_provider.usage_limit.providers.<provider>.disable_seconds`  | int/null  | `null`   | Per-provider fallback duration; `null` inherits `llm_provider.usage_limit.disable_seconds`. `grok` ships a non-null built-in default of `172800` (48h): Grok Build reports no reset instant in any usage-limit message, and paid usage meters against one shared weekly pool, so the flat 24h global default would under-shoot a real reset. |
| `llm_provider.usage_limit.providers.<provider>.honor_reset_hint` | bool/null | `null`   | Per-provider reset-hint policy; `null` inherits the global value.                                                                                                                                                                                                                                                                            |

Automatic disables are written to the same machine-wide provider-disable state used by
Launch Control, with `source: "usage_limit"`. They expire and self-clean like manual
disables, can be cleared early from Launch Control, and do not unregister or rewrite a
provider. If a fallback is available, retry/fallback may proceed only to a different
enabled provider; the disabled provider remains skipped until expiry or clearing. See
[Usage-Limit Auto-Disable](llms.md#usage-limit-auto-disable) for reset-hint parsing,
notification, and replacement details.

The same panel's fixed `Ctrl+E` binding manages the separate machine-wide default-effort
override at `~/.sase/llm_effort_override.json`. It uses the alias override duration and
exact-time cards, but its state and precedence are independent: explicit prompt effort
and alias/member effort win, then the temporary effort override, then
`llm_provider.default_effort`, then the provider default. See
[Reasoning Effort](llms.md#reasoning-effort).

Its fixed `Ctrl+R` binding manages `max_running_agents`: persistent edits target the
user-base `sase.yml` (or its chezmoi source), while temporary values live independently
in `~/.sase/max_running_agents_override.json`. This is a Launch Control binding, not an
`ace.keymaps` option.

#### `llm_provider.retry`

Per-provider retry and fallback configuration. See
[docs/llms.md](llms.md#retry-and-fallback) for the full retry flow and TUI display.

```yaml
llm_provider:
  retry:
    claude:
      max_retries: 3
      error_patterns:
        - "API Error: 500"
      wait_times: [60, 300, 1800]
      fallback_model: "sonnet"
      continuation_prompt: "Please continue from the last preserved work."
      preserve_workspace: true
      spawn_new_agent: false
```

| Field                                               | Type | Default | Description                                                            |
| --------------------------------------------------- | ---- | ------- | ---------------------------------------------------------------------- |
| `llm_provider.retry.<provider>`                     | dict | -       | Retry config for a specific provider (e.g., `agy`, `claude`, `codex`). |
| `llm_provider.retry.<provider>.max_retries`         | int  | `0`     | Maximum retry attempts. `0` disables retrying.                         |
| `llm_provider.retry.<provider>.error_patterns`      | list | `[]`    | Case-insensitive substring patterns matched against error output.      |
| `llm_provider.retry.<provider>.wait_times`          | list | `[30]`  | Per-retry wait times in seconds. Last value reused if list is shorter. |
| `llm_provider.retry.<provider>.fallback_model`      | str  | `null`  | Alternate model to use after exhausting all retries.                   |
| `llm_provider.retry.<provider>.continuation_prompt` | str  | `null`  | Prompt text prepended when continuing after a retryable failure.       |
| `llm_provider.retry.<provider>.preserve_workspace`  | bool | `false` | Preserve on-disk edits across legacy in-process retry attempts.        |
| `llm_provider.retry.<provider>.spawn_new_agent`     | bool | `false` | Retry by launching a fresh detached agent that inherits the workspace. |

Configured retry policy is merged with provider-supplied retry defaults when a provider
declares them. For list fields such as `error_patterns`, built-in patterns are kept and
configured patterns are appended with duplicates removed. Claude's provider hook adds
workspace-preserving matching for context-limit, socket-close, and Claude CLI API-error
output, plus a continuation nudge. Those hook defaults are merged with the bundled
Claude policy in `default_config.yml`, so the configured wait times and fallback model
still apply unless you override them.

Source: `src/sase/llm_provider/retry_config.py`, `src/sase/llm_provider/config.py`

### commit

Configures commit enforcement around SASE-launched agents. The current commit finalizer
is provider-neutral and runs in the shared LLM invocation layer after a successful
provider invocation in a SASE agent session, identified by `SASE_AGENT_TIMESTAMP`.

```yaml
commit:
  finalizer:
    enabled: true
    max_passes: 2
```

| Field                         | Type | Default | Description                                                                          |
| ----------------------------- | ---- | ------- | ------------------------------------------------------------------------------------ |
| `commit.finalizer.enabled`    | bool | `true`  | Run the post-invocation commit finalizer for SASE-launched agent sessions.           |
| `commit.finalizer.max_passes` | int  | `2`     | Maximum follow-up invocations before a still-dirty enforced workspace fails the run. |

When enabled, the finalizer checks the main workspace through the active VCS provider
and configured `repos.linked` Git worktrees at their resolved paths. Repositories opened
through `/sase_repo`, including external repos, are recorded in
`opened_linked_workspaces.json` for ACE context and in the host project's durable
repo-open log. Dirty enforced workspaces trigger a follow-up invocation that instructs
the same provider to use the appropriate commit skill. Dirty opened repos are enforced
like the main workspace. When the only enforced change is one tracked markdown file
under `sdd/plans/`, and that file's only diff is leading front matter changing exactly
from `status: wip` to `status: done`, the finalizer creates a direct
`chore: Mark SDD plan done` commit instead of invoking the provider again. When
`$SASE_ARTIFACTS_DIR` is set, each pass writes prompt/response artifacts there, and the
final outcome is recorded in `commit_finalizer_result.json`.

Set `SASE_DISABLE_COMMIT_STOP_HOOK=1` for a one-off bypass. The environment variable
name is historical; it now disables the provider-neutral finalizer.

#### commit.message

Configures the Conventional Commit subject gate that `sase stitch create` applies to
every `create_commit`, `create_proposal`, and `create_pull_request` message before any
side effect runs.

```yaml
commit:
  message:
    require_conventional_subject: true
    allowed_types:
      [build, chore, ci, deps, docs, feat, fix, perf, refactor, revert, style, test]
```

| Field                                         | Type | Default            | Description                                                                            |
| --------------------------------------------- | ---- | ------------------ | -------------------------------------------------------------------------------------- |
| `commit.message.require_conventional_subject` | bool | `true`             | Reject a `sase stitch create` message whose subject line is not a Conventional Commit. |
| `commit.message.allowed_types`                | list | the 12 types above | Commit types this project accepts. A configured list **replaces** the built-in set.    |

The subject must match `<type>[(<scope>)][!]: <description>`. The scope is optional, one
or more spaces may follow the colon, and no length or capitalization rule is applied to
the description. The type itself must be lowercase, because release tooling does not
classify capitalized types reliably. Only the first line is inspected; nothing below the
subject is validated.

Subjects beginning with `Merge `, `Revert "`, `fixup!`, `squash!`, or `amend!` are
exempt and always pass — these are mechanical git-generated or rebase-directive
subjects. An empty message is always rejected.

A rejection fails the workflow before beads are closed, plans are staged, or the
before-commit hook runs, and the `-M` message file is preserved so the same command can
be re-run after the subject is rewritten. There is no per-invocation bypass flag or
environment variable; a project that does not use Conventional Commits sets
`require_conventional_subject: false`.

Source: `src/sase/llm_provider/commit_finalizer.py`, `src/sase/commit_instructions.py`,
`src/sase/workflows/commit/message_validation.py`,
`src/sase/core/commit_subject_facade.py`

### repos

Declares linked and sidecar repositories related to a project. Git linked-repo worktrees
are eligible for commit-finalizer checks at their resolved `workspace_dir`. Agents use
`/sase_repo` to prepare them; its audited `sase repo open` command records manually
opened linked workspaces in run artifacts for ACE context and appends a durable audit
event. SASE materializes a hidden sibling-state ProjectSpec for the linked repo when
needed. Entries can live in user config or a project-local `sase/sase.yml`; local
entries are resolved relative to the project's primary workspace directory.

Linked repositories are lazy by default. Set `auto_clone: true` for a repository that
every launched agent needs; SASE materializes and prepares those entries before
execution. Lazy entries remain available through `sase repo open`, but their
per-repository `*_DIR` environment variables are not exported until the clone exists.
Repositories with `auto_clone: true` are omitted from generated agent instructions
because agents do not need to open them manually.

`auto_clone` and `auto_sync` are independent settings on a sidecar entry. `auto_clone`
controls whether a numbered workspace materializes its own clone of the sidecar before
each agent launch; that clone is disposable and owned by the launched agent's workspace.
`auto_sync` instead opts the _primary checkout's_ already-materialized sidecar clone
into conservative background convergence: SASE fetches and fast-forwards it only while
it is clean, attached, and non-diverged, and never rebases, commits, hard-resets, or
removes user state. A dirty, detached, diverged, remote-mismatched, or
not-yet-materialized primary sidecar clone is left untouched and reported rather than
repaired. Managed projects enable `auto_sync` for the generated `plans`, `beads`, and
`research` entries; custom roles default to `false` and opt in with the same property.
See [Ownership Boundary](workspace.md#ownership-boundary) for the underlying
primary/leased distinction and how sync is scheduled.

`repos.sidecar` is a two-bucket mapping keyed by role: `builtin` holds overrides of the
reserved `plans`, `beads`, and `agents` roles, and `custom` holds user-declared document
sidecars such as `research`. The map key _is_ the role, so an entry never carries a
`name` field and a role cannot be declared twice in one bucket. Because both buckets are
mappings, a later config layer merges into an inherited entry per key — a project-local
`custom: {research: {disabled: true}}` opts out of a global `research` sidecar. The
former list form (a sequence of entries each carrying `name`) is no longer accepted and
is ignored; run `sase doctor` to see which bucket each stale entry belongs in.

Sidecar entries use their role key as the primary CLI lookup key. Ordinary roles use
`sase/repos/<role>` as their workspace clone directory. Their repository defaults to
`<project>--<role>` in the primary repository's GitHub organization; `repo` can pin a
bare slug or `owner/repo`. An explicit unpinned entry uses that project-local derivation
even when a legacy SDD store record names a different repository. Configured sidecars
appear in `sase repo list` even before cloning and can be opened by role name or
repository slug. Enabled ordinary sidecars that are not auto-cloned also appear by
repository slug in generated agent instruction files, where their `description` tells
agents when to open them with `/sase_repo`. Set `disabled: true` in a later config layer
to suppress a matching global entry or implicit fallback; disabled and auto-cloned
sidecars are omitted from generated instructions.

The roles `plans`, `beads`, and `agents` are reserved and are configured under
`repos.sidecar.builtin`. `plans` owns canonical plans, `beads` owns the event store, and
`agents` is the hidden machine-level publication store plus the canonical prompt and
prompt-artifact archive. Every other enabled role lives under `repos.sidecar.custom` and
is a document sidecar: a `<YYYYMM>/*.md` corpus whose kind label is the role name.
Document roles receive clone/store resolution, `sase repo path <role>`, doctor
validation, commit routing, `SASE_SDD_<ROLE>_DIR`, plan-search visibility, and an ACE
Plans kind. `research` is simply the default-seeded document role; only its illustrated
README/directory-map preset is name-specific.

The `agents` role is intrinsically hidden from agent workflows. It never appears in
generated memory, launch metadata, linked-repository environment variables, or a
workspace's `sase/repos/` tree, even if an override sets `auto_clone: true`. It remains
visible to users as a `sidecar` row in `sase repo list`, and `sase repo path agents` or
`sase repo open agents -r "<reason>"` explicitly accesses the one machine-level clone at
`~/.sase/projects/<project_key>/repos/agents`. The derived or pinned repository slug is
also accepted by those commands.

The workspace provider owns sidecar transport. GitHub sidecars use canonical SSH origins
on the primary repository's GitHub host (`git@host:owner/repo.git`, or
`ssh://git@host:port/owner/repo.git` when a port is configured). Read-only store
resolution converts a legacy GitHub HTTPS record to that exact SSH form in memory, so
inventory, launch-time auto-cloning, and on-demand materialization are safe immediately
without rewriting the durable record. Matching retained HTTPS clones keep their checkout
and local state while SASE rewrites `origin` in place. Any HTTP(S) sidecar remote that
cannot be derived from consistent GitHub provider, host, and repository metadata fails
materialization before Git runs. Rerun `sase repo init` to persist the migrated record;
it is not required to make a launch safe.

Managed projects (`is_sase_managed: true`) receive deterministic `<project>--plans`
(`auto_clone: true`) and `<project>--agents` (`auto_clone: false`, public visibility)
entries when no matching explicit sidecar is configured. Research is config-declared per
project and defaults to `<owner>/<project>--research`; `sase repo init` writes the plans
and research entries. A project-local `agents` entry replaces the implicit entry: use
`disabled: true` to opt out or `visibility: private` to retain it with a private remote
policy. Project-local `default_linked_repos: false` suppresses both implicit
managed-project entries. `sase repo init` can create and seed the agents remote only
after its separate default-no consent prompt. Successful agent commit/PR workflows
publish the committing hood, while `sase agent sync` imports shared history and
reconciles every locally commit-eligible hood through the stable machine-level clone.
See [Agent Hood Synchronization](agents_sidecar.md) before enabling a public remote.

The deprecated `linked_repos` and `sibling_repos` keys are still accepted as aliases
during the compatibility window. Canonical `repos.linked` entries take precedence over
both aliases when the same name is defined.

```yaml
github_orgs:
  - sase-org
repos:
  linked:
    - name: core
      path: ../sase-core
      description: Shared backend/domain behavior used by SASE frontends.
      auto_clone: true
  sidecar:
    builtin:
      plans:
        auto_clone: true
        ref:
          use: builtin@plan
      agents:
        visibility: private
    custom:
      research:
        description: Durable SASE research reports and generated media.
        visibility: public
        ref:
          icon: ∴
          inventory:
            globs: ["reports/**/*.md", "!drafts/**"]
```

| Field                                         | Type           | Default                             | Description                                                                                  |
| --------------------------------------------- | -------------- | ----------------------------------- | -------------------------------------------------------------------------------------------- |
| `github_orgs`                                 | string or list | -                                   | GitHub user/org namespaces available to provider completion and PR workflows.                |
| `default_linked_repos`                        | boolean        | `true`                              | Inject managed-project `--plans` and hidden `--agents` sidecars.                             |
| `repos.linked[].auto_clone`                   | boolean        | `false`                             | Materialize and prepare the repository automatically before each agent launch.               |
| `repos.linked[].name`                         | string         | required                            | Stable alias used in generated environment variable names and memory summaries.              |
| `repos.linked[].path`                         | string         | required                            | Primary checkout path. Relative paths resolve from the project's primary workspace.          |
| `repos.linked[].description`                  | string         | required                            | Human-readable purpose used when generating agent memory for the linked repository.          |
| `repos.sidecar.builtin.<role>`                | object         | -                                   | Override for a reserved role; the key must be `plans`, `beads`, or `agents`.                 |
| `repos.sidecar.custom.<role>`                 | object         | -                                   | User-declared document sidecar; the key is the role and must not be a reserved one.          |
| `repos.sidecar.*.<role>.repo`                 | string         | derived                             | Optional bare slug or `owner/repo` pin.                                                      |
| `repos.sidecar.*.<role>.description`          | string         | -                                   | Purpose shown in inventory; required in generated instructions for lazy entries.             |
| `repos.sidecar.*.<role>.auto_clone`           | boolean        | `false`                             | Materialize before agent launch; intrinsically ignored for `agents`.                         |
| `repos.sidecar.*.<role>.auto_sync`            | boolean        | `false`                             | Fetch/fast-forward the primary clone when clean; intrinsically ignored for `agents`.         |
| `repos.sidecar.*.<role>.visibility`           | public/private | `public`                            | Remote visibility; project-local `private` overrides the `agents` default.                   |
| `repos.sidecar.*.<role>.disabled`             | boolean        | `false`                             | Disable the entry and suppress matching implicit sidecars, including `agents`.               |
| `repos.sidecar.*.<role>.ref.use`              | string         | role/provider dependent             | Installed artifact-reference provider, qualified `<plugin>@<id>`, to use as the base policy. |
| `repos.sidecar.*.<role>.ref.kind`             | string         | role name (`plan` for `plans`)      | Prompt kind exposed as `@<kind>:<path>`.                                                     |
| `repos.sidecar.*.<role>.ref.icon`             | string         | role/provider dependent             | Artifacts tab mark shown beside the pane label.                                              |
| `repos.sidecar.*.<role>.ref.expansion_format` | string         | `@{checkout_path}`                  | Provider expansion format; see [Expansion](artifact_references.md#expansion).                |
| `repos.sidecar.*.<role>.ref.properties`       | object         | `{}`                                | Typed metadata fields extracted by the provider.                                             |
| `repos.sidecar.*.<role>.ref.detail`           | object         | `{}`                                | Metadata fields shown by completion and detail surfaces.                                     |
| `repos.sidecar.*.<role>.ref.identity`         | object         | `{}`                                | Optional provider identity rule.                                                             |
| `repos.sidecar.*.<role>.ref.inventory.globs`  | list[string]   | `["**/*.md"]` for document sidecars | Repo-relative POSIX includes and `!` exclusions.                                             |
| `repos.sidecar.*.<role>.ref.publication`      | object         | VCS permalink / Markdown references | Publication link and reverse-reference policy.                                               |

Every enabled document sidecar exposes one compact `@<kind>:<path>` reference. Plans use
the built-in `plan` provider, and `sase repo init` records `ref: {use: builtin@plan}`.
Other document roles default to their role name, `@{checkout_path}` (path-bound)
expansion, and `**/*.md` inventory even when `ref` is omitted.

`ref.use` selects a declarative provider installed through the `sase_artifact_refs`
plugin entry-point group, qualified as `<plugin>@<id>` where `<plugin>` is the literal
`builtin` or the installed distribution name. Any sibling keys deep-merge over that
provider's base spec. A cloned sidecar does not install its provider: when `use` names
an unavailable provider or omits its plugin prefix, the role's reference policy is
disabled and `sase doctor -C config.repos` reports how to fix it. Authors may omit `use`
and provide the inline fields in the table instead.

`ref.xprompt` is retired and invalid. `ref.filters.path_globs` remains a deprecated
alias that warns and maps to `ref.inventory.globs`; new configuration must use
`inventory.globs`. The `beads` and `agents` sidecars are entity-backed rather than
document inventories, so document filters do not apply to them. See
[Artifact References](artifact_references.md) for canonical prompt forms and
project-context rules.

Workspace numbers `0` and `1` use the linked repo's primary checkout. Higher workspace
numbers use `<host_workspace>/sase/repos/linked/<linked_repo>`, naturally namespaced by
host project and workspace number. Agent and workflow launch preparation atomically
removes the numbered checkout's entire `<host_workspace>/sase/repos/` tree. The required
`plans` sidecar is then cloned directly from the canonical SSH or local remote resolved
from its recorded metadata; other linked repositories and sidecars remain lazy unless
configured with `auto_clone: true`. Legacy GitHub HTTPS metadata is normalized before
the clone command is built, and unresolved HTTP(S) metadata stops launch setup before
Git executes. The hidden `agents` sidecar is excluded from this clone mapping and always
resolves every registered workspace number to
`~/.sase/projects/<project_key>/repos/agents`. Agents materialize ordinary lazy entries
on demand through `/sase_repo`. `sase repo init` manages the tracked `/sase/repos/`
ignore rule, while SASE also installs the rule in `.git/info/exclude` before
materialization. SASE passes resolved metadata for all entries and exports
per-repository paths only for materialized entries:

| Variable                                  | Description                                      |
| ----------------------------------------- | ------------------------------------------------ |
| `SASE_LINKED_REPOS_JSON`                  | JSON metadata for all resolved linked repos.     |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR`         | Workspace-matched directory for a linked repo.   |
| `SASE_LINKED_REPO_<ENV_NAME>_PRIMARY_DIR` | Primary checkout directory for that linked repo. |

The legacy `SASE_SIBLING_REPOS_JSON` and `SASE_SIBLING_REPO_<ENV_NAME>_*` variables are
still emitted alongside the canonical ones during the compatibility window.

`<ENV_NAME>` is the uppercased, sanitized repo `name`; duplicates are uniquified with a
numeric suffix.

Source: `src/sase/linked_repos.py`, `src/sase/agent/launch_spawn.py`

#### External repositories

External repositories are per-task repos that are not part of the host project's
configured inventory. They require no configuration entry. `sase repo open` resolves
them after inventory names in two forms:

- Another registered SASE project name opens that project's primary repo from its local
  checkout, without network access, under `sase/repos/external/projects/<project>`.
- `gh:owner/repo`, or the `owner/repo` shorthand, clones through the installed GitHub
  workspace provider under `sase/repos/external/gh/<owner>/<repo>`.

Successful external opens are idempotent, audited, and included in `sase repo list`,
commit-finalizer enforcement, ACE file and commit deltas, and revert. Agents must use
`/sase_repo` before reading or modifying any external repo and must use the path printed
by the skill rather than locating or cloning the repo themselves. External repos are
workspace-local and do not create project registry records.

### vcs_provider

Configures the version control system backend. See [docs/vcs.md](vcs.md) for the full
VCS provider reference including per-command behavior, Git/Mercurial details, and
troubleshooting.

GitHub Enterprise host configuration (`github_hosts`) is owned by the `sase-github`
plugin; see its
[GitHub Enterprise setup walkthrough](https://github.com/sase-org/sase-github/blob/master/docs/configuration.md#github-enterprise-setup).

```yaml
vcs_provider:
  provider: auto # "git", "hg", or "auto" (default: "auto")
  workspace_root: ~/workspace # optional workspace root directory
  default_hooks: # optional list overriding built-in default hooks
    - "!$my_presubmit"
    - "$my_lint"
  pr_tags: # optional key-value tags appended to PR commit messages (keys are rendered SASE_-prefixed, e.g. SASE_BUG)
    BUG: "b/12345"
  use_project_pr_prefix: false # prepend [<project>] to PR titles (default: false)
```

| Field                                | Type              | Default  | Description                                                                                                   |
| ------------------------------------ | ----------------- | -------- | ------------------------------------------------------------------------------------------------------------- |
| `vcs_provider.provider`              | string            | `"auto"` | VCS provider: `"git"`, `"hg"`, or `"auto"` for directory detection.                                           |
| `vcs_provider.workspace_root`        | string            | -        | Legacy VCS helper workspace root. New numbered-checkout layout is configured by `workspace.root` below.       |
| `vcs_provider.default_hooks`         | list[string]      | -        | Hook commands added to new Patches. Replaces built-in defaults.                                               |
| `vcs_provider.pr_tags`               | dict[string, str] | `{}`     | Key-value tags appended as `SASE_TAG=VALUE` lines to PR commit messages (keys are rendered `SASE_`-prefixed). |
| `vcs_provider.use_project_pr_prefix` | bool              | `false`  | Prepend `[<project>] ` to PR titles / PR descriptions (see below).                                            |

When `default_hooks` is not set, plugins may provide their own defaults via
`default_config.yml` (for example, Mercurial-specific hooks from a provider plugin). The
core `sase` package has no built-in default hooks.

When `use_project_pr_prefix` is `true`, a `[<project>] ` prefix is prepended to PR
titles (GitHub) or PR descriptions (Mercurial) without polluting the Patch DESCRIPTION
or git commit message. The prefix is automatically stripped when reading descriptions
back.

Source: `src/sase/vcs_provider/config.py`, `src/sase/ace/hooks/defaults.py`

### vcs_repo_completion

Configures repository-name completion inside VCS workflow refs such as `#gh:owner/`.

```yaml
vcs_repo_completion:
  enabled: true
  cache_ttl_seconds: 600
  max_repos: 200
```

| Field                                   | Type | Default | Description                                                                                 |
| --------------------------------------- | ---- | ------- | ------------------------------------------------------------------------------------------- |
| `vcs_repo_completion.enabled`           | bool | `true`  | Enable ACE and helper-bridge repository completion for registered VCS workflow refs.        |
| `vcs_repo_completion.cache_ttl_seconds` | int  | `600`   | Freshness window for the shared on-disk repository candidate cache, in seconds.             |
| `vcs_repo_completion.max_repos`         | int  | `200`   | Maximum repository candidates kept from a provider response and returned to completion UIs. |

When disabled, ACE does not detect repository-completion triggers, and the editor helper
bridge returns an empty catalog. Repository candidates are listed through
workspace-provider hooks, so provider-specific authentication and network requirements
belong to the installed plugin. For GitHub, the `sase-github` plugin uses the `gh` CLI
and can return private repositories visible to the authenticated user.

Source: `src/sase/default_config.yml`, `src/sase/xprompt/vcs_repo_completion.py`

### vcs_ref_completion

Configures project, Patch, and namespace completion at the root of VCS workflow refs
such as `#gh:` and `#git:`.

```yaml
vcs_ref_completion:
  enabled: true
```

| Field                        | Type | Default | Description                                                             |
| ---------------------------- | ---- | ------- | ----------------------------------------------------------------------- |
| `vcs_ref_completion.enabled` | bool | `true`  | Enable ACE and xprompt LSP completion at the root of VCS workflow refs. |

When disabled, ACE does not detect VCS ref-root completion triggers and the materialized
xprompt LSP VCS catalog omits namespace rows. Project and Patch candidates come from
local ProjectSpecs; provider namespace rows come from fast local workspace-provider
hooks.

Source: `src/sase/default_config.yml`, `src/sase/xprompt/vcs_ref_completion.py`

### axe

Configures the `sase axe` lumberjack-based daemon. The axe architecture uses an
orchestrator that spawns multiple lumberjacks, each running a set of chops on a fixed
interval. Defaults are provided by `src/sase/default_config.yml`.

The YAML below is an abridged illustration of the shipped defaults, not the whole file:
it shows the shape of a lane and a chop and omits some lanes and chops entirely. See
[AXE Automation](axe.md#default-lumberjacks) for the complete lane-by-lane inventory,
and `src/sase/default_config.yml` for the literal defaults.

```yaml
axe:
  max_hook_runners: 3 # concurrent hook runners (default: 3)
  max_agent_runners: 3 # concurrent agent runners (default: 3)
  zombie_timeout_seconds: 7200 # seconds (default: 7200 = 2 hours)
  query: "" # query filter for Patches (default: all)
  chop_script_dirs: [] # additional directories to search for chop scripts
  lumberjacks:
    hooks:
      description: |-
        Fast lane that advances hook, mentor, and workflow lifecycle state every few seconds

        Runs every five seconds with a 90-second per-chop timeout so completed work is noticed and new work starts
        promptly. Put latency-sensitive Patch lifecycle reconciliation here; slower remote polling, wait
        coordination, and maintenance belong in the other lanes.
      interval: 5
      chop_timeout: "90s"
      chops:
        - name: hook_checks
          script: sase_chop_hook_checks
          description: |-
            Complete finished hooks and start stale ones, with zombie detection

            Scans hook entries on every matching Patch, records completed process results, and starts stale hooks
            when a runner slot is free. Honors max_hook_runners across the tick; stale fix-hook suffixes older than
            zombie_timeout_seconds become ZOMBIE, while terminal Patches may finish hooks but cannot start new ones.
        - name: mentor_checks
          script: sase_chop_mentor_checks
          description: |-
            Start mentor workflows once all hook prerequisites are met

            Reconciles running mentors, stops mentors left behind by older commits, adds matching mentor profiles, and
            launches ready profiles after their hooks finish. Mentor launches share max_agent_runners with other agent
            workflows, and review-ineligible or terminal Patches are skipped.
        - name: workflow_checks
          script: sase_chop_workflow_checks
          description: |-
            Complete finished CRS/fix-hook workflows and start stale ones

            Reads workflow state from every matching Patch, records results for finished CRS and fix-hook agents,
            and launches stale workflows. New workflows share max_agent_runners and the current tick's agent-launch
            budget with mentors, so a full runner pool defers work instead of queueing it.
        - name: pending_checks_poll
          script: sase_chop_pending_checks_poll
          description: |-
            Poll background is_cl_submitted and critique_comments checks for results

            Scans the pending-check directory once per tick, applies completed results to matching Patches, and
            reaps output files orphaned by killed or crashed checks. This chop only consumes background results;
            pr_submitted_checks and comment_checks launch the remote checks.
        - name: comment_zombie_checks
          script: sase_chop_comment_zombie_checks
          description: |-
            Mark comment threads older than zombie_timeout as ZOMBIE

            Examines comment-entry suffix timestamps on matching Patches and writes a ZOMBIE suffix when an entry
            exceeds zombie_timeout_seconds. It performs no remote comment fetch; comment_checks starts those checks and
            pending_checks_poll applies their results.
        - name: suffix_transforms
          script: sase_chop_suffix_transforms
          description: |-
            Strip stale suffixes from older proposals and update mail-readiness markers

            Normalizes matching Patches in place by converting old proposal markers from !: to ~:, removing error
            markers from superseded stitches, and acknowledging attention markers on terminal statuses. It only
            repairs stored suffix state and never launches hooks or agents.
        - name: orphan_cleanup
          script: sase_chop_orphan_cleanup
          description: |-
            Release workspace claims orphaned by reverted PRs with dead PIDs

            Reads all Patches and workspace claims, regardless of the axe query, then releases unpinned claims tied
            to Reverted Patches when their owning PID is absent or dead. Live claims and pinned workspaces are left
            untouched.
        - name: stale_running_cleanup
          script: sase_chop_stale_running_cleanup
          description: |-
            Release workspace claims held by dead processes

            Walks every project, including disabled projects, and releases unpinned workspace claims whose owning
            process has exited. A pinned held claim is preserved while its agent artifacts still exist; this fast-lane
            placement frees ordinary dead claims within seconds.
    waits:
      description: |-
        Resolve agent wait dependencies and keep bead claims and stores in sync

        Runs every ten seconds so waiting agents resume promptly and short-lived bead claims are reconciled quickly.
        Put agent dependency, bead-claim, and bead-store coordination here; Patch lifecycle checks and general
        cleanup belong in their dedicated lanes.
      interval: 10
      chops:
        - name: bead_claim_checks
          script: sase_chop_bead_claim_checks
          description: |-
            Acquire missing bead claims for live pre-launch agents and release claims held by dead ones

            Scans pre-launch agent artifacts, backfills a missing claim for a live waiting agent, and releases a
            claimed bead when its unpromoted owner has died. Reconciled dead records are tombstoned so later ticks avoid
            reopening their stores, while a failed project read is retried safely.
        - name: epic_launch_flush
          script: sase_chop_epic_launch_flush
          run_every: "30s"
          description: |-
            Flush planner completion notifications orphaned by an unsettled epic launch

            Preserves deferrals while a matching detached epic-launch task is active, flushes unowned deferrals after
            a 90-second grace period with a resume command, and reaps unclaimed settle markers after one hour.
        - name: sidecar_auto_sync
          script: sase_chop_sidecar_auto_sync
          run_every: "30s"
          timeout: "2m"
          description: |-
            Fetch and fast-forward opted-in primary sidecar clones (plans, beads, research, custom)

            Scans every enabled project's auto_sync sidecar roles, syncing a role immediately when a publisher left a
            pending hint and otherwise backstopping it at most every five minutes. Projects with a live agent waiting
            on bead completion also hint the beads role every tick, even when that role has not opted into auto_sync,
            so waiters unblock promptly instead of relying on the runner's coarser fallback. Only a clean, attached,
            non-diverged clone with a matching remote is fetched and fast-forwarded; dirty, detached, diverged,
            mismatched, missing, or busy clones are left untouched and reported. Bounded work budget and persistent
            per-role backoff keep one unhealthy clone from stalling the rest.
        - name: wait_checks
          script: sase_chop_wait_checks
          description: |-
            Resolve agent wait dependencies and write ready.json when satisfied

            Scans waiting markers across projects and resolves named-agent, artifact, and closed-bead dependencies from
            shared agent metadata and canonical bead state. It writes ready.json only after every dependency is
            satisfied; invalid or already-ready markers are skipped without blocking other agents.
    checks:
      description: |-
        Poll slower PR-submission and workspace-claim checks on a five-minute cadence

        Runs every five minutes for checks that can tolerate delay or may touch remote PR state, reducing needless
        polling while retaining a cleanup backstop. Fast hook progression, minute-level comments, and hourly
        maintenance deliberately live elsewhere.
      interval: 300
      chops:
        - name: bead_task_triage
          script: sase_chop_bead_task_triage
          timeout: "2m"
          description: |-
            Raise one human gate for each ready or snoozed task bead, and for each due flag-typed task bead

            Scans enabled projects every five minutes and gives every live task bead exactly one pending
            gate: a TaskTriage gate while a task bead is ready and has at least its effective +1 bar in reports
            (its own task type's triage.min_plus_ones, else the global bead.task_triage.min_plus_ones), a BeadSnooze
            wake gate while it is snoozed, and a FlagTriage gate once a flag-typed task bead's date and
            release removal thresholds have both passed. A ready task bead below the +1 bar is withheld from
            triage without changing its stored status, and a gate already raised for a bead that falls below the
            bar is canceled and its notification dismissed. Deterministic gate generations in lane state prevent
            duplicate notifications, a gate of the wrong kind is replaced when its bead's status or due-ness
            changes, and a snoozed bead's notification is re-snoozed to its wake time if it ever drifts. Gates are
            canceled when their beads leave those states, while answered or missing gates can be regenerated
            safely if work remains. Gates stranded by removed projects or forgotten lane state are swept without
            touching projects that are only temporarily unreadable. A gateable bead with a detached launch still
            in flight is deferred instead of re-gated.
        - name: plugins_required
          script: sase_chop_plugins_required
          timeout: "2m"
          description: |-
            Raise one human gate per project whose required plugins are missing

            Scans enabled projects every five minutes and compares each project's plugins.required list against
            installed distributions. A project with a missing or version-mismatched required set gets exactly one
            pending PluginsRequired gate offering Install and Dismiss. Install runs sase plugin install for each
            missing name from the answering surface and keeps the gate pending when that command fails, including
            when sase is not a uv tool install. Dismiss records the decision so the same missing set is not
            re-offered until it changes. The chop cancels the gate when the set becomes satisfied. Deterministic
            generations in lane state prevent duplicate notifications. Agent and non-interactive contexts still
            fail closed and never auto-install.
        - name: pr_submitted_checks
          script: sase_chop_pr_submitted_checks
          description: |-
            Start background is_cl_submitted checks for leaf PRs with a submitted parent

            Applies the axe query, finds eligible leaf Patches with PR URLs, and launches non-blocking submission
            checks whose results are collected by pending_checks_poll. A five-minute sync cache suppresses duplicate
            remote work, except that the first cycle checks eligible leaves immediately.
        - name: stale_running_cleanup
          script: sase_chop_stale_running_cleanup
          description: |-
            Backstop release of workspace claims held by dead processes

            Runs the same all-project dead-process reconciliation as the hooks-lane cleanup, including conservative
            handling of pinned claims with agent artifacts. This five-minute placement still frees stale workspace
            claims if the fast hooks lane is disabled, restarting, or repeatedly failing.
    comments:
      description: |-
        Start background critique-comment checks for mailed PRs every minute

        Runs every minute so reviewer feedback reaches active Patches promptly without polling on every hooks tick.
        Only remote comment-check launches belong here; pending result collection and zombie marking remain in the
        faster hooks lane.
      interval: 60
      chops:
        - name: comment_checks
          script: sase_chop_comment_checks
          description: |-
            Start background critique_comments checks for all mailed PRs

            Applies the axe query and starts non-blocking critique_comments checks for mailed Patches that have an
            available workspace, then records a comment-cycle summary. The lumberjack's one-minute interval is the
            polling throttle; pending_checks_poll later consumes each background result.
    housekeeping:
      description: |-
        Run hourly error digests, managed-temp cleanup, and stale task-bead sweep

        Runs once an hour because notification batching, bounded scratch reclamation, and stale-backlog
        cleanup are useful but not latency-sensitive. Put durable maintenance that may scan substantial
        local state here, not lifecycle, dependency, or remote polling work.
      interval: 3600
      chops:
        - name: error_digest
          script: sase_chop_error_digest
          description: |-
            Send a notification digest of errors from the last hour

            Reads the AXE error log and the last successful digest timestamp, then notifies only about newer errors
            within the rolling one-hour window. The checkpoint advances to the newest notified timestamp, preventing
            duplicate digests while leaving unsent errors eligible after a notification failure.
        - name: managed_tmp_reap
          script: sase_chop_managed_tmp_reap
          description: |-
            Prune stale scratch under the managed SASE temp root

            Removes old children from known managed-temp buckets using workload-specific age limits, without following
            symlinks or deleting the stable bucket directories. Each pass removes at most 2,000 entries and de-indexes
            deleted agent-artifact directories, so a neglected root converges without blocking interactive commands.
        - name: bead_stale_cleanup
          script: sase_chop_bead_stale_cleanup
          timeout: "2m"
          description: |-
            Sweep stale sub-threshold ready task beads into one BeadStaleCleanup gate

            Reads every enabled project's ready task beads and offers those that have sat below
            their effective +1 bar (their own task type's triage.min_plus_ones, else the global
            bead.task_triage.min_plus_ones) for bead.task_triage.stale_after_days once at least
            bead.task_triage.stale_cleanup_min_beads such beads exist. One pending gate at a time
            carries at most 50 beads, oldest first; a larger backlog is reported in omitted_count and
            offered on later ticks. An unchanged roster leaves the pending gate alone. The gate is
            canceled when the backlog drops below the bar.
```

**Top-level fields:**

| Field                                    | Type         | Default    | Description                                                               |
| ---------------------------------------- | ------------ | ---------- | ------------------------------------------------------------------------- |
| `max_hook_runners`                       | int          | `3`        | Maximum concurrent hook runners (non-`$` hooks) across all Patches.       |
| `max_agent_runners`                      | int          | `3`        | Maximum concurrent agent runners (agents and mentors) across all Patches. |
| `zombie_timeout_seconds`                 | int          | `7200`     | Seconds after which a running hook or workflow is flagged as a zombie.    |
| `query`                                  | string       | `""`       | Query string for filtering Patches (empty = all).                         |
| `chop_script_dirs`                       | list[string] | `[]`       | Additional directories to search for external chop scripts.               |
| `lumberjack_log_max_bytes`               | int          | `52428800` | Maximum bytes retained for each bounded lumberjack log.                   |
| `lumberjack_log_temp_max_age_seconds`    | int          | `300`      | Minimum age before orphaned log-rotation temp files are removed.          |
| `lumberjack_restart_backoff_max_seconds` | int          | `60`       | Maximum delay between retries for a crashing lumberjack.                  |
| `verbose_lumberjack_diagnostics`         | bool         | `false`    | Include verbose diagnostics in chop script context JSON.                  |
| `lumberjacks`                            | dict         | -          | Mapping of lumberjack name → config (see below).                          |

**Lumberjack fields** (per entry under `lumberjacks`):

| Field          | Type                    | Required | Default | Description                                                                                                                     |
| -------------- | ----------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `description`  | string                  | yes      | -       | Summary line, blank line, optional body describing the lane's cadence and work.                                                 |
| `interval`     | int                     | no       | `1`     | Seconds between chop polling cycles.                                                                                            |
| `chop_timeout` | string                  | no       | -       | Positive compound duration limit, such as `"90s"`, `"1h30m"`, or `"1d"`.                                                        |
| `wait_runners` | int                     | no       | -       | Start a lane agent once at most this many other agents hold runner slots; omitting it uses the global `max_running_agents` cap. |
| `env`          | dict[string, env-value] | no       | `{}`    | Environment inherited by every chop in this lumberjack.                                                                         |
| `chops`        | list[object] or map     | no       | `[]`    | Composable chop definitions (see below).                                                                                        |

**Chop fields** (per entry under `chops`):

| Field         | Type                    | Required  | Default  | Description                                                                                                     |
| ------------- | ----------------------- | --------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| `name`        | string                  | list only | -        | Stable identity; map form uses the entry key.                                                                   |
| `script`      | string                  | no        | `name`   | Exact executable name; no prefix is added automatically.                                                        |
| `enabled`     | boolean                 | no        | `true`   | Soft-disable a keyed entry while retaining inherited fields.                                                    |
| `description` | string                  | yes       | -        | Summary line, blank line, optional body describing what the chop does.                                          |
| `run_every`   | string                  | no        | -        | Positive compound cadence such as `"60m"`, `"1h30m"`, or `"1d"`.                                                |
| `timeout`     | string                  | no        | -        | Per-chop duration limit. Overrides lumberjack `chop_timeout`.                                                   |
| `env`         | dict[string, env-value] | no        | `{}`     | Literal values or `{env:}`, `{file:}`, `{pass:}` references.                                                    |
| `inhibit_if`  | list or map             | no        | -        | `patch` / `agent_hood` / `agent_clan` / `agent_runners` guards before dispatch; `changespec` is a legacy alias. |
| `trigger`     | string or map           | no        | `always` | `always` or `git.commits_since` scheduled-run trigger.                                                          |
| `once_per`    | string or object        | no        | -        | Bounded per-proposal dedupe-key template.                                                                       |
| `for_each`    | list or source          | no        | -        | Literal targets or the filtered `projects` source.                                                              |
| `vars`        | object                  | no        | `{}`     | Non-secret values copied to the chop context.                                                                   |

Both `description` fields use one grammar: a non-blank summary line of at most 100
characters, then — if anything follows — a blank line, then a free-form body, with the
whole string capped at 2000 characters. Violations produce the
`description_summary_blank`, `description_summary_too_long`,
`description_body_separator_required`, and `description_too_long` diagnostics. See
[AXE — Description Grammar](axe.md#description-grammar) for the full contract, the
authoring style guide, and the YAML literal-block form.

All chops are scripts. Exact-name resolution checks `chop_script_dirs`, then the running
interpreter's bin directory, then `$PATH`. Invalid fields, duplicate identities,
non-positive intervals, and invalid durations fail config loading with a dotted config
path and source-layer diagnostic. `agent:` and `xprompt:` are rejected with a migration
message.

Environment values resolve at dispatch time. Use a literal for non-secret data or
`{env: NAME}`, `{file: path}`, and `{pass: entry}` references for secrets.
Lumberjack-level `env` is inherited by every chop, then a chop's own `env` overrides
matching names.

The built-in `wait_checks` chop writes `ready.json` only after named `%wait`
dependencies complete successfully. Failed, killed, crashed, still-running, malformed,
or missing `done.json` artifacts do not satisfy the dependency.

Map form is the composable form. Higher-priority config layers patch matching fields by
key, and per-field source provenance is shown by the verbose chop inventory:

```yaml
axe:
  lumberjacks:
    docs:
      description:
        Refresh project documentation when repositories accumulate meaningful changes
      interval: 60
      env:
        API_TOKEN: { env: DOCS_API_TOKEN }
      chops:
        refresh_docs:
          description: Refresh documentation after meaningful repository drift
          script: sase_chop_refresh_docs
          run_every: "30m"
          trigger:
            git.commits_since:
              project: "{target.name}"
              threshold: 10
              checkpoint: on_action_success
          for_each:
            source: projects
            vcs: [git, gh]
        packaged_but_disabled:
          description: Retain a packaged documentation check without running it
          enabled: false
```

`for_each` produces stable identities such as `refresh_docs[sase-core]`. Each instance
has independent scheduling, history, checkpoints, and once-per state. Target data is
available in the context JSON under `target` and through `SASE_CHOP_TARGET_KEY` /
`SASE_CHOP_TARGET_<FIELD>`. Literal target rows may include `overrides:` for per-target
chop fields such as `run_every` and trigger thresholds.

`inhibit_if` accepts keyed `patch`, `agent_hood`, `agent_clan`, and `agent_runners`
providers. The legacy `changespec` key remains accepted as an alias. The clan provider
requires a case-sensitive `name_prefix` and checks canonical clan metadata for active
agents, including waiting members; it never infers clans from dotted names.
`agent_runners.max` defaults to `0` and inhibits while more than that many agents hold
runner slots, the same population counted by `%wait(runners=N)` and the ACE
runner-capacity chip. A `STARTING` agent has not yet been admitted and does not count;
an agent parked on a question has yielded its slot and does not count. `trigger` accepts
`always` or `git.commits_since`; the git provider requires `project` and `threshold`,
and its checkpoint policy is `on_observation`, `on_action_accepted`, or
`on_action_success`. Skips are recorded with reasons. Manual runs bypass the trigger but
honor guards; with `agent_runners`, a manual run while agents hold runner slots skips
unless `sase axe chop run -f/--force` is used. `once_per` can be a key template string
or an object with `key` and bounded `capacity`; proposal-supplied `dedupe_key` values
take precedence. When dedupe removes a proposal from a `wait_on` chain, AXE walks
through the skipped dependencies to the nearest earlier proposal that survives
filtering. If none survives, AXE removes the wait. Proposal previews expose the
resulting `wait_on` value and explain a relink in `dedupe_reason`.

The builtin `sase_chop_refresh_docs` emits an update proposal plus a polish proposal
that waits for the update. It uses the target source's `workspace`, while cadence and
commit thresholds stay declarative in configuration. Its default prompts are strictly
documentation-scoped and tell agents to report suspected code bugs instead of fixing
them. The defaults can be replaced with non-blank `vars.prompt` and `vars.polish_prompt`
strings; operators are responsible for the scoping language in replacement prompts. See
[Axe structured results and launch proposals](axe.md#structured-results-and-launch-proposals)
for the result document, proposal fields, lifecycle statuses, and debugging commands.

Every chop entry must carry a `description` following the
[description grammar](axe.md#description-grammar). Bare-string list entries are no
longer valid because they cannot carry one; use map form or object-form list entries:

```yaml
chops:
  # Object-form list entry
  - name: hook_checks
    script: sase_chop_hook_checks
    description: Check for completed or failed hooks
  - name: custom_chop
    script: my_full_executable_name
    description: Run custom analysis
    run_every: "1h30m"
    env:
      MY_API_KEY: { env: MY_API_KEY }
```

CLI flags on `sase axe start` override `max_hook_runners`, `max_agent_runners`,
`zombie_timeout_seconds`, and `query` for a single run (see [CLI Flags](#cli-flags)).

Source: `src/sase/axe/config.py`, `src/sase/default_config.yml`

### file_hooks

Defines non-gating commands that run once per matching file event. Use
`sase file-hook list` to inspect the effective hooks, including the config layer that
contributed each entry; add `-j/--json` for machine-readable output.

```yaml
file_hooks:
  - name: research-highlights
    description: Render new research reports into Highlights PDFs.
    command: bob highlights create
    filters:
      projects: [sase]
      sidecars: [research]
      path_globs: ["20*/**/*.md", "!20*/*/*__*.md"]
      agent_name_globs: ["!research.*.cld", "!research.*.cdx"]
      ops: [ADD]
    timeout: 120s
```

Hook fields:

| Field         | Type     | Required | Default           | Description                                                                                           |
| ------------- | -------- | -------- | ----------------- | ----------------------------------------------------------------------------------------------------- |
| `use`         | string   | no       | -                 | Installed `sase_file_hooks` provider, qualified `<plugin>@<id>`, whose template supplies base fields. |
| `name`        | string   | yes\*    | provider ID       | Unique lowercase slug shown in notifications and `sase file-hook list`.                               |
| `description` | string   | no       | provider          | Human-readable purpose for the hook.                                                                  |
| `command`     | string   | yes\*    | provider          | Shell command; the matched absolute file path is appended as its final arg.                           |
| `filters`     | object   | no       | `{}` / provider   | Event-selection criteria. Omitted or empty means unrestricted.                                        |
| `timeout`     | duration | no       | `120s` / provider | Per-run integer duration with an `ms`, `s`, `m`, or `h` suffix.                                       |

Without `use`, `name` and `command` are required. With `use`, SASE deep-merges the local
entry over the installed provider's template, defaults `name` to the provider ID, and
requires any fields the provider marks as local. `use` must be qualified as
`<plugin>@<id>`, where `<plugin>` is the literal `builtin` or the installed distribution
name; a bare, unprefixed, or unknown `use` value disables only that invalid entry, is
reported while `sase file-hook list` loads effective hooks, and also fails
`sase doctor -C config.file_hooks` and `sase validate` so a disappeared hook can never
go unnoticed. A plugin can therefore ship safe defaults while requiring the
machine-specific command or destination in user configuration.

Filter fields under `filters`:

| Field                      | Type         | Required | Default        | Description                                                                                             |
| -------------------------- | ------------ | -------- | -------------- | ------------------------------------------------------------------------------------------------------- |
| `filters.projects`         | list[string] | no       | all projects   | User-facing project names.                                                                              |
| `filters.sidecars`         | list[string] | no       | all repos      | Sidecar role names such as `research`, `plans`, or `beads`.                                             |
| `filters.path_globs`       | list[string] | no       | all files      | Repo-relative POSIX globs; `!` prefixes a veto exclusion.                                               |
| `filters.agent_name_globs` | list[string] | no       | all agents     | SASE agent-name globs matched against the agent that produced the event; `!` prefixes a veto exclusion. |
| `filters.ops`              | list[string] | no       | all operations | Any subset of `ADD`, `MODIFY`, and `REMOVE`.                                                            |
| `filters.causes`           | list[string] | no       | none           | Non-user event causes to accept in addition to ordinary user commits; currently `referenced_by`.        |

Matching semantics:

- **Event sources.** Hooks receive files from commits created by `sase stitch create`,
  commits written through the SDD sidecar commit path, and `sase artifact create`
  (treated as `ADD`).
- **Ops.** Commit operations come from `git diff --name-status`; renames split into
  `REMOVE` plus `ADD`, root-commit files are `ADD`, and unknown status letters fold to
  `MODIFY`.
- **Path glob matching.** `filters.path_globs` match the file's repo-root-relative POSIX
  path. Positive globs are OR-ed, while any matching `!` negative veto-excludes the
  file. `*` does not cross `/`; `**` does. A negative-only list means “everything
  except.” Dotfiles are eligible.
- **Agent-name matching.** `filters.agent_name_globs` match the resolved SASE agent
  name. Positives are OR-ed and `!` vetoes, exactly as for paths. Agent names contain no
  `/`, so `*` spans the whole name (`research.*.cld` matches `research.7.cld`). An event
  with no resolvable agent name matches a negative-only list, but never a list
  containing any positive pattern.
- **Attribution.** The agent name is resolved in the producing process from
  `$SASE_ARTIFACTS_DIR/agent_meta.json`'s `name`, falling back to `$SASE_AGENT_NAME`, so
  a commit made outside a SASE agent has no agent name.
- **Causes.** Ordinary user-originated commits always remain eligible. Internally
  generated commits are ignored unless their cause appears in `filters.causes`; the
  current non-user cause is `referenced_by`, used when SASE updates managed
  `Referenced By` blocks in artifact sidecars. This opt-in prevents a projection update
  from recursively triggering ordinary document-processing hooks.
- **Filters.** All configured dimensions are AND-ed. `filters.projects` compares
  alias-resolved, user-facing project names, never ProjectSpec keys. `filters.sidecars`
  compares sidecar role names. A project-local `sase/sase.yml` declaration without
  `filters.projects` is automatically scoped to the detected project.
- **Execution.** Runs are post-commit and non-gating. Hook failures never fail or block
  a commit. Each matched command runs with the absolute path appended as a shell-quoted
  final argument and reports success or failure through a SASE notification.

The user layer (`~/.config/sase/sase.yml`) replaces the bundled/default `file_hooks`
list. Selected machine overlays (`sase_*.yml`) and project-local `sase/sase.yml`
concatenate entries onto the effective list, matching `mentor_profiles` merge behavior.
Hook names must remain unique across the effective list; invalid or duplicate entries
are warned about and skipped. Unknown `file_hooks` keys are rejected the same way, so a
hook carrying one is skipped with a warning rather than silently losing that filter.
Filter fields at the hook top level are no longer accepted; move `projects`, `sidecars`,
`path_globs`, `agent_name_globs`, `ops`, and `causes` under `filters`. Note that `globs`
was renamed to `filters.path_globs`; the old key is not accepted.

Source: `src/sase/config/file_hooks.py`, `src/sase/config/sase.schema.json`

### plugins

Declares the distributions this project needs installed in the running environment. A
linked or sidecar checkout is not an install.

```yaml
plugins:
  required:
    - sase-github
    - sase-research-artifacts>=0.2
```

| Field              | Type     | Default | Description                                                                                        |
| ------------------ | -------- | ------- | -------------------------------------------------------------------------------------------------- |
| `plugins.required` | string[] | `[]`    | PEP 508 requirement strings checked against installed distributions. Duplicate names are an error. |

Every non-`builtin` `<plugin>@` prefix used anywhere in this project config — artifact
references, file hooks, and `bead.task_types[].use` — must name a distribution listed
here. That single rule keeps a project's declared dependencies honest.

Enforcement is graded by blast radius:

| Surface                                                          | Behavior                                                                                         |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `sase memory init`, `sase validate`                              | Hard error, raised before any memory-drift comparison so a missing plugin never looks like drift |
| `sase bead create -T 'task(<slug>)'` for a missing plugin's slug | Hard error naming the plugin and `sase plugin install <name>`                                    |
| `sase doctor -C plugins.required`                                | `ERROR` severity, listing each missing requirement and the install command                       |
| Interactive human CLI and ACE                                    | A `PluginsRequired` gate offering to install                                                     |
| Agent / non-interactive contexts                                 | Fail closed with the human-directed command; never auto-install                                  |
| `sase bead show` / `list` of an unknown type                     | Degraded render, never a failure                                                                 |

`use:` values themselves must be qualified as `<plugin>@<id>`, where `<plugin>` is the
literal `builtin` or a distribution name. A bare value is a hard error that names the
correct replacement when the live registry can resolve it.

See [Task Types](beads.md#task-types) for how required plugins feed the committed
`sase/task_types.json` snapshot, and
[Required Plugin Notification](notifications.md#required-plugin-notification) for the
human install offer.

Source: `src/sase/plugins/required.py`, `src/sase/config/sase.schema.json`

### mentor_profiles

Defines mentor agents that run automated code reviews when a Patch's diff, changed
files, or amend notes match configurable criteria. Each profile groups one or more
mentors with shared matching rules. See [docs/mentors.md](mentors.md) for the full
mentor system reference.

```yaml
mentor_profiles:
  - profile_name: python_review
    file_globs:
      - "*.py"
    mentors:
      - mentor_name: style_checker
        role: "Python style expert"
        focus_areas:
          - focus_name: style
            description: "PEP 8 compliance and code style"
          - focus_name: naming
            description: "Variable and function naming conventions"

  - profile_name: first_commit_review
    first_commit: true
    mentors:
      - mentor_name: architecture
        role: "Software architect"
        focus_areas:
          - focus_name: design
            description: "Overall design and architectural patterns"
```

**Profile fields:**

| Field                | Type         | Required | Description                                                                   |
| -------------------- | ------------ | -------- | ----------------------------------------------------------------------------- |
| `profile_name`       | string       | yes      | Unique name identifying this profile.                                         |
| `mentors`            | list         | yes      | List of mentor definitions (see below).                                       |
| `file_globs`         | list[string] | no\*     | Glob patterns matched against changed file paths.                             |
| `diff_regexes`       | list[string] | no\*     | Regex patterns matched against the diff content.                              |
| `amend_note_regexes` | list[string] | no\*     | Regex patterns matched against commit/amend notes.                            |
| `first_commit`       | bool         | no       | If true, match only on the first commit of a Patch.                           |
| `projects`           | list[string] | no       | Only match Patches in these projects. Auto-set for local `sase.yml` profiles. |

\*At least one of `file_globs`, `diff_regexes`, `amend_note_regexes`, or `first_commit`
must be provided per profile.

**Mentor fields:**

| Field         | Type         | Required | Description                                                 |
| ------------- | ------------ | -------- | ----------------------------------------------------------- |
| `mentor_name` | string       | yes      | Unique name identifying this mentor within its profile.     |
| `role`        | string       | yes      | Role or persona for the mentor (e.g., "Security reviewer"). |
| `focus_areas` | list[object] | yes      | List of review focus areas (see below).                     |

**Focus area fields:**

| Field         | Type   | Required | Description                                           |
| ------------- | ------ | -------- | ----------------------------------------------------- |
| `focus_name`  | string | yes      | Short name for this focus area (e.g., "correctness"). |
| `description` | string | yes      | Description of what this focus area reviews.          |

Mentors run automatically on Patches with Ready or Mailed status when their matching
criteria are met. Mentor comments are structured JSON with severity levels (error,
warning, suggestion) that can be reviewed and applied through the ACE TUI's Mentor
Review modal (`,C`).

Source: `src/sase/config/mentor.py`

### metahooks

Metahooks intercept failing hooks before the summarize agent runs. They match based on
the hook command (substring match) and the hook output (regex match). When a metahook
matches, it can trigger specialized handling instead of the default summarization.

```yaml
metahooks:
  - name: scuba
    hook_command: sase_hg_presubmit
    output_regex: "SCUBA_ERROR.*timeout"

  - name: flaky_test
    hook_command: blaze test
    output_regex: "FLAKY"
```

| Field          | Type   | Required | Description                                            |
| -------------- | ------ | -------- | ------------------------------------------------------ |
| `name`         | string | yes      | Unique identifier for this metahook.                   |
| `hook_command` | string | yes      | Substring matched against the executed hook command.   |
| `output_regex` | string | yes      | Regex pattern matched against hook output (multiline). |

Source: `src/sase/config/metahook.py`

### xprompts

Defines reusable prompt snippets that can be referenced with `#name` syntax in any
prompt. Supports both simple string content and structured definitions with typed inputs
and Jinja2 templates.

```yaml
xprompts:
  # Simple string format
  greeting: "Hello, please review this code."

  # Structured format with inputs
  review:
    input:
      language: word
      strict: { type: bool, default: false }
    content: "Review this {{ language }} code.{{ ' Be strict.' if strict }}"

  # With tags for semantic role lookup
  my_crs:
    content: "Summarize the code review..."
    tags: [crs]
```

Xprompts use the shared first-wins content-layout order:

1. Project `sase/xprompts/`, then legacy project `.xprompts/` and `xprompts/`
2. Home `~/sase/xprompts/`, then legacy home `~/.xprompts/` and `~/xprompts/`
3. `~/sase/xprompts/{project}/`, then legacy `~/.config/sase/xprompts/{project}/`
4. Project `sase/sase.yml` (root `sase.yml` is an exclusive legacy fallback)
5. User `sase_*.yml` overlays, then `~/.config/sase/sase.yml`
6. Plugin config and package default config
7. Plugin xprompt resources
8. `<sase_package>/default_xprompts/*.md`, then `<sase_package>/xprompts/*.md`

Earlier sources win on name conflicts. Project and home canonical directories are the
only writable filesystem destinations; legacy directories remain read-compatible but are
not offered for new saves. File-based xprompts use YAML front matter for metadata and
the file body for content. The [XPrompt discovery table](xprompt.md#discovery-order)
lists every source separately.

Source: `src/sase/xprompt/loader.py`

### xprompt_aliases

Defines raw text-level alias substitutions that are applied _before_ any xprompt
processing. This is useful for creating shorthand references where the alias must be
present in the raw text for other processing logic (such as VCS directory-switching) to
work correctly.

```yaml
xprompt_aliases:
  c: commit # #c → #commit
  p: propose # #p → #propose
  gh_sase: "gh:sase" # #gh_sase → #gh:sase
  gh_foo: "gh:foo/bar" # #gh_foo → #gh:foo/bar
```

| Field             | Type         | Default                   | Description                                                  |
| ----------------- | ------------ | ------------------------- | ------------------------------------------------------------ |
| `xprompt_aliases` | dict[string] | `{c: commit, p: propose}` | Mapping of alias name → target. Applied as text substitution |

The built-in defaults provide `#c` as a shorthand for `#commit` and `#p` for `#propose`.
Additional aliases can be added in user config files.

Each entry maps an alias name to a target string. When the processor encounters
`#alias_name` in a prompt, it replaces it with `#target` before any other xprompt
resolution occurs. Only `#`-prefixed references are substituted; the alias name must
match `[a-zA-Z_][a-zA-Z0-9_]*`.

Source: `src/sase/xprompt/processor.py`

### use_chezmoi

Enables chezmoi-aware home-file writes. When set to `true`, SASE writes generated home
instructions, memory, skills, and home-directory xprompt paths through the chezmoi
source tree under `~/.local/share/chezmoi/home/` instead of writing the live home files
directly. Canonical `~/sase/xprompts/` and `~/sase/memory/` map to source paths
`home/sase/xprompts/` and `home/sase/memory/`. The unchanged global config still maps to
`home/dot_config/sase/sase.yml`.

This affects initialization workflow as well as xprompt editing. `sase memory init`
targets the chezmoi home source root when it needs to initialize home-level `AGENTS.md`,
writes home memory there, and may run the configured chezmoi deploy path;
`sase skill init` writes provider skill files there before optional commit, push, and
apply steps.

Home-level provider instruction files (`CLAUDE.md`, `GEMINI.md`, `QWEN.md`,
`OPENCODE.md`) in the chezmoi source are written as static `.md` files that are
byte-for-byte copies of the root's generated `AGENTS.md`. Because the inlined
`AGENTS.md` carries no template variables, the chezmoi source uses a static preferred
file rather than a `*.md.tmpl` import; legacy `*.md.tmpl` shims that imported
`@{{ .chezmoi.homeDir }}/AGENTS.md` are still recognized and migrated to full copies.

```yaml
use_chezmoi: true # default: false
```

| Field         | Type | Default | Description                                                         |
| ------------- | ---- | ------- | ------------------------------------------------------------------- |
| `use_chezmoi` | bool | `false` | Write home-managed SASE files through the chezmoi source directory. |

Source: `src/sase/config/core.py`

### commit_hooks

Shell commands that bracket commit-producing VCS dispatches. `before` runs in the
repository root after bead and plan mutations but before diff capture and dispatch.
`after` runs in the repository root only after `create_commit` or `create_pull_request`
succeeds, including its push where applicable. Proposals run `before` but never run
`after` because they save a diff without creating a commit.

Both fields default to an empty string. Because the object is deep-merged, a global
`before` hook and project-local `after` hook compose without either configuration
repeating the other phase.

```yaml
commit_hooks:
  before: "just fix" # default: ""
  after: "chezmoi update -a --force" # default: ""
```

| Field                 | Type   | Default | Description                                                                |
| --------------------- | ------ | ------- | -------------------------------------------------------------------------- |
| `commit_hooks.before` | string | `""`    | Command before diff capture and VCS dispatch. Empty means disabled.        |
| `commit_hooks.after`  | string | `""`    | Command after a commit/PR dispatch and push succeed. Empty means disabled. |

Hook output is captured and a bounded stdout/stderr tail is printed on failure. A
failing `before` hook aborts before dispatch. A failing `after` hook leaves the commit
checkpoint in place and returns failure even though the commit may already be pushed;
fix the command and run `sase stitch create --resume`. The completed after-hook step is
checkpointed so a normal resume does not rerun it. A crash after the external command
succeeds but before that checkpoint write can run it again, so `after` commands must be
safe to repeat.

Source: `src/sase/default_config.yml`, `src/sase/workflows/commit/commit_hooks.py`,
`src/sase/workflows/commit/workflow.py`

### max_running_agents

The configured global cap on concurrently occupied runner slots across all projects. A
**runner slot is held by one running sase agent.** A standalone agent holds one slot. A
serial agent family holds one slot for as long as any of its shells is live — the root,
a serial child, a monitor proc shell, or a post-handoff `--next` agent — regardless of
which shell that is and whether earlier shells have exited. Independently launched clan
members each hold one slot. Each live parallel family member holds its own slot.

Holding a slot and waiting for one are separate questions. Roots and live parallel
family members wait at the admission gate. Serial family members — including monitors
and monitor follow-ups — inherit the slot their family already holds and never park.
Workflow Python/bash steps and axe Patch runners hold none of these slots; axe runners
continue to use their separate `axe.max_*_runners` limits. An unanswered participant at
`QUESTION` temporarily yields its family's slot. After the user answers, it must
reacquire against the current effective cap before follow-up work resumes and may
therefore appear as a runner-slot `QUEUED` row.

On a host that uses monitors heavily, the same `max_running_agents` value now admits
fewer new agents than it did before this occupancy rule: a monitor is not a way to free
capacity. Raising the value (persistently in this field, or temporarily from Launch
Control) is the supported response. The packaged default remains `10`.

```yaml
max_running_agents: 10
```

| Field                | Type | Default | Minimum | Description                                                       |
| -------------------- | ---- | ------- | ------- | ----------------------------------------------------------------- |
| `max_running_agents` | int  | `10`    | `1`     | Configured maximum concurrent occupied runner slots on this host. |

The effective cap is an active machine-wide temporary override first and this merged
configured value second. In Launch Control, fixed `Ctrl+R` opens **Max Running Agents**:
`e` previews and writes the user-base/chezmoi source, `o` chooses a relative, custom,
until-cleared, or exact-time override, and `x` clears it. Temporary state is stored as a
versioned record at `~/.sase/max_running_agents_override.json`; a new set replaces the
previous value, expiry is enforced at its deadline, and a persistent edit leaves an
active override in force. Lowering the effective value is non-preemptive, so existing
agents continue and new implicit-cap launches wait for occupancy to drain. Parked
implicit waiters and question continuations reread the effective cap on each normal
poll. An explicit `%wait(runners=N)` keeps its own initial-admission threshold and may
be either stricter or looser than the global cap.

### max_agent_pipe_chain

The bound on how many times one agent family may hand its turn forward with `sase pipe`.
The originally launched agent is depth `0`; each successful pipe records `pipe_depth` on
the successor and increments it by one. A pipe is refused when the next link would
exceed this value, and the refusal names the limit, this configuration key, and the
chain length already reached. The calling agent stays alive on a refusal, so it can
finish the work itself instead of handing it on.

```yaml
max_agent_pipe_chain: 8
```

| Field                  | Type | Default | Minimum | Description                                         |
| ---------------------- | ---- | ------- | ------- | --------------------------------------------------- |
| `max_agent_pipe_chain` | int  | `8`     | `1`     | Maximum `sase pipe` hops in one agent family chain. |

This is a configuration field rather than a feature flag: the number is one users choose
permanently to stop a self-piping chain from running away. A missing or malformed value
falls back to the packaged default rather than allowing an unbounded chain. Only
`sase pipe` records `pipe_depth`, so a plan-approval, question, or monitor follow-up
member created in between starts the count over at `0`. The bound is per family chain,
not per host, so it is unrelated to the concurrency cap in
[max_running_agents](#max_running_agents).

Source: `src/sase/default_config.yml`, `src/sase/config/core.py`,
`src/sase/main/pipe_handler.py`

### runner_slots

Bounded deference for deprioritized runner-slot waiters. Admission sorts eligible
waiters by lower numeric `%wait(priority=N)` first, but that sort only compares agents
already parked at the instant a slot frees. Dependency-chained work joins the queue
seconds after its predecessor exits, so a long-parked deprioritized waiter would
otherwise reliably win that race against exactly the normal-priority work it was meant
to yield to. A waiter whose priority is numerically **worse than** the `10` default
therefore holds back for a bounded window instead of claiming the moment it becomes
eligible, which gives a better-priority agent time to park and win through the existing
sort.

```yaml
runner_slots:
  deference_seconds_per_step: 3
  deference_max_seconds: 60
```

| Field                                     | Type | Default | Minimum | Description                                                          |
| ----------------------------------------- | ---- | ------- | ------- | -------------------------------------------------------------------- |
| `runner_slots.deference_seconds_per_step` | int  | `3`     | `0`     | Seconds of deference added per priority step worse than the default. |
| `runner_slots.deference_max_seconds`      | int  | `60`    | `0`     | Upper bound on the deference window regardless of priority.          |

The window is `min((priority - 10) * deference_seconds_per_step, deference_max_seconds)`
seconds. With the defaults, `priority=20` defers for up to 30s and any priority at or
beyond `30` clamps to the 60s cap. Priority `10` is the boundary and it is inclusive:
default-priority and better-priority waiters (`priority <= 10`) never defer and claim on
the first eligible poll exactly as before. The asymmetry is deliberate—you cannot defer
to work that may never arrive, so only an agent that explicitly volunteered to be
deprioritized pays a delay.

Deference measures **continuous** eligibility, not total time parked. The window starts
when the waiter first becomes eligible while a better-priority agent is pending, and it
resets whenever the waiter stops being eligible, so time spent parked behind a full cap
never counts toward it. It also exits early: on any poll where no live, unstarted,
not-yet-parked agent with a better priority remains, the waiter claims immediately
instead of serving out the rest of the window. The agent log prints one
`Deferring for up to Ns (priority N)` line on entry into the window.

Both fields are read fail-open. Deference is a politeness optimization, so a missing,
non-integer, negative, or unreadable value falls back to the built-in default rather
than propagating an error. This differs deliberately from `max_running_agents`, where
configuration errors do propagate: a bad value here must never strand a runner.

Bounded deference is not priority aging and not preemption. A running agent is never
stopped to make room, and a deferred waiter's own priority does not improve while it
waits. See [Agent waiting for a runner slot](troubleshooting/runner-slots.md) for
diagnosis, and [`%wait(priority=N)`](xprompt.md#supported-directives) for the directive
itself.

### procs

Durable proc records live in `~/.sase/procs/procs.jsonl`, with combined output logs
under `~/.sase/procs/logs/`. Retention keeps every pending or running proc plus the
newest configured number of finished procs. Lowering the limit trims the oldest finished
rows and their logs; active work is never pruned. The legacy `tasks.history_limit` key
is still honored as a deprecated alias.

```yaml
procs:
  history_limit: 100
```

| Field                 | Type | Default | Minimum | Description                                 |
| --------------------- | ---- | ------- | ------- | ------------------------------------------- |
| `procs.history_limit` | int  | `100`   | `1`     | Number of finished procs to preserve.       |
| `tasks.history_limit` | int  | `100`   | `1`     | Deprecated alias for `procs.history_limit`. |

### markdown

The column width SASE wraps generated Markdown prose at. It governs every Markdown
surface SASE writes or renders itself: plan files, bead notes and pages, memory shims
and the generated `AGENTS.md`/provider instruction files, generated skills, prompt
archives, SDD documents, and the default `--wrap` for `sase bead show` and
`sase plan show`. The value is resolved on each call, so an edit takes effect on the
next command without restarting anything.

Values below the minimum, of the wrong type, or in a malformed config fall back to the
shipped default rather than raising: a broken `sase.yml` must never turn
`sase plan propose` into a traceback.

```yaml
markdown:
  print_width: 88
```

| Field                  | Type | Default | Minimum | Description                                          |
| ---------------------- | ---- | ------- | ------- | ---------------------------------------------------- |
| `markdown.print_width` | int  | `88`    | `20`    | Column width SASE wraps generated Markdown prose at. |

The minimum of `20` is the floor below which SASE's display wrapper stops wrapping
entirely, so a smaller value would silently do nothing.

**Sharp edge: the prettier CLI cannot read this field.** `prettier` (via `just fmt-md`,
CI, or an editor integration) discovers its configuration from files on disk — a repo's
`package.json`, `.prettierrc`, and friends — and those declarations mirror SASE's
_shipped default_, not your effective configured value, so that a stock checkout is
self-consistent for a contributor with no SASE config at all. If you configure a
non-default `markdown.print_width` and then run `sase init` inside a repo whose prettier
config still declares the default, the regenerated `AGENTS.md` will be wrapped at your
width and that repo's `fmt-md-check` will fail on it. Change the repo's prettier config
to match, or leave the field at its default.

### timezone

The timezone that governs all SASE wall-clock display and timestamp generation
(notifications, agent logs, artifact/agent-name timestamps, runtime durations, TUI
displays, CLI tables, and generated Markdown pages). Columns or labels that previously
carried a literal `UTC` suffix now render the configured zone abbreviation. When unset,
SASE uses the host **system timezone**, so machines that don't share our timezone
assumptions get sensible behavior out of the box.

```yaml
timezone: "America/New_York" # default: system timezone
```

| Field      | Type   | Default           | Description                                                                        |
| ---------- | ------ | ----------------- | ---------------------------------------------------------------------------------- |
| `timezone` | string | _system timezone_ | IANA timezone name governing all SASE wall-clock display and timestamp generation. |

### chat_install

Configuration for chat-driven update workflows. External chat integrations can call
`sase.integrations.chat_install.start_chat_install_worker()` to run the built-in
`sase update --json` engine in a detached worker. The worker uses the same
managed-vs-dev routing as the TUI Updates tab and the `sase update` CLI, so no custom
update command is required.

```yaml
chat_install:
  timeout_seconds: 900
  restart_attempts: 3
```

| Field                           | Type | Default | Description                                                                |
| ------------------------------- | ---- | ------- | -------------------------------------------------------------------------- |
| `chat_install.timeout_seconds`  | int  | `900`   | Maximum runtime for `sase update --json` before returning exit code `124`. |
| `chat_install.restart_attempts` | int  | `3`     | Number of axe start attempts when axe is not running after the update.     |

Only one chat update worker may run at a time; a lock under
`~/.sase/chat_install/install.lock` rejects concurrent starts. Worker output is written
to timestamped logs under `~/.sase/chat_install/logs/`. The configuration key and state
paths remain named `chat_install` for compatibility. The old `chat_install.command` and
`chat_install.sync_workspace` keys have been removed; delete them from user config if
schema validation reports them. See
[`docs/integrations.md`](integrations.md#chat-update-worker) for the integration-facing
Python API.

Source: `src/sase/default_config.yml`, `src/sase/integrations/chat_install.py`

### telegram

Custom Telegram slash commands are keyed by the bot command name. Define them in user
configuration or an overlay; the Telegram integration deliberately ignores project-local
configuration so a repository cannot add commands to your bot. Core SASE validates the
definitions, and `sase doctor` checks that each command's executable resolves.

```yaml
telegram:
  commands:
    projects:
      description: List enabled SASE projects.
      run: sase project list --state enabled
      output: message
      timeout: 60s
```

| Field                                  | Type   | Default   | Description                                                                    |
| -------------------------------------- | ------ | --------- | ------------------------------------------------------------------------------ |
| `telegram.commands.<name>.description` | string | required  | Slash-menu description, from 1 to 256 characters.                              |
| `telegram.commands.<name>.run`         | string | required  | Executable plus fixed arguments, parsed as an argument vector without a shell. |
| `telegram.commands.<name>.output`      | string | `message` | Deliver Markdown stdout as a `message` or rendered `pdf`.                      |
| `telegram.commands.<name>.timeout`     | string | `60s`     | Integer duration ending in `s`, `m`, or `h`.                                   |

Command names must contain 1–32 lowercase letters, digits, or underscores. The built-in
names `bead`, `beads`, `changes`, `fork`, `kill`, `list`, `update`, and `xprompts` are
reserved. The integration parses `run` as an argument vector and never invokes a shell.
Text following `/name` is appended as one final argument, and the process runs from an
isolated temporary directory, so use absolute paths or commands available on `PATH`
rather than relying on a project working directory.

Run `sase doctor -C integrations.telegram_commands` after editing the map; unresolved
command heads produce a warning with the affected names.

Source: `src/sase/default_config.yml`, `src/sase/doctor/checks_integrations.py`

### tmux_agent {#tmux_agent}

Configuration for [tmux Agent](ace.md#tmux-agent): Launch Control's `t` binding and
`sase tmux-agent`. Both surfaces share this block. A bad value is dropped with a warning
rather than making the tmux key binding fail.

```yaml
tmux_agent:
  # Base tmux window name. The first window is this name; later ones get a
  # numeric suffix (ai, ai2, ai3, ...).
  window_name: "ai"
  # Pass each agent CLI's approval-bypass flags (see the provider's
  # llm_interactive_cli descriptor). Per-provider overrides win.
  bypass_permissions: true
  # Reasoning effort applied to launches. "" follows llm_provider.default_effort;
  # "off" passes no effort flags at all.
  effort: ""
  # Run `clear` in the new window before starting the CLI.
  clear_screen: true
  # Optional shell command run after an agent CLI window closes, alongside
  # SASE's own window renumbering. Empty means nothing extra runs.
  after_close_command: ""
  # Per-provider overrides, keyed by registered provider name.
  providers:
    claude:
      enabled: true # false hides the provider from both surfaces
      key: "" # override the single-key menu shortcut
      model: "" # pin a model, e.g. "gemini-3.7-flash-high"
      effort: "" # per-provider effort; "" inherits, "off" disables
      args: [] # extra CLI args appended verbatim
      env: {} # environment variables for the new tmux window
      bypass_permissions: true # omit to inherit the global default
```

| Field                                            | Type    | Default | Description                                                                                             |
| ------------------------------------------------ | ------- | ------- | ------------------------------------------------------------------------------------------------------- |
| `tmux_agent.window_name`                         | string  | `"ai"`  | Base tmux window name. First window is this name; later ones get a numeric suffix (`ai2`, `ai3`).       |
| `tmux_agent.bypass_permissions`                  | bool    | `true`  | Pass each agent CLI's approval-bypass flags. The resolved command always shows whether bypass is on.    |
| `tmux_agent.effort`                              | string  | `""`    | Effort applied to launches. `""` follows `llm_provider.default_effort`; `"off"` passes no effort flags. |
| `tmux_agent.clear_screen`                        | bool    | `true`  | Run `clear` in the new window before starting the CLI.                                                  |
| `tmux_agent.after_close_command`                 | string  | `""`    | Extra shell command run after an agent CLI window closes, alongside SASE's own window renumbering.      |
| `tmux_agent.providers.<name>.enabled`            | bool    | `true`  | `false` hides the provider from both the tmux menu and the ACE panel.                                   |
| `tmux_agent.providers.<name>.key`                | string  | `""`    | Override the single-key menu shortcut. Must be exactly one printable non-whitespace character.          |
| `tmux_agent.providers.<name>.model`              | string  | `""`    | Pin a model (substituted into the provider's `model_args`).                                             |
| `tmux_agent.providers.<name>.effort`             | string  | `""`    | Per-provider effort; `""` inherits the global `tmux_agent.effort`; `"off"` disables effort flags.       |
| `tmux_agent.providers.<name>.args`               | list    | `[]`    | Extra CLI args appended verbatim after the resolved launch argv.                                        |
| `tmux_agent.providers.<name>.env`                | mapping | `{}`    | Environment variables for the new tmux window; user values win over the provider descriptor.            |
| `tmux_agent.providers.<name>.bypass_permissions` | bool    | inherit | Omit to inherit `tmux_agent.bypass_permissions`. `false` launches without bypass args.                  |

`effort` accepts `""`, `"off"`, `"none"`, `"minimal"`, `"low"`, `"medium"`, `"high"`,
`"xhigh"`, and `"max"`. A config-default effort is best-effort: a provider that cannot
honor the level launches without the flag rather than failing. An explicit
`sase tmux-agent -e <level>` that the provider cannot honor is a usage error.

Three per-provider entries are load-bearing if you want the resolved argv to match the
shell script this feature replaces:

```yaml
tmux_agent:
  effort: "max"
  providers:
    claude: { env: { EDITOR: nvim } }
    codex: { effort: "xhigh" }
    grok: { effort: "xhigh" }
    opencode: { effort: "off" }
    agy: { model: "gemini-3.7-flash-high" }
    qwen: { model: "qwen3.6-plus" }
    muse: { model: "muse-spark-1.2" }
```

- `codex` and `grok` cap out at `xhigh`. A config-default effort is best-effort, so
  `effort_cli_args` logs and skips `max` rather than downgrading it — without the
  per-provider `xhigh` they would launch with no effort flag at all, unlike the script.
- `opencode` accepts every level as `--variant <level>`, so a global `max` would add a
  flag the script never passes; `effort: "off"` keeps it bare.
- `agy` and `qwen` need no effort entry: both declare an empty supported-effort map, so
  the global `max` is skipped for them automatically and their argv already matches.
  Their `model` pins reproduce the script's hardcoded models.

`EDITOR=nvim` is a personal preference, not a provider requirement, which is why it
lives on `tmux_agent.providers.claude.env` rather than in the Claude plugin.

Source: `src/sase/default_config.yml`, `src/sase/config/tmux_agent.py`

### mobile_gateway

Configuration for `sase mobile gateway start`, which launches the workstation-hosted
Rust gateway for paired mobile clients.

```yaml
mobile_gateway:
  bind_address: "127.0.0.1"
  port: 7629
  state_dir: ""
  allow_non_loopback: false
  command: ""
  push_provider: "disabled"
  fcm_project_id: ""
  fcm_service_account_json: ""
  fcm_credential_env: ""
  fcm_dry_run: false
  push_timeout_seconds: 5
  push_retry_limit: 1
  startup_timeout_seconds: 10
```

| Field                                     | Type   | Default       | Description                                                               |
| ----------------------------------------- | ------ | ------------- | ------------------------------------------------------------------------- |
| `mobile_gateway.bind_address`             | string | `"127.0.0.1"` | Host address to bind. Non-loopback values require explicit opt-in.        |
| `mobile_gateway.port`                     | int    | `7629`        | Gateway HTTP port.                                                        |
| `mobile_gateway.state_dir`                | string | `""`          | SASE state root for gateway storage. Empty uses the Rust gateway default. |
| `mobile_gateway.allow_non_loopback`       | bool   | `false`       | Allow LAN or tailnet binds after explicit user opt-in.                    |
| `mobile_gateway.command`                  | string | `""`          | Gateway binary command override, parsed without a shell.                  |
| `mobile_gateway.push_provider`            | string | `"disabled"`  | Push provider: `disabled`, `test`, or `fcm`.                              |
| `mobile_gateway.fcm_project_id`           | string | `""`          | Firebase project ID for FCM HTTP v1.                                      |
| `mobile_gateway.fcm_service_account_json` | string | `""`          | Local service-account JSON path. Do not commit this file.                 |
| `mobile_gateway.fcm_credential_env`       | string | `""`          | Env var containing an FCM bearer token or service-account JSON.           |
| `mobile_gateway.fcm_dry_run`              | bool   | `false`       | Ask FCM to validate messages without delivering them.                     |
| `mobile_gateway.push_timeout_seconds`     | float  | `5`           | Timeout per push provider HTTP attempt.                                   |
| `mobile_gateway.push_retry_limit`         | int    | `1`           | Retry attempts for best-effort push delivery.                             |
| `mobile_gateway.startup_timeout_seconds`  | float  | `10`          | Seconds to wait for gateway readiness before exiting.                     |

Push payloads are hint-only and must not contain bearer tokens, pairing codes, prompt
bodies, response text, attachment contents, attachment tokens, or host paths. Only
credential paths or environment-variable names are placed on the gateway command line.
See [`docs/mobile_gateway.md`](mobile_gateway.md#push-hints) for setup examples and
security notes.

Source: `src/sase/default_config.yml`, `src/sase/integrations/mobile_gateway.py`

### sdd

Configuration for spec-driven development features, including prompt, tale, epic,
research, and bead storage.

```yaml
sdd:
  bead_refresh:
    mode: background
    ttl_seconds: 120
  repo:
    name: "" # provider-specific sidecar repo override
  push_after_commit: async
```

| Field                          | Type        | Default      | Description                                                                                                                                                                                                                                                                                                                              |
| ------------------------------ | ----------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sdd.bead_refresh.mode`        | string      | `background` | Sidecar bead-store freshness: `background` launches a TTL-gated managed sync after commands, `blocking` pulls before commands, and `off` disables remote refresh, including the live-bead-waiter hint the `sidecar_auto_sync` chop marks and the equivalent hint in the runner's bead-wait fallback. Local dependency rechecks continue. |
| `sdd.bead_refresh.ttl_seconds` | float       | `120`        | Minimum age of the last successful remote integration before another background worker is launched.                                                                                                                                                                                                                                      |
| `sdd.repo.name`                | string      | `""`         | Optional sidecar repo override for providers that support `separate_repo`; accepts `name` or `owner/name`. For GitHub, empty checks only `<owner>/<repo>--sdd`; set `sdd.repo.name` to use another repo such as `sdd` or `owner/sdd`.                                                                                                    |
| `sdd.push_after_commit`        | bool or str | `async`      | Controls `git push` after SDD commits in sidecar repositories: `async`, `true`, or `false`. Local commits are preserved.                                                                                                                                                                                                                 |

The workspace provider owns storage selection. Built-in bare-git projects store SDD
under `sdd/`. Managed GitHub projects use a `--plans` sidecar cloned at
`sase/repos/plans`; every configured document role resolves at `sase/repos/<role>`. The
default-seeded `research` role derives `<owner>/<project>--research`. Current managed
initialization also records a `--beads` sidecar at `sase/repos/beads`. Unmigrated GitHub
projects retain their provider-backed `.sase/sdd/` clone. Materialized layouts record
metadata in the primary workspace's `.sase/sdd-store.json`. Providerless projects fall
back to a primary-workspace `.sase/sdd/` store. The retired `sdd.storage` and
`sdd.version_controlled` keys are ignored, stripped before validation, and reported by
`sase doctor` for cleanup. See [SDD Storage](sdd_storage.md) and [Beads](beads.md).

The default current layout has a schema-version 3 `sidecar_repos` record: every recorded
role resolves to its role-specific clone, and bead state lives at the root of `--beads`.
A record without a beads role remains schema version 2 and resolves bead state to
`beads/` in `--plans`. Ordinary resolution preserves that compatibility shape. Running
managed `sase repo init` with the beads role enabled is the adoption step: it prepares
the dedicated sidecar and writes a schema-version 3 record. A project that disables or
otherwise omits the beads role stays on schema version 2. Initialization prepares
configured sidecars in its current workspace and re-records stale compatibility metadata
with the derived repository. Later workspaces clone lazy document roles on demand. The
legacy single-sidecar shape continues to resolve byte-for-byte as before.

Built-in bare-git projects also auto-create or refresh generated SDD guide files during
first-use `#git:<project>` initialization, existing bare-repo registration,
`#git`/workspace materialization, and the first in-tree SDD write. Setup/materialization
flows commit and push only those generated init paths with an `Initialize SDD` init
commit when needed.

For a repository whose own `sase/sase.yml` sets `is_sase_managed: true`, running
`sase repo init` or its `sase init repo` alias writes managed entries for plans, beads,
research, and agents, initializes configured sidecars, then refreshes generated guides
and the directory map. On GitHub it derives the remotes as `<owner>/<repo>--<role>` for
those four roles while honoring optional explicit `repo` pins. It initializes and pushes
every enabled entry, then maintains the split store record; the agents role is not part
of the SDD store record. Existing legacy `--sdd` files remain untouched locally and in
their remote, while normal SDD routing uses the configured sidecars. `--check` previews
provider and generated-file work without writing. Missing or false management markers
make both forms successful no-ops; invalid local marker configuration fails before
provider calls or writes.

Explicit initialization first performs authoritative provider discovery for every
enabled sidecar. Each missing GitHub repository triggers a separate prompt naming its
role and resolved repository; only `y` or `yes` authorizes that invocation to create it.
The prompts are default-no and unavailable on non-interactive stdin. Bare
`sase init --yes` cannot authorize repository creation: it reports a missing remote and
defers creation to an interactive `sase repo init` without failing automated onboarding.
`--check` remains network-free.

Source: `src/sase/default_config.yml`

### bead

Configuration for the bead issue tracker.

```yaml
bead:
  big_epic_phase_threshold: 5 # minimum authored phase count for llm_provider.big_epic_lander_model
  task_triage:
    min_plus_ones: 1 # +1 reports a ready untyped/undeclared task needs before it earns a TaskTriage gate
    stale_after_days: 7 # age at which a still-sub-threshold ready task bead is stale
    stale_cleanup_min_beads: 10 # stale beads required before bead_stale_cleanup gates
  task_types: [] # optional catalog overrides and project-local types
  epic_resume:
    settle_seconds: 120 # how long a newest clan-member failure must sit before epic_resume gates it
  push_after_commit: true # compatibility field; current bead-work launches do not consult it
```

| Field                                      | Type        | Default | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------------ | ----------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bead.big_epic_phase_threshold`            | int         | `5`     | Minimum total authored phase count that selects `llm_provider.big_epic_lander_model` for an epic without an explicit land model. Must be at least `1`; malformed runtime values defensively fall back to `5`.                                                                                                                                                                                                                                                                                                                                                                             |
| `bead.task_triage.min_plus_ones`           | int         | `1`     | Fallback `+1` bar, applied only to untyped legacy beads and to types that declare no `triage.min_plus_ones` of their own. A typed bead uses its own spec bar instead, which is why this default does not describe most task beads: `flake` ships as `3`, and every other builtin ships as `0`. See [Task Types](beads.md#task-types) for how a bead resolves its bar. Must be at least `0`. Suppression withholds only the gate — a sub-threshold bead stays stored as `ready`, and a gate already raised for a bead that falls below the bar is canceled and its notification dismissed. |
| `bead.task_types`                          | list        | `[]`    | Project catalog entries. `{use: <plugin>@<slug>, ...}` deep-merges sibling keys onto an installed type; a full spec without `use:` defines a new slug and may not shadow a builtin.                                                                                                                                                                                                                                                                                                                                                                                                       |
| `bead.task_triage.stale_after_days`        | int         | `7`     | Days after creation at which a still-sub-threshold ready task bead is considered stale and eligible for the `bead_stale_cleanup` gate. Must be at least `1`.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `bead.task_triage.stale_cleanup_min_beads` | int         | `10`    | Stale beads required across all enabled projects before `bead_stale_cleanup` raises its gate; below this count the chop does nothing. Must be at least `1`.                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `bead.epic_resume.settle_seconds`          | int         | `120`   | Seconds the newest clan-member failure must sit before the beta `epic_resume` chop treats the epic as stalled and eligible for an `EpicResume` gate. Guards against gating on a handoff race or a fast retry. Only takes effect once the `epic_resume_gate` [feature flag](#feature_flags) is enabled; see below.                                                                                                                                                                                                                                                                         |
| `bead.push_after_commit`                   | bool or str | `true`  | Retained in the accepted configuration shape, but the current `sase bead work` path does not read it. Without `--no-push`, bead-ID launches synchronously run managed sync even for an in-tree Git store; a remote-backed detached store additionally requires an actual pre-spawn push.                                                                                                                                                                                                                                                                                                  |

Below the threshold, an epic land agent uses `llm_provider.epic_lander_model`. At or
above it, it uses `llm_provider.big_epic_lander_model` instead. An explicit land model
remains authoritative over both.

See [`bead_task_triage`](axe.md#checks-5-minute-interval) for how the `task_triage`
fields gate `TaskTriage` notifications,
[Task Triage Notification](notifications.md#task-triage-notification) for the
post-upgrade dismissal of already-raised sub-threshold gates,
[Discovered Follow-Up Capture and Triage](beads.md#discovered-follow-up-capture-and-triage)
for the human-facing triage lifecycle, and
[`epic_resume`](axe.md#checks-5-minute-interval) plus
[Stalled Epic Notification](notifications.md#stalled-epic-notification) for how
`settle_seconds` gates a stalled epic once the beta flag is on.

The `epic_resume_gate` feature flag is off by default while the stall detector soaks
against real epics. Enable the beta with:

```bash
sase flag show epic_resume_gate                        # inspect current resolution
sase -f epic_resume_gate axe chop run epic_resume       # force one gated pass without editing config
```

or set `feature_flags.epic_resume_gate: true` in `sase.yml` to enable it durably for the
running axe daemon; see [`feature_flags`](#feature_flags) below for the full resolution
order.

In Launch Control (`,m`), the `big epic starts at` row shows this effective threshold
next to the two epic-lander rows. `e` or Enter opens a focused positive-integer editor,
and `r` previews an unset reset against `bead.big_epic_phase_threshold` in the writable
user-base config or its chezmoi source. There is no temporary override for this setting;
pressing `o` or `x` on the row only reports that Edit/Reset are available.

See [`docs/beads.md`](beads.md#sase-bead-work-target) for the current pre-spawn
checkpoint and publication flow.

Source: `src/sase/default_config.yml`

### external_mirror

Configuration for the external tracker mirror. See
[External Issue Mirroring](beads.md#external-issue-mirroring) and the
[`external_mirror` lane](axe.md#external_mirror-15-minute-interval)'s
`external_issue_mirror` and `external_pr_mirror` chops, the first production use of
`for_each: {source: projects}` fan-out.

One shared filter surface governs which tracker issues become beads
(`external_mirror.issues.filters`) and which remote pull requests become Patches
(`external_mirror.pull_requests.filters`). Each criterion is either a `*_globs` list
(accepting `!`-prefixed exclusions, matched like [`file_hooks`](#file_hooks)'s
`path_globs`) or a `states` enum list. A record matches a criterion if it matches any
positive glob (or the criterion has no positive globs) and matches no negative glob; a
record is mirrored only when every criterion accepts it, and matching is case-folded.
Setting a criterion replaces the shipped defaults for that criterion rather than
appending to them. **Filters gate creation only**: a record a filter now excludes keeps
whatever bead or Patch it already has, the mirror never deletes.

```yaml
external_mirror:
  issues:
    filters:
      author_globs: []
      label_globs: []
      title_globs: []
      states: []
  pull_requests:
    filters:
      author_globs: []
      base_ref_globs: []
      head_ref_globs:
        - "!release-please--*"
        - "!release-please/*"
        - "!release-plz-*"
        - "!release-plz/*"
      title_globs: []
      states: []
```

Pull requests ship with the four `head_ref_globs` exclusions above, so release-please
and release-plz PRs stop becoming Patches by default. Head ref is the key those defaults
filter on rather than author or title: release automation can author as a human account
on some repos, and PR titles are user-configurable, but the release branch name is
stable.

| Field                                                  | Type        | Default                                                                           | Description                                                  |
| ------------------------------------------------------ | ----------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `external_mirror.issues.filters.author_globs`          | list of str | `[]`                                                                              | Issue author globs, including `!`-prefixed exclusions.       |
| `external_mirror.issues.filters.label_globs`           | list of str | `[]`                                                                              | Issue label globs, matched against every label on the issue. |
| `external_mirror.issues.filters.title_globs`           | list of str | `[]`                                                                              | Issue title globs.                                           |
| `external_mirror.issues.filters.states`                | list of str | `[]`                                                                              | Issue states (`open`/`closed`) accepted for mirroring.       |
| `external_mirror.pull_requests.filters.author_globs`   | list of str | `[]`                                                                              | Remote PR author globs.                                      |
| `external_mirror.pull_requests.filters.base_ref_globs` | list of str | `[]`                                                                              | Remote PR base-ref globs.                                    |
| `external_mirror.pull_requests.filters.head_ref_globs` | list of str | `["!release-please--*", "!release-please/*", "!release-plz-*", "!release-plz/*"]` | Remote PR head-ref globs.                                    |
| `external_mirror.pull_requests.filters.title_globs`    | list of str | `[]`                                                                              | Remote PR title globs.                                       |
| `external_mirror.pull_requests.filters.states`         | list of str | `[]`                                                                              | Remote PR states (`open`/`closed`) accepted for adoption.    |

`external_mirror.exclude_labels` and `external_mirror.pr_authors` are deprecated aliases
for `external_mirror.issues.filters.label_globs` (folded in as negated globs) and
`external_mirror.pull_requests.filters.author_globs` (folded in as plain globs),
respectively. The fold applies only when the modern criterion is empty — a non-empty
modern criterion always wins, and the legacy key's value is then ignored.
`sase doctor -C config.external_mirror` flags both a set legacy key and the "set
alongside a non-empty modern criterion" case.

Records a filter drops are visible rather than silently missing:
`sase patch sync-external`'s table gets a `Filtered` column, `sase bead sync-external`'s
per-project line gains `filtered=<n>` when non-zero, and the Patches pane's project
banners show a `· M remote-only` suffix when a filtered-PR count is known.

Source: `src/sase/default_config.yml`

### feature_flags

`feature_flags` is the user and project override surface for code-owned SASE feature
flags. Registry defaults live in `src/sase/feature_flags/registry.py`; the config block
only overrides registered keys.

```yaml
feature_flags:
  coder_inherits_planner_chat: false
  prettier_enabled: true
```

The generated JSON Schema exposes one boolean property per registered flag with its
description and default. Unknown keys are tolerated by the schema so downgraded installs
can still read a config written by a newer SASE, but the resolver warns and ignores
unknown keys at runtime.

Resolution order is registry default, user config, overlay configs, explicit in-process
test overrides, `SASE_FEATURE_FLAGS`, then the root CLI options. Plugin config layers
never flip first-party flag defaults. A local-config entry for any feature flag is
ignored with a `scope_violation` warning: a feature flag cannot be set from the `local`
config layer, because ACE disables project-local config and flags must resolve
consistently across frontends.

Root-level `-f/--enable-feature` and `-F/--disable-feature` force a registered flag on
or off for one `sase` invocation. They must appear before the subcommand
(`sase -f coder_inherits_planner_chat run "..."`). They outrank every config layer and
an inherited `SASE_FEATURE_FLAGS` value, and they merge into `SASE_FEATURE_FLAGS` so
launched agents and other child processes inherit the same overrides.

`SASE_FEATURE_FLAGS` is a strict JSON object of booleans, for example
`{"coder_inherits_planner_chat":true}`. Malformed JSON, a non-object payload, or a
non-boolean value is a startup error for that process. SASE-launched children inherit a
resolved snapshot through the same variable, so `sase flag list` marks env provenance
prominently. CLI overrides are marked the same way (`CLI:--enable-feature` /
`CLI:--disable-feature`).

Create temporary flags with `sase flag new <key>` rather than editing the registry by
hand. The command creates a task bead of type `flag`, prints the registry entry, and
gives the both-states test checklist. Kinds are `beta` (default off) and `sunset`
(default on); the registry default is derived from the kind. See
[Beads](beads.md#flag-bead-lifecycle) for the removal lifecycle.

Source: `src/sase/feature_flags/registry.py`, `src/sase/feature_flags/schema.py`

### workspace

Controls how SASE chooses the physical location of managed workspace checkouts. See
[`docs/workspace.md`](workspace.md#workspace-directory-layout) for the directory-layout
reference and CLI workflows.

```yaml
workspace:
  root: xdg-state # "xdg-state", "adjacent", or an absolute path
  project_key: "" # explicit project-key override; empty = derive from git remote / primary path
  cleanup_ttl_days: 14 # age threshold for `sase workspace cleanup --stale`
```

| Field                        | Type   | Default       | Description                                                                                                                                                                                                                                    |
| ---------------------------- | ------ | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workspace.root`             | string | `"xdg-state"` | Root policy. `"xdg-state"` uses the platform state dir; `"adjacent"` keeps the legacy `<primary>_<num>/` layout as an explicit opt-in; an absolute path is used as the managed-root base. `SASE_WORKSPACE_ROOT` overrides this base directory. |
| `workspace.project_key`      | string | `""`          | Override the per-project namespace under managed roots. Empty derives a stable key from a single git remote slug or the primary-path basename plus a short hash.                                                                               |
| `workspace.cleanup_ttl_days` | int    | `14`          | Minimum age (in days) of an unclaimed managed checkout before `sase workspace cleanup --stale` will remove it.                                                                                                                                 |

Platform defaults for the `xdg-state` policy:

| Platform | Managed root                                                                       |
| -------- | ---------------------------------------------------------------------------------- |
| Linux    | `$XDG_STATE_HOME/sase/workspaces` (falls back to `~/.local/state/sase/workspaces`) |
| macOS    | `~/Library/Application Support/sase/workspaces`                                    |
| Windows  | `%LOCALAPPDATA%\sase\workspaces`                                                   |

Numeric identity is the same on every root policy: `#0` is the primary checkout,
`#1`–`#9` are reserved, and managed claim workspaces start at `#10`. See
[`docs/workspace.md`](workspace.md#numeric-identity) for the full identity model and
backup/container/NFS caveats.

For non-adjacent policies, physical checkouts live under
`<managed-root>/<project_key>/<project>_<num>/`. For example,
`workspace.root: /mnt/sase-workspaces` with project key `github.com_org_repo` places
workspace `#10` at `/mnt/sase-workspaces/github.com_org_repo/<project>_10/`. When
`SASE_WORKSPACE_ROOT` is set, it supplies the same `<managed-root>` base for the
process.

Existing adjacent checkouts are not moved automatically by the default. Run
`sase workspace migrate --to xdg-state` to carry legacy `<primary>_<num>/` directories
into the managed root, or set `workspace.root: adjacent` explicitly to keep the old
sibling layout.

`sase repo open <primary-repo> -w NUM -r "<reason>"` is an explicit preparation command
for a checkout you plan to use outside a normal `sase run` launch. It uses the same root
policy when it materializes the checkout, backs up uncommitted local changes through the
active VCS provider, cleans the checkout, checks out and syncs the provider default
parent revision, and prints the resulting path. For manual scratch work, choose a
claim-range number such as `10`; `#0` is the primary checkout and `#1` through `#9` are
reserved compatibility numbers.

Source: `src/sase/default_config.yml`, `src/sase/workspace_provider/store.py`

### telemetry

Configures local telemetry recording and retention. See
[docs/telemetry.md](telemetry.md) for the full telemetry reference, including the CLI,
metric catalog, local store, and Admin Center tab.

```yaml
telemetry:
  enabled: true
  flush_interval_seconds: 15
  retention:
    raw_seconds: 172800
    rollup_5m_seconds: 2592000
    rollup_1h_seconds: 31536000
  health_thresholds:
    error_rate_warn: 10.0
    error_rate_critical: 25.0
    retry_rate_warn: 10.0
    retry_rate_critical: 25.0
    p95_latency_warn: 300.0
    p95_latency_critical: 600.0
```

| Field                                              | Type  | Default    | Description                                      |
| -------------------------------------------------- | ----- | ---------- | ------------------------------------------------ |
| `telemetry.enabled`                                | bool  | `true`     | Enable or disable local telemetry recording.     |
| `telemetry.flush_interval_seconds`                 | float | `15`       | Flush interval for long-lived processes.         |
| `telemetry.retention.raw_seconds`                  | int   | `172800`   | Retain raw samples for 48 hours.                 |
| `telemetry.retention.rollup_5m_seconds`            | int   | `2592000`  | Retain five-minute rollups for 30 days.          |
| `telemetry.retention.rollup_1h_seconds`            | int   | `31536000` | Retain hourly rollups for one year.              |
| `telemetry.health_thresholds.error_rate_warn`      | float | `10.0`     | Error rate % threshold for WARN health status.   |
| `telemetry.health_thresholds.error_rate_critical`  | float | `25.0`     | Error rate % threshold for CRITICAL status.      |
| `telemetry.health_thresholds.retry_rate_warn`      | float | `10.0`     | Retry rate % threshold for WARN health status.   |
| `telemetry.health_thresholds.retry_rate_critical`  | float | `25.0`     | Retry rate % threshold for CRITICAL status.      |
| `telemetry.health_thresholds.p95_latency_warn`     | float | `300.0`    | P95 latency threshold (seconds) for WARN status. |
| `telemetry.health_thresholds.p95_latency_critical` | float | `600.0`    | P95 latency threshold (seconds) for CRITICAL.    |

Source: `src/sase/default_config.yml`, `src/sase/telemetry/_config.py`

### update

Configures install-mode switching (see
[Install mode switching](plugins.md#install-mode-switching)).

```yaml
update:
  dev_root: "~/projects/github"
```

| Field             | Type | Default             | Description                                                                                               |
| ----------------- | ---- | ------------------- | --------------------------------------------------------------------------------------------------------- |
| `update.dev_root` | str  | `~/projects/github` | Base directory for dev-mode editable checkouts, materialized owner-nested as `<dev_root>/<owner>/<repo>`. |

Source: `src/sase/default_config.yml`, `src/sase/mode_switch/repos.py`

## Environment Variables

### LLM Provider

| Variable                                 | Description                                                                         |
| ---------------------------------------- | ----------------------------------------------------------------------------------- |
| `SASE_MODEL_TIER_OVERRIDE`               | Force all LLM invocations to a specific tier (`large` or `small`).                  |
| `SASE_MODEL_SIZE_OVERRIDE`               | Legacy alias for `SASE_MODEL_TIER_OVERRIDE` (`big` or `little`).                    |
| `SASE_LLM_EXEC_PROVIDER`                 | Execute through this registered provider while preserving requested model metadata. |
| `SASE_LLM_LARGE_ARGS`                    | Extra CLI args appended for `large` tier invocations (any provider).                |
| `SASE_LLM_SMALL_ARGS`                    | Extra CLI args appended for `small` tier invocations (any provider).                |
| `SASE_CLAUDE_LARGE_ARGS`                 | Claude-specific extra args for `large` tier (fallback if generic unset).            |
| `SASE_CLAUDE_SMALL_ARGS`                 | Claude-specific extra args for `small` tier (fallback if generic unset).            |
| `SASE_CODEX_PATH`                        | Path to the Codex CLI binary (default: PATH lookup, then NVM_BIN/codex).            |
| `SASE_CODEX_LARGE_ARGS`                  | Codex-specific extra args for `large` tier (fallback if generic unset).             |
| `SASE_CODEX_SMALL_ARGS`                  | Codex-specific extra args for `small` tier (fallback if generic unset).             |
| `SASE_CODEX_DISABLE_SHADOW_HOME`         | Set to `1` to launch Codex with the inherited `CODEX_HOME`.                         |
| `SASE_QWEN_PATH`                         | Path to the Qwen Code CLI binary (default: `qwen`).                                 |
| `SASE_QWEN_LARGE_ARGS`                   | Qwen-specific extra args for `large` tier (fallback if generic unset).              |
| `SASE_QWEN_SMALL_ARGS`                   | Qwen-specific extra args for `small` tier (fallback if generic unset).              |
| `SASE_OPENCODE_PATH`                     | Path to the OpenCode CLI binary (default: `opencode`).                              |
| `SASE_OPENCODE_LARGE_ARGS`               | OpenCode-specific extra args for `large` tier (fallback if generic unset).          |
| `SASE_OPENCODE_SMALL_ARGS`               | OpenCode-specific extra args for `small` tier (fallback if generic unset).          |
| `SASE_AGY_PATH`                          | Path to the Antigravity CLI binary (default: `agy`).                                |
| `SASE_AGY_PRINT_TIMEOUT`                 | Override the `agy --print-timeout` Go duration (default: `24h`).                    |
| `SASE_AGY_MAX_NO_PROGRESS_CONTINUATIONS` | Override the no-progress continuation cap (default: `2`).                           |
| `SASE_AGY_LARGE_ARGS`                    | Antigravity-specific extra args for `large` tier (fallback if generic unset).       |
| `SASE_AGY_SMALL_ARGS`                    | Antigravity-specific extra args for `small` tier (fallback if generic unset).       |
| `SASE_MUSE_PATH`                         | Path to the Muse Code CLI binary (default: `muse`).                                 |
| `SASE_MUSE_LARGE_ARGS`                   | Muse-specific extra args for `large` tier (fallback if generic unset).              |
| `SASE_MUSE_SMALL_ARGS`                   | Muse-specific extra args for `small` tier (fallback if generic unset).              |
| `SASE_MUSE_SANDBOX`                      | Set to `on` to keep Muse's sandbox with `--sandbox-network enabled`.                |
| `SASE_GROK_PATH`                         | Path to the Grok Build CLI binary (default: `grok`).                                |
| `SASE_GROK_LARGE_ARGS`                   | Grok-specific extra args for `large` tier (fallback if generic unset).              |
| `SASE_GROK_SMALL_ARGS`                   | Grok-specific extra args for `small` tier (fallback if generic unset).              |

For the per-provider args, the generic `SASE_LLM_*_ARGS` variables are checked first. If
unset, the provider-specific variable is used as a fallback. Values are split on
whitespace and appended to the CLI command.

SASE-launched Codex subprocesses use a disposable shadow `CODEX_HOME` by default. The
shadow home is created under `~/.cache/sase/codex_home/`, receives a copy of the real
`config.toml`, symlinks other Codex home entries back to the real home, and is removed
when the subprocess exits. If the real Codex home does not provide `AGENTS.override.md`
or `AGENTS.md`, SASE also links `~/AGENTS.md` into the shadow as Codex's
`$CODEX_HOME/AGENTS.md` fallback. This prevents Codex runtime config rewrites from
dirtying the user-managed Codex config while preserving auth, hooks, skills, logs, and
caches.

Qwen Code uses
`qwen --input-format text --output-format stream-json --yolo --model <model>` and
expects users to configure Qwen auth through Qwen's supported settings path. Qwen OAuth
free tier access ended on 2026-04-15; use API keys, Alibaba Cloud Coding Plan,
OpenRouter, Fireworks, or another Qwen-supported provider.

OpenCode uses
`opencode run --format json --dangerously-skip-permissions --model <provider/model> --dir <cwd> <prompt>`
and expects users to configure OpenCode auth/settings through its normal XDG paths.
OpenCode model names usually include a provider prefix; use `opencode models` to list
models in your configured environment.

Muse Code uses
`muse exec --json --workspace <cwd> --model <model> --trust-workspace --disable-approval --disable-sandbox --user-input-auto-resolve --no-foreign-personal-context --session-id <uuid> --prompt-file <tempfile>`
and expects users to authenticate with `muse login` or `META_API_KEY`. SASE always sets
`MUSE_NO_AUTO_UPDATE=1` for agent runs so Muse's launcher cannot replace its binary
mid-run; update Muse with `sase agent-cli update muse` instead. Muse's sandbox makes
`.git` read-only inside the workspace, which would break in-run commits, so SASE
disables it by default; `SASE_MUSE_SANDBOX=on` keeps the sandbox with
`--sandbox-network enabled` at the documented cost of in-run commits failing.

Muse's `muse-spark-1.2-contributor` model carries a **model advisory**: Meta uses its
inputs and outputs to train and improve Meta's AI models. SASE keeps it fully reachable
by name but never routes a tier map or any built-in size alias to it automatically. The
advisory renders in the ACE model picker, in `%model` completion detail, and in the
resolved model label, and `sase doctor -C llm.model_advisory` warns when a configured
default or model alias resolves to any advisory-flagged model. See
[LLM Providers — Model advisories](llms.md#model-advisories).

Grok Build uses
`grok --prompt-file /dev/stdin --output-format streaming-messages-json --permission-mode bypassPermissions --model <model> --cwd <cwd> --session-id <uuid> --no-plan --no-ask-user --no-auto-update --no-leader`
and expects users to authenticate with `grok login` or `XAI_API_KEY`. `grok` is a
generic executable name shared with a stale community CLI (`grok-dev`) and Homebrew's
deprecated regex tool, so Grok never participates in autodetection like Muse; it is
reached by explicit selection (see [llm_provider.provider](#llm_provider) above) or
automatically whenever the `grok` CLI is installed: through the shipped `@xsmall`,
`@small`, and `@medium` round-robin pools, or as the last candidate in `@xlarge`'s
ordered fallback (behind Claude and Codex). Grok's `grok-4.6` model accepts only
`low`/`medium`/`high`/`xhigh` for `--effort`; see
[LLM Providers — Reasoning Effort](llms.md#reasoning-effort).

### VCS Provider

| Variable                          | Description                                                                                                                                               |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_VCS_PROVIDER`               | Override VCS provider selection (`git`, `hg`, or `auto`).                                                                                                 |
| `SASE_WORKSPACE_ROOT`             | Override the workspace-root base for this process. Use an absolute path; `WorkspaceStore` appends `<project_key>/<project>_<num>/` for managed checkouts. |
| `SASE_BUG_ID`                     | Bug ID for PR workflows. When set and non-zero, injects `SASE_BUG=<id>` into PR tags and Patch.                                                           |
| `SASE_BEAD_ID`                    | Bead ID for commit workflows. When set, `sase stitch create` adds a linked `SASE_BEAD=` footer tag and leaves the subject unchanged.                      |
| `SASE_DISABLE_COMMIT_STOP_HOOK`   | Disable commit finalization for this process.                                                                                                             |
| `SASE_LINKED_REPOS_JSON`          | Resolved linked-repo metadata passed to launched agents.                                                                                                  |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR` | Workspace-matched directory for one configured linked repo.                                                                                               |

### SDD Git Operations

| Variable                                    | Description                                                                                                                                                    |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_SDD_STORE_WRITE_LOCK_TIMEOUT`         | Non-negative seconds to wait for the cooperative SDD store lock. Overrides both the 10-second metadata-write default and 180-second worktree-mutation default. |
| `SASE_SDD_GIT_LOCK_RETRY_DELAYS`            | Comma-separated non-negative delays, in seconds, for transient Git lock failures. Invalid or empty values use the built-in shared retry schedule.              |
| `SASE_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT`        | Positive seconds an epic plan launch waits for another launch in the same project (default: 900).                                                              |
| `SASE_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT` | Positive seconds an approval preflight waits for an in-flight epic launch before deferring its health check to the detached launch (default: 120).             |

See [SDD storage concurrency and recovery](sdd_storage.md#concurrency-and-recovery) for
the lock, recovery snapshot, and failed-integration cooldown behavior.

### Plugin System

These switches affect plugin-provided resources and declarative artifact providers. The
VCS, workspace, and LLM registries load provider entry points directly.

| Variable                            | Description                                                              |
| ----------------------------------- | ------------------------------------------------------------------------ |
| `SASE_DISABLE_PLUGINS`              | Disable plugin resources and third-party artifact-provider entry points. |
| `SASE_DISABLE_PLUGIN_XPROMPTS`      | Disable plugin-provided xprompt and workflow files.                      |
| `SASE_DISABLE_PLUGIN_CONFIG`        | Disable plugin-provided `default_config.yml` files and config xprompts.  |
| `SASE_DISABLE_PLUGIN_ARTIFACT_REFS` | Disable plugin-provided artifact-reference specifications.               |
| `SASE_DISABLE_PLUGIN_FILE_HOOKS`    | Disable plugin-provided file-hook templates.                             |
| `SASE_DISABLE_PLUGIN_TASK_TYPES`    | Disable plugin-provided task-type specifications.                        |

### State Root

| Variable                  | Description                                                                                                                                                          |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_HOME`               | Override the SASE state root. Defaults to `~/.sase`; project files, chats, artifacts, notifications, dismissed bundles, saved groups, and logs move under this root. |
| `SASE_PROC_LOG_MAX_BYTES` | Maximum active proc-log segment size in bytes (default: 2 MiB); `0` disables rotation.                                                                               |

### General

| Variable                              | Description                                                                                                                                                                                                                                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SASE_TMPDIR`                         | Override SASE's managed temp root. When unset, the root is `$SASE_HOME/tmp` (`~/.sase/tmp` by default).                                                                                                                                                                                                |
| `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION` | Plan-specific auto-approval action for an agent; currently `approve` or `epic`.                                                                                                                                                                                                                        |
| `SASE_AGENT_AUTO_PLAN_ACTION`         | Backward-compatible alias for `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION`.                                                                                                                                                                                                                                   |
| `SASE_AGENT_AUTO_APPROVE`             | Legacy boolean auto-approve flag; maps plan submissions to normal approval.                                                                                                                                                                                                                            |
| `SASE_FEATURE_FLAGS`                  | Strict JSON object of booleans carrying the resolved feature-flag snapshot for this process and its children. Overrides config-layer values. Root `-f/--enable-feature` and `-F/--disable-feature` merge into this variable so launched processes inherit those CLI overrides.                         |
| `SASE_XPROMPT_LSP_CMD`                | Override the command used by `sase lsp` to launch the xprompt language server.                                                                                                                                                                                                                         |
| `SASE_CORE_DIR`                       | Preferred `sase-core` source checkout for `Justfile` Rust build/install targets; overrides `../sase-core`.                                                                                                                                                                                             |
| `SASE_PYTEST_DIST`                    | xdist scheduler for the `just` pytest recipes: `worksteal` (default) or `loadfile` (fallback). Invalid values fail before worker-token acquisition; serial inline-snapshot modes ignore it.                                                                                                            |
| `SASE_PYTEST_SANDBOX_DIR`             | Pytest-published sandbox root inherited by test subprocesses; bead-store writes during pytest must target a path at or below this directory.                                                                                                                                                           |
| `SASE_PYTEST_WORKERS`                 | Request exactly this positive number of governed xdist workers for the `just` pytest recipes. The request must fit the active host pool unless accounting is deliberately disabled.                                                                                                                    |
| `SASE_PYTEST_WORKER_FLOOR`            | Positive minimum token grant required to start an automatically sized `just` pytest run. Defaults to 4, clamped on smaller hosts, and cannot exceed the ceiling or host pool.                                                                                                                          |
| `SASE_PYTEST_WORKER_CEILING`          | Positive maximum token grant for an automatically sized `just` pytest run. Defaults to at most 28 while reserving another floor-sized grant when capacity permits.                                                                                                                                     |
| `SASE_ALLOW_UNSANDBOXED_BEAD_WRITES`  | Test-only override; set to `1` to allow a pytest bead-store write outside `SASE_PYTEST_SANDBOX_DIR` for a deliberate exception.                                                                                                                                                                        |
| `SASE_ACE_PAGE_GROUP_ISOLATION`       | Test-only override; set to `1` to make `AcePageGroup` create a fresh `AcePage` for each checkout instead of sharing one app across related tests. `just test-ace-page-group-isolated` sets this for every module in `tests/ace/tui/ace_page_group_files.txt`.                                          |
| `SASE_TEST_GATE_SLOTS`                | Override the host-wide pytest capacity in worker tokens. Unlike the former whole-suite gate, one token now represents one xdist worker.                                                                                                                                                                |
| `SASE_TEST_GATE_DIR`                  | Override the shared pytest token-pool directory. Defaults to a UID-scoped `sase-pytest-tokens-<uid>` directory under `/tmp`.                                                                                                                                                                           |
| `SASE_TEST_GATE_TIMEOUT`              | Non-negative seconds to wait for a sufficient worker-token grant before failing with requested capacity and current-holder diagnostics.                                                                                                                                                                |
| `SASE_TEST_GATE_STALE`                | Non-negative seconds without a progress heartbeat before a _live_ holder is treated as wedged and reclaimed. Default `1800` (30 minutes). `0` disables stale-heartbeat reclaim.                                                                                                                        |
| `SASE_TEST_GATE_MAX_HOLD`             | Non-negative seconds a live holder may keep its grant even while heartbeats continue. Default `14400` (4 hours). `0` disables the absolute age cap.                                                                                                                                                    |
| `SASE_TEST_GATE_WATCHDOG`             | Non-negative seconds between a holder's self-checks of those bounds. Default `30`. `0` disables the holder-side watchdog; waiters still reclaim.                                                                                                                                                       |
| `SASE_TEST_GATE_DISABLED`             | Set to `1` to bypass the pytest worker-token pool deliberately. The bypass takes no tokens and never waits, but its width is still clamped to the host budget and announced on stderr; raise `SASE_TEST_GATE_SLOTS` to run wider. Every held lease also exports it to prevent nested pytest deadlocks. |
| `SASE_TEST_GATE_GOVERNED`             | Internal marker exported by every held worker-token lease, meaning an ancestor already paid for this process's workers. It is what separates a corroborated exemption from a top-level bypass; inherited pytest configuration must not lease again.                                                    |
| `SASE_JUST_INVOCATION_DIR`            | Internal value set by `just` so test selectors are normalized from the caller's directory.                                                                                                                                                                                                             |

The pytest variables above describe one UID-scoped pool shared by `just` recipes and
direct parallel pytest controllers. The first active lease records the effective
capacity; later launchers honor that capacity until every holder exits, even if
`MemAvailable` changes in the meantime. Automatic launchers require their floor
atomically and then take currently free tokens up to the ceiling. Exact
`SASE_PYTEST_WORKERS` requests wait for the complete request, and an explicit
`SASE_TEST_GATE_SLOTS` value must match an already-active pool. The former whole-suite
slot gate is fully superseded: admission, diagnostics, and SIGKILL-safe release are all
expressed in worker tokens. A live holder also writes a progress heartbeat (collection
and completed test calls). Waiters and a holder-side watchdog reclaim a grant whose
heartbeat is older than `SASE_TEST_GATE_STALE` or whose age exceeds
`SASE_TEST_GATE_MAX_HOLD`: the watchdog releases its own tokens, and a waiter SIGTERMs
(then SIGKILLs) a still-held wedged process so `flock` can return the tokens to the
pool. Waiting and timeout messages print each holder's age, heartbeat age, and reclaim
reason.

### Workspace Management (Internal)

These are set automatically by sase when launching agent subprocesses and are not
intended for manual use. Workspace plugins declare an env-var prefix, then SASE passes
`<PREFIX>_PRE_ALLOCATED`, `<PREFIX>_WORKSPACE_NUM`, and `<PREFIX>_WORKSPACE_DIR` into
the child process. Built-in prefixes include `SASE_GIT` for `#git`; plugin packages may
add prefixes such as `SASE_GH` for GitHub. The launcher clears inherited
`SASE_*_PRE_ALLOCATED`, `SASE_*_WORKSPACE_NUM`, and `SASE_*_WORKSPACE_DIR` variables
before applying the current launch's values so follow-up agents cannot inherit stale
workspace claims.

| Variable                 | Description                                                                |
| ------------------------ | -------------------------------------------------------------------------- |
| `SASE_SYNC_CWD`          | Working directory override for sync operations.                            |
| `<PREFIX>_PRE_ALLOCATED` | Set to `"1"` when a workspace provider has pre-allocated a launch context. |
| `<PREFIX>_WORKSPACE_NUM` | Pre-allocated workspace number.                                            |
| `<PREFIX>_WORKSPACE_DIR` | Pre-allocated workspace directory path.                                    |
| `SASE_GIT_*`, ...        | Concrete forms for built-in and plugin-provided workspace prefixes.        |

## CLI Flags

Command groups that default to a nested `list` command still parse flags at the
subcommand level. Use the explicit `list` form when passing list options, such as
`sase notify list -j`, `sase memory list -j`, or `sase workspace list --json`.

### `sase (global)`

These options are recognized only in the leading run of option tokens, before the first
subcommand. They do not steal `-f`/`-F` from commands such as `sase bead list -f json`.

| Flag                    | Values              | Default | Description                                                                                                                                                            |
| ----------------------- | ------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-f, --enable-feature`  | registered flag key | -       | Force a registered feature flag on for this invocation and every process it launches. Repeatable. Outranks config layers and an inherited `SASE_FEATURE_FLAGS` value.  |
| `-F, --disable-feature` | registered flag key | -       | Force a registered feature flag off for this invocation and every process it launches. Repeatable. Outranks config layers and an inherited `SASE_FEATURE_FLAGS` value. |

### `sase ace`

| Flag                     | Values                                                 | Default                          | Description                                                                                                                                                                                                                       |
| ------------------------ | ------------------------------------------------------ | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[query]`                | string                                                 | last used, first saved, or `!!!` | Query string for filtering Patches.                                                                                                                                                                                               |
| `-m, --model-tier`       | `large`, `small`                                       | -                                | Override model tier for all LLM invocations.                                                                                                                                                                                      |
| `-M, --model-size`       | `big`, `little`                                        | -                                | Deprecated alias for `--model-tier`.                                                                                                                                                                                              |
| `-p, --profile`          | optional path                                          | -                                | Profile the TUI session with pyinstrument. Without a path, write `ace-profiles/ace_profile_<timestamp>.txt` under SASE's managed temp root; after exit, print a shortened path and copy it to the system clipboard when possible. |
| `-r, --refresh-interval` | int (seconds)                                          | `10`                             | Auto-refresh interval (0 to disable).                                                                                                                                                                                             |
| `-R, --restart-axe`      | flag                                                   | -                                | Restart the axe daemon on startup (no-op if axe is not running).                                                                                                                                                                  |
| `-t, --tab`              | `artifacts`, `changespecs`, `patches`, `agents`, `axe` | `agents`                         | Tab to focus on startup (`changespecs` and `patches` are legacy aliases for `artifacts`).                                                                                                                                         |
| `-T, --tmux`             | flag                                                   | -                                | Launch ACE in a new tmux window named `sase_tmux_<N>` and print the session/window target for external control.                                                                                                                   |
| `-x, --no-axe`           | flag                                                   | -                                | Disable auto-starting the axe daemon.                                                                                                                                                                                             |
| `-v, --vcs-provider`     | `git`, `hg`, `auto`                                    | -                                | Override VCS provider.                                                                                                                                                                                                            |

### `sase tmux-agent`

Launch an interactive agent CLI in a new tmux window. There are no subcommands — in
particular no `list` child — so a bare `sase tmux-agent` paints the tmux menu instead of
delegating. See [tmux Agent](ace.md#tmux-agent).

| Flag            | Values                                                            | Default                        | Description                                                               |
| --------------- | ----------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------- |
| `[provider]`    | registered provider name                                          | paint the menu                 | Launch this provider directly. Omit to paint the tmux Agent menu.         |
| `-c, --dir`     | path                                                              | current pane path, else `$PWD` | Launch directory.                                                         |
| `-e, --effort`  | `off`, `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | inherit from config            | Explicit effort for this launch; unsupported levels are a usage error.    |
| `-j, --json`    | flag                                                              | -                              | Versioned JSON envelope of the catalog or the dry-run plan.               |
| `-l, --list`    | flag                                                              | -                              | Print the catalog as a table; works outside tmux. Not a subcommand.       |
| `-n, --dry-run` | flag                                                              | -                              | Print the window name, directory, env, and exact command; change nothing. |
| `-r, --refresh` | flag                                                              | -                              | Rebuild the catalog cache before doing anything else.                     |
| `-s, --safe`    | flag                                                              | -                              | Launch without the provider's approval-bypass args.                       |
| `-v, --verbose` | flag                                                              | -                              | With `--list`, add resolved paths, full commands, and install hints.      |

`--renumber` is an internal hook invoked when an agent CLI window exits and is omitted
from help. Outside tmux with no `--list`/`--dry-run`/`--json`, the command exits 2,
explains that a tmux session is required, and still prints the catalog.

### `sase axe`

| Flag                 | Values              | Default | Description            |
| -------------------- | ------------------- | ------- | ---------------------- |
| `-v, --vcs-provider` | `git`, `hg`, `auto` | -       | Override VCS provider. |

### `sase axe status`

Collects one read-only whole-system AXE snapshot. Human output is the default; JSON
output is the exact stable schema-version-1 wire object and never contains Rich markup
or ANSI escapes.

| Flag         | Values | Default | Description                                               |
| ------------ | ------ | ------- | --------------------------------------------------------- |
| `-j, --json` | flag   | -       | Emit the machine-readable schema-version-1 status object. |

The classifier-owned exit code is `0` for healthy or intentionally inactive states, `1`
for actionable degradation, and `2` for a collection or classification error. See
[Axe Whole-System Status](axe.md#whole-system-status) for the state, health, field, and
recovery-command contract.

### `sase axe start`

| Flag                      | Values        | Default          | Description                                         |
| ------------------------- | ------------- | ---------------- | --------------------------------------------------- |
| `-q, --query`             | string        | `""` (all)       | Query string for filtering Patches.                 |
| `-H, --max-hook-runners`  | int           | config or `3`    | Maximum concurrent hook runners.                    |
| `-A, --max-agent-runners` | int           | config or `3`    | Maximum concurrent agent runners.                   |
| `-z, --zombie-timeout`    | int (seconds) | config or `7200` | Timeout before marking a hook/workflow as a zombie. |

For `sase axe start`, CLI flags take precedence over values from the `axe` config
section in `sase.yml`. If neither is set, the built-in defaults from
`default_config.yml` are used.

### `sase repro`

Agents-tab reproduction bundles capture and replay the loader/apply sequence used to
render agent rows. The command is intended for debugging row disappearance,
reappearance, and duplicate-parent regressions; see
[Agents Tab Reproduction Bundles](ace.md#agents-tab-reproduction-bundles).

| Form                            | Flag                | Values | Default  | Description                                                                |
| ------------------------------- | ------------------- | ------ | -------- | -------------------------------------------------------------------------- |
| `sase repro capture agents-tab` | `--output`          | path   | required | Directory where `agents_tab_repro.json` and capture artifacts are written. |
| `sase repro capture agents-tab` | `--commit-safe`     | flag   | enabled  | Redact local names and paths for a shareable bundle.                       |
| `sase repro capture agents-tab` | `--no-commit-safe`  | flag   | -        | Keep unredacted local identifiers in the capture.                          |
| `sase repro capture agents-tab` | `--size`            | `WxH`  | `120x40` | Terminal size label stored with the bundle.                                |
| `sase repro capture agents-tab` | `--json`            | flag   | -        | Emit a machine-readable capture result.                                    |
| `sase repro replay`             | `path`              | path   | required | Bundle JSON file or bundle directory to replay.                            |
| `sase repro replay`             | `--assert-stable`   | flag   | -        | Exit non-zero if replay invariants fail.                                   |
| `sase repro replay`             | `--json`            | flag   | -        | Emit a machine-readable replay verdict.                                    |
| `sase repro replay`             | `--write-artifacts` | path   | -        | Directory for replay screen text and SVG artifacts.                        |
| `sase repro replay`             | `--size`            | `WxH`  | `120x40` | Headless terminal size used for replay.                                    |

### `sase axe stop`

No flags. Stops the running axe orchestrator.

### `sase axe maintenance`

Maintenance mode pauses scheduled lumberjack ticks without stopping the orchestrator.

| Command                       | Flags / exit code                    | Description                                     |
| ----------------------------- | ------------------------------------ | ----------------------------------------------- |
| `sase axe maintenance enter`  | `-r, --reason` required              | Write the maintenance marker with a reason.     |
| `sase axe maintenance exit`   | exits 0                              | Remove the marker if present.                   |
| `sase axe maintenance status` | exits 0 when active, 1 when inactive | Print the active marker reason, PID, timestamp. |

See [axe.md — Maintenance Mode](axe.md#maintenance-mode) for the runtime behavior.

### `sase axe chop`

With no subcommand, `sase axe chop` defaults to `sase axe chop list`. Use the explicit
`list` or `doctor` subcommand when passing diagnostic flags.

| Form                   | Flags                                         | Description                                                                                                                                                     |
| ---------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sase axe chop list`   | `-a/--available`, `-j/--json`, `-v/--verbose` | List configured chops with one summary line each; `--available` also shows discoverable executable chop scripts, and `--verbose` adds a full-description panel. |
| `sase axe chop doctor` | `-j/--json`, `-v/--verbose`                   | Diagnose missing configured chops, unconfigured scripts, and Telegram chop prerequisites.                                                                       |
| `sase axe chop run`    | `-L/--lumberjack`                             | Run a single chop once in the foreground.                                                                                                                       |

`sase axe chop doctor` exits `1` when any check is `ERROR` (a configured script chop
cannot be resolved) and `0` otherwise. Unconfigured available scripts and Telegram
prerequisite gaps report `WARN`. The same chop diagnostics are also surfaced by
`sase doctor -C axe.chops`.

### `sase axe lumberjack`

With no subcommand, `sase axe lumberjack` defaults to `sase axe lumberjack list`.

| Form                         | Flags                  | Description                                                                                                  |
| ---------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------ |
| `sase axe lumberjack list`   | `-v/--verbose`         | List configured lumberjacks and their chops; `--verbose` adds each description body under a `details` block. |
| `sase axe lumberjack run`    | `-q`, `-H`, `-A`, `-z` | Run one lumberjack once in the foreground with optional query and runner-limit overrides.                    |
| `sase axe lumberjack status` | -                      | Show per-lumberjack process status.                                                                          |

Both listings print only the description summary line by default so the output stays
scannable; `-v/--verbose` renders the full [description](axe.md#description-grammar).

### `sase stitch create`

Dispatches a commit, proposal, or PR via the VCS provider layer. `sase commit` remains
accepted as a deprecated alias for this subcommand. See
[commit_workflows.md](commit_workflows.md) for the full flow, payload, checkpoint, and
resume semantics.

| Flag                      | Values                        | Default                 | Description                                                                                 |
| ------------------------- | ----------------------------- | ----------------------- | ------------------------------------------------------------------------------------------- |
| `-m, --message`           | string                        | -                       | Commit message (mutually exclusive with `-M`).                                              |
| `-M, --message-file`      | path                          | -                       | File containing the commit message / PR description (mutually exclusive with `-m`).         |
| `-f, --file`              | path (repeatable)             | stage all               | Specific file to stage. Repeat for multiple; omit to stage everything.                      |
| `-n, --name`              | string                        | -                       | Branch/PR name (required for `create_pull_request`).                                        |
| `-b, --bug-id`            | int                           | `$SASE_BUG_ID`          | Bug ID to associate with the commit.                                                        |
| `-B, --do-not-close-bead` | flag                          | -                       | Do not auto-close the assigned in-progress task bead after commit.                          |
| `-c, --checkout-target`   | string                        | `HEAD~1`                | Branch point for PR creation.                                                               |
| `-p, --parent`            | Patch name                    | auto                    | Parent Patch name (overrides branch-based auto-detection). Unresolvable values are dropped. |
| `-r, --resume`            | flag                          | -                       | Resume a previously-checkpointed commit after manual conflict resolution.                   |
| `-s, --status`            | `wip` / `draft` / `ready`     | `$SASE_PR_STATUS`/draft | Patch status override for PRs.                                                              |
| `-t, --type`              | `commit` / `propose` / `pr` … | `$SASE_COMMIT_METHOD`   | Commit method — full names (`create_commit`, etc.) and short aliases are both accepted.     |

### `sase stitch`

`sase stitch` defaults to `sase stitch list`, which shows a merged timeline for the
primary repo and configured linked repos. Add `-S/--sdd` to include sidecar repository
history. The legacy `sase vcs` spelling is still accepted as a deprecated alias.

| Subcommand | Flags                                                                                                                                                                                                                                                                                                           | Description                                                       |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `list`     | `-a/--all`, `-A/--author`, `-b/--branch/--ref`, `-c/--color`, `-o/--current-only`, `-F/--fetch`, `-f/--format pretty\|full\|oneline\|json`, `-n/--limit`, `-m/--merges hide\|show\|only`, `-N/--no-fetch`, `-T/--no-tags`, `-r/--repo`, `-R/--reverse`, `-S/--sdd`, `-s/--since/--after`, `-u/--until/--before` | Show a merged commit timeline with local/remote presence markers. |

`sase stitch list` date filters accept relative offsets (`Nh`, `Nd`, `Nw`), `today`,
`yesterday`, `YYYY-MM-DD`, or `YYYY-MM-DDTHH:MM`. Day-granular `--until` / `--before`
values include the full named day; relative and minute-precise values remain instant
bounds. See [VCS Providers](vcs.md#per-command-vcs-usage) for output examples and
provider notes. `--all` spans every registered enabled or disabled project and
deduplicates shared physical checkouts. Internal sibling backing checkouts remain
visible as linked repositories of their owning projects. Global scope can be combined
with repeatable `--repo` filters but not `--current-only`. Add `--sdd` to either scope
before selecting SDD history with `--repo sdd`; without the opt-in, that repo filter
does not expand the eligible set. `--all --sdd` includes materialized separate SDD
repositories across registered projects. The `--limit` is the cap on the final merged
timeline.

### `sase patch search`

| Flag           | Values                      | Default    | Description                                           |
| -------------- | --------------------------- | ---------- | ----------------------------------------------------- |
| `query`        | string                      | (required) | Query string for filtering Patches.                   |
| `-f, --format` | `plain`, `rich`, `markdown` | `rich`     | Output format (`markdown` for agent-friendly output). |

Search uses the normal enabled-project discovery scope. Disabled projects and internal
sibling backing records are omitted from this CLI path; run
`sase project list --state all` or `sase project show <project>` to inspect them, then
run `sase project enable <project>` before using normal search and launch surfaces for
new work.

### `sase patch migrate-extension`

One-time cleanup for older installs: renames legacy ProjectSpec files under
`~/.sase/projects` from `.gp` to `.sase`, including archive siblings. Current readers
still accept `.gp` as a fallback, so migration is not required before using SASE; it
just normalizes on-disk filenames to the canonical extension.

If a `.sase` sibling already exists with identical contents, the redundant `.gp` copy is
removed. If the sibling differs, the command reports a conflict and preserves both files
unless `--force` is set.

| Flag             | Values | Default             | Description                                                               |
| ---------------- | ------ | ------------------- | ------------------------------------------------------------------------- |
| `--force`        | flag   | -                   | Replace an existing differing `.sase` sibling with the legacy `.gp` file. |
| `--projects-dir` | path   | `~/.sase/projects/` | Override the project root scanned for legacy `.gp` files.                 |

### `sase project`

With no subcommand, `sase project` defaults to `sase project list`. Project lifecycle
state is stored as `PROJECT_STATE` metadata in the ProjectSpec header; missing state
means `enabled`.

| Form                                       | Flags                                         | Description                                                                    |
| ------------------------------------------ | --------------------------------------------- | ------------------------------------------------------------------------------ |
| `sase project list`                        | `-s, --state enabled\|disabled\|sibling\|all` | List records in one state; default is true enabled projects.                   |
| `sase project list`                        | `-j, --json`                                  | Emit machine-readable lifecycle and derived project/VCS fields.                |
| `sase project current`                     | `-j, --json`                                  | Show the current project derived from the VCS xprompt MRU.                     |
| `sase project show <project>`              | `-j, --json`                                  | Show state, source, project/archive files, workspace, launchability, warnings. |
| `sase project set-state <project> <state>` | `-f, --force`                                 | Set `enabled`, `disabled`, or internal backing marker `sibling`.               |
| `sase project enable <project>`            | `-f, --force`                                 | Enable a project; `--force` has no effect when enabling.                       |
| `sase project disable <project>`           | `-f, --force`                                 | Disable a project after live-work safety checks.                               |

Disabling refuses projects with live `RUNNING` claims or live artifact markers
(`running.json`, `waiting.json`, or `pending_question.json`) unless `--force` is passed.
Legacy `active` normalizes to enabled; `inactive`, `archived`, and `closed` normalize to
disabled. Deprecated `activate`, `deactivate`, `archive`, and `close` command aliases
remain accepted. The system-managed `home` project cannot be mutated. Normal launch and
discovery surfaces default to enabled projects. `sibling` remains an internal
backing-record marker for configured linked repos, not a third project state.

ACE exposes the same lifecycle mutations through the **Projects** tab of the SASE Admin
Center (press `#`). That tab also supports marks for bulk lifecycle operations, alias
editing with `A`, ProjectSpec editing through `$EDITOR`, confirmed deletion of whole
SASE project directories, and the Repos/Workspaces inventory sub-tabs described above.

### `sase repo`

Bare `sase repo` defaults to `sase repo list`. The command family inventories primary,
sidecar, linked, and opened external repositories, prepares a selected repo inside one
workspace context, and exposes the durable audit history of successful opens.

`sase repo list` defaults to the current project and infers both the project and
workspace context from cwd. Primary repos come from ProjectSpecs, sidecars from
`repos.sidecar` plus SDD store records, linked repos from resolved `repos.linked`
(including compatibility aliases), and external repos from materialized workspace-local
clones; a sidecar wins when the same checkout is also auto-injected as linked. The Rich
table reports whether each repo is cloned in the selected workspace plus the number of
registered workspaces containing it. External rows use the canonical project name or
provider ref such as `gh:pallets/click`. Hidden `agents` rows remain visible and report
the same stable machine-level path for every registered workspace context.

| List flag         | Description                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| `-a, --all`       | Show all enabled and disabled projects at primary workspace context (`#0`). |
| `-j, --json`      | Emit deterministic records with the full per-workspace `clones` matrix.     |
| `-p, --project`   | Select one enabled or disabled project instead of inferring from cwd.       |
| `-w, --workspace` | Select a workspace number instead of inferring it from cwd.                 |

`--all` and `--project` are mutually exclusive. JSON records retain source, description,
`auto_clone`, environment, and SDD-storage metadata while making `path` and `exists`
describe the selected workspace context.

`sase repo open REPO -r "<reason>"` resolves `REPO` in three tiers: a host-project
inventory name, another registered SASE project name, then an external provider ref
(`gh:owner/repo` or `owner/repo` GitHub shorthand). It materializes and prepares the
repo, prints only its path to stdout, records the per-run artifact markers used by ACE
and the commit finalizer, and appends an event to
`~/.sase/projects/<project>/repo_opens.jsonl`. Run it inside a managed checkout to infer
the host project and workspace. Reopening a valid external clone preserves its current
contents and records a new open event.

| Open argument / flag | Description                                                                             |
| -------------------- | --------------------------------------------------------------------------------------- |
| `REPO`               | Inventory name, registered project name, `gh:owner/repo`, `owner/repo`, or record path. |
| `-p, --project`      | Select the host project instead of inferring it from cwd.                               |
| `-r, --reason`       | Required non-empty audit reason.                                                        |
| `-w, --workspace`    | Select the host workspace number instead of inferring it from cwd.                      |

When two inventory records share a name or slug, `sase repo open` refuses rather than
guessing and lists each candidate as `<kind> '<name>' (<path>)`. To pick one, re-run the
command with that candidate's path as `REPO`, copied exactly as printed: a record path
is matched literally, ahead of any name or slug, so it selects that record even when its
name collides with another's. This is a disambiguator, not a general "open any
directory" mode — a path that matches no primary, sidecar, or linked record falls
through to the usual name and provider-ref tiers and fails there.

`sase repo log` renders a project-scoped summary and per-repo rollup of durable open
events. Repo, agent, or workspace filters add agent and event drill-down panels; an
event ID prefix shows one complete event. `--json` returns the same filtered data
deterministically.

| Log flag          | Description                                               |
| ----------------- | --------------------------------------------------------- |
| `-a, --agent`     | Filter by agent name or interactive user.                 |
| `-i, --id`        | Show one event by exact ID or unambiguous ID prefix.      |
| `-j, --json`      | Emit deterministic structured output.                     |
| `-p, --project`   | Select the host project instead of inferring it from cwd. |
| `-r, --repo`      | Filter by repository name.                                |
| `-w, --workspace` | Filter by host workspace number.                          |

### `sase revert`

| Flag   | Values | Default    | Description                  |
| ------ | ------ | ---------- | ---------------------------- |
| `name` | string | (required) | NAME of the Patch to revert. |

### `sase restore`

| Flag         | Values | Default | Description                            |
| ------------ | ------ | ------- | -------------------------------------- |
| `[name]`     | string | -       | NAME of the reverted Patch to restore. |
| `-l, --list` | flag   | -       | List all reverted Patches.             |

### `sase run`

| Flag      | Values | Default | Description                                                                                                   |
| --------- | ------ | ------- | ------------------------------------------------------------------------------------------------------------- |
| `[query]` | string | -       | Prompt text, inline reference (`#name`), standalone workflow reference (`#!name`), or `.` for history picker. |

When invoked with no arguments, opens `$EDITOR` for composing a prompt interactively.
When invoked with `.`, opens a prompt history picker. All prompts launch as detached
background agents, and multi-prompt queries (containing `---` separators) are launched
as sequential detached background agents.

### `sase repro`

`sase repro` captures and replays debugging bundles for narrow, reproducible TUI bug
classes. The current target is the Agents-tab loader/apply sequence used to diagnose row
disappearance, reappearance, and duplicate workflow parents.

| Form                            | Flags                                                                     | Description                                                                                        |
| ------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `sase repro replay <path>`      | `--assert-stable`, `--json`, `--write-artifacts <dir>`, `--size`          | Replay a bundle JSON file or bundle directory through the headless TUI harness.                    |
| `sase repro capture agents-tab` | `--output <dir>`, `--commit-safe`, `--no-commit-safe`, `--size`, `--json` | Capture a baseline bundle from current filesystem state. `--commit-safe` redaction is the default. |

Use the in-TUI `,B` capture when a transient row-list bug has just happened in a live
ACE session. The CLI capture path is out-of-band: it loads current filesystem state and
cannot reconstruct refreshes that already passed through the running TUI.

### `sase xprompt`

With no subcommand, `sase xprompt` defaults to `sase xprompt list`.

### `sase xprompt expand`

| Flag          | Values | Default | Description                                                  |
| ------------- | ------ | ------- | ------------------------------------------------------------ |
| `[prompt]`    | string | stdin   | Prompt text to expand (reads from stdin if omitted).         |
| `-t, --trace` | flag   | -       | Print expansion trace to stderr showing resolved references. |

### `sase xprompt explain`

| Flag            | Values | Default    | Description                                 |
| --------------- | ------ | ---------- | ------------------------------------------- |
| `workflow_name` | string | (required) | Workflow name to explain.                   |
| `[args]`        | string | -          | Positional arguments for the workflow.      |
| `-a, --arg`     | string | -          | Named argument as `KEY=VALUE` (repeatable). |

### `sase xprompt list`

No flags. Outputs a JSON array of all available xprompts with name, type, source,
inputs, tags, `is_skill`, and preview. Clients that insert references should prefer
`kind`/`insertion` metadata when present so standalone workflows are inserted as
`#!name` and inline-capable entries, including markdown xprompt swarms, are inserted as
`#name`. Slash skill completion clients should filter to entries where `is_skill` is
`true`.

### `sase xprompt show`

| Flag            | Values                  | Default    | Description                                                                   |
| --------------- | ----------------------- | ---------- | ----------------------------------------------------------------------------- |
| `NAME`          | string                  | (required) | XPrompt or workflow name; copied markers and argument suffixes are tolerated. |
| `-c, --color`   | `auto`,`always`,`never` | `auto`     | Color mode for rendered output.                                               |
| `-f, --format`  | `full`,`json`,`raw`     | `full`     | Rendered detail view, stable JSON record, or exact definition source bytes.   |
| `-p, --project` | string                  | auto       | Resolve within a specific project namespace instead of the detected project.  |

### `sase xprompt graph`

| Flag              | Values           | Default   | Description                                             |
| ----------------- | ---------------- | --------- | ------------------------------------------------------- |
| `[workflow_name]` | string           | -         | Workflow name to graph. Lists all workflows if omitted. |
| `-f, --format`    | `mermaid`,`text` | `mermaid` | Output format for the DAG visualization.                |

### `sase xprompt catalog`

| Flag        | Values | Default | Description                                       |
| ----------- | ------ | ------- | ------------------------------------------------- |
| `-o, --out` | path   | tempdir | Directory where the rendered PDF should be saved. |

### `sase init`

Bare `sase init` is the onboarding coordinator for SASE-managed resources. It runs
read-only planners for memory, SDD, and skills, prints a grouped summary, and prompts
once per initializer that needs work when stdin is interactive. Non-interactive runs
never prompt; they print the drift summary and ask the caller to rerun with `--yes`.
That flag runs needed initializers but cannot authorize creation of a missing GitHub SDD
sidecar, which always requires its own interactive `y`/`yes` response. The memory
planner (which owns agent-document initialization) only generates managed project
`AGENTS.md` from bare `sase init` when the current project's own `sase/sase.yml` sets
`is_sase_managed: true`. The SDD planner uses that same local marker and skips unmanaged
repositories before provider work. Neither planner infers project ownership from
`memory.h1_title`, existing memory notes, lifecycle state, or merged configuration.

`--all` applies that coordinator to every registered enabled main project from its
recorded primary workspace, even when the command starts outside a project. It excludes
disabled projects, internal sibling backing records, `home`, and other system-managed
records, continues after per-project failures, and returns non-zero if any project has
drift, is unavailable, or fails. `--all --check` is read-only, while non-interactive
apply still requires `--yes`. `--all` is incompatible with `--enable-project-memory` and
with explicit compatibility subcommands.

Advanced deploy controls stay on explicit subcommands such as
`sase memory init --no-commit` and `sase skill init --no-push`.

| Flag                          | Values | Default | Description                                                                              |
| ----------------------------- | ------ | ------- | ---------------------------------------------------------------------------------------- |
| `-a, --all`                   | flag   | -       | Attempt every known enabled main SASE project and report one aggregate status.           |
| `-c, --check`                 | flag   | -       | Report initialization drift without writing; exits non-zero when changes are needed.     |
| `-M, --enable-project-memory` | flag   | -       | Mark the repository with `is_sase_managed: true` before initialization.                  |
| `-y, --yes`                   | flag   | -       | Run needed initializers without generic prompts; cannot approve GitHub sidecar creation. |

### `sase memory agent-docs`

With no subcommand, `sase memory agent-docs` defaults to `sase memory agent-docs list`.

| Form                          | Flags | Description                                                                        |
| ----------------------------- | ----- | ---------------------------------------------------------------------------------- |
| `sase memory agent-docs`      | -     | Show the same read-only agent-document inventory as `sase memory agent-docs list`. |
| `sase memory agent-docs list` | -     | Inspect project, home, and chezmoi `AGENTS.md` files and provider shims.           |

### `sase memory`

With no subcommand, `sase memory` defaults to `sase memory list`.

| Form                      | Flags                                                                                                                                                   | Description                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `sase memory`             | -                                                                                                                                                       | Show the same read-only memory context dashboard as `sase memory list`.                         |
| `sase memory list`        | -                                                                                                                                                       | Show loaded, referenced, available, and missing memory files for the current launch context.    |
| `sase memory read <path>` | `-r, --reason <reason>` required                                                                                                                        | Agent-side read of a `type: long` memory note without leading frontmatter, plus an audit event. |
| `sase memory write`       | `--title`, `--target` or `--slug`, repeatable `--evidence`, `--from-chat`, `--body`, `--file`, `--allow-large`, `--manual-author`, `--notify`, `--json` | Create an attributable long-term memory proposal without modifying canonical memory files.      |
| `sase memory review [id]` | `--list`, `--show`, `--approve`, `--edit`, `--reject`, `--all`, `--target`, `--edited-file`, `--reason`, `--json`                                       | Human review of pending memory proposals; a bare TTY command opens the interactive review app.  |
| `sase memory log`         | `--path`, `--agent`, `--id`, `--include`, `--json`                                                                                                      | Summarize or inspect audited memory reads, optionally including proposal and review events.     |

Examples:

```bash
# read requires SASE agent identity; write requires agent identity unless --manual-author is used for demos
sase memory read generated_skills.md --reason "Need generated skill context"
sase memory write --title "Generated skills" --slug generated_skills --evidence chat:abc123 --body "Durable memory body" --notify
sase memory review --list
sase memory review mem-20260523-142233-a1b2c3d4 --approve
sase memory log
sase memory log --include proposals
sase memory log --path generated_skills.md
sase memory log --id <read-id>
```

### `sase memory init`

Creates or refreshes home memory and memory for SASE-managed projects. Project ownership
requires `is_sase_managed: true` in the project's own `sase/sase.yml`; `memory.h1_title`
is optional title customization, with a stable derived title otherwise. The retired
`memory.enabled` key does not authorize management. It never creates or alters an
unmanaged project's root `AGENTS.md`. Independently, it overwrites each provider
instruction file (`CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md`) with a
byte-for-byte copy of that root's `AGENTS.md` (legacy `@AGENTS.md` / `*.md.tmpl` import
shims are recognized and migrated to full copies). This copy applies to every existing
project-tree `AGENTS.md`; directories without one are untouched. For managed roots,
memory init synchronizes memory: short-term notes are inlined into the Tier 1 block of
`AGENTS.md`, every heading in the generated document is numbered, long-term notes are
rendered as numbered sections headed by the note path with the description as the body,
and missing long-memory `description` frontmatter is inserted. By default it also tries
to commit, rebase-pull, and push generated project-side files. `sase init memory` is a
compatibility alias for this command. Generated repository memory requires agents to use
`/sase_repo` before reading or modifying any repo outside their own workspace checkout.
The rule covers linked repos, sidecars, different SASE projects, and unlinked GitHub
repos even when no linked repositories are configured. When a managed project has a
nonempty `memory.glossary` section, the same run also refreshes the generated
`sase/memory/glossary.md` note and its Tier 1 inlining; `sase memory init --check`
reports drift if the note or its inlined section is stale.

| Flag                          | Values | Default | Description                                                                                             |
| ----------------------------- | ------ | ------- | ------------------------------------------------------------------------------------------------------- |
| `-c, --check`                 | flag   | -       | Report memory initialization drift without writing project or home files.                               |
| `-M, --enable-project-memory` | flag   | -       | Set `is_sase_managed: true`, enabling managed project memory; incompatible with `--check`.              |
| `-C, --no-commit`             | flag   | -       | Write files, but skip only the project git commit/pull/push path; home deployment still follows config. |

### `sase init repo`

`sase init repo` is an alias for `sase repo init`. For targets marked
`is_sase_managed: true` in their own `sase/sase.yml`, it initializes configured
sidecars, creates or refreshes generated README files, ensures the managed plans and
research declarations, and maintains the root `/sase/repos/` ignore rule. Missing or
false markers produce an informative successful no-op, while invalid local configuration
fails before provider or filesystem work. `--path` always checks the target repository's
marker. GitHub setup creates missing sidecars with their configured public/private
visibility. Bare-git projects refresh generated files automatically during repository
setup and first SDD writes; the explicit command remains useful for refreshes and
`--check` audits.

When the GitHub sidecar is missing, this alias uses the same default-no
repository-specific confirmation as `sase repo init`. EOF, interruption, and any answer
other than `y`/`yes` return nonzero before remote creation. Generic `--yes` approval
never authorizes repository creation; non-interactive bare onboarding instead reports
the missing remote and defers its creation.

| Flag          | Values | Default         | Description                                                        |
| ------------- | ------ | --------------- | ------------------------------------------------------------------ |
| `-c, --check` | flag   | -               | Report provider and generated-file work without writing files.     |
| `-p, --path`  | path   | current project | Project root whose provider-owned SDD store should be initialized. |

### `sase skill`

With no subcommand, `sase skill` defaults to the read-only `sase skill list` dashboard.
It reports loaded skill sources, provider targets, and deployed-file drift without
writing files. `sase skill init` generates and deploys agent skill files from xprompt
sources marked with the `skill` field. Generated skill files begin with a
`sase skill use` directive so agent-side skill use can be audited and later summarized
with `sase skill log`, unless the source sets `log_skill_use: false`. See
[xprompt.md — Skill Field](xprompt.md#skill-field) for the skill-source contract and
provider targets. Existing files are skipped in non-interactive runs unless `--force` is
passed; interactive runs prompt before overwriting. Commit and land xprompt template
changes before deploying: writing chezmoi deploys are refused from dirty or unmerged
sources, and refused when they would move the destination off the source commit recorded
in the provenance manifest — see
[Commit Before Deploying](init.md#commit-before-deploying). `sase init skills` is a
compatibility alias for `sase skill init`.

| Form               | Flags                                                                   | Description                                                                                             |
| ------------------ | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `sase skill`       | -                                                                       | Show the same read-only dashboard as `sase skill list`.                                                 |
| `sase skill list`  | -                                                                       | Inspect generated skill sources, provider targets, and deployed-file drift.                             |
| `sase skill init`  | `-f, --force`                                                           | Overwrite deployed skill files without confirmation; bypass the provenance manifest guard.              |
| `sase skill init`  | `-D, --allow-dirty`                                                     | Deploy from uncommitted or unmerged xprompt sources; can revert other agents' deployments.              |
| `sase skill init`  | `-n, --dry-run`                                                         | Show what would be written without writing files.                                                       |
| `sase skill init`  | `-c, --check`; `-d, --diff`                                             | Report or diff generated skill-file drift without writing files.                                        |
| `sase skill init`  | `-p, --provider <name>`                                                 | Deploy only for one registered provider (`claude`, `agy`, `codex`, `grok`, `muse`, `opencode`, `qwen`). |
| `sase skill init`  | `-A, --no-apply`                                                        | With `use_chezmoi`, skip `chezmoi apply` after generated files are committed and pushed.                |
| `sase skill init`  | `-C, --no-commit`                                                       | With `use_chezmoi`, skip the entire git commit, push, and apply sequence.                               |
| `sase skill init`  | `-P, --no-push`                                                         | With `use_chezmoi`, commit generated files but skip pull/rebase, push, and `chezmoi apply`.             |
| `sase skill log`   | `-a, --agent`; `-R, --runtime`; `-s, --skill`; `-i, --id`; `-j, --json` | Summarize or inspect audited generated skill-use events.                                                |
| `sase skill use`   | `-r, --reason <reason>` required                                        | Agent-side audit event recording that the current agent is using a generated skill.                     |
| `sase init skills` | same as `sase skill init`                                               | Compatibility alias for `sase skill init`.                                                              |

### `sase repo init`

`sase repo init` declares the managed plans, beads, and default `research` document
sidecar, initializes every enabled configured sidecar, and ensures the project root
`.gitignore` contains `/sase/repos/`, protecting host-scoped repository clones durably.
`-c, --check` reports drift without writing, `-d, --diff` renders proposed full-file
diffs, and `-C, --no-commit` writes project config and ignore changes without the normal
project commit/pull/push sequence. `sase init repo` is an alias; bare `sase init` and
`sase validate` include the same check for Git projects.

### `sase workspace`

Workspace commands inspect and maintain the managed checkout registry for the inferred
project, or for the project named by `-p/--project`. With no subcommand,
`sase workspace` defaults to `sase workspace list` with default options. Use
`sase workspace list -p <project>`, `sase workspace list --all`, or
`sase workspace list --json` when passing list flags.

| Command                  | Flag / argument            | Values       | Description                                                                                         |
| ------------------------ | -------------------------- | ------------ | --------------------------------------------------------------------------------------------------- |
| `sase workspace list`    | `-p, --project`            | project name | Query a project other than the one inferred from the current directory.                             |
| `sase workspace list`    | `-a, --all`                | flag         | Inventory registered workspaces across every enabled and disabled project.                          |
| `sase workspace list`    | `-j, --json`               | flag         | Emit a machine-readable JSON object.                                                                |
| `sase workspace path`    | `workspace_num`            | integer      | Workspace number to resolve; `0` is the primary checkout and managed claims normally start at `10`. |
| `sase workspace path`    | `-p, --project`            | project name | Query a project other than the inferred one.                                                        |
| `sase workspace cleanup` | `-p, --project`            | project name | Clean a project other than the inferred one.                                                        |
| `sase workspace cleanup` | `-s, --stale`              | flag         | Remove unclaimed managed checkouts older than `workspace.cleanup_ttl_days`.                         |
| `sase workspace cleanup` | `-i, --include-shares`     | flag         | Also consider workflow-share managed checkouts for removal.                                         |
| `sase workspace cleanup` | `-n, --dry-run`            | flag         | Report planned removals without touching the filesystem.                                            |
| `sase workspace repair`  | `-p, --project`            | project name | Repair a project other than the inferred one.                                                       |
| `sase workspace repair`  | `-n, --dry-run`            | flag         | Report registry/filesystem reconciliation without writing.                                          |
| `sase workspace migrate` | `-p, --project`            | project name | Migrate a project other than the inferred one.                                                      |
| `sase workspace migrate` | `-t, --to`                 | `xdg-state`  | Target managed root policy for migration.                                                           |
| `sase workspace migrate` | `-s, --symlink-transition` | flag         | Leave `<primary>_<num>` symlinks pointing to migrated managed checkouts.                            |
| `sase workspace migrate` | `-f, --finalize`           | flag         | Remove transition symlinks left behind by a prior migration.                                        |
| `sase workspace migrate` | `-n, --dry-run`            | flag         | Report planned migration or finalization actions without touching files or the registry.            |

For built-in bare-git projects, `sase repo open` may initialize generated SDD guide
files in the primary checkout before materializing a numbered workspace.
`sase workspace list` and `sase workspace path` remain read-only and do not run SDD
initialization.

### `sase bead`

With no subcommand, `sase bead` defaults to `sase bead list`.

| Flag         | Values                                                                                                                                                                                                                                    | Default | Description     |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | --------------- |
| _subcommand_ | `blocked`, `close`, `create`, `dep`, `doctor`, `epic-symbols`, `history`, `init`, `list`, `note`, `onboard`, `open`, `pages`, `ready`, `ref`, `resolve-conflicts`, `rm`, `search`, `show`, `stats`, `sync`, `task-type`, `update`, `work` | `list`  | Bead subcommand |

#### `sase bead create`

| Flag                           | Values                                         | Default    | Description                                                                                                         |
| ------------------------------ | ---------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------- |
| `-t, --title`                  | string                                         | (required) | Issue title                                                                                                         |
| `-T, --type`                   | string                                         | (required) | `plan(<file>)`, `plan(<file>,<parent>)`, `phase(<parent_id>)`, or `task(<slug>)`. Feature flags use `sase flag new` |
| `-f, --field`                  | `k=v`                                          | -          | Task-type field value; repeatable. `@<path>` reads the value from a file                                            |
| `-d, --description`            | string                                         | -          | Issue description                                                                                                   |
| `-a, --assignee`               | string                                         | -          | Assignee name                                                                                                       |
| `-m, --model`                  | string                                         | -          | Epic land-agent, phase-worker, or task-worker model                                                                 |
| `-R, --ref`                    | artifact reference                             | -          | Artifact reference to attach; repeatable                                                                            |
| `-z, --size`                   | `xsmall`, `small`, `medium`, `large`, `xlarge` | -          | Phase/task size; phases use model and plan-first routing, tasks use model routing only                              |
| `-r, --tier`                   | `plan`, `epic`                                 | -          | Plan-bead tier; invalid for phase and task beads                                                                    |
| `--patch` / `-c, --changespec` | Patch name                                     | -          | Attach Patch metadata to a plan bead; `--changespec` is legacy-compatible                                           |
| `-b, --bug-id`                 | string                                         | -          | Bug ID for the attached Patch; requires `--patch` or `--changespec`                                                 |

#### `sase bead list`

| Flag              | Values                                              | Default     | Description                                                            |
| ----------------- | --------------------------------------------------- | ----------- | ---------------------------------------------------------------------- |
| `-f, --format`    | `compact`, `json`, `full`                           | `compact`   | Output format                                                          |
| `-n, --limit`     | non-negative integer                                | (unlimited) | Maximum beads to print; closed listings default to 20, `0` means all   |
| `-s, --status`    | `open`, `claimed`, `ready`, `in_progress`, `closed` | -           | Filter by status (repeatable)                                          |
| `-T, --task-type` | catalog slug or `untyped`                           | -           | Filter by task type (repeatable); `untyped` selects legacy beads       |
| `-r, --tier`      | `plan`, `epic`                                      | -           | Filter by plan-bead tier (repeatable)                                  |
| `-t, --type`      | `plan`, `phase`, `task`                             | -           | Filter by issue type (repeatable). Flag beads are tasks; use `-T flag` |

#### `sase bead search`

| Flag              | Values                                              | Default     | Description                                                            |
| ----------------- | --------------------------------------------------- | ----------- | ---------------------------------------------------------------------- |
| `query`           | string                                              | (required)  | Literal non-empty text to search for                                   |
| `-c, --color`     | `auto`, `always`, `never`                           | `auto`      | Color mode for compact output                                          |
| `-f, --format`    | `compact`, `json`, `full`                           | `compact`   | Output format                                                          |
| `-n, --limit`     | non-negative integer                                | (unlimited) | Maximum results to print; `0` also means unlimited                     |
| `-s, --status`    | `open`, `claimed`, `ready`, `in_progress`, `closed` | -           | Filter by status (repeatable); all statuses are searched by default    |
| `-T, --task-type` | catalog slug or `untyped`                           | -           | Filter by task type (repeatable); `untyped` selects legacy beads       |
| `-r, --tier`      | `plan`, `epic`                                      | -           | Filter by plan-bead tier (repeatable)                                  |
| `-t, --type`      | `plan`, `phase`, `task`                             | -           | Filter by issue type (repeatable). Flag beads are tasks; use `-T flag` |

#### `sase bead task-type`

With no subcommand, `sase bead task-type` defaults to `sase bead task-type list`.

| Flag / argument | Values | Default | Description                                            |
| --------------- | ------ | ------- | ------------------------------------------------------ |
| `list`          |        |         | Colored catalog table; `-a/--all` includes uncreatable |
| `show <slug>`   |        |         | Full spec, fields, template, triage, and provenance    |
| `-j, --json`    | flag   | -       | Machine-readable output on `list` and `show`           |

#### `sase bead epic-symbols`

| Flag           | Values                    | Default   | Description                                |
| -------------- | ------------------------- | --------- | ------------------------------------------ |
| `id`           | string                    | (all)     | Optional bead ID; omit to list every entry |
| `-c, --color`  | `auto`, `always`, `never` | `auto`    | Color mode for compact output              |
| `-f, --format` | `compact`, `json`         | `compact` | Output format                              |

#### `sase bead show`

| Flag           | Values                    | Default    | Description   |
| -------------- | ------------------------- | ---------- | ------------- |
| `id`           | string                    | (required) | Issue ID      |
| `-f, --format` | `compact`, `json`, `full` | `full`     | Output format |

#### `sase bead open`

| Flag | Values | Default    | Description        |
| ---- | ------ | ---------- | ------------------ |
| `id` | string | (required) | Issue ID to reopen |

#### `sase bead update`

| Flag                | Values                                              | Default    | Description                              |
| ------------------- | --------------------------------------------------- | ---------- | ---------------------------------------- |
| `ids`               | string                                              | (required) | One or more full or shorthand issue IDs  |
| `-s, --status`      | `open`, `claimed`, `ready`, `in_progress`, `closed` | -          | Change status; `ready` is task-only      |
| `-t, --title`       | string                                              | -          | Change title                             |
| `-d, --description` | string                                              | -          | Change description                       |
| `-n, --notes`       | string                                              | -          | Change notes                             |
| `-D, --design`      | path                                                | -          | Change design path; all types accepted   |
| `-a, --assignee`    | string                                              | -          | Change assignee                          |
| `-m, --model`       | string                                              | -          | Change launch model                      |
| `-b, --remove-by`   | `YYYY-MM-DD/release`                                | -          | Extend one `flag` task bead's thresholds |
| `-z, --size`        | `xsmall`, `small`, `medium`, `large`, `xlarge`      | -          | Change phase/task size                   |
| `-r, --tier`        | `plan`, `epic`                                      | -          | Change plan-bead tier                    |

#### `sase bead close`

| Flag               | Values                           | Default    | Description                                            |
| ------------------ | -------------------------------- | ---------- | ------------------------------------------------------ |
| `ids`              | string                           | (required) | One or more IDs; exactly one epic ID with `--phases`   |
| `-f, --force`      | flag                             | -          | Sweep unfinished descendants; needs both below         |
| `-P, --no-push`    | flag                             | -          | Commit the close locally but skip the post-commit push |
| `-n, --note`       | string                           | -          | Attributed note appended to each listed issue          |
| `-p, --phases`     | number/range list                | -          | Close numbered phase beads of the target epic          |
| `-r, --reason`     | string                           | -          | Optional close reason text                             |
| `-R, --resolution` | `canceled`, `done`, `superseded` | `done`     | How this bead was resolved                             |

#### `sase bead rm`

Atomically removes the requested issues and the recursive union of their descendants.
Every requested ID must exist; overlapping or repeated selections remove each issue only
once. Removal is irreversible.

| Flag  | Values | Default    | Description           |
| ----- | ------ | ---------- | --------------------- |
| `ids` | string | (required) | One or more issue IDs |

#### `sase bead dep add`

| Flag         | Values | Default    | Description               |
| ------------ | ------ | ---------- | ------------------------- |
| `issue`      | string | (required) | Issue that depends        |
| `depends_on` | string | (required) | Issue being depended upon |

#### `sase bead sync`

| Flag           | Values | Default | Description                          |
| -------------- | ------ | ------- | ------------------------------------ |
| `-s, --status` | flag   | -       | Check sync status without committing |

#### `sase bead work`

| Flag                  | Values                 | Default    | Description                                                                                        |
| --------------------- | ---------------------- | ---------- | -------------------------------------------------------------------------------------------------- |
| `targets`             | bead IDs or plan paths | (required) | One or more epic/task beads or validated epic plan files, processed in order until the first error |
| `-a, --artifacts-dir` | directory              | -          | Back-fill planner artifacts after each approved epic; plan-file targets only                       |
| `-c, --cl-name`       | Patch name             | -          | Approved epic Patch name applied per plan-file target                                              |
| `-n, --dry-run`       | flag                   | -          | Preview the epic wave plan or task prompt without mutating files, beads, or agents                 |
| `-j, --json`          | flag                   | -          | Print one result object per processed target as JSON Lines and imply `--yes-to-all`                |
| `-P, --no-push`       | flag                   | -          | Commit checkpoint state locally but skip post-commit pushes                                        |
| `-p, --parent`        | bead ID or `top-level` | -          | Override a plan file's `parent_bead`, including forcing an unparented epic; plan-file targets only |
| `-y, --yes`           | flag                   | -          | Skip only the launch confirmation prompt                                                           |
| `-Y, --yes-to-all`    | flag                   | -          | Skip both destructive-cleanup and launch confirmation prompts                                      |

Multiple `sase bead work` targets are non-atomic: earlier successes are not rolled back,
later targets are not prevalidated, and every command-wide flag is checked again for the
current target.

### SDD repository and plan commands

SDD initialization/path resolution lives under `sase repo`; artifact browsing and
prompt/plan link maintenance live under `sase plan`. Link commands accept `-p/--path`,
which may point at an SDD root or a project root. Bare `sase plan links` defaults to its
`list` child.

| Command                    | Flags                                                                     | Description                                                    |
| -------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `sase repo init`           | `-p/--path`, `-c/--check`, `-d/--diff`, `-C/--no-commit`                  | Initialize configured sidecars and repository wiring           |
| `sase repo path REPO`      | `-e/--ensure`, `-p/--project`, `-w/--workspace`                           | Print a primary or sidecar path; optionally materialize it     |
| `sase plan links [list]`   | `-p/--path`, `-j/--json`                                                  | List prompt/plan artifact links and bidirectional status       |
| `sase plan links repair`   | `-p/--path`, `-w/--write`                                                 | Infer unambiguous prompt/plan pairs and optionally write fixes |
| `sase plan links validate` | `-p/--path`, `-j/--json`, `-q/--quiet`, `-W/--show-warnings`              | Validate a plan's own metadata and `PROMPT` bullet             |
| `sase plan search`         | `-k/--kind`, `-o/--source`, `-f/--format`, plus query/date/status filters | Search or browse tale, epic, prompt, and research artifacts    |

### `sase validate`

`sase validate` is the top-level portable SASE validation command. It runs the explicit
`sase init memory --check`, `sase init repo --check`, and `sase init skills --check`
surfaces plus `sase plan links validate`, prints one status line per check, and exits
non-zero if any check fails. It deliberately leaves the machine-local Config planner to
bare `sase init --check` and `sase doctor`, so clean CI hosts do not need a synthetic
machine identity. The command can still fail on user/home memory or skill deployment
drift even when repository-local SDD validation passes.

A check can pass and still have something to say. When a check that exits 0 prints its
own `Warnings:` section — `sase init skills --check` deferring a chezmoi redeploy is the
common case — `sase validate` collects those lines and reprints them under a single
`Warnings:` block, after the per-check status lines and before any failure output. The
block is informational: it does not change the exit code, and it is separate from the
stdout dump that a failing or skipped check still produces.

### `sase doctor`

Runs the read-only support diagnostics bundle for the active runtime, configuration,
provider setup, project/workspace state, bead store, agent index, and telemetry when
configured. Default mode is bounded and safe to run before asking for help; deep mode
adds slower read-only checks.

| Flag                  | Values   | Default | Description                                                             |
| --------------------- | -------- | ------- | ----------------------------------------------------------------------- |
| `-j`, `--json`        | flag     | -       | Emit the `schema_version: 1` JSON support report.                       |
| `-v`, `--verbose`     | flag     | -       | Show every check plus bounded details in human output.                  |
| `-D`, `--deep`        | flag     | -       | Include slower read-only deep checks.                                   |
| `-s`, `--strict`      | flag     | -       | Exit non-zero for warnings as well as errors.                           |
| `-L`, `--list-checks` | flag     | -       | List registered default and deep check ids without running them.        |
| `-C`, `--check`       | id/group | repeat  | Run only the selected check id or group; may be passed multiple times.  |
| `-p`, `--project`     | string   | infer   | Inspect a named project when doctor cannot infer one from the checkout. |

Use `sase doctor -L` to list targeted check IDs. Useful focused checks include
`runtime`, `llm.default`, `plugins.required`, `plugins.resources`, `beads.task_types`,
`project.junk_directories`, `workspace.missing_checkouts`,
`workspace.occupancy_conflicts`, and `config.model_xprompts`. The two inventory checks
report telemetry-only directories without ProjectSpecs and registered workspace paths
missing from disk; both are read-only and provide cleanup/repair guidance.
`workspace.occupancy_conflicts` reports RUNNING-field and occupant-record collisions and
never auto-repairs.

Default exit behavior is `0` for `OK`, `WARN`, and `SKIP`, and `1` for `ERROR`. Attach
`sase doctor -v` or `sase doctor -j` when asking for help.

### `sase flag`

With no subcommand, `sase flag` defaults to `sase flag list`.

| Form             | Flag or argument                                                                                                                                | Description                                                                  |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `sase flag list` | `-j, --json`                                                                                                                                    | List registered flags, resolved values, provenance, beads, and due state.    |
| `sase flag show` | `<key>`, `-j/--json`                                                                                                                            | Show one flag's full decision, bead thresholds, diagnostics, and call sites. |
| `sase flag new`  | `<key>`, `--when-enabled`, `--when-disabled`, `--remove-when`, `-d/--description`, `-k/--kind` (`beta`/`sunset`), `-r/--remove-by`, `-z/--size` | Create a `flag` task bead and print the registry entry to paste.             |

`new` requires a SASE-managed checkout because the registry lives in this source tree.
`--when-enabled`, `--when-disabled`, and `--remove-when` are required and each accepts
`@<path>`. `-k/--kind` is `beta` (default; off) or `sunset` (on). There is no `--scope`.

### `sase file-hook`

With no subcommand, `sase file-hook` delegates to `sase file-hook list`. The list shows
each valid effective hook's name, description, command, project/sidecar/glob/operation
filters, timeout, and contributing config source. Invalid and duplicate hooks are
already excluded with configuration warnings, so this is the runtime-effective view
rather than a raw config dump.

| Form                         | Flag         | Description                         |
| ---------------------------- | ------------ | ----------------------------------- |
| `sase file-hook list`        | —            | Render the effective hook table.    |
| `sase file-hook list --json` | `-j, --json` | Emit machine-readable hook records. |

See [`file_hooks`](#file_hooks) for matching, merge, execution, and notification
behavior.

### `sase version`

`sase version` reports the local runtime that the current `sase` process is using. It
does not query PyPI, GitHub, or latest available releases. The inventory always includes
the host `sase` package and the required `sase-core-rs` Rust core distribution, then
adds installed SASE plugin packages discovered through SASE entry points, SASE console
scripts, or `sase-*` distribution names.

The default human output is a compact runtime panel plus a package table with role,
effective version, and code directory. Development checkouts use PEP 440 local versions
such as `0.1.2+4.g26c39e004` or `0.1.2+0.g26c39e004.dirty`. Editable installs prefer
source metadata over stale installed distribution metadata, while `--verbose` and
`--json` expose both values for auditability.

| Flag            | Values | Default | Description                                                                   |
| --------------- | ------ | ------- | ----------------------------------------------------------------------------- |
| `-j, --json`    | flag   | -       | Emit a stable JSON object with `schema_version: 1`, runtime, and packages.    |
| `-v, --verbose` | flag   | -       | Include install type, dist/source versions, git metadata, and plugin signals. |

### `sase var`

`sase var` inspects and publishes SASE agent output variables. Agents publish values
with `sase var set`, which merges named JSON-shaped values into the current run's
`agent_meta.json["output_variables"]`. The stored values appear in ACE's Agents-tab
`OUTPUT VARIABLES` metadata panel, Telegram agent-completion messages, indexed agent
history, and downstream `%wait` prompt contexts. Later agents that wait on a producer
load that producer's stored values when they start and can render them through the
`agents` Jinja dictionary in prompts and xprompt workflows.

With no subcommand, `sase var` prints a delegation notice and runs `sase var list`.

| Form                                 | Flags / arguments                    | Description                                                                  |
| ------------------------------------ | ------------------------------------ | ---------------------------------------------------------------------------- |
| `sase var get`                       | `-c`, `-f pretty\|json`              | Show the current agent's output-variable snapshot from `SASE_ARTIFACTS_DIR`. |
| `sase var get '<AGENT_NAME>'`        | `-c`, `-f pretty\|json`, `-p`, `-H`  | Show the newest exact-name historical snapshot. Quote the wrappers.          |
| `sase var get SELECTOR [...]`        | `-c`, `-f pretty\|raw\|json\|jsonl`  | Resolve precise values by exact, wildcard, hood, and JSON-path selectors.    |
| `sase var list`                      | `-a`, `-k`, `-p`, dates, value flags | Discover keys and distinct typed values across indexed agent history.        |
| `sase var set KEY=VALUE [...]`       | positional assignments               | Store one or more strings, splitting each assignment at the first `=`.       |
| `sase var set KEY --value TEXT`      | `-v, --value TEXT`                   | Store one string verbatim, including spaces or newlines.                     |
| `sase var set KEY --value-file PATH` | `-f, --value-file PATH`              | Read one string as UTF-8 text; use `-` to read standard input.               |
| `sase var set ... --json`            | `-j, --json` plus a form above       | Decode supplied values as JSON strings, scalars, lists, maps, or `null`.     |

`sase var get` has three modes. With no target, it reads the current agent's artifact
directory directly so recent writes are visible before the agent completes; this form
requires `SASE_ARTIFACTS_DIR`. With exactly one quoted `<AGENT_NAME>`, it searches
indexed history and returns the newest exact-name artifact. Quote the wrappers so the
shell keeps them intact, for example `sase var get '<build>' --format json`. Use
`--project PROJECT` to disambiguate repeated names across projects, where `PROJECT` may
be a display name or alias and may be repeated. `--hidden` includes hidden indexed
agents. An agent with no variables is an empty success; an unknown name is an error.
`--format pretty` renders the same readable block form used in ACE, while
`--format json` emits the variable map as compact machine-readable JSON. Snapshot mode
rejects selector-only `--format raw` / `jsonl` and an explicit `--limit`.

`sase var list` is historical discovery. It groups indexed output variables by key,
orders keys by most-recent occurrence, and shows each key's distinct typed values plus
the contributing agent names. Repeated filters in one dimension are ORed; different
dimensions are ANDed. Major filters are:

- `--agent GLOB` / `-a`: filter by agent-name glob. `hood.*` includes the hood root.
- `--key GLOB` / `-k`: filter by case-sensitive variable-key glob.
- `--project PROJECT` / `-p`: filter by project display name or alias; repeatable.
- `--hidden` / `-H`: include hidden indexed agents; visible history is the default.
- `--since DATE` / `-s` and `--until DATE` / `-u`: filter by launch time using the same
  date grammar as bead history filters.
- `--value TEXT` / `-v`: case-insensitive substring match over scalar text and canonical
  JSON.
- `--value-json JSON` / `-V`: exact typed JSON value match after output-variable
  normalization. It is mutually exclusive with `--value`.
- `--limit KEYS[:VALUES]` / `-n`: cap returned keys and distinct values per key. The
  default is `20:5`; `0` means unlimited for that dimension; a single number changes
  only the key limit.
- `--reverse` / `-r`: invert the normal recent-first key and value order.

`sase var list --format pretty` prints readable grouped blocks. `--format json` emits a
stable envelope with `schema_version`, the normalized query, limit metadata, and grouped
values. `--format jsonl` emits one compact JSON object per returned distinct value.

With one or more ordinary targets, `sase var get` retrieves exact values from indexed
history with selectors:

```text
[SCOPE.]KEY[PATH ...]
```

`KEY` is a variable name or `*`. `SCOPE` may be an exact agent name, `*` for every
agent, or `HOOD.*` for a hood. Unscoped keys choose the newest matching occurrence.
Exact-agent selectors choose that name's newest artifact. Global and hood wildcard
selectors collapse repeated runs to the newest value per agent name. JSON paths follow
the selected value with `[INDEX]` for lists or `["KEY"]` for map keys; dotted map
traversal is not accepted. `sase var get build.*` remains selector mode and is distinct
from snapshot-mode `sase var get '<build>'`.

Examples:

```bash
sase var get
sase var get --format json
sase var get '<build>' --format json
sase var get status
sase var get build.status --format raw
sase var get '*.status' --format json
sase var get 'research.*.report["summary"]'
sase var get results[0]
```

Selector `--format pretty` prints each match with attribution. `--format raw` prints one
value only and fails unless the selector resolves to exactly one untruncated match;
strings print as text, and structured values print as compact JSON. `--format json`
emits a stable envelope with `schema_version`, query, limit metadata, and matches.
`--format jsonl` emits one compact JSON object per match. Wildcard expansion defaults to
20 matches; `--limit 0` is unlimited. `--project` is repeatable, and `--hidden` includes
hidden indexed agents. `--limit` applies only to selector wildcard expansion.

`sase var set` is the mutation command. It is agent-scoped and requires `SASE_AGENT=1`
and `SASE_ARTIFACTS_DIR`. Successful writes print the current agent name when known, the
stored keys, and the artifact directory.

Keys must be valid Jinja attribute identifiers (`[A-Za-z_][A-Za-z0-9_]*`). Values may
contain spaces, blank lines, newlines, and additional equals signs. The `KEY=VALUE` form
splits only on the first `=` and preserves everything after it; quote the whole
assignment when the shell would otherwise split it. `--value` likewise preserves exactly
the text supplied by the shell, including any trailing newlines. `--value-file` reads a
file or stdin and removes at most one trailing newline after normalizing line endings,
which makes files, pipes, and heredocs convenient without discarding an intentional
trailing blank line. With `--json`, JSON whitespace is ignored by the decoder and no
trailing newline is removed before parsing:

```bash
sase var set 'suites=["unit","integration"]' --json
sase var set cfg --json --value '{"retries":3,"enabled":true}'
sase var set report --json --value-file report.json
sase var set findings --json --value-file - <<'JSON'
[{"file":"src/a.py","severity":"high"}]
JSON
```

A value may be any JSON string, number, boolean, null, list, or map. Nested map keys may
be any non-empty NUL-free string. Map keys are normalized into sorted order for
deterministic storage and display; list order is always preserved. Structured values
reach Jinja as real containers, so consumers can use attribute/subscript access and
loops. Rendering an entire container with `{{ agents["build"].cfg }}` yields compact
JSON, while `| tojson` remains available for explicit JSON formatting.

An agent may store at most 256 variables. Each string leaf and nested map key is limited
to 8,192 UTF-8 bytes; each variable is limited to depth 8, 1,024 total
container-plus-leaf nodes, and 65,536 compact encoded JSON bytes. Numbers must be finite
and integers must fit the signed 64-bit range. Every string converts CRLF and lone CR
line endings to LF and rejects NUL characters. Invalid or oversized values fail visibly
instead of disappearing during publication.

Multiple calls merge into the same variable map; later writes for the same key replace
earlier values. The command does not update prompts that have already started rendering,
so write variables before the producing agent completes and before dependent agents
unblock. Downstream prompts read each producer's variables from the single `agents`
dictionary keyed by the producer's stable agent name, e.g.
`{{ agents["build"].report_path }}` (or `{{ agents.build.report_path }}` for
identifier-safe names). Do not store secrets; output variables are persisted in
`agent_meta.json` and shown in ACE and Telegram completion messages.

`STOP` is a reserved output variable. `sase var set` stays generic and stores it like
any other key, but repeat orchestration interprets it: setting `STOP` (e.g.
`sase var set STOP=1`) inside a `%repeat` / `%r` iteration stops the remaining repeat
slots, which finalize as successful skipped slots. `null`, `false`, numeric zero, empty
strings, empty lists, and empty maps are not-stop; string values `0`, `false`, `no`, and
`off` are also not-stop case-insensitively after trimming. Any other value stops the
chain. `STOP` affects only repeat-chain continuation; ordinary `%wait` consumers read it
as a normal variable. See [Repeat Directive](xprompt.md#repeat-directive) in the xprompt
reference for the full cascade semantics.

### `sase telemetry`

With no subcommand, `sase telemetry` prints a delegation notice and runs
`sase telemetry list`.

| Flag         | Values                                                      | Default | Description          |
| ------------ | ----------------------------------------------------------- | ------- | -------------------- |
| _subcommand_ | `cleanup-test-data`, `health`, `list`, `snapshot`, `status` | `list`  | Telemetry subcommand |

See [docs/telemetry.md](telemetry.md) for the full CLI reference including
per-subcommand flags.

### `sase logs`

| Flag        | Values | Default    | Description                                                     |
| ----------- | ------ | ---------- | --------------------------------------------------------------- |
| `daterange` | string | (required) | Date range to collect (e.g., `-7d`, `260318`, `260315..260318`) |

Supported date range formats:

- **Absolute**: `YYmmdd` or `YYmmddHHMMSS`
- **Relative**: `-Nd` (days ago), `-Nh` (hours ago), `-Nm` (minutes ago), `0d` (today)
- **Ranges**: `START..END` (e.g., `-7d..0d`); single point means "from that point to
  now"

The run and event inputs at `~/.sase/logs/runs.jsonl` and `events.jsonl` rotate
independently before appending a record would make a non-empty file exceed 2 MiB.
Rotation keeps one `.1` generation and replaces an older backup; set
`SASE_RUN_LOG_MAX_BYTES` to another byte limit, or `0` for no size rotation. The current
`sase logs` collector reads only the active `.jsonl` files and skips malformed lines
there, so copy the matching `.1` files separately when a support bundle must include
records from the previous generation.

### `sase editor`

`sase editor` exposes JSON-over-stdin helper operations for editor integrations. It is
intentionally a fixed-operation bridge rather than a generic shell or filesystem API.

| Form                                         | Input                | Description                                                                                                      |
| -------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `sase editor helper-bridge agent-catalog`    | JSON object on stdin | Return active/recent agents and derived family, clan, and tribe prompt targets.                                  |
| `sase editor helper-bridge xprompt-catalog`  | JSON object on stdin | Return the structured xprompt catalog; accepts the same schema as the mobile `xprompt-catalog` helper operation. |
| `sase editor helper-bridge snippet-catalog`  | JSON object on stdin | Return the composed ACE snippet registry used by `sase lsp` and editor completion clients.                       |
| `sase editor helper-bridge vcs-repo-catalog` | JSON object on stdin | Return repository completion candidates for a VCS workflow and namespace.                                        |

The `agent-catalog` request is just `{"schema_version":1}`; it has no project filter and
reads the cross-project agent snapshot. Ordinary rows are de-duplicated by name and
include `status` and `project`, with `kind: agent` for agents and `kind: monitor` for
monitors. When group metadata is available, additive family, clan, and `@tribe` rows
include `kind`, `member_count`, and display-ready `detail`; clan rows also include
aggregate `status`. For the 20 most recently active families, SASE tries to enrich
`detail` with the associated plan or bead's kind, structure, and title, and to add
Markdown `documentation` carrying the goal, phase list, or parent/task context plus a
family status footer. Unresolved or older families keep the plain member-count detail,
and enrichment failure never removes ordinary rows; see
[Editor Integration: Helper Bridge](editor.md#helper-bridge) for the exact fallback
ladder. The structured xprompt catalog includes insertion metadata (`insertion`,
`reference_prefix`, `kind`), typed argument metadata, display/source fields, and
`definition_path` when SASE can resolve a real file to jump to.

The snippet catalog uses the same source ordering as ACE: xprompts marked with `snippet`
front matter plus user-defined `ace.snippets`, with `ace.snippets` winning on trigger
collisions. It also includes the generated initial-capital aliases (`foo` → `Foo`), so
editor completion and the native fallback expose exactly the same trigger/template pairs
as the TUI.

### `sase file`

With no subcommand, `sase file` defaults to `sase file list`.

| Form             | Flags                     | Description                                                                                     |
| ---------------- | ------------------------- | ----------------------------------------------------------------------------------------------- |
| `sase file list` | `-p/--path`, `-t/--token` | Emit JSON filesystem completion candidates rooted at `--path` and filtered by the cursor token. |

### `sase file-history`

With no subcommand, `sase file-history` defaults to `sase file-history list`.

| Form                       | Flags       | Description                                                      |
| -------------------------- | ----------- | ---------------------------------------------------------------- |
| `sase file-history list`   | none        | Emit the recency-ordered file-reference history as a JSON array. |
| `sase file-history delete` | `-p/--path` | Remove one entry from the file-reference history.                |

### `sase gate`

Create a durable command-backed gate from a schema-version 3 JSON specification, or wait
mechanically for a gate's terminal result.

| Form               | Flags                                               | Description                                               |
| ------------------ | --------------------------------------------------- | --------------------------------------------------------- |
| `sase gate create` | `-s/--sender`, `-t/--tag`                           | Create a durable gate from a JSON specification on stdin  |
| `sase gate wait`   | `-i/--id`, `-j/--json`, `-k/--kind`, `-t/--timeout` | Wait for a gate; exits 0 answered, 3 cancelled, 4 timeout |

Gate creation accepts one option `query`, a required complete `primary_branch`, an
`options` list with configurable labels, icons, default selections, and feedback modes,
plus optional `groups` metadata for AND-branch submit controls. It returns a stable JSON
descriptor with the request identity, owned paths, continuation/auto state, and hashes.
`sase gate wait -j` emits `status`, `selected_option_ids`, `feedback`, and
`response_path`; a CLI timeout can shorten but not extend the request timeout.

### `sase lsp`

Starts the xprompt language server over stdio for editor integrations.
`SASE_XPROMPT_LSP_CMD` can override the server command during development. Without that
override, `sase lsp` uses the current Python environment's `bin/sase-xprompt-lsp`, then
`sase-xprompt-lsp` from `PATH`, then the newer debug/release binary from a sibling
`../sase-core` checkout, then falls back to `cargo run` from that sibling checkout when
Cargo is available. Full editable-install SASE updates reinstall the server into the
uv-tool venv when pulled `sase-core` commits change.

| Flag              | Values | Default | Description                            |
| ----------------- | ------ | ------- | -------------------------------------- |
| `-V`, `--version` | flag   | -       | Print the xprompt LSP version and exit |

### `sase path`

| Flag   | Values                                                                           | Default    | Description         |
| ------ | -------------------------------------------------------------------------------- | ---------- | ------------------- |
| `name` | `xprompts-dir`, `xprompts-schema`, `xprompts-collection-schema`, `config-schema` | (required) | Which path to print |

### `sase notify`

With no subcommand, `sase notify` defaults to the compact `sase notify list` view. Use
`sase notify list` for JSON, limit, query, unread, dismissed, or the clearest sender/tag
filtering form. Use `sase notify create` to write a raw, non-privileged notification
from stdin JSON. Use `sase gate create` and `sase gate wait` for command-backed gates.

| Form                 | Flags                                                                                         | Description                                                 |
| -------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `sase notify`        | `-s/--sender`, `-t/--tag`                                                                     | Shortcut for `sase notify list` with default compact output |
| `sase notify create` | `-s/--sender`, `-t/--tag`                                                                     | Create a raw notification from stdin JSON                   |
| `sase notify list`   | `-j/--json`, `-l/--limit`, `-q/--query`, `-t/--tag`, `-s/--sender`, `-u/--unread`, `-a/--all` | List recent notifications; `-j` emits the stable JSON shape |
| `sase notify show`   | `-i/--id`, `-f/--format` (`markdown` or `json`)                                               | Show one notification by id; defaults to markdown           |

Raw creation accepts JSON `icon`, `tags`, and `silent` fields plus repeatable
`-t/--tag`; icons must be one emoji or display glyph, and CLI tags are appended to JSON
tags, then normalized and deduplicated. Raw creation cannot create a registered
privileged gate action. The query form, `sase notify list -q`, also matches tags, and
`sase notify list --tag <tag>` filters to notifications with that exact normalized tag.

### `sase plan`

With no subcommand, `sase plan` defaults to the `sase plan list` dashboard.

| Form                             | Flags                                                                                                                         | Description                                                             |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `sase plan approve [selector]`   | `-k/--kind`, `-m/--model`, `-p/--prompt`                                                                                      | Approve one pending proposal by notification ID or unique ID prefix.    |
| `sase plan` / `sase plan list`   | `-j/--json`, `-n/--limit`, `-s/--status`, `-t/--tier`                                                                         | List pending proposals, approvals, and inferred rejected rows.          |
| `sase plan propose <plan_file>`  | -                                                                                                                             | Submit a Markdown plan file for approval from the `/sase_plan` skill.   |
| `sase plan reject [selector]`    | -                                                                                                                             | Reject one pending proposal by notification ID or unique ID prefix.     |
| `sase plan search [query]`       | `-f/--format`, `-k/--kind`, `-s/--status`, `-o/--source`, `-r/--sort`, `-A/--since`, `-B/--until`, `-n/--limit`, `-c/--color` | Search SDD and machine-local Markdown plans.                            |
| `sase plan validate <plan_file>` | `-e/--explain`, `-j/--json`, `-q/--quiet`                                                                                     | Validate using the plan's authored `tier: tale` or `tier: epic` schema. |

`sase plan list` prints a Rich dashboard by default and emits a stable JSON projection
with `summary`, `proposed`, `approved`, and `rejected` keys when `-j/--json` is set.
Repeat `-s/--status` with `approved`, `proposed`, or `rejected` to render or serialize
only those sections; unrequested JSON section keys are omitted, while summary counts
continue to describe the full collected view. `-n/--limit` controls the maximum rows in
each Approved and Rejected history section (default `10`, with `0` meaning unlimited).
Proposed rows are always shown in full. `-t/--tier` composes with both filters. The JSON
summary includes `status_filter`, `tier_filter`, and a non-default `limit` when
applicable, plus `approved_scan_truncated` if a finite artifact scan may have omitted
older approvals.

Use the Proposed row's `id_prefix` as the selector for `sase plan approve` or
`sase plan reject`; omitting the selector is valid only when exactly one pending
proposal exists. The Rejected rows are inferred from archived proposal files that are
not represented by current proposed or approved state, so they are useful for history
but are not actionable selectors. Omitting `--kind` uses the plan's authored tier;
explicit choices override it and tale/epic targets are validated before the proposal is
consumed. Approval kind `approve` runs the coder without asking the runner to commit an
SDD plan, `tale` commits the plan as an SDD tale and then runs the coder, `epic` commits
the matching SDD tier and launches the bead follow-up, and `commit` records the approved
plan in SDD without launching a coder. The `-m/--model` flag applies to the follow-up
agent; `-p/--prompt` adds extra coder instructions only for the `approve` and `tale`
paths. `sase plan reject` writes the rejection response first, then attempts the same
durable cleanup path as TUI no-feedback rejection when the matching planner row is still
discoverable.

`sase plan search [query]` scans plans in the resolved SDD store (the `repo` source) and
the machine-local `~/.sase/plans/` archive. The query is a literal case-insensitive
substring; omit it to browse and filter. `--format` accepts `compact`, `full`, `json`,
or `markdown`; `--kind` is repeatable and filters SDD-store plans to `tale`, `epic`,
`research`; `--status` is repeatable and filters frontmatter status to `wip` or `done`;
`--source` selects `all`, `repo`, or `local`; `--sort` selects `relevance`, `recent`, or
`title` (defaulting to relevance with a query and recent without one);
`--since`/`--until` accept `YYYY-MM-DD`, `YYYY-MM`, `YYYYMM`, or relative durations such
as `14d`; and `--limit 0` prints all matches.

`sase plan validate <plan_file>` infers the validation schema from the authored `tier`;
it no longer accepts `-t/--tier`. `--explain` prints tier-specific authoring guidance
before human results or adds it to the JSON envelope, while `--quiet` suppresses only
the successful human summary. See
[Plan Frontmatter Schema and Validation](sdd.md#plan-frontmatter-schema-and-validation)
for diagnostics and exit codes.

### `sase artifact`

`sase artifact` creates, discovers, inspects, resolves, opens, and repairs indexed
artifacts. Bare `sase artifact` delegates to `sase artifact list`, and
`sase artifact-file` remains a compatibility alias for the whole group.

`sase artifact create` is intended for code agents running with `SASE_AGENT=1` and
`SASE_ARTIFACTS_DIR` set. It copies a generated file into persistent SASE artifact
storage and associates it with the current agent so the Agents tab can open it with `A`,
even after the agent has been dismissed and revived. `-k/--kind` accepts `chat`, `plan`,
`image`, `markdown`, `pdf`, or `file` and defaults to a kind inferred from the file
extension. `-m/--move` opts into removing the source after it is stored. On success the
command prints the artifact's `id:`, absolute `source:`, stored `path:`, and durable
`ref:` (`file:<id>`). Only `create` is agent-gated; every other artifact subcommand
works outside an agent run.

| Form                                 | Flags                                                                                                                            | Description                                                                                       |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `sase artifact create`               | `-b/--bead`, `-k/--kind`, `-l/--label`, `-m/--move`, `-p/--path`                                                                 | Store one explicit artifact for the current agent                                                 |
| `sase artifact doctor`               | `-f/--fix`, `-v/--verify`                                                                                                        | Report index health (including VCS reference counts), backfill enrichment fields, verify hashes   |
| `sase artifact list`                 | `-a/--agent`, `-e/--explicit`, `-j/--json`, `-k/--kind`, `-l/--limit`, `-p/--project`, `-q/--query`, `-s/--since`, `-u/--unused` | List indexed artifacts newest-first                                                               |
| `sase artifact open`                 | (positional `reference`)                                                                                                         | Open a resolved reference with a kind-appropriate viewer                                          |
| `sase artifact path`                 | (positional `reference`)                                                                                                         | Print the one absolute path a reference resolves to                                               |
| `sase artifact prune`                | `-a/--apply`, `-b/--before`, `-g/--keep-generations`, `-j/--json`, `-k/--kind`, `-l/--limit`, `-m/--min-size`, `-p/--project`    | Plan retention, then move selected automatic rows to restorable trash only with `--apply`         |
| `sase artifact reclaim`              | `-a/--apply`, `-d/--max-history-scan`, `-j/--json`, `-l/--limit`, `-p/--project`                                                 | Convert eligible stored automatic rows to verified VCS-backed rows only with `--apply`            |
| `sase artifact show`                 | `-j/--json`, (positional `reference`)                                                                                            | Show metadata, resolution, and consumption                                                        |
| `sase artifact stats`                | `-j/--json`, `-p/--project`, `-t/--top`                                                                                          | Report store economics, protection-source evidence, trash occupancy, and default-policy selection |
| `sase artifact trash` / `trash list` | `-j/--json`, `-l/--limit`                                                                                                        | List trash entries newest-first, flagging entries past the grace period                           |
| `sase artifact trash purge`          | `-a/--all`, `-j/--json`                                                                                                          | Permanently delete entries past the grace period, or every entry with `-a`                        |
| `sase artifact trash restore`        | `-j/--json`, (positional `reference`)                                                                                            | Restore one entry's payload and complete index row by entry id or artifact ref                    |

`list` filters: `-k/--kind` is repeatable and accepts the artifact kinds above;
`-l/--limit` defaults to `50` and `0` means unlimited; `-p/--project` accepts a display
name, alias, or canonical key and exits 2 for an unknown project; `-q/--query` is a
case-insensitive substring match over label and paths; `-s/--since` accepts the same
DATE forms as `sase plan search` (`YYYY-MM-DD`, `YYYY-MM`, `YYYYMM`, or relative `14d` /
`3w` / `2m`); and `-u/--unused` shows only artifact files with no recorded `file:<id>`
consumption. Pretty output is a Rich panel with KIND, REF, LABEL, PROJECT (display
name), AGENT, SIZE, and CREATED columns; `-j/--json` emits every record field —
including `sha256`, `size_bytes`, and `mime_type` — plus the rendered `ref`.

`show`, `path`, and `open` accept canonical artifact references (`file:`, `stitch:`,
`patch:`, `bead:`, `agent:`, and document kinds such as `plan:`, `research:`, or
`designs:`). Historical `commit:`, `chat:`, `bug:`, and `plans:` aliases remain readable
for compatibility. Document kinds and `file:` preserve supported `#L`, `#page=`, and
`#t=` fragments; `bead:` and `agent:` reject fragments because they resolve to
regenerated pages whose anchors can drift. `bead:` resolves to the generated bead page
in the current project's beads sidecar, and `agent:` resolves to the generated
`agents/<global-name>/README.md` page in the current project's agents sidecar, so `path`
and `open` work for both after `sase bead pages refresh` or `sase agent sync` has
published the page. Bead and agent resolution is intentionally scoped to the reference
context's single project; foreign bead prefixes report `unknown_project` instead of
scanning every enabled project.

A bare `default:<hash>` or `explicit:<hash>` index id is accepted as sugar for
`file:<id>`. `path` exits 0 on success, 1 when the reference is malformed, missing, or
ambiguous (status and candidates go to stderr), and 2 for kinds with no filesystem
identity (`stitch:`, `patch:`, and historical `commit:` / `bug:`), pointing at `show`
instead. `open` treats historical `commit:` as non-viewable, opens historical `bug:` in
a browser, and currently opens a canonical `stitch:` at its resolved checkout; `patch:`
has no viewer path. `show` also reports consumption from the append-only
`~/.sase/artifacts/consumption.jsonl` ledger: `consumption_count`, `consumed_by_agents`,
`consuming_agents`, and `last_consumed_at` in pretty output, plus an additive
`consumption` object in `-j/--json` output. `doctor` exits 1 when it finds missing
enrichment fields, missing stored files, duplicate ids, unsupported schema versions,
malformed rows, or digest mismatches, and 0 on a clean bill of health.

`stats`, `prune`, `reclaim`, and opt-in automatic retention use one shared protection
collector. It unions IDs found in persistent ProjectSpec and SDD text with canonical
fragment-free `file:` IDs recorded in the consumption ledger, then passes the
deduplicated set to the applicable planner. Stats keeps referenced, consumed, overlap,
and total protection counts distinct. Prune and reclaim are dry runs unless `--apply` is
passed and never select explicit or protected rows; automatic retention enforces the
same union after agent finalization when `artifacts.retention.enabled` is true. A
missing consumption ledger contributes no IDs; a present ledger that cannot be queried
appears in protection-source evidence and blocks destructive apply or skips automatic
enforcement.

Every removal `prune`, `reclaim`, and automatic retention perform routes through the
restorable trash under `~/.sase/artifacts/trash/`: one directory per entry holding
`entry.json` (the complete original index row plus `trashed_at`, `reason`, and
`size_bytes`) and, for a byte-backed row, the moved payload file. Nothing else
hard-deletes. `trash restore` puts the payload back and re-inserts the index row; only
`trash purge` deletes permanently, and without `-a/--all` it deletes only entries older
than `artifacts.retention.trash_grace_days`. Because trashed bytes still occupy disk,
`du` does not drop until a purge runs; both apply summaries print the trash root, and
`reclaim --apply` says so outright. See
[Store Lifecycle](agent_images.md#store-lifecycle) for the end-to-end workflow.

### `sase questions`

| Flag             | Values | Default    | Description                             |
| ---------------- | ------ | ---------- | --------------------------------------- |
| `questions_json` | string | (required) | JSON string containing questions to ask |

### `sase agent`

`sase agent` provides cross-project visibility into running agents and synchronizes
shared agent history. Subcommands:

| Subcommand  | Flags                                                                                                                                    | Description                                                                                                                                                                                                                                                                                                                                                              |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `list`      | `-a/--all`, `-j/--json`, `-p/--project`                                                                                                  | List running agents. `-a` includes DONE/FAILED agents (capped at 50 per project). `-j` emits a JSON array with a stable schema. `-p` limits output to a single project.                                                                                                                                                                                                  |
| `show`      | `<name>`                                                                                                                                 | Render a full detail panel (prompt, reply, metadata) for a single agent by name.                                                                                                                                                                                                                                                                                         |
| `kill`      | `-n/--name`                                                                                                                              | SIGTERM a running agent by name.                                                                                                                                                                                                                                                                                                                                         |
| `tribe`     | `set` / `unset` / `list`                                                                                                                 | Manage the user-defined tribe on an agent (used by the Agents tab tribe side panels). `tribe set -n <agent> -t <tribe>` replaces any prior tribe; `tribe unset -n <agent>` clears it; `tribe list [-n <agent>]` prints tribes as JSON (filtered when given).                                                                                                             |
| `archive`   | `rebuild-index` / `verify`                                                                                                               | Maintain the dismissed-agent bundle summary index under `~/.sase/dismissed_bundles/`. `verify` exits non-zero if rows are stale or missing.                                                                                                                                                                                                                              |
| `artifacts` | `layout status` / `migrate` / `verify` / `rollback`, `-P/--project`, `-p/--projects-root`, `-i/--index-path`, `-j/--json`                | Inspect and migrate the physical `ace-run` artifact directory layout. `status` reports flat and sharded directory counts, `migrate` moves flat timestamp directories into day shards, `verify` checks current or manifest-backed state, and `rollback` reverses a manifest-backed migration.                                                                             |
| `index`     | `status` / `rebuild` / `verify` / `gc` / `repair`, `-i/--index-path`, `-p/--projects-root`, `-j/--json`; `repair -a/--apply`             | Maintain the persistent artifact index. `status` is a lightweight check, `verify` compares source artifacts, `gc` rebuilds the index and dismissed projection, and `repair` handles invalid future-dated import state.                                                                                                                                                   |
| `names`     | `migrate-auto`, `-f/--force`, `-j/--json`                                                                                                | Maintain the permanent agent-name registry. `migrate-auto` runs the historical generated-name namespace migration; `--force` reruns it after the completion marker exists and `--json` emits a machine-readable summary.                                                                                                                                                 |
| `prompts`   | `list` / `migrate` / `show` / `validate`, `-p/--project`, `-m/--month`, `-j/--json`; `migrate -w/--write`, `validate -s/--show-warnings` | Inspect the canonical agents-sidecar prompt archive. `list` browses `prompts/<YYYYMM>/`; `show` prints the archived Markdown document; `validate` checks headers, artifact bytes, manifests, and plan links; and `migrate` moves historical plans-sidecar prompts only with `--write`.                                                                                   |
| `sync`      | `-c/--check`, `-d/--drop-retired`, `-j/--json`, repeatable `-p/--project`, `-q/--retry-quarantined`, `-r/--refresh`                      | Import shared agent history, publish locally commit-eligible hoods, and drain Referenced By write-backs. Plain `--check` uses cached status without Git or artifact scans; `--check --refresh` fetches and recomputes status. Mutating sync can retry quarantined or drop retired hood and back-reference requests. See [Agent Hood Synchronization](agents_sidecar.md). |

Agent-index paths default to `~/.sase/agent_artifact_index.sqlite` and
`~/.sase/projects`. `sase agent index repair` is a dry run unless `-a`/`--apply` is
supplied. It selects future-dated agent artifacts and dismissed bundles only when they
carry import provenance (or belong to a matching import transaction), then includes the
associated import journals, staging data, artifact-index and dismissed-identity rows,
and name-registry entries. Apply removes those selected files and rebuilds the
dismissed-bundle index and name registry. It does not select locally produced
future-dated records or correctly dated imported records.

### `sase agent-cli`

`sase agent-cli` inventories the supported coding-agent CLIs, installs the ones whose
provider declares an install script, and updates the ones whose install method can be
identified safely. With no subcommand, it defaults to `sase agent-cli list`. See
[Agent providers](agent_providers.md#inventory-and-updates) for the per-install-method
update behavior.

| Subcommand | Flags                                                                                               | Description                                                                                                                                                                                                                                                                                              |
| ---------- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list`     | `-j/--json`, `-o/--offline`, `-r/--refresh`, `-v/--verbose`                                         | List every supported CLI with its binary, installed and latest versions, install method, and update marker. `-v` adds executable paths, docs URLs, and probe errors.                                                                                                                                     |
| `update`   | `<name> ...`, `-a/--all`, `-j/--json`, `-n/--dry-run`, `-o/--offline`, `-r/--refresh`               | Update named CLIs or, with `-a`, every installed one. `-n` prints exact commands and skip reasons without running them. Passing neither names nor `-a` is a usage error.                                                                                                                                 |
| `install`  | `<name> ...`, `-f/--force`, `-j/--json`, `-n/--dry-run`, `-o/--offline`, `-r/--refresh`, `-y/--yes` | Install named CLIs from the install script their provider declares. Shows the URL, SHA-256 digest, exact shell-free command, env overlay, and target directory, then requires `-y` or an interactive confirmation. `-n` prints that plan and executes nothing; `-f` reinstalls an already-installed CLI. |

`-o/--offline` uses only cached latest-version data and never contacts the network;
`-r/--refresh` bypasses that cache.

### `sase chat`

`sase chat` discovers and inspects saved agent chat transcripts. With no subcommand, it
defaults to `sase chat list`. Subcommands:

| Subcommand | Flags                                                                      | Description                                                                                                         |
| ---------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `list`     | `-j/--json`, `-l/--limit`, `-m/--machine`, `-P/--provenance`, `-q/--query` | List recent transcripts with sync provenance. `-j` emits the stable JSON shape consumed by the `/sase_chats` skill. |
| `show`     | `-n/--agent`, `-p/--path`, `-b/--basename`, `-f/--format`                  | Show one transcript by agent name, path, or basename. `--format` accepts `raw`, `resume`, or `response`.            |

## Directory Sharding

Older SASE layouts wrote many agent artifacts (chat logs, notifications, workflow state,
etc.) directly under `~/.sase/<kind>/`. After a few months of heavy use those
directories can accumulate tens of thousands of files, which slows down filesystem walks
and makes `ls`-style inspection painful.

Current high-volume writers use a `YYYYMM/` shard inside each managed artifact directory
(keyed by the current month). Readers transparently merge sharded and non-sharded files,
so the layout is backwards-compatible - existing unsharded files at the top level are
still found and the layout is fully read/write compatible across both forms.

Prompt history uses its own monthly JSON shard directory,
`~/.sase/prompt_history/YYMM.json`, because each shard stores a bounded JSON list rather
than one file per prompt. Entries whose last-used timestamp cannot be parsed are kept in
`unknown.json`. The legacy `~/.sase/prompt_history.json` file is migrated into that
directory on first read or write when the shard directory does not already exist, then
preserved as a `legacy-imported-<timestamp>.json.bak` backup.

ACE run artifacts also support a day-sharded physical layout under each project's
artifact root. Use `sase agent artifacts layout status` to inspect flat versus sharded
`ace-run` directories, `migrate` to move legacy flat timestamp directories into shards
while writing index aliases, `verify` to check the current or manifest-backed state, and
`rollback -m <manifest>` to reverse a migration when needed. Migration skips live
artifact directories with `running.json`, refuses existing targets, and can be previewed
with `--dry-run`.
