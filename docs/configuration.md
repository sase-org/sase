# Configuration Reference

This document is the central reference for all sase configuration: config files, YAML sections, environment variables,
and CLI flags.

## Table of Contents

- [Config File Location](#config-file-location)
- [Machine Identity](#machine-identity)
- [SASE Admin Center (interactive editor)](#sase-admin-center-interactive-editor)
  - [Config tab](#config-tab)
  - [Projects tab](#projects-tab)
  - [Updates tab](#updates-tab)
- [Deep-Merge System](#deep-merge-system)
- [Configuration Sections](#configuration-sections)
  - [amd_h1_title](#amd_h1_title)
  - [generated templates](#generated-templates)
  - [is_sase_managed](#is_sase_managed)
  - [machine_name](#machine_name)
  - [ace](#ace)
  - [llm_provider](#llm_provider)
  - [commit](#commit)
  - [repos](#repos)
  - [vcs_provider](#vcs_provider)
  - [vcs_repo_completion](#vcs_repo_completion)
  - [vcs_ref_completion](#vcs_ref_completion)
  - [axe](#axe)
  - [mentor_profiles](#mentor_profiles)
  - [metahooks](#metahooks)
  - [xprompts](#xprompts)
  - [xprompt_aliases](#xprompt_aliases)
  - [use_chezmoi](#use_chezmoi)
  - [commit_hooks](#commit_hooks)
  - [max_running_agents](#max_running_agents)
  - [timezone](#timezone)
  - [chat_install](#chat_install)
  - [telegram](#telegram)
  - [mobile_gateway](#mobile_gateway)
  - [sdd](#sdd)
  - [bead](#bead)
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

Overlay files matching the glob `~/.config/sase/sase_*.yml` are merged on top of the base file. In the SASE Admin Center
new-overlay prompt, enter a single local overlay name rather than a path: `extra`, `sase_extra`, and `sase_extra.yml`
all resolve to `~/.config/sase/sase_extra.yml`. SASE trims surrounding whitespace and rejects empty names, `.` / `..`,
or names containing `/` or `\`, so the create-overlay flow cannot escape the user config directory. A project-local
`sase/sase.yml` at the detected project root usually takes highest priority. A root-level `sase.yml` remains an
exclusive read fallback during the [layout compatibility window](content_layout.md#compatibility-and-collisions); if
both files exist, SASE reports a collision instead of merging them. The ACE TUI deliberately disables project-local
config loading for its own process so opening `sase ace` inside a repo does not inherit that repo's agent-run settings.
See [Deep-Merge System](#deep-merge-system) below.

## Machine Identity

SASE has one explicit, machine-local identity. Initialize it interactively with either equivalent command:

```bash
sase config init
sase init config
```

The initializer lists identities already declared by machine overlays, suggests the lowercase hostname with every
character outside `[a-z_]` replaced by `_`, and keeps prompting until the selected name matches `^[a-z_]+$`. If the
chosen top-level hood is already occupied in the durable agent-name registry, continuing requires an explicit `y` or
`yes` confirmation; the default is no. Prompting requires a TTY. Use `sase config init --check` or
`sase init config --check` for a read-only status check.

The selection itself is stored in the bounded local state file `~/.sase/machine_name` (or `$SASE_HOME/machine_name`). It
contains exactly one valid name and is deliberately not portable configuration. The corresponding overlay contains the
schema field:

```yaml
machine_name: athena
```

Any `sase_*.yml` overlay with a top-level `machine_name` is machine-specific. SASE loads it only when that value matches
the local selector; foreign machine overlays do not contribute runtime settings, Config inventory layers, or config-
defined xprompts. Overlays without `machine_name` remain ordinary overlays and always participate. Changing the selector
invalidates the merged-config cache just like changing a config file.

Selecting an existing identity writes only `~/.sase/machine_name`. Creating a new identity minimally adds `machine_name`
to `~/.config/sase/sase_<name>.yml`, preserving unrelated YAML where possible, then writes the selector. With
`use_chezmoi: true`, the overlay edit is made in the chezmoi source tree. Direct `sase config init` uses the normal
commit/push/apply deployment; bare `sase init` combines that source edit with its deferred chezmoi deployment.

There is intentionally no bundled `machine_name` default. Existing installations continue to load and run with the
optional machine identity unset until initialization, while features that require a machine hood report the actionable
`sase config init` instruction.

Machine hoods also provide stable ownership for the hidden agents sidecar. See
[Completed Agent Synchronization](agents_sidecar.md) for privacy controls, bundle contents, sync commands, and recovery.

## SASE Admin Center (interactive editor)

Press `#` in the `sase ace` TUI to open **SASE Admin Center**. The first press always starts on its lightweight home
page, where the seven working sections—**Config**, **Logs**, **Projects**, **Statistics**, **Tasks**, **Updates**, and
**XPrompts**—are introduced without loading their data. While home is visible, press `#` again to resume the last
section that was successfully active in this ACE process. Before the first section visit, the repeated key leaves home
unchanged and constructs no pane. Press `1`–`7` or click the numbered tab strip to enter a section. From home, `Tab`
enters Config and `Shift+Tab` enters XPrompts; within a working section they wrap across the same seven tabs. Pane-local
`[` / `]` keys switch sub-tabs or views where the active pane provides them.

Each pane is constructed only on first entry and is then reused until the Admin Center closes, preserving filters,
selection, and scroll state while avoiding unrelated config, project, log, statistics, task, update, and xprompt work on
open. Direct commands such as **Open logs panel**, **Open tasks panel**, **Open statistics**, and update actions still
open their requested pane immediately and make that successfully mounted section the next resume target. Closing and
reopening with one `#` still returns to home; only a second press while home is visible resumes. The target is
memory-only and is cleared by starting a new ACE process. Filters, selections, loaded data, and pane instances are never
carried between modal lifetimes.

### Config tab

The Config tab answers four questions for every field — what value is effective, why (its provenance), where an edit
will go, and whether it validates:

- **Browse / inspect** (read-only): a source rail lists each config layer with loaded/missing/invalid/read-only badges;
  the field tree is generated from the schema (`/` filters, `:` jumps to a dotted path, `m` shows only modified fields,
  `r` refreshes). In the tree, `j` / `k` move through visible rows and wrap at the ends, while Down / Up use clamped
  navigation; the detail pane shows the type, default, effective value, and the full provenance stack with the winning
  layer marked. Structured values (object maps and arrays of objects, such as `ace.lumberjack` or [`repos`](#repos))
  render as a multi-line, syntax-highlighted YAML block instead of a one-line JSON blob, while scalars and short flat
  lists keep their compact inline form.
- **Edit** (`↵` or `e` on a field): a typed editor is generated from the schema — a toggle for booleans, an option cycle
  for enums, validated inputs for numbers and strings, a line editor for string lists, and a raw-YAML escape hatch for
  complex shapes. Pick the write **scope** (`ctrl+t` cycles user base / overlays / a selected local file; `ctrl+n`
  creates a new overlay), or reset a field to its default (`ctrl+r`, which deletes the key from the chosen scope). A
  banner states the list-merge consequence (replace vs. append) for the chosen scope.
- **Preview / write** (`ctrl+s`): before anything is written you see the exact per-file text diff, the resulting
  effective merged value, and schema validation of the candidate config. The write is source-preserving (comments, key
  order, and quoting are kept) and is remapped to the chezmoi source tree when `use_chezmoi` is enabled.

For a chezmoi-remapped write, ACE first applies the changed target; an apply failure leaves the source edit in place and
keeps the editor open. After a successful write and any targeted apply, ACE checks the file that was actually changed.
If that file is dirty inside a git repository, it offers to **commit and push** the change as a tracked background task.
Confirming stages that config file, commits the repository's current index, pulls with rebase, and pushes; pre-existing
staged changes are therefore included in the same commit. The repository is discovered from the written file, so a
remapped edit uses the chezmoi source repository. When `use_chezmoi` is enabled, a successful push is followed by a full
`chezmoi apply`. Each failure stops the sequence at that step, without undoing the written config change. Skipping the
offer—or editing a file outside git—also leaves the successful write in place. The
[Models panel](ace.md#persistent-edits) uses the same workflow for persistent alias edits, while its fixed `Ctrl+E`
binding previews and writes `llm_provider.default_effort` specifically to the user-base layer. `Ctrl+E` is local to the
Models modal (including bucket rows), not a configurable leader-key entry. Choosing Provider default writes the empty
schema sentinel; a currently active temporary effort override remains effective until expiry or clear.

The deprecated `linked_repos` and `sibling_repos` keys remain readable as compatibility aliases for
[`repos.linked`](#repos), but the Config tab no longer offers a one-key migration action. Prefer editing the config to
use `repos.linked` directly.

SASE Admin Center never writes without showing the diff and validation first, and never edits a built-in or plugin
default (those layers are read-only).

### Projects tab

The Projects tab is an inventory and lifecycle surface with three clickable sub-tabs: **Projects · Repos · Workspaces**.
`[` / `]` cycle those sub-tabs, while `Tab` / `Shift+Tab` switch the Admin Center's main tabs.

- **Projects** lists true projects—projects backed by their own main ProjectSpec, excluding `home` and internal
  linked-repo backing records. Enabled and disabled rows appear together with VCS kind, claim, workspace, repo, and
  warning counts. `a` / `d` enable or disable, `r` / `w` cross-navigate to the selected project's inventories, and the
  established mark, alias, edit, force, and confirmed-delete actions remain available.
- **Repos** lists primary, sidecar, linked, and opened external repos for enabled projects by default. It reports
  checkout presence, source/config metadata, `auto_clone`, environment names, and SDD storage mode.
- **Workspaces** joins registry entries with active claims, PID liveness, pins, last-used timestamps, TTL staleness, and
  checkout presence. Missing checkouts point to `sase workspace repair`.

On Repos and Workspaces, `p` opens a shared project picker. Choosing a disabled project explicitly reveals its rows;
`Esc` clears the project scope, `/` text-filters within it, and `R` refreshes the off-thread cached inventory.

### Statistics tab

The Statistics tab aggregates durable agent run and activity records over a selectable time range. Its eight views are
**Overview**, **Runs**, **Runners**, **Projects**, **Providers**, **Runtime**, **Activity**, and **Plans & Questions**.
The Runners view uses today's effective global limit—including a temporary override—as present-day context, never as
historical configuration. The Projects view can group by project, by ChangeSpec, or as a project-to-ChangeSpec
drilldown. A pane-wide project filter lets you apply the same scope to the other views.

The pane loads only while visible, refreshes every 30 seconds, and performs its queries off the UI thread. Use `[` / `]`
to change views, `t`/`T` or `c` to choose a preset or custom range, `g` to change the Projects or Runtime grouping,
`p`/`P` to cycle the project filter forward or backward, and `r` to refresh immediately. Keyed scope chips keep the
effective range, grouping, and project visible; the **Group** chip appears only in Projects and Runtime and names the
selected dimension there. Project scopes use configured display names while retaining canonical keys internally. The
filter order is **All projects**, followed by projects ranked by run count in the most recently loaded unfiltered
result, and then wraps: `p` moves forward and `P` backward. Return to **All** after changing the range to rebuild that
list for the new range. If a selected project produces an empty result, either project-cycle key clears directly to
**All projects**. Every populated view includes a compact metric legend, `?` opens the complete glossary and current
scope, and empty/error states show the effective keys for widening, clearing, or retrying. The Overview plan and
question tiles remain all-project values even when a project is selected; see
[Telemetry: Admin Center Statistics tab](telemetry.md#admin-center-statistics-tab) for the view contents, range syntax,
and project-filter caveats.

### Updates tab

The Updates tab keeps SASE, its plugins, and its supported agent CLIs current without leaving the TUI. Use `]` / `[` to
cycle its three pane-local sub-tabs:

- **Core** (the default) shows the installed and latest versions of `sase` and `sase-core`, incoming commits, and the
  all-current banner.
- **Plugins** brings the full [`sase plugin`](plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show) experience
  into the TUI: filter the catalog, inspect a plugin, and install, update, uninstall, or switch install mode.
- **Agent CLIs** is a provider-colored master/detail browser for Claude Code, Codex CLI, OpenCode, Qwen Code, and
  Antigravity. Rows show installed → latest versions, install method, `↑` availability, and update marks. Details show
  the resolved executable, exact automatic or manual update command, skip reason, canonical vendor docs URL, and the
  last result.

The Plugins browser stays visually consistent with the CLI by reusing the same catalog loader and Rich renderables. Its
list is split into **Built-in** and **Community** (third-party, shown with a warning) sections; status glyphs match the
CLI exactly: `●` installed, `○` available, `↑` update available. Editable / dev installs (both core packages and
plugins) carry a lowercase `dev` marker and are compared against their git upstream instead of PyPI. Update actions
route editable packages through the [dev-update](plugins.md#dev-editable-installs) planner and managed packages through
the `uv` path. Blocked editable states appear as dim reasons such as `dev · local changes`, `dev · diverged`,
`dev · detached HEAD`, `dev · no upstream`, or `dev · offline`.

ACE computes one composite SASE/plugin/agent-CLI snapshot after first paint. The existing ten-minute session tick only
revalidates that cached snapshot and locally probes provider names already present in it. A full inventory/network
recompute is eligible on the longer `ace.updates.recompute_interval_minutes` cadence (one hour by default), while npm
latest-version lookups retain their separate six-hour cache. Source failures remain independent, so a provider lookup
failure does not erase known SASE/plugin results and vice versa.

The persistent top-bar badge uses separate joined segments: purple `↑ N` for routine SASE/plugin updates, amber `↑ N *`
when `sase-core-rs` requires a Rust rebuild, and cyan `CLI ↑ N` for supported agent CLIs. Mixed states join the SASE and
CLI segments, and the tooltip spells out both counts plus any manual-only CLI updates. Clicking the badge opens this tab
without mutating anything.

The global `,U` action captures the provider names from the latest completed automatic snapshot at keypress time,
revalidates those names against the live inventory, and previews one comprehensive update. Its foreground load cannot
add a newly discovered provider to that invocation. Safe commands run sequentially; Homebrew, non-writable npm, and
unknown-provenance installs remain visible with manual guidance. The pane-wide `u` remains SASE/core/plugins-only, and
pane-wide `A` remains the deliberate action for the current agent-CLI inventory.

Every mutation **previews first**, and long confirmation panes scroll with `Ctrl+D` / `Ctrl+U`. Plugin and core actions
show the exact `uv` command or editable-checkout plan. When commit previews are enabled and a comparable range is
available, confirmations for core and installed-plugin **updates** load incoming commits by repository in the
background; install, uninstall, and mode-switch confirmations do not claim a commit range. The global `,U` comprehensive
confirmation groups SASE and Agent CLI work into labeled sections with update/current/skipped glyphs, counts, and
commands (home paths display as `~/`). `A` previews every exact agent-CLI command and every skip with its reason and
docs URL; on the Agent CLIs sub-tab it uses the marked subset, otherwise it targets every safely updatable installed
CLI. Agent-CLI commands execute sequentially as one tracked task and refresh the browser without restarting ACE; new
agent launches naturally use the updated binaries. Installable plugins use `I` / `Space` marks, while updatable agent
CLIs use `Space`; `Esc` clears marks in the active sub-tab before closing. All slow work runs off the event loop.
Core/plugin code changes retain the existing automatic ACE/axe restart behavior. The context-sensitive keymaps are:

| Key                 | Action                                                                                                      |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| `]` / `[`           | Cycle Core / Plugins / Agent CLIs sub-tabs                                                                  |
| `j` / `k`           | Move the highlight down / up in Plugins or Agent CLIs                                                       |
| `I` / `Space`       | Mark / unmark an installable plugin; `Space` marks an updatable agent CLI on that sub-tab                   |
| `i`                 | Open the install preview for the marked set, or for the highlighted plugin when no install marks are active |
| `x`                 | Uninstall the highlighted plugin (only when installed)                                                      |
| `u`                 | Run `sase update` for SASE core plus all installed plugins                                                  |
| `A`                 | Update marked agent CLIs on that sub-tab, or every safely updatable installed agent CLI otherwise           |
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
| `#` (default)       | From home, resume the last section used in this ACE process; otherwise do not open a nested Admin Center    |
| `Tab` / `Shift+Tab` | From home enter Config / XPrompts; otherwise switch SASE Admin Center tabs (`1`–`7` jump directly)          |
| `Esc`               | Clear active plugin/agent-CLI marks first; close when no marks are active                                   |
| `q`                 | Close SASE Admin Center                                                                                     |

The Admin Center opener is the effective `ace.keymaps.app.open_config_center` binding (`number_sign` / `#` by default),
so a custom binding is repeated in the same way and appears in the landing-page hint. The remaining section-navigation
keymaps above are widget-local and are not configurable through `default_config.yml`.

## Deep-Merge System

Sase builds a merged configuration through five layers, each merged on top of the previous:

1. **`default_config.yml`** — bundled package defaults
2. **Plugin `default_config.yml` files** — from installed plugin packages (via `sase_config` entry points), sorted by
   entry-point name; lists concatenate
3. **`sase.yml`** — user config (`~/.config/sase/sase.yml`); lists **replace** defaults (not concatenate)
4. **Selected `sase_*.yml` overlays** — ordinary overlays plus only the machine overlay whose `machine_name` matches
   `~/.sase/machine_name`, sorted alphabetically; lists **concatenate**
5. **Local `sase.yml`** — project-level config in the current working directory; lists **concatenate** (highest
   priority)

This allows splitting shared configuration across ordinary files (e.g., `sase_work.yml`, `sase_personal.yml`) without
duplication and keeping machine-specific settings in selector-safe overlays. Plugins can provide sensible defaults that
users can override, and individual projects can customize behavior without changing global config.

Merge semantics:

| Type        | Behavior                                                                   |
| ----------- | -------------------------------------------------------------------------- |
| **Dicts**   | Merged recursively (overlay keys override base keys).                      |
| **Lists**   | Concatenated in layers 2, 4, and 5; **replaced** in layer 3 (user config). |
| **Scalars** | Override (overlay value replaces base value).                              |

For example, given a base file with two mentor profiles and an overlay or local project config that adds a third, the
merged result contains all three profiles. A user `~/.config/sase/sase.yml` list replaces earlier defaults instead. If
two files define the same scalar key (e.g., `axe.max_hook_runners`), the later layer wins.

Source: `src/sase/config/core.py`

## Configuration Sections

### amd_h1_title

Optionally customizes the Markdown H1 title of a generated managed `AGENTS.md`.

```yaml
amd_h1_title: "Structured Agentic Software Engineering (SASE) - Agent Instructions" # default: null
```

| Field          | Type           | Default | Description                                                                             |
| -------------- | -------------- | ------- | --------------------------------------------------------------------------------------- |
| `amd_h1_title` | string \| null | `null`  | H1 title used by the `sase memory init` `AGENTS.md` generator when enabled for a scope. |

For ordinary project roots, `is_sase_managed: true` in that root's own `sase/sase.yml` is the authorization switch. A
managed project with no title derives `<project> - Agent Instructions`; `amd_h1_title` alone does not opt a project in.

Home roots are the exception. For the live home root, user config from `~/.config/sase/sase.yml` and
`~/.config/sase/sase_*.yml` can provide the home `AGENTS.md` title. For the chezmoi home source root, source-side config
under `dot_config/sase/` is used instead. With `use_chezmoi: true`, `sase memory init` initializes the chezmoi home
source root rather than writing a live-home `AGENTS.md`.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`

### generated templates

SASE packages default Jinja templates for managed agent instructions and generated memory Markdown. Managed projects can
replace them with root-relative files named in their own `sase/sase.yml`:

```yaml
amd_agents_template: templates/AGENTS.template.md
amd_agents_minimal_template: templates/AGENTS.minimal.template.md
memory_sase_template: templates/memory-sase.template.md
memory_readme_template: templates/memory-README.template.md
```

| Field                         | Required Jinja variables                                                                  | Generated target or use               |
| ----------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------- |
| `amd_agents_template`         | `title`, `tier1_sections`, `tier2_entries`                                                | Managed root `AGENTS.md`              |
| `amd_agents_minimal_template` | `title`, `tier1_sections`                                                                 | Create-if-missing minimal `AGENTS.md` |
| `memory_sase_template`        | `project_name`, `linked_repo_entries`                                                     | Generated `sase/memory/sase.md`       |
| `memory_readme_template`      | `memory_notes`, `total_notes`, `short_notes`, `long_notes`, `total_lines`, `total_tokens` | Generated `sase/memory/README.md`     |

Every configured path must remain inside the project root. Rendering uses strict variables: required placeholders must
appear, unknown placeholders are rejected, and the rendered instruction/memory structure is validated before any file is
written.

Home initialization uses convention-based files instead of the project-local path keys. Put `AGENTS.template.md`,
`AGENTS.minimal.template.md`, `memory-sase.template.md`, or `memory-README.template.md` directly in `~/.config/sase/`;
with `use_chezmoi: true`, put them in the corresponding source-side `dot_config/sase/` directory. See
[Memory initialization](init.md#memory-initialization) for ownership, preview, and deployment behavior.

Source: `src/sase/amd/_template.py`, `src/sase/main/init_memory/root_rendering.py`

### is_sase_managed

Controls whether SASE owns repository resources such as project memory, the root `AGENTS.md`, and explicit SDD
initialization.

```yaml
is_sase_managed: false # default
```

| Field             | Type    | Default | Description                                                              |
| ----------------- | ------- | ------- | ------------------------------------------------------------------------ |
| `is_sase_managed` | boolean | `false` | Explicitly authorize SASE to manage resources in the current repository. |

Only the target repository's own checked-in `sase/sase.yml` is consulted for this authorization. A legacy root
`sase.yml` remains readable only when the canonical file is absent. Defaults, user config, and merged overlays cannot
opt repositories in globally. When false or absent, memory init does not create, refresh, or validate project memory and
does not create or alter the root `AGENTS.md`; it still propagates every existing project `AGENTS.md` to provider files
beside it. Explicit `sase repo init` and its `sase init repo` alias become successful no-ops before provider and storage
work. Invalid local YAML or a non-boolean marker fails safely.

This is a direct migration: `memory.enabled` is retired and does not authorize repository management. Existing managed
projects must replace it with top-level `is_sase_managed: true`.

Home and chezmoi-home memory initialization does not use this project-local switch, and provider instruction copies for
existing project `AGENTS.md` files remain independent of it.

Source: `src/sase/default_config.yml`, `src/sase/config/sase.schema.json`

### machine_name

Declares the identity owned by a machine-specific user overlay:

```yaml
machine_name: athena
```

| Field          | Type   | Default | Description                                                               |
| -------------- | ------ | ------- | ------------------------------------------------------------------------- |
| `machine_name` | string | none    | Required schema identity matching `^[a-z_]+$`; activated by the selector. |

The public schema requires this field, but the bundled defaults do not synthesize one. Runtime config therefore remains
compatible with a legacy/uninitialized installation: no machine overlay is selected and the optional accessor returns
unset. Run `sase config init` to select or create the overlay and write the local state selector. See
[Machine Identity](#machine-identity) for loading and deployment behavior.

Source: `src/sase/config/core.py`, `src/sase/config/sase.schema.json`, `src/sase/core/paths.py`

### ace

Configures the ACE TUI behavior. Defaults are provided by `src/sase/default_config.yml`.

```yaml
ace:
  artifacts:
    commits:
      default_query: "sidecar:false since:24h"
  tribes:
    default:
      icon: "⌂"
      color: "#87D7FF"
    chop:
      icon: "†"
      color: "#FFAF5F"
      initially_expanded: false
  updates:
    startup_toast: true # show SASE/plugin/agent-CLI updates on startup
    startup_toast_max_commits: 20 # total incoming subjects across repositories
    post_update_toast: true # confirm the version transition after self-update restart
    post_update_toast_diffstat: true # show applied file and line counts
    post_update_toast_commits: true # show applied commits grouped by repository
    post_update_toast_max_commits: 5 # applied subjects shown per repository
    indicator: true # show the segmented SASE + agent-CLI update badge
    incoming_commits:
      enabled: true # show incoming commit subjects in the Updates tab
      max_per_repo: 7 # cap subjects per repository
      confirm_max_per_repo: 250 # larger per-repository cap in confirmations
    check_interval_minutes: 10 # attempt a periodic check this often
    check_ttl_minutes: 10 # refresh latest-version checks at most this often
    recompute_interval_minutes: 60 # periodic full network recompute cadence
  keymaps:
    statistics:
      prev_view: "left_square_bracket" # active only while Statistics is focused
      next_view: "right_square_bracket"
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
      next_changespec: "j"
      prev_changespec: "k"
      edit_query: "slash" # defaults render as `/` outside Agents
      # ... all app-level keybindings are configurable
    modes:
      # Built-in modes (fold, copy, leader, bang) are configurable
      leader_mode:
        prefix: "comma"
        keys:
          repeat_last: "comma" # press the leader prefix, then this key; defaults render as `,,`
          edit_query: "slash" # Agents structured query; defaults render as `,/`
          show_help: "question_mark" # defaults render as `,?`
          models_panel: "m"
          update_sase: "U"
          full_history_refresh: "y"
      fold_mode:
        prefix: "z"
        keys:
          set_level_1: "1" # PR detail: set every section to level 1
          set_level_2: "2"
          set_level_3: "3"
          cycle_commits: "c"
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

| Field               | Type         | Default   | Description                                                                                                                                                |
| ------------------- | ------------ | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `artifacts`         | dict         | see below | Per-pane settings for ACE's Artifacts tab.                                                                                                                 |
| `keymaps`           | dict         | -         | Configurable keybindings (see below).                                                                                                                      |
| `prompt_completion` | dict         | see below | Live soft-completion settings for the ACE prompt input.                                                                                                    |
| `repro_output_dir`  | str          | `""`      | Base directory for [Agents-tab reproduction bundles](ace.md#agents-tab-reproduction-bundles). Empty means `<SASE_HOME>/repros` (default `~/.sase/repros`). |
| `snippets`          | dict[string] | `{}`      | Trigger-word → template mappings for prompt input snippet expansion.                                                                                       |
| `tribes`            | dict         | see below | Per-tribe Agents-tab panel icons, identity colors, and initial expansion.                                                                                  |
| `updates`           | dict         | see below | Startup update checks, the top-bar update badge, and the one-shot post-update restart confirmation toast.                                                  |

#### `ace.artifacts.commits`

| Field           | Type | Default                   | Description                                                                                                         |
| --------------- | ---- | ------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `default_query` | str  | `sidecar:false since:24h` | Initial persistent Commits query. Relative windows re-anchor on refresh; configuration changes apply on next start. |

The Commits pane validates this value with its live query parser. Invalid runtime configuration produces a warning and
falls back to the bundled query. An empty configured query is valid and includes sidecars; the visible canonical row
renders that state as `sidecar:true`. Commits queries are uncapped unless they contain an explicit positive `limit:N`,
so the bundled 24-hour query has no row cap. When an explicit cap clips the result, ACE keeps the token visible and
shows a lower-bound total such as `[1/40+]` in the repository legend while the filter row says `capped`. The legend's
`[P/N]` form means selected one-based position over displayed matched entries. `limit:all` is accepted as an unlimited
synonym but is omitted from canonical query text. Day-granular `until:` values include the full named day. This setting
is independent of the `sase vcs log` CLI's sidecar opt-in and limit contract.

#### `ace.tribes`

`ace.tribes` is keyed by bare tribe name (without `@`). The special `default` key configures the reserved `@default`
panel. Each entry accepts these optional fields:

| Field                | Type | Default | Description                                                                                     |
| -------------------- | ---- | ------- | ----------------------------------------------------------------------------------------------- |
| `icon`               | str  | `""`    | Short glyph rendered before the panel name. Set `""` to remove an icon inherited from defaults. |
| `color`              | str  | `""`    | `#RRGGBB` foreground for the icon and `@tribe` name. Set `""` to restore ACE's gold fallback.   |
| `initially_expanded` | bool | `true`  | Initial state the first time the panel appears.                                                 |

The bundled defaults use ⌂ in sky blue for `default`, ▲ in lavender-purple for `epic`, ∴ in teal-green for `research`,
and † in amber-orange for `chop`. They also use ◆ for `pinned` and ◉ for `review`, whose identities retain ACE's gold
fallback; `chop` starts collapsed. Because config entries merge deeply, setting `color: ""` explicitly clears an
inherited color without replacing that tribe's other defaults. Once a user explicitly expands or collapses a panel, that
durable choice takes precedence over `initially_expanded`, including after ACE restarts. Changing the config still
affects panels the user has not folded explicitly.

ACE reads this TUI setting from the user-level `~/.config/sase/sase.yml` (and user overlays), not project-local
`sase/sase.yml`.

#### `ace.updates`

| Field                                   | Type   | Default | Description                                                                                                                       |
| --------------------------------------- | ------ | ------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `startup_toast`                         | bool   | `true`  | Show the startup toast when cached status reports SASE, plugin, or supported agent-CLI updates.                                   |
| `startup_toast_max_commits`             | int    | `20`    | Maximum total incoming commit subjects shown across all repositories in the startup toast.                                        |
| `post_update_toast`                     | bool   | `true`  | Show a one-shot combined result after an update changes SASE code and restarts ACE.                                               |
| `post_update_toast_diffstat`            | bool   | `true`  | Show per-repository applied file and line-change statistics when available.                                                       |
| `post_update_toast_commits`             | bool   | `true`  | Show applied commits grouped by repository when available.                                                                        |
| `post_update_toast_max_commits`         | int    | `5`     | Maximum applied commit subjects shown per repository; `0` keeps totals but hides subjects.                                        |
| `indicator`                             | bool   | `true`  | Show the segmented SASE and agent-CLI badge when cached status reports available updates.                                         |
| `incoming_commits.enabled`              | bool   | `true`  | Fetch and show incoming commit subjects for SASE core and plugin repositories.                                                    |
| `incoming_commits.max_per_repo`         | int    | `7`     | Maximum incoming commit subjects to show per repository in Updates-tab details.                                                   |
| `incoming_commits.confirm_max_per_repo` | int    | `250`   | Maximum subjects fetched per repository in update confirmations; larger ranges show an explicit `+N more` marker.                 |
| `check_interval_minutes`                | number | `10`    | Interval between local cached-snapshot revalidation attempts in a running ACE session.                                            |
| `check_ttl_minutes`                     | number | `10`    | Minimum age before a startup update check recomputes cached status; this bundled default always wins over the legacy hours key.   |
| `check_ttl_hours`                       | number | unset   | Deprecated and schema-valid, but currently has no effect in a normal merged config because `check_ttl_minutes` is always present. |
| `recompute_interval_minutes`            | number | `60`    | Minimum snapshot age before a full SASE/plugin/agent-CLI network recompute; intervening checks only revalidate locally.           |

Set `check_ttl_minutes` to change the startup cache TTL. Although `check_ttl_hours` remains accepted for compatibility,
ACE resolves the merged `check_ttl_minutes` value first; the bundled 10-minute default therefore prevents an hours-only
override from taking effect.

#### `ace.keymaps`

All TUI keybindings are configurable. The `keymaps` section has four scopes:

**`gate`** — Bindings active in the shared branch controls used by plan and custom gate modals:

| Field              | Default  | Description                                      |
| ------------------ | -------- | ------------------------------------------------ |
| `next_control`     | `j`      | Focus the next branch control.                   |
| `previous_control` | `k`      | Focus the previous branch control.               |
| `toggle_option`    | `space`  | Toggle the focused option in an AND group.       |
| `submit_primary`   | `enter`  | Submit the gate's declared primary branch.       |
| `submit_branch`    | `ctrl+s` | Submit the currently active branch and feedback. |

Gate keys are scoped to the active modal and may overlap app-level bindings. `activate_control` remains accepted as a
deprecated alias for `submit_primary`.

**`statistics`** — Bindings active only while the Admin Center Statistics pane is focused. The available actions are:

| Field                          | Default                | Description                                                           |
| ------------------------------ | ---------------------- | --------------------------------------------------------------------- |
| `prev_view`                    | `left_square_bracket`  | Select the previous Statistics view.                                  |
| `next_view`                    | `right_square_bracket` | Select the next Statistics view.                                      |
| `cycle_range`                  | `t`                    | Cycle to the next statistics time range.                              |
| `cycle_range_reverse`          | `T`                    | Cycle to the previous statistics time range.                          |
| `custom_range`                 | `c`                    | Enter a custom statistics time range.                                 |
| `cycle_group`                  | `g`                    | Cycle grouping in the Projects or Runtime view.                       |
| `cycle_project_filter`         | `p`                    | Cycle forward through All and the latest unfiltered project ranking.  |
| `cycle_project_filter_reverse` | `P`                    | Cycle backward through All and the latest unfiltered project ranking. |
| `scroll_down`                  | `ctrl+d`               | Scroll the Statistics body down by half a page.                       |
| `scroll_up`                    | `ctrl+u`               | Scroll the Statistics body up by half a page.                         |
| `refresh`                      | `r`                    | Refresh from durable run and activity records.                        |
| `help`                         | `question_mark`        | Open contextual Statistics help; the same key closes it.              |

Statistics keys may overlap app-level bindings because they are registered on the focused pane, not globally.

**`app`** — App-level keybindings. Each key is an action name mapped to a key string. See `src/sase/default_config.yml`
for the full list of configurable actions and their defaults. Rebinding `open_config_center` also changes the Admin
Center's home-page resume key; it does not add a second keymap action or setting.

**`modes`** — Prefix-key mode definitions. Built-in modes (`fold_mode`, `copy_mode`, `leader_mode`, `bang_mode`) can be
reconfigured, and custom modes can be added. Each mode has:

| Field    | Type | Description                                                                                           |
| -------- | ---- | ----------------------------------------------------------------------------------------------------- |
| `prefix` | str  | The activation key for the mode.                                                                      |
| `keys`   | dict | Sub-key definitions. For custom modes, each entry needs a `key` field and either `shell` or `action`. |

The built-in `fold_mode` direct actions are `set_level_1` through `set_level_3` for PR details and the nested
`agents.set_level_1` through `agents.set_level_4` for Agents metadata. Their defaults produce `z1`-`z3` on PRs; Agents
accepts levels 1-2 for a family, 1-3 for a clan or regular-agent session scope, and 1-4 for a selected whole tribe
panel. The configured prefix and subkeys are used by dispatch, the command palette, footers, and help.

Query editing has two contextual scopes. `ace.keymaps.app.edit_query` controls PRs, Commits, Plans, and Axe and defaults
to bare `/`. `ace.keymaps.modes.leader_mode.keys.edit_query` independently controls the Agents structured-query chord
and defaults to `,/`; bare `/` on Agents starts inline metadata search. Help remains a leader action controlled by
`leader_mode.keys.show_help` and defaults to `,?`; the retired `ace.keymaps.app.show_help` override is ignored.

The app-level `edit_query` and Agents-only `search_forward` actions may intentionally share a key because their tab
scopes do not overlap. Other duplicate app bindings continue to be rejected by validation.

Custom mode key fields:

| Field    | Type | Required | Description                            |
| -------- | ---- | -------- | -------------------------------------- |
| `key`    | str  | yes      | The sub-key to press after the prefix. |
| `shell`  | str  | no\*     | Shell command to execute.              |
| `action` | str  | no\*     | Built-in action name to invoke.        |

\*Exactly one of `shell` or `action` must be provided.

The keymap loader validates configuration: invalid keys are reverted to defaults, duplicate bindings within a scope are
warned, and prefix conflicts between custom modes and app bindings are detected.

Source: `src/sase/default_config.yml`, `src/sase/ace/tui/keymaps/`

#### `ace.snippets`

Defines expandable text snippets for the prompt input widget. Each entry maps a trigger word to a template string. Press
`Tab` in the prompt input to expand the trigger word before the cursor.

```yaml
ace:
  snippets:
    fix: "Please fix the following issue:\n$0"
    review: "Review this code for correctness, performance, and style."
    plan: "#plan\n$0"
```

Templates can contain `$0` to mark where the cursor should be placed after expansion. If no `$0` is present, the cursor
moves to the end of the expanded text. Templates can also splice another merged snippet with `#[trigger]`; use
`#[trigger(value)]` or `#[trigger:value]` to fill referenced `$1`, `$2`, ... tabstops before splicing.

See [docs/ace.md — Snippets](ace.md#snippets) for usage details.

Source: `src/sase/ace/tui/widgets/prompt_text_area.py`

#### `ace.prompt_completion`

Controls automatic non-disruptive suggestions and manual prompt-local and prompt-history word completion in the ACE
prompt input. Suggestions appear in the prompt-bar subtitle and are accepted with `Ctrl+L`; `Enter` still submits the
prompt as typed. Manual structured/path `Ctrl+T` completion is independent of the automatic settings, and the `Ctrl+R`
recursive fuzzy file finder is always manual.

```yaml
ace:
  prompt_completion:
    auto: soft
    debounce_ms: 90
    auto_file_paths: false
    auto_xprompt_menu: true
    auto_directive_menu: true
    max_auto_rows: 1
    history_word_count: 1000
    word_min_length: 5
```

| Field                 | Type        | Default | Description                                                                                                       |
| --------------------- | ----------- | ------- | ----------------------------------------------------------------------------------------------------------------- |
| `auto`                | bool/string | `soft`  | Automatic mode. `soft`, `true`, `on`, `yes`, or `1` enable subtitle suggestions; false/off disables them.         |
| `debounce_ms`         | int         | `90`    | Delay before computing a live suggestion after text or cursor changes.                                            |
| `auto_file_paths`     | bool        | `false` | Allow live suggestions to scan file-path candidates. Manual `Ctrl+T` file completion still works when false.      |
| `auto_xprompt_menu`   | bool        | `true`  | Automatically open the xprompt/skill completion menu while typing matching `#name`, `#!name`, or `/skill` tokens. |
| `auto_directive_menu` | bool        | `true`  | Automatically open directive completion while typing `%id` tokens and fixed values such as `%model:`.             |
| `max_auto_rows`       | int         | `1`     | Reserved row limit for automatic completion modes; current soft mode shows one suggestion.                        |
| `history_word_count`  | int         | `1000`  | Maximum unique recent prompt-history words retained for manual completion; `0` disables the history fallback.     |
| `word_min_length`     | int         | `5`     | Shared minimum length for prompt-local and prompt-history word candidates; values below `1` clamp to `1`.         |

The minimum applies to the complete candidate, so a shorter typed prefix can still complete an eligible word.
Prompt-local words below the threshold are skipped before ACE considers the prompt-history fallback. Candidates from
history retain their original spelling and appear in most-recently-used order. The cache is warmed off-thread and
rebuilt when history shards or the shared minimum change. Setting `history_word_count: 0` disables only the history
fallback; eligible prompt-local words remain available.

The former `history_word_min_length` key has been replaced by `word_min_length`. Existing overrides must rename the key
to keep controlling word completion.

The `+query` project/ChangeSpec picker uses the same completion panel and opens when the plus is at absolute prompt
offset zero or immediately follows a literal ASCII space. It is not disabled by `auto_xprompt_menu`. Manual `Ctrl+T`
project/ChangeSpec completion uses the same token rule and works regardless of these automatic-completion settings.

The `%model:` / `%m:` value menu is also controlled by `auto_directive_menu`. It lists inline-typable model names,
implicit role aliases (`@default`, `@coder`, `@<provider>_coder`, `@epic_lander`, `@big_epic_lander`,
`@small_phase_worker`, `@medium_phase_worker`, `@large_phase_worker`, `@smartest`, `@cheaper`, `@cheapest`), and
configured model aliases; provider short aliases are shown as filter/display hints but are not inserted.

File-path completion roots relative lookups in the prompt-selected workspace. Registered workspace-provider refs and
known-project refs such as `#git:<project>` or `#gh:<owner>/<repo>` can root lookup in that project checkout. If no
prompt workspace ref resolves, lookups fall back to the TUI process directory. These root rules are shared by live path
suggestions, manual `Ctrl+T` path completion, and the manual `Ctrl+R` recursive finder.

Source: `src/sase/ace/tui/widgets/prompt_completion.py`, `src/sase/ace/tui/widgets/_prompt_soft_completion.py`,
`src/sase/ace/tui/widgets/history_word_completion.py`, `src/sase/history/prompt_words.py`,
`src/sase/ace/tui/widgets/prompt_completion_root.py`, `src/sase/ace/tui/widgets/recursive_file_finder.py`

### llm_provider

Configures which LLM backend sase uses and how model tiers map to concrete models. See [docs/llms.md](llms.md) for the
full LLM provider architecture, preprocessing pipeline, and invocation lifecycle.

```yaml
llm_provider:
  provider: claude # or "qwen", "opencode", "agy" (default: auto-detect)
  model_tier_map:
    large: opus
    small: sonnet
  model_aliases:
    builtin:
      default: opus # model used when a prompt has no %model directive
      claude_coder: codex/gpt-5.6-sol # coder follow-ups from Claude-authored plans
      codex_coder: claude/opus # coder follow-ups from Codex-authored plans
      big_epic_lander: codex/gpt-5.6-sol # specialize threshold-selected epic landers
      cheaper: claude/opus@medium | codex/gpt-5.5 # small-phase pool
      cheapest: claude/sonnet | codex/gpt-5.3-codex-spark # explicit-use pool
      medium_phase_worker: codex/gpt-5.6-sol # medium phase agents
      large_phase_worker: "@smartest"
      smartest: claude/claude-fable-5 || codex/gpt-5.6-sol # ordered fallback
    custom:
      blogger:
        model: claude/opus
        description: Agents that draft and edit blog posts.
    buckets:
      coders:
        description: Coder defaults and provider-specific follow-ups.
      phase_worker:
        description: Size-specific phase-agent roles.
```

| Field                                | Type   | Default     | Description                                                                                                                              |
| ------------------------------------ | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `llm_provider.provider`              | string | auto-detect | Which registered provider to use. Auto-detects by plugin-declared priority; built-ins default to claude → codex → qwen → opencode → agy. |
| `llm_provider.model_tier_map.large`  | string | -           | Model identifier for the `large` tier.                                                                                                   |
| `llm_provider.model_tier_map.small`  | string | -           | Model identifier for the `small` tier.                                                                                                   |
| `llm_provider.model_aliases.builtin` | dict   | -           | Builtin alias overrides. Values use the single-target grammar, `\|` round-robin pools, or `\|\|` ordered fallbacks.                      |
| `llm_provider.model_aliases.custom`  | dict   | -           | User-defined aliases usable from `%model:@<alias>` / `%m:@<alias>`. Each requires `model` (single target or selector) and `description`. |
| `llm_provider.model_aliases.buckets` | dict   | -           | Optional display-only ACE Models-panel bucket descriptions.                                                                              |

Model aliases are resolved when an agent launches, so reusable xprompts can point at names such as `%model:@default` or
`%model:@blogger` while each user's `sase.yml` controls the concrete provider/model. Alias config keys stay bare; the
`@` marker is only used in `%model`/`%m` directive values. Alias values may reference another alias with `@<alias>`
(chains are followed with cycle/depth protection). Unknown non-alias model values keep the existing fallback behavior
and run on the default provider. Use `model_aliases.builtin` for builtin role overrides and `model_aliases.custom` for
user-defined aliases with descriptions. `A | B` round-robins across real launches, skips providers whose CLI is
unavailable, and stores its machine-global cursor in `~/.sase/llm_lb.json`; display and preview surfaces only peek.
`A || B` always selects the first installed provider CLI and never reads or advances that cursor. Ordered fallback is
based on CLI installation, not later model/runtime success, and preserves its first candidate for normal diagnostics
when none are installed. Members may carry a trailing effort. The operators cannot be mixed, selectors cannot be nested,
and selectors are not accepted in `%model` directives or launch-scoped/temporary overrides. In the ACE Models panel, the
pool row reports the available/total count, selector member lists mark the current selection with `→`, and active
temporary overrides label selection suspended.

ACE automatically supplies two display-only built-in buckets while alias resolution and configuration remain flat:
`coders` groups `@coder` with every registered `@<provider>_coder`, and `phase_worker` groups `@small_phase_worker`,
`@medium_phase_worker`, and `@large_phase_worker`. `model_aliases.buckets.<bucket>.description` overrides either
built-in description. A custom alias tagged with either built-in bucket name joins that row while remaining
independently addressable and editable.

On top of any configured aliases, SASE exposes a fixed set of **implicit role aliases** that resolve even when unset:
`@default` (no-`%model` launches), `@coder` and the per-provider `@<provider>_coder` (plan coder follow-ups),
`@epic_lander`, `@big_epic_lander`, the three `<size>_phase_worker` aliases, `@smartest`, `@cheaper`, and `@cheapest`
(bead/epic role launches). `@epic_lander` falls back to `@default`, while `@big_epic_lander` falls back independently to
`@smartest`; small phases fall back to `@cheaper`, medium phases to `@default`, and large phases to `@smartest`. The
implicit `@smartest` value is `claude/claude-fable-5 || codex/gpt-5.6-sol`, preferring Claude when its CLI is installed.
`@cheaper` owns the automatic small-phase pool, while `@cheapest` owns an independent explicit-use pool. Override only
threshold-sized epic landers with `model_aliases.builtin.big_epic_lander`; override only large phases with
`model_aliases.builtin.large_phase_worker`. `@smartest` is selected automatically through the threshold-sized epic and
large-phase fallback chains. See [Implicit role aliases](llms.md#implicit-role-aliases) for the full table and
[Role Aliases for Delegated Work](llms.md#role-aliases-for-delegated-work) for how delegated launches pick a role.

Legacy `model_aliases.builtin.epic_creator` entries remain accepted so existing configs still load, but SASE no longer
launches an epic-creator agent or resolves that alias implicitly.

> The `llm_provider.worker_models` map and the reserved `@worker` / `@other` aliases were removed in epic sase-5d. Use
> `@coder`, a size-specific phase alias, or an explicit model instead of `@worker`, and `@default` instead of `@other`.
> `@phase_worker` is also no longer builtin; move a stale builtin override to `medium_phase_worker` or define a custom
> alias deliberately. `sase doctor` reports configs that still reference removed keys or aliases.

The TUI also supports **temporary**, per-alias session-level provider/model overrides (set from the
[Models panel](ace.md#models-panel), `,m`) that do **not** edit this config. They are persisted to
`~/.sase/llm_override.json` and expired entries are deleted on next read. See
[docs/llms.md](llms.md#temporary-model-overrides) for the resolution order, state-file format, and precedence relative
to `SASE_MODEL_TIER_OVERRIDE`.

The same panel's fixed `Ctrl+E` binding manages the separate machine-wide default-effort override at
`~/.sase/llm_effort_override.json`. It uses the alias override duration and exact-time cards, but its state and
precedence are independent: explicit prompt effort and alias/member effort win, then the temporary effort override, then
`llm_provider.default_effort`, then the provider default. See [Reasoning Effort](llms.md#reasoning-effort).

Its fixed `Ctrl+R` binding manages `max_running_agents`: persistent edits target the user-base `sase.yml` (or its
chezmoi source), while temporary values live independently in `~/.sase/max_running_agents_override.json`. This is a
Models-modal binding, not an `ace.keymaps` option.

#### `llm_provider.retry`

Per-provider retry and fallback configuration. See [docs/llms.md](llms.md#retry-and-fallback) for the full retry flow
and TUI display.

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

Configured retry policy is merged with provider-supplied retry defaults when a provider declares them. For list fields
such as `error_patterns`, built-in patterns are kept and configured patterns are appended with duplicates removed.
Claude's provider hook adds workspace-preserving matching for context-limit, socket-close, and Claude CLI API-error
output, plus a continuation nudge. Those hook defaults are merged with the bundled Claude policy in
`default_config.yml`, so the configured wait times and fallback model still apply unless you override them.

Source: `src/sase/llm_provider/retry_config.py`, `src/sase/llm_provider/config.py`

### commit

Configures commit enforcement around SASE-launched agents. The current commit finalizer is provider-neutral and runs in
the shared LLM invocation layer after a successful provider invocation in a SASE agent session, identified by
`SASE_AGENT_TIMESTAMP`.

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

When enabled, the finalizer checks the main workspace through the active VCS provider and configured `repos.linked` Git
worktrees at their resolved paths. Repositories opened through `/sase_repo`, including external repos, are recorded in
`opened_linked_workspaces.json` for ACE context and in the host project's durable repo-open log. Dirty enforced
workspaces trigger a follow-up invocation that instructs the same provider to use the appropriate commit skill. Dirty
opened repos are enforced like the main workspace. When the only enforced change is one tracked markdown file under
`sdd/plans/`, and that file's only diff is leading front matter changing exactly from `status: wip` to `status: done`,
the finalizer creates a direct `chore: Mark SDD plan done` commit instead of invoking the provider again. When
`$SASE_ARTIFACTS_DIR` is set, each pass writes prompt/response artifacts there, and the final outcome is recorded in
`commit_finalizer_result.json`.

Set `SASE_DISABLE_COMMIT_STOP_HOOK=1` for a one-off bypass. The environment variable name is historical; it now disables
the provider-neutral finalizer.

Source: `src/sase/llm_provider/commit_finalizer.py`, `src/sase/commit_instructions.py`

### repos

Declares linked and sidecar repositories related to a project. Git linked-repo worktrees are eligible for
commit-finalizer checks at their resolved `workspace_dir`. Agents use `/sase_repo` to prepare them; its audited
`sase repo open` command records manually opened linked workspaces in run artifacts for ACE context and appends a
durable audit event. SASE materializes a hidden sibling-state ProjectSpec for the linked repo when needed. Entries can
live in user config or a project-local `sase/sase.yml`; local entries are resolved relative to the project's primary
workspace directory.

Linked repositories are lazy by default. Set `auto_clone: true` for a repository that every launched agent needs; SASE
materializes and prepares those entries before execution. Lazy entries remain available through `sase repo open`, but
their per-repository `*_DIR` environment variables are not exported until the clone exists. Repositories with
`auto_clone: true` are omitted from generated agent instructions because agents do not need to open them manually.

Sidecar entries use their `name` as the role and primary CLI lookup key. Ordinary roles use `sase/repos/<name>` as their
workspace clone directory. Their repository defaults to `<project>--<name>` in the primary repository's GitHub
organization; `repo` can pin a bare slug or `owner/repo`. An explicit unpinned entry uses that project-local derivation
even when a legacy SDD store record names a different repository. Configured sidecars appear in `sase repo list` even
before cloning and can be opened by role name or repository slug. Enabled ordinary sidecars that are not auto-cloned
also appear by repository slug in generated agent instruction files, where their `description` tells agents when to open
them with `/sase_repo`. Set `disabled: true` in a later config layer to suppress a matching global entry or implicit
fallback; disabled and auto-cloned sidecars are omitted from generated instructions.

The `agents` role is intrinsically hidden from agent workflows. It never appears in generated memory, launch metadata,
linked-repository environment variables, or a workspace's `sase/repos/` tree, even if an override sets
`auto_clone: true`. It remains visible to users as a `sidecar` row in `sase repo list`, and `sase repo path agents` or
`sase repo open agents -r "<reason>"` explicitly accesses the one machine-level clone at
`~/.sase/projects/<project_key>/repos/agents`. The derived or pinned repository slug is also accepted by those commands.

The workspace provider owns sidecar transport. GitHub sidecars use canonical SSH origins on the primary repository's
GitHub host (`git@host:owner/repo.git`, or `ssh://git@host:port/owner/repo.git` when a port is configured). Read-only
store resolution converts a legacy GitHub HTTPS record to that exact SSH form in memory, so inventory, launch-time
auto-cloning, and on-demand materialization are safe immediately without rewriting the durable record. Matching retained
HTTPS clones keep their checkout and local state while SASE rewrites `origin` in place. Any HTTP(S) sidecar remote that
cannot be derived from consistent GitHub provider, host, and repository metadata fails materialization before Git runs.
Rerun `sase repo init` to persist the migrated record; it is not required to make a launch safe.

Managed projects (`is_sase_managed: true`) receive deterministic `<project>--plans` (`auto_clone: true`) and
`<project>--agents` (`auto_clone: false`, public visibility) entries when no matching explicit sidecar is configured.
Research is config-declared per project and defaults to `<owner>/<project>--research`; `sase repo init` writes the plans
and research entries. A project-local `agents` entry replaces the implicit entry: use `disabled: true` to opt out or
`visibility: private` to retain it with a private remote policy. Project-local `default_linked_repos: false` suppresses
both implicit managed-project entries. This foundation only declares, inventories, and explicitly materializes the
agents sidecar; automatic repo-init creation, consent, seeding, and agent-data synchronization are separate behavior.

The deprecated `linked_repos` and `sibling_repos` keys are still accepted as aliases during the compatibility window.
Canonical `repos.linked` entries take precedence over both aliases when the same name is defined.

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
    - name: plans
      auto_clone: true
    - name: research
      description: Durable SASE research reports and generated media.
      visibility: public
    - name: agents
      visibility: private
```

| Field                         | Type           | Default  | Description                                                                         |
| ----------------------------- | -------------- | -------- | ----------------------------------------------------------------------------------- |
| `github_orgs`                 | string or list | -        | GitHub user/org namespaces available to provider completion and PR workflows.       |
| `default_linked_repos`        | boolean        | `true`   | Inject managed-project `--plans` and hidden `--agents` sidecars.                    |
| `repos.linked[].auto_clone`   | boolean        | `false`  | Materialize and prepare the repository automatically before each agent launch.      |
| `repos.linked[].name`         | string         | required | Stable alias used in generated environment variable names and memory summaries.     |
| `repos.linked[].path`         | string         | required | Primary checkout path. Relative paths resolve from the project's primary workspace. |
| `repos.linked[].description`  | string         | required | Human-readable purpose used when generating agent memory for the linked repository. |
| `repos.sidecar[].name`        | string         | required | Role and CLI key; `agents` uses the stable machine-level clone path.                |
| `repos.sidecar[].repo`        | string         | derived  | Optional bare slug or `owner/repo` pin.                                             |
| `repos.sidecar[].description` | string         | -        | Purpose shown in inventory; required in generated instructions for lazy entries.    |
| `repos.sidecar[].auto_clone`  | boolean        | `false`  | Materialize before agent launch; intrinsically ignored for `agents`.                |
| `repos.sidecar[].visibility`  | public/private | `public` | Remote visibility; project-local `private` overrides the `agents` default.          |
| `repos.sidecar[].disabled`    | boolean        | `false`  | Disable the entry and suppress matching implicit sidecars, including `agents`.      |

Workspace numbers `0` and `1` use the linked repo's primary checkout. Higher workspace numbers use
`<host_workspace>/sase/repos/linked/<linked_repo>`, naturally namespaced by host project and workspace number. Agent and
workflow launch preparation atomically removes the numbered checkout's entire `<host_workspace>/sase/repos/` tree. The
required `plans` sidecar is then cloned directly from the canonical SSH or local remote resolved from its recorded
metadata; other linked repositories and sidecars remain lazy unless configured with `auto_clone: true`. Legacy GitHub
HTTPS metadata is normalized before the clone command is built, and unresolved HTTP(S) metadata stops launch setup
before Git executes. The hidden `agents` sidecar is excluded from this clone mapping and always resolves every
registered workspace number to `~/.sase/projects/<project_key>/repos/agents`. Agents materialize ordinary lazy entries
on demand through `/sase_repo`. `sase repo init` manages the tracked `/sase/repos/` ignore rule, while SASE also
installs the rule in `.git/info/exclude` before materialization. SASE passes resolved metadata for all entries and
exports per-repository paths only for materialized entries:

| Variable                                  | Description                                      |
| ----------------------------------------- | ------------------------------------------------ |
| `SASE_LINKED_REPOS_JSON`                  | JSON metadata for all resolved linked repos.     |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR`         | Workspace-matched directory for a linked repo.   |
| `SASE_LINKED_REPO_<ENV_NAME>_PRIMARY_DIR` | Primary checkout directory for that linked repo. |

The legacy `SASE_SIBLING_REPOS_JSON` and `SASE_SIBLING_REPO_<ENV_NAME>_*` variables are still emitted alongside the
canonical ones during the compatibility window.

`<ENV_NAME>` is the uppercased, sanitized repo `name`; duplicates are uniquified with a numeric suffix.

Source: `src/sase/linked_repos.py`, `src/sase/agent/launch_spawn.py`

#### External repositories

External repositories are per-task repos that are not part of the host project's configured inventory. They require no
configuration entry. `sase repo open` resolves them after inventory names in two forms:

- Another registered SASE project name opens that project's primary repo from its local checkout, without network
  access, under `sase/repos/external/projects/<project>`.
- `gh:owner/repo`, or the `owner/repo` shorthand, clones through the installed GitHub workspace provider under
  `sase/repos/external/gh/<owner>/<repo>`.

Successful external opens are idempotent, audited, and included in `sase repo list`, commit-finalizer enforcement, ACE
file and commit deltas, and revert. Agents must use `/sase_repo` before reading or modifying any external repo and must
use the path printed by the skill rather than locating or cloning the repo themselves. External repos are
workspace-local and do not create project registry records.

### vcs_provider

Configures the version control system backend. See [docs/vcs.md](vcs.md) for the full VCS provider reference including
per-command behavior, Git/Mercurial details, and troubleshooting.

GitHub Enterprise host configuration (`github_hosts`) is owned by the `sase-github` plugin; see its
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
| `vcs_provider.default_hooks`         | list[string]      | -        | Hook commands added to new ChangeSpecs. Replaces built-in defaults.                                           |
| `vcs_provider.pr_tags`               | dict[string, str] | `{}`     | Key-value tags appended as `SASE_TAG=VALUE` lines to PR commit messages (keys are rendered `SASE_`-prefixed). |
| `vcs_provider.use_project_pr_prefix` | bool              | `false`  | Prepend `[<project>] ` to PR titles / PR descriptions (see below).                                            |

When `default_hooks` is not set, plugins may provide their own defaults via `default_config.yml` (for example,
Mercurial-specific hooks from a provider plugin). The core `sase` package has no built-in default hooks.

When `use_project_pr_prefix` is `true`, a `[<project>] ` prefix is prepended to PR titles (GitHub) or PR descriptions
(Mercurial) without polluting the ChangeSpec DESCRIPTION or git commit message. The prefix is automatically stripped
when reading descriptions back.

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

When disabled, ACE does not detect repository-completion triggers, and the editor helper bridge returns an empty
catalog. Repository candidates are listed through workspace-provider hooks, so provider-specific authentication and
network requirements belong to the installed plugin. For GitHub, the `sase-github` plugin uses the `gh` CLI and can
return private repositories visible to the authenticated user.

Source: `src/sase/default_config.yml`, `src/sase/xprompt/vcs_repo_completion.py`

### vcs_ref_completion

Configures project, ChangeSpec, and namespace completion at the root of VCS workflow refs such as `#gh:` and `#git:`.

```yaml
vcs_ref_completion:
  enabled: true
```

| Field                        | Type | Default | Description                                                             |
| ---------------------------- | ---- | ------- | ----------------------------------------------------------------------- |
| `vcs_ref_completion.enabled` | bool | `true`  | Enable ACE and xprompt LSP completion at the root of VCS workflow refs. |

When disabled, ACE does not detect VCS ref-root completion triggers and the materialized xprompt LSP VCS catalog omits
namespace rows. Project and ChangeSpec candidates come from local ProjectSpecs; provider namespace rows come from fast
local workspace-provider hooks.

Source: `src/sase/default_config.yml`, `src/sase/xprompt/vcs_ref_completion.py`

### axe

Configures the `sase axe` lumberjack-based daemon. The axe architecture uses an orchestrator that spawns multiple
lumberjacks, each running a set of chops on a fixed interval. Defaults are provided by `src/sase/default_config.yml`.

```yaml
axe:
  max_hook_runners: 3 # concurrent hook runners (default: 3)
  max_agent_runners: 3 # concurrent agent runners (default: 3)
  zombie_timeout_seconds: 7200 # seconds (default: 7200 = 2 hours)
  query: "" # query filter for ChangeSpecs (default: all)
  chop_script_dirs: [] # additional directories to search for chop scripts
  lumberjacks:
    hooks:
      interval: 5
      chop_timeout: "90s"
      chops:
        - name: hook_checks
          script: sase_chop_hook_checks
          description: Complete finished hooks and start stale ones, with zombie detection
        - name: mentor_checks
          script: sase_chop_mentor_checks
          description: Start mentor workflows once all hook prerequisites are met
        - name: workflow_checks
          script: sase_chop_workflow_checks
          description: Complete finished CRS/fix-hook workflows and start stale ones
        - name: pending_checks_poll
          script: sase_chop_pending_checks_poll
          description: Poll background is_cl_submitted and critique_comments checks for results
        - name: comment_zombie_checks
          script: sase_chop_comment_zombie_checks
          description: Mark comment threads older than zombie_timeout as ZOMBIE
        - name: suffix_transforms
          script: sase_chop_suffix_transforms
          description: Strip stale suffixes from older proposals and update mail-readiness markers
        - name: orphan_cleanup
          script: sase_chop_orphan_cleanup
          description: Release workspace claims orphaned by reverted PRs with dead PIDs
        - name: stale_running_cleanup
          script: sase_chop_stale_running_cleanup
          description: Release workspace claims held by dead processes
    waits:
      interval: 10
      chops:
        - name: wait_checks
          script: sase_chop_wait_checks
          description: Resolve successful agent wait dependencies and write ready.json
    checks:
      interval: 300
      chops:
        - name: pr_submitted_checks
          script: sase_chop_pr_submitted_checks
          description: Check if PRs have been submitted
        - name: stale_running_cleanup
          script: sase_chop_stale_running_cleanup
          description: Backstop cleanup of stale RUNNING entries
    comments:
      interval: 60
      chops:
        - name: comment_checks
          script: sase_chop_comment_checks
          description: Check for new comments on PRs
    housekeeping:
      interval: 3600
      chops:
        - name: error_digest
          script: sase_chop_error_digest
          description: Summarize recent errors into a notification
```

**Top-level fields:**

| Field                                    | Type         | Default    | Description                                                                   |
| ---------------------------------------- | ------------ | ---------- | ----------------------------------------------------------------------------- |
| `max_hook_runners`                       | int          | `3`        | Maximum concurrent hook runners (non-`$` hooks) across all ChangeSpecs.       |
| `max_agent_runners`                      | int          | `3`        | Maximum concurrent agent runners (agents and mentors) across all ChangeSpecs. |
| `zombie_timeout_seconds`                 | int          | `7200`     | Seconds after which a running hook or workflow is flagged as a zombie.        |
| `query`                                  | string       | `""`       | Query string for filtering ChangeSpecs (empty = all).                         |
| `chop_script_dirs`                       | list[string] | `[]`       | Additional directories to search for external chop scripts.                   |
| `lumberjack_log_max_bytes`               | int          | `52428800` | Maximum bytes retained for each bounded lumberjack log.                       |
| `lumberjack_log_temp_max_age_seconds`    | int          | `300`      | Minimum age before orphaned log-rotation temp files are removed.              |
| `lumberjack_restart_backoff_max_seconds` | int          | `60`       | Maximum delay between retries for a crashing lumberjack.                      |
| `verbose_lumberjack_diagnostics`         | bool         | `false`    | Include verbose diagnostics in chop script context JSON.                      |
| `lumberjacks`                            | dict         | -          | Mapping of lumberjack name → config (see below).                              |

**Lumberjack fields** (per entry under `lumberjacks`):

| Field          | Type                        | Default | Description                                                             |
| -------------- | --------------------------- | ------- | ----------------------------------------------------------------------- |
| `interval`     | int                         | `1`     | Seconds between chop polling cycles.                                    |
| `chop_timeout` | string                      | -       | Positive compound duration limit, such as `"90s"`, `"1h30m"`, or `"1d"` |
| `env`          | dict[string, env-value]     | `{}`    | Environment inherited by every chop in this lumberjack.                 |
| `chops`        | list[string\|object] or map | `[]`    | Legacy list or composable map of chops (see below).                     |

**Chop fields** (per entry under `chops`):

| Field         | Type                    | Required  | Default  | Description                                                        |
| ------------- | ----------------------- | --------- | -------- | ------------------------------------------------------------------ |
| `name`        | string                  | list only | -        | Stable identity; map form uses the entry key.                      |
| `script`      | string                  | no        | `name`   | Exact executable name; no prefix is added automatically.           |
| `enabled`     | boolean                 | no        | `true`   | Soft-disable a keyed entry while retaining inherited fields.       |
| `description` | string                  | no        | `""`     | Human-readable description of what the chop does.                  |
| `run_every`   | string                  | no        | -        | Positive compound cadence such as `"60m"`, `"1h30m"`, or `"1d"`.   |
| `timeout`     | string                  | no        | -        | Per-chop duration limit. Overrides lumberjack `chop_timeout`.      |
| `env`         | dict[string, env-value] | no        | `{}`     | Literal values or `{env:}`, `{file:}`, `{pass:}` references.       |
| `inhibit_if`  | list or map             | no        | -        | `changespec` / `agent_hood` / `agent_clan` guards before dispatch. |
| `trigger`     | string or map           | no        | `always` | `always` or `git.commits_since` scheduled-run trigger.             |
| `once_per`    | string or object        | no        | -        | Bounded per-proposal dedupe-key template.                          |
| `for_each`    | list or source          | no        | -        | Literal targets or the filtered `projects` source.                 |
| `vars`        | object                  | no        | `{}`     | Non-secret values copied to the chop context.                      |

All chops are scripts. Exact-name resolution checks `chop_script_dirs`, then the running interpreter's bin directory,
then `$PATH`. Invalid fields, duplicate identities, non-positive intervals, and invalid durations fail config loading
with a dotted config path and source-layer diagnostic. `agent:` and `xprompt:` are rejected with a migration message.

Environment values resolve at dispatch time. Use a literal for non-secret data or `{env: NAME}`, `{file: path}`, and
`{pass: entry}` references for secrets. Lumberjack-level `env` is inherited by every chop, then a chop's own `env`
overrides matching names.

The built-in `wait_checks` chop writes `ready.json` only after named `%wait` dependencies complete successfully. Failed,
killed, crashed, still-running, malformed, or missing `done.json` artifacts do not satisfy the dependency.

Map form is the composable form. Higher-priority config layers patch matching fields by key, and per-field source
provenance is shown by the verbose chop inventory:

```yaml
axe:
  lumberjacks:
    docs:
      interval: 60
      env:
        API_TOKEN: { env: DOCS_API_TOKEN }
      chops:
        refresh_docs:
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
          enabled: false
```

`for_each` produces stable identities such as `refresh_docs[sase-core]`. Each instance has independent scheduling,
history, checkpoints, and once-per state. Target data is available in the context JSON under `target` and through
`SASE_CHOP_TARGET_KEY` / `SASE_CHOP_TARGET_<FIELD>`. Literal target rows may include `overrides:` for per-target chop
fields such as `run_every` and trigger thresholds.

`inhibit_if` accepts keyed `changespec`, `agent_hood`, and `agent_clan` providers. The clan provider requires a
case-sensitive `name_prefix` and checks canonical clan metadata for active agents, including waiting members; it never
infers clans from dotted names. `trigger` accepts `always` or `git.commits_since`; the git provider requires `project`
and `threshold`, and its checkpoint policy is `on_observation`, `on_action_accepted`, or `on_action_success`. Skips are
recorded with reasons. Manual runs bypass the trigger but honor guards unless `sase axe chop run -f/--force` is used.
`once_per` can be a key template string or an object with `key` and bounded `capacity`; proposal-supplied `dedupe_key`
values take precedence. When dedupe removes a proposal from a `wait_on` chain, AXE walks through the skipped
dependencies to the nearest earlier proposal that survives filtering. If none survives, AXE removes the wait. Proposal
previews expose the resulting `wait_on` value and explain a relink in `dedupe_reason`.

The builtin `sase_chop_refresh_docs` emits an update proposal plus a polish proposal that waits for the update. It uses
the target source's `workspace`, while cadence and commit thresholds stay declarative in configuration. Its default
prompts are strictly documentation-scoped and tell agents to report suspected code bugs instead of fixing them. The
defaults can be replaced with non-blank `vars.prompt` and `vars.polish_prompt` strings; operators are responsible for
the scoping language in replacement prompts. See
[Axe structured results and launch proposals](axe.md#structured-results-and-launch-proposals) for the result document,
proposal fields, lifecycle statuses, and debugging commands.

Each chop entry can also be a plain string (chop name only, legacy format):

```yaml
chops:
  # Object format (required for new chops)
  - name: hook_checks
    script: sase_chop_hook_checks
    description: Check for completed or failed hooks
  - name: custom_chop
    script: my_full_executable_name
    description: Run custom analysis
    run_every: "1h30m"
    env:
      MY_API_KEY: { env: MY_API_KEY }
  # String format (legacy, description defaults to empty)
  - hook_checks
```

CLI flags on `sase axe start` override `max_hook_runners`, `max_agent_runners`, `zombie_timeout_seconds`, and `query`
for a single run (see [CLI Flags](#cli-flags)).

Source: `src/sase/axe/config.py`, `src/sase/default_config.yml`

### mentor_profiles

Defines mentor agents that run automated code reviews when a ChangeSpec's diff, changed files, or amend notes match
configurable criteria. Each profile groups one or more mentors with shared matching rules. See
[docs/mentors.md](mentors.md) for the full mentor system reference.

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

| Field                | Type         | Required | Description                                                                       |
| -------------------- | ------------ | -------- | --------------------------------------------------------------------------------- |
| `profile_name`       | string       | yes      | Unique name identifying this profile.                                             |
| `mentors`            | list         | yes      | List of mentor definitions (see below).                                           |
| `file_globs`         | list[string] | no\*     | Glob patterns matched against changed file paths.                                 |
| `diff_regexes`       | list[string] | no\*     | Regex patterns matched against the diff content.                                  |
| `amend_note_regexes` | list[string] | no\*     | Regex patterns matched against commit/amend notes.                                |
| `first_commit`       | bool         | no       | If true, match only on the first commit of a ChangeSpec.                          |
| `projects`           | list[string] | no       | Only match ChangeSpecs in these projects. Auto-set for local `sase.yml` profiles. |

\*At least one of `file_globs`, `diff_regexes`, `amend_note_regexes`, or `first_commit` must be provided per profile.

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

Mentors run automatically on ChangeSpecs with Ready or Mailed status when their matching criteria are met. Mentor
comments are structured JSON with severity levels (error, warning, suggestion) that can be reviewed and applied through
the ACE TUI's Mentor Review modal (`,C`).

Source: `src/sase/config/mentor.py`

### metahooks

Metahooks intercept failing hooks before the summarize agent runs. They match based on the hook command (substring
match) and the hook output (regex match). When a metahook matches, it can trigger specialized handling instead of the
default summarization.

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

Defines reusable prompt snippets that can be referenced with `#name` syntax in any prompt. Supports both simple string
content and structured definitions with typed inputs and Jinja2 templates.

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

Earlier sources win on name conflicts. Project and home canonical directories are the only writable filesystem
destinations; legacy directories remain read-compatible but are not offered for new saves. File-based xprompts use YAML
front matter for metadata and the file body for content. The [XPrompt discovery table](xprompt.md#discovery-order) lists
every source separately.

Source: `src/sase/xprompt/loader.py`

### xprompt_aliases

Defines raw text-level alias substitutions that are applied _before_ any xprompt processing. This is useful for creating
shorthand references where the alias must be present in the raw text for other processing logic (such as VCS
directory-switching) to work correctly.

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

The built-in defaults provide `#c` as a shorthand for `#commit` and `#p` for `#propose`. Additional aliases can be added
in user config files.

Each entry maps an alias name to a target string. When the processor encounters `#alias_name` in a prompt, it replaces
it with `#target` before any other xprompt resolution occurs. Only `#`-prefixed references are substituted; the alias
name must match `[a-zA-Z_][a-zA-Z0-9_]*`.

Source: `src/sase/xprompt/processor.py`

### use_chezmoi

Enables chezmoi-aware home-file writes. When set to `true`, SASE writes generated home instructions, memory, skills, and
home-directory xprompt paths through the chezmoi source tree under `~/.local/share/chezmoi/home/` instead of writing the
live home files directly. Canonical `~/sase/xprompts/` and `~/sase/memory/` map to source paths `home/sase/xprompts/`
and `home/sase/memory/`. The unchanged global config still maps to `home/dot_config/sase/sase.yml`.

This affects initialization workflow as well as xprompt editing. `sase memory init` targets the chezmoi home source root
when it needs to initialize home-level `AGENTS.md`, writes home memory there, and may run the configured chezmoi deploy
path; `sase skill init` writes provider skill files there before optional commit, push, and apply steps.

Home-level provider instruction files (`CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md`) in the chezmoi source are
written as static `.md` files that are byte-for-byte copies of the root's generated `AGENTS.md`. Because the inlined
`AGENTS.md` carries no template variables, the chezmoi source uses a static preferred file rather than a `*.md.tmpl`
import; legacy `*.md.tmpl` shims that imported `@{{ .chezmoi.homeDir }}/AGENTS.md` are still recognized and migrated to
full copies.

```yaml
use_chezmoi: true # default: false
```

| Field         | Type | Default | Description                                                         |
| ------------- | ---- | ------- | ------------------------------------------------------------------- |
| `use_chezmoi` | bool | `false` | Write home-managed SASE files through the chezmoi source directory. |

Source: `src/sase/config/core.py`

### commit_hooks

Shell commands that bracket commit-producing VCS dispatches. `before` runs in the repository root after bead and plan
mutations but before diff capture and dispatch. `after` runs in the repository root only after `create_commit` or
`create_pull_request` succeeds, including its push where applicable. Proposals run `before` but never run `after`
because they save a diff without creating a commit.

Both fields default to an empty string. Because the object is deep-merged, a global `before` hook and project-local
`after` hook compose without either configuration repeating the other phase.

```yaml
commit_hooks:
  before: "just fix" # default: ""
  after: "chezmoi update -a --force" # default: ""
```

| Field                 | Type   | Default | Description                                                                |
| --------------------- | ------ | ------- | -------------------------------------------------------------------------- |
| `commit_hooks.before` | string | `""`    | Command before diff capture and VCS dispatch. Empty means disabled.        |
| `commit_hooks.after`  | string | `""`    | Command after a commit/PR dispatch and push succeed. Empty means disabled. |

Hook output is captured and a bounded stdout/stderr tail is printed on failure. A failing `before` hook aborts before
dispatch. A failing `after` hook leaves the commit checkpoint in place and returns failure even though the commit may
already be pushed; fix the command and run `sase commit --resume`. The completed after-hook step is checkpointed so a
normal resume does not rerun it. A crash after the external command succeeds but before that checkpoint write can run it
again, so `after` commands must be safe to repeat.

Source: `src/sase/default_config.yml`, `src/sase/workflows/commit/commit_hooks.py`,
`src/sase/workflows/commit/workflow.py`

### max_running_agents

The configured global cap on concurrently running slot participants across all projects. Participants are top-level user
agents—including independently launched clan members—and eligible parallel family members. Serial family follow-ups,
workflow Python/bash steps, and axe ChangeSpec runners are excluded; axe runners continue to use their separate
`axe.max_*_runners` limits. An unanswered participant at `QUESTION` temporarily yields its slot. After the user answers,
it must reacquire against the current effective cap before follow-up work resumes and may therefore appear as a
runner-slot `WAITING` row.

```yaml
max_running_agents: 10
```

| Field                | Type | Default | Minimum | Description                                                   |
| -------------------- | ---- | ------- | ------- | ------------------------------------------------------------- |
| `max_running_agents` | int  | `10`    | `1`     | Configured maximum concurrent slot participants on this host. |

The effective cap is an active machine-wide temporary override first and this merged configured value second. In the
Models panel, fixed `Ctrl+R` opens **Max Running Agents**: `e` previews and writes the user-base/chezmoi source, `o`
chooses a relative, custom, until-cleared, or exact-time override, and `x` clears it. Temporary state is stored as a
versioned record at `~/.sase/max_running_agents_override.json`; a new set replaces the previous value, expiry is
enforced at its deadline, and a persistent edit leaves an active override in force. Lowering the effective value is
non-preemptive, so existing agents continue and new implicit-cap launches wait for occupancy to drain. Parked implicit
waiters and question continuations reread the effective cap on each normal poll. An explicit `%wait(runners=N)` keeps
its own initial-admission threshold and may be either stricter or looser than the global cap.

### timezone

The timezone that governs all SASE wall-clock display and timestamp generation (notifications, agent logs,
artifact/agent-name timestamps, runtime durations, and TUI displays). When unset, SASE uses the host **system
timezone**, so machines that don't share our timezone assumptions get sensible behavior out of the box.

```yaml
timezone: "America/New_York" # default: system timezone
```

| Field      | Type   | Default           | Description                                                                        |
| ---------- | ------ | ----------------- | ---------------------------------------------------------------------------------- |
| `timezone` | string | _system timezone_ | IANA timezone name governing all SASE wall-clock display and timestamp generation. |

### chat_install

Configuration for chat-driven update workflows. External chat integrations can call
`sase.integrations.chat_install.start_chat_install_worker()` to run the built-in `sase update --json` engine in a
detached worker. The worker uses the same managed-vs-dev routing as the TUI Updates tab and the `sase update` CLI, so no
custom update command is required.

```yaml
chat_install:
  timeout_seconds: 900
  restart_attempts: 3
```

| Field                           | Type | Default | Description                                                                |
| ------------------------------- | ---- | ------- | -------------------------------------------------------------------------- |
| `chat_install.timeout_seconds`  | int  | `900`   | Maximum runtime for `sase update --json` before returning exit code `124`. |
| `chat_install.restart_attempts` | int  | `3`     | Number of axe start attempts when axe is not running after the update.     |

Only one chat update worker may run at a time; a lock under `~/.sase/chat_install/install.lock` rejects concurrent
starts. Worker output is written to timestamped logs under `~/.sase/chat_install/logs/`. The configuration key and state
paths remain named `chat_install` for compatibility. The old `chat_install.command` and `chat_install.sync_workspace`
keys have been removed; delete them from user config if schema validation reports them. See
[`docs/integrations.md`](integrations.md#chat-update-worker) for the integration-facing Python API.

Source: `src/sase/default_config.yml`, `src/sase/integrations/chat_install.py`

### telegram

Custom Telegram slash commands are keyed by the bot command name. Define them in user configuration or an overlay; the
Telegram integration deliberately ignores project-local configuration so a repository cannot add commands to your bot.
Core SASE validates the definitions, and `sase doctor` checks that each command's executable resolves.

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

Command names must contain 1–32 lowercase letters, digits, or underscores. The built-in names `bead`, `beads`,
`changes`, `fork`, `kill`, `list`, `update`, and `xprompts` are reserved. The integration parses `run` as an argument
vector and never invokes a shell. Text following `/name` is appended as one final argument, and the process runs from an
isolated temporary directory, so use absolute paths or commands available on `PATH` rather than relying on a project
working directory.

Run `sase doctor -C integrations.telegram_commands` after editing the map; unresolved command heads produce a warning
with the affected names.

Source: `src/sase/default_config.yml`, `src/sase/doctor/checks_integrations.py`

### mobile_gateway

Configuration for `sase mobile gateway start`, which launches the workstation-hosted Rust gateway for paired mobile
clients.

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

Push payloads are hint-only and must not contain bearer tokens, pairing codes, prompt bodies, response text, attachment
contents, attachment tokens, or host paths. Only credential paths or environment-variable names are placed on the
gateway command line. See [`docs/mobile_gateway.md`](mobile_gateway.md#push-hints) for setup examples and security
notes.

Source: `src/sase/default_config.yml`, `src/sase/integrations/mobile_gateway.py`

### sdd

Configuration for spec-driven development features, including prompt, tale, epic, research, and bead storage.

```yaml
sdd:
  bead_refresh:
    mode: background
    ttl_seconds: 120
  repo:
    name: "" # provider-specific sidecar repo override
  push_after_commit: async
```

| Field                          | Type        | Default      | Description                                                                                                                                                                                                                           |
| ------------------------------ | ----------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sdd.bead_refresh.mode`        | string      | `background` | Sidecar bead-store freshness: `background` launches a TTL-gated managed sync after commands, `blocking` pulls before commands, and `off` disables command-triggered refresh.                                                          |
| `sdd.bead_refresh.ttl_seconds` | float       | `120`        | Minimum age of the last successful remote integration before another background worker is launched.                                                                                                                                   |
| `sdd.repo.name`                | string      | `""`         | Optional sidecar repo override for providers that support `separate_repo`; accepts `name` or `owner/name`. For GitHub, empty checks only `<owner>/<repo>--sdd`; set `sdd.repo.name` to use another repo such as `sdd` or `owner/sdd`. |
| `sdd.push_after_commit`        | bool or str | `async`      | Controls `git push` after SDD commits in sidecar repositories: `async`, `true`, or `false`. Local commits are preserved.                                                                                                              |

The workspace provider owns storage selection. Built-in bare-git projects store SDD under `sdd/`. Managed GitHub
projects use a `--plans` sidecar cloned at `sase/repos/plans`; the project-local research sidecar resolves at
`sase/repos/research` and defaults to `<owner>/<project>--research`. Unmigrated GitHub projects retain their
provider-backed `.sase/sdd/` clone. Materialized layouts record metadata in the primary workspace's
`.sase/sdd-store.json`. Providerless projects fall back to a primary-workspace `.sase/sdd/` store. The retired
`sdd.storage` and `sdd.version_controlled` keys are ignored, stripped before validation, and reported by `sase doctor`
for cleanup. See [SDD Storage](sdd_storage.md) and [Beads](beads.md).

Initialized managed GitHub projects and migrated projects have a schema-version 2 `sidecar_repos` record. Their plans
and beads resolve into the auto-cloned `--plans` repository, while research resolves through the configured `research`
role. Initialization writes an unpinned per-project research entry, prepares configured sidecars in its current
workspace, and re-records stale compatibility metadata with the derived repository. Later workspaces clone research on
demand. The legacy single-sidecar shape continues to resolve byte-for-byte as before.

Built-in bare-git projects also auto-create or refresh generated SDD guide files during first-use `#git:<project>`
initialization, existing bare-repo registration, `#git`/workspace materialization, and the first in-tree SDD write.
Setup/materialization flows commit and push only those generated init paths with an `Initialize SDD` init commit when
needed.

For a repository whose own `sase/sase.yml` sets `is_sase_managed: true`, running `sase repo init` or its
`sase init repo` alias writes the managed plans and research entries, initializes configured sidecars, then refreshes
generated guides and the directory map. On GitHub it derives the remotes as `<owner>/<repo>--plans` and
`<owner>/<repo>--research`, while honoring optional explicit `repo` pins. It initializes and pushes every enabled entry,
then maintains the split store record. Existing legacy `--sdd` files remain untouched locally and in their remote, while
normal SDD routing uses the configured sidecars. `--check` previews provider and generated-file work without writing.
Missing or false management markers make both forms successful no-ops; invalid local marker configuration fails before
provider calls or writes.

Explicit initialization first performs authoritative provider discovery for every enabled sidecar. Each missing GitHub
repository triggers a separate prompt naming its role and resolved repository; only `y` or `yes` authorizes that
invocation to create it. The prompts are default-no and unavailable on non-interactive stdin. Bare `sase init --yes`
cannot authorize repository creation: it reports a missing remote and defers creation to an interactive `sase repo init`
without failing automated onboarding. `--check` remains network-free.

Source: `src/sase/default_config.yml`

### bead

Configuration for the bead issue tracker.

```yaml
bead:
  big_epic_phase_threshold: 5 # minimum authored phase count for @big_epic_lander
  push_after_commit: true # default: true (also accepts false or async)
```

| Field                           | Type        | Default | Description                                                                                                                                                                                                                                                                                        |
| ------------------------------- | ----------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bead.big_epic_phase_threshold` | int         | `5`     | Minimum total authored phase count that selects `@big_epic_lander` for an epic without an explicit land model. Must be at least `1`; malformed runtime values defensively fall back to `5`.                                                                                                        |
| `bead.push_after_commit`        | bool or str | `true`  | Controls the post-commit `git push` after `sase bead work`. `true` pushes synchronously (failures only warn); `false` skips the push; `async` launches a detached background push and returns immediately, logging the result to a file. `sase bead work --no-push` overrides this per-invocation. |

Below the threshold, `@epic_lander` inherits `@default`. At or above it, `@big_epic_lander` instead inherits the
provider-aware `@smartest` fallback. An explicit land model or a direct alias override remains authoritative.

Set to `false` for local-only checkouts, or when you would rather batch the bead-launch commit with later commits before
pushing. Set to `async` to keep auto-pushing without blocking the command on remote network/credential latency. See
[`docs/beads.md`](beads.md#sase-bead-work-target) for the full `sase bead work` flow.

Source: `src/sase/default_config.yml`

### workspace

Controls how SASE chooses the physical location of managed workspace checkouts. See
[`docs/workspace.md`](workspace.md#workspace-directory-layout) for the directory-layout reference and CLI workflows.

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

Numeric identity is the same on every root policy: `#0` is the primary checkout, `#1`–`#9` are reserved, and managed
claim workspaces start at `#10`. See [`docs/workspace.md`](workspace.md#numeric-identity) for the full identity model
and backup/container/NFS caveats.

For non-adjacent policies, physical checkouts live under `<managed-root>/<project_key>/<project>_<num>/`. For example,
`workspace.root: /mnt/sase-workspaces` with project key `github.com_org_repo` places workspace `#10` at
`/mnt/sase-workspaces/github.com_org_repo/<project>_10/`. When `SASE_WORKSPACE_ROOT` is set, it supplies the same
`<managed-root>` base for the process.

Existing adjacent checkouts are not moved automatically by the default. Run `sase workspace migrate --to xdg-state` to
carry legacy `<primary>_<num>/` directories into the managed root, or set `workspace.root: adjacent` explicitly to keep
the old sibling layout.

`sase repo open <primary-repo> -w NUM -r "<reason>"` is an explicit preparation command for a checkout you plan to use
outside a normal `sase run` launch. It uses the same root policy when it materializes the checkout, backs up uncommitted
local changes through the active VCS provider, cleans the checkout, checks out and syncs the provider default parent
revision, and prints the resulting path. For manual scratch work, choose a claim-range number such as `10`; `#0` is the
primary checkout and `#1` through `#9` are reserved compatibility numbers.

Source: `src/sase/default_config.yml`, `src/sase/workspace_provider/store.py`

### telemetry

Configures local telemetry recording and retention. See [docs/telemetry.md](telemetry.md) for the full telemetry
reference, including the CLI, metric catalog, local store, and Admin Center tab.

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

Configures install-mode switching (see [Install mode switching](plugins.md#install-mode-switching)).

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

For the per-provider args, the generic `SASE_LLM_*_ARGS` variables are checked first. If unset, the provider-specific
variable is used as a fallback. Values are split on whitespace and appended to the CLI command.

SASE-launched Codex subprocesses use a disposable shadow `CODEX_HOME` by default. The shadow home is created under
`~/.cache/sase/codex_home/`, receives a copy of the real `config.toml`, symlinks other Codex home entries back to the
real home, and is removed when the subprocess exits. If the real Codex home does not provide `AGENTS.override.md` or
`AGENTS.md`, SASE also links `~/AGENTS.md` into the shadow as Codex's `$CODEX_HOME/AGENTS.md` fallback. This prevents
Codex runtime config rewrites from dirtying the user-managed Codex config while preserving auth, hooks, skills, logs,
and caches.

Qwen Code uses `qwen --input-format text --output-format stream-json --yolo --model <model>` and expects users to
configure Qwen auth through Qwen's supported settings path. Qwen OAuth free tier access ended on 2026-04-15; use API
keys, Alibaba Cloud Coding Plan, OpenRouter, Fireworks, or another Qwen-supported provider.

OpenCode uses `opencode run --format json --dangerously-skip-permissions --model <provider/model> --dir <cwd> <prompt>`
and expects users to configure OpenCode auth/settings through its normal XDG paths. OpenCode model names usually include
a provider prefix; use `opencode models` to list models in your configured environment.

### VCS Provider

| Variable                          | Description                                                                                                                                               |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_VCS_PROVIDER`               | Override VCS provider selection (`git`, `hg`, or `auto`).                                                                                                 |
| `SASE_WORKSPACE_ROOT`             | Override the workspace-root base for this process. Use an absolute path; `WorkspaceStore` appends `<project_key>/<project>_<num>/` for managed checkouts. |
| `SASE_BUG_ID`                     | Bug ID for PR workflows. When set and non-zero, injects `SASE_BUG=<id>` into PR tags and ChangeSpec.                                                      |
| `SASE_BEAD_ID`                    | Bead ID for commit workflows. When set, `sase commit` automatically tags the commit message.                                                              |
| `SASE_DISABLE_COMMIT_STOP_HOOK`   | Disable commit finalization for this process.                                                                                                             |
| `SASE_LINKED_REPOS_JSON`          | Resolved linked-repo metadata passed to launched agents.                                                                                                  |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR` | Workspace-matched directory for one configured linked repo.                                                                                               |

### Plugin System

These switches affect plugin-provided resource loading. The VCS, workspace, and LLM provider registries load provider
entry points directly.

| Variable                       | Description                                                             |
| ------------------------------ | ----------------------------------------------------------------------- |
| `SASE_DISABLE_PLUGINS`         | Disable plugin-provided xprompts, workflows, and config defaults.       |
| `SASE_DISABLE_PLUGIN_XPROMPTS` | Disable plugin-provided xprompt and workflow files.                     |
| `SASE_DISABLE_PLUGIN_CONFIG`   | Disable plugin-provided `default_config.yml` files and config xprompts. |

### State Root

| Variable    | Description                                                                                                                                                          |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_HOME` | Override the SASE state root. Defaults to `~/.sase`; project files, chats, artifacts, notifications, dismissed bundles, saved groups, and logs move under this root. |

### General

| Variable                              | Description                                                                                                                                                                                 |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_TMPDIR`                         | Override the temp directory for all sase operations. Falls back to system default when unset.                                                                                               |
| `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION` | Plan-specific auto-approval action for an agent; currently `approve` or `epic`.                                                                                                             |
| `SASE_AGENT_AUTO_PLAN_ACTION`         | Backward-compatible alias for `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION`.                                                                                                                        |
| `SASE_AGENT_AUTO_APPROVE`             | Legacy boolean auto-approve flag; maps plan submissions to normal approval.                                                                                                                 |
| `SASE_XPROMPT_LSP_CMD`                | Override the command used by `sase lsp` to launch the xprompt language server.                                                                                                              |
| `SASE_CORE_DIR`                       | Preferred `sase-core` source checkout for `Justfile` Rust build/install targets; overrides `../sase-core`.                                                                                  |
| `SASE_PYTEST_DIST`                    | xdist scheduler for the `just` pytest recipes: `worksteal` (default) or `loadfile` (fallback). Invalid values fail before worker-token acquisition; serial inline-snapshot modes ignore it. |
| `SASE_PYTEST_WORKERS`                 | Request exactly this positive number of governed xdist workers for the `just` pytest recipes. The request must fit the active host pool unless accounting is deliberately disabled.         |
| `SASE_PYTEST_WORKER_FLOOR`            | Positive minimum token grant required to start an automatically sized `just` pytest run. Defaults to 4, clamped on smaller hosts, and cannot exceed the ceiling or host pool.               |
| `SASE_PYTEST_WORKER_CEILING`          | Positive maximum token grant for an automatically sized `just` pytest run. Defaults to at most 28 while reserving another floor-sized grant when capacity permits.                          |
| `SASE_TEST_GATE_SLOTS`                | Override the host-wide pytest capacity in worker tokens. Unlike the former whole-suite gate, one token now represents one xdist worker.                                                     |
| `SASE_TEST_GATE_DIR`                  | Override the shared pytest token-pool directory. Defaults to a UID-scoped `sase-pytest-tokens-<uid>` directory under `/tmp`.                                                                |
| `SASE_TEST_GATE_TIMEOUT`              | Non-negative seconds to wait for a sufficient worker-token grant before failing with requested capacity and current-holder diagnostics.                                                     |
| `SASE_TEST_GATE_DISABLED`             | Set to `1` to bypass the pytest worker-token pool deliberately. Governed parents also export it to prevent nested pytest deadlocks.                                                         |
| `SASE_TEST_GATE_GOVERNED`             | Internal marker indicating that `tools/run_pytest` already leased the controller's worker tokens; inherited pytest configuration must not lease them again.                                 |
| `SASE_JUST_INVOCATION_DIR`            | Internal value set by `just` so test selectors are normalized from the caller's directory.                                                                                                  |

The pytest variables above describe one UID-scoped pool shared by `just` recipes and direct parallel pytest controllers.
The first active lease records the effective capacity; later launchers honor that capacity until every holder exits,
even if `MemAvailable` changes in the meantime. Automatic launchers require their floor atomically and then take
currently free tokens up to the ceiling. Exact `SASE_PYTEST_WORKERS` requests wait for the complete request, and an
explicit `SASE_TEST_GATE_SLOTS` value must match an already-active pool. The former whole-suite slot gate is fully
superseded: admission, diagnostics, and SIGKILL-safe release are all expressed in worker tokens.

### Workspace Management (Internal)

These are set automatically by sase when launching agent subprocesses and are not intended for manual use. Workspace
plugins declare an env-var prefix, then SASE passes `<PREFIX>_PRE_ALLOCATED`, `<PREFIX>_WORKSPACE_NUM`, and
`<PREFIX>_WORKSPACE_DIR` into the child process. Built-in prefixes include `SASE_GIT` for `#git`; plugin packages may
add prefixes such as `SASE_GH` for GitHub. The launcher clears inherited `SASE_*_PRE_ALLOCATED`, `SASE_*_WORKSPACE_NUM`,
and `SASE_*_WORKSPACE_DIR` variables before applying the current launch's values so follow-up agents cannot inherit
stale workspace claims.

| Variable                 | Description                                                                |
| ------------------------ | -------------------------------------------------------------------------- |
| `SASE_SYNC_CWD`          | Working directory override for sync operations.                            |
| `<PREFIX>_PRE_ALLOCATED` | Set to `"1"` when a workspace provider has pre-allocated a launch context. |
| `<PREFIX>_WORKSPACE_NUM` | Pre-allocated workspace number.                                            |
| `<PREFIX>_WORKSPACE_DIR` | Pre-allocated workspace directory path.                                    |
| `SASE_GIT_*`, ...        | Concrete forms for built-in and plugin-provided workspace prefixes.        |

## CLI Flags

Command groups that default to a nested `list` command still parse flags at the subcommand level. Use the explicit
`list` form when passing list options, such as `sase notify list -j`, `sase memory list -j`, or
`sase workspace list --json`.

### `sase ace`

| Flag                     | Values                                      | Default                   | Description                                                                                                                                                                           |
| ------------------------ | ------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[query]`                | string                                      | last saved query or `!!!` | Query string for filtering ChangeSpecs.                                                                                                                                               |
| `-m, --model-tier`       | `large`, `small`                            | -                         | Override model tier for all LLM invocations.                                                                                                                                          |
| `-M, --model-size`       | `big`, `little`                             | -                         | Deprecated alias for `--model-tier`.                                                                                                                                                  |
| `-p, --profile`          | optional path                               | -                         | Profile the TUI session with pyinstrument (default output `$SASE_TMPDIR/ace_profile_<ts>.txt`); after exit, print a shortened path and copy it to the system clipboard when possible. |
| `-r, --refresh-interval` | int (seconds)                               | `10`                      | Auto-refresh interval (0 to disable).                                                                                                                                                 |
| `-R, --restart-axe`      | flag                                        | -                         | Restart the axe daemon on startup (no-op if axe is not running).                                                                                                                      |
| `-t, --tab`              | `artifacts`, `changespecs`, `agents`, `axe` | `agents`                  | Tab to focus on startup (`changespecs` is a legacy alias for `artifacts`).                                                                                                            |
| `-T, --tmux`             | flag                                        | -                         | Launch ACE in a new tmux window named `sase_tmux_<N>` and print the session/window target for external control.                                                                       |
| `-x, --no-axe`           | flag                                        | -                         | Disable auto-starting the axe daemon.                                                                                                                                                 |
| `-v, --vcs-provider`     | `git`, `hg`, `auto`                         | -                         | Override VCS provider.                                                                                                                                                                |

### `sase axe`

| Flag                 | Values              | Default | Description            |
| -------------------- | ------------------- | ------- | ---------------------- |
| `-v, --vcs-provider` | `git`, `hg`, `auto` | -       | Override VCS provider. |

### `sase axe start`

| Flag                      | Values        | Default          | Description                                         |
| ------------------------- | ------------- | ---------------- | --------------------------------------------------- |
| `-q, --query`             | string        | `""` (all)       | Query string for filtering ChangeSpecs.             |
| `-H, --max-hook-runners`  | int           | config or `3`    | Maximum concurrent hook runners.                    |
| `-A, --max-agent-runners` | int           | config or `3`    | Maximum concurrent agent runners.                   |
| `-z, --zombie-timeout`    | int (seconds) | config or `7200` | Timeout before marking a hook/workflow as a zombie. |

For `sase axe start`, CLI flags take precedence over values from the `axe` config section in `sase.yml`. If neither is
set, the built-in defaults from `default_config.yml` are used.

### `sase repro`

Agents-tab reproduction bundles capture and replay the loader/apply sequence used to render agent rows. The command is
intended for debugging row disappearance, reappearance, and duplicate-parent regressions; see
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

With no subcommand, `sase axe chop` defaults to `sase axe chop list`. Use the explicit `list` or `doctor` subcommand
when passing diagnostic flags.

| Form                   | Flags                                         | Description                                                                                       |
| ---------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `sase axe chop list`   | `-a/--available`, `-j/--json`, `-v/--verbose` | List configured chops with status; `--available` also shows discoverable executable chop scripts. |
| `sase axe chop doctor` | `-j/--json`, `-v/--verbose`                   | Diagnose missing configured chops, unconfigured scripts, and Telegram chop prerequisites.         |
| `sase axe chop run`    | `-L/--lumberjack`                             | Run a single chop once in the foreground.                                                         |

`sase axe chop doctor` exits `1` when any check is `ERROR` (a configured script chop cannot be resolved) and `0`
otherwise. Unconfigured available scripts and Telegram prerequisite gaps report `WARN`. The same chop diagnostics are
also surfaced by `sase doctor -C axe.chops`.

### `sase commit`

Dispatches a commit, proposal, or PR via the VCS provider layer. See [commit_workflows.md](commit_workflows.md) for the
full flow, payload, checkpoint, and resume semantics.

| Flag                    | Values                        | Default                 | Description                                                                                      |
| ----------------------- | ----------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------ |
| `-m, --message`         | string                        | -                       | Commit message (mutually exclusive with `-M`).                                                   |
| `-M, --message-file`    | path                          | -                       | File containing the commit message / PR description (mutually exclusive with `-m`).              |
| `-f, --file`            | path (repeatable)             | stage all               | Specific file to stage. Repeat for multiple; omit to stage everything.                           |
| `-n, --name`            | string                        | -                       | Branch/PR name (required for `create_pull_request`).                                             |
| `-B, --bug-id`          | int                           | `$SASE_BUG_ID`          | Bug ID to associate with the commit.                                                             |
| `-c, --checkout-target` | string                        | `HEAD~1`                | Branch point for PR creation.                                                                    |
| `-p, --parent`          | ChangeSpec name               | auto                    | Parent ChangeSpec name (overrides branch-based auto-detection). Unresolvable values are dropped. |
| `-r, --resume`          | flag                          | -                       | Resume a previously-checkpointed commit after manual conflict resolution.                        |
| `-s, --status`          | `wip` / `draft` / `ready`     | `$SASE_PR_STATUS`/draft | ChangeSpec status override for PRs.                                                              |
| `-t, --type`            | `commit` / `propose` / `pr` … | `$SASE_COMMIT_METHOD`   | Commit method — full names (`create_commit`, etc.) and short aliases are both accepted.          |

### `sase vcs`

`sase vcs` defaults to `sase vcs list`, which inspects the available repository constellation made up of the primary
repo, configured linked repos, and the materialized separate SDD store when present. `sase vcs log` includes primary and
linked history by default; add `-S/--sdd` to include materialized separate SDD repository history.

| Subcommand | Flags                                                                                                                                                                                                                                                                           | Description                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `list`     | `-c/--color`, `-f/--format pretty\|oneline\|json`, `-N/--no-fetch`, `-o/--current-only`, `-r/--repo`, `-s/--sort`                                                                                                                                                               | List resolved repositories, descriptions, branch state, dirty state, stats, and latest activity. |
| `log`      | `-a/--all`, `-A/--author`, `-b/--branch/--ref`, `-c/--color`, `-o/--current-only`, `-F/--fetch`, `-f/--format pretty\|full\|oneline\|json`, `-n/--limit`, `-N/--no-fetch`, `-T/--no-tags`, `-r/--repo`, `-R/--reverse`, `-S/--sdd`, `-s/--since/--after`, `-u/--until/--before` | Show a merged commit timeline with local/remote presence markers.                                |

`sase vcs log` date filters accept relative offsets (`Nh`, `Nd`, `Nw`), `today`, `yesterday`, `YYYY-MM-DD`, or
`YYYY-MM-DDTHH:MM`. Day-granular `--until` / `--before` values include the full named day; relative and minute-precise
values remain instant bounds. See [VCS Providers](vcs.md#per-command-vcs-usage) for output examples and provider notes.
`--all` spans every registered enabled or disabled project and deduplicates shared physical checkouts. Internal sibling
backing checkouts remain visible as linked repositories of their owning projects. Global scope can be combined with
repeatable `--repo` filters but not `--current-only`. Add `--sdd` to either scope before selecting SDD history with
`--repo sdd`; without the opt-in, that repo filter does not expand the eligible set. `--all --sdd` includes materialized
separate SDD repositories across registered projects. The `--limit` is the cap on the final merged timeline.

### `sase changespec search`

| Flag           | Values                      | Default    | Description                                           |
| -------------- | --------------------------- | ---------- | ----------------------------------------------------- |
| `query`        | string                      | (required) | Query string for filtering ChangeSpecs.               |
| `-f, --format` | `plain`, `rich`, `markdown` | `rich`     | Output format (`markdown` for agent-friendly output). |

Search uses the normal enabled-project discovery scope. Disabled projects and internal sibling backing records are
omitted from this CLI path; run `sase project list --state all` or `sase project show <project>` to inspect them, then
run `sase project enable <project>` before using normal search and launch surfaces for new work.

### `sase changespec migrate-extension`

One-time cleanup for older installs: renames legacy ProjectSpec files under `~/.sase/projects` from `.gp` to `.sase`,
including archive siblings. Current readers still accept `.gp` as a fallback, so migration is not required before using
SASE; it just normalizes on-disk filenames to the canonical extension.

If a `.sase` sibling already exists with identical contents, the redundant `.gp` copy is removed. If the sibling
differs, the command reports a conflict and preserves both files unless `--force` is set.

| Flag             | Values | Default             | Description                                                               |
| ---------------- | ------ | ------------------- | ------------------------------------------------------------------------- |
| `--force`        | flag   | -                   | Replace an existing differing `.sase` sibling with the legacy `.gp` file. |
| `--projects-dir` | path   | `~/.sase/projects/` | Override the project root scanned for legacy `.gp` files.                 |

### `sase project`

With no subcommand, `sase project` defaults to `sase project list`. Project lifecycle state is stored as `PROJECT_STATE`
metadata in the ProjectSpec header; missing state means `enabled`.

| Form                                       | Flags                                         | Description                                                                    |
| ------------------------------------------ | --------------------------------------------- | ------------------------------------------------------------------------------ |
| `sase project list`                        | `-s, --state enabled\|disabled\|sibling\|all` | List records in one state; default is true enabled projects.                   |
| `sase project list`                        | `-j, --json`                                  | Emit machine-readable lifecycle and derived project/VCS fields.                |
| `sase project show <project>`              | `-j, --json`                                  | Show state, source, project/archive files, workspace, launchability, warnings. |
| `sase project set-state <project> <state>` | `-f, --force`                                 | Set `enabled`, `disabled`, or internal backing marker `sibling`.               |
| `sase project enable <project>`            | `-f, --force`                                 | Enable a project; `--force` has no effect when enabling.                       |
| `sase project disable <project>`           | `-f, --force`                                 | Disable a project after live-work safety checks.                               |

Disabling refuses projects with live `RUNNING` claims or live artifact markers (`running.json`, `waiting.json`, or
`pending_question.json`) unless `--force` is passed. Legacy `active` normalizes to enabled; `inactive`, `archived`, and
`closed` normalize to disabled. Deprecated `activate`, `deactivate`, `archive`, and `close` command aliases remain
accepted. The system-managed `home` project cannot be mutated. Normal launch and discovery surfaces default to enabled
projects. `sibling` remains an internal backing-record marker for configured linked repos, not a third project state.

ACE exposes the same lifecycle mutations through the **Projects** tab of the SASE Admin Center (press `#`). That tab
also supports marks for bulk lifecycle operations, alias editing with `A`, ProjectSpec editing through `$EDITOR`,
confirmed deletion of whole SASE project directories, and the Repos/Workspaces inventory sub-tabs described above.

### `sase repo`

Bare `sase repo` defaults to `sase repo list`. The command family inventories primary, sidecar, linked, and opened
external repositories, prepares a selected repo inside one workspace context, and exposes the durable audit history of
successful opens.

`sase repo list` defaults to the current project and infers both the project and workspace context from cwd. Primary
repos come from ProjectSpecs, sidecars from `repos.sidecar` plus SDD store records, linked repos from resolved
`repos.linked` (including compatibility aliases), and external repos from materialized workspace-local clones; a sidecar
wins when the same checkout is also auto-injected as linked. The Rich table reports whether each repo is cloned in the
selected workspace plus the number of registered workspaces containing it. External rows use the canonical project name
or provider ref such as `gh:pallets/click`. Hidden `agents` rows remain visible and report the same stable machine-level
path for every registered workspace context.

| List flag         | Description                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| `-a, --all`       | Show all enabled and disabled projects at primary workspace context (`#0`). |
| `-j, --json`      | Emit deterministic records with the full per-workspace `clones` matrix.     |
| `-p, --project`   | Select one enabled or disabled project instead of inferring from cwd.       |
| `-w, --workspace` | Select a workspace number instead of inferring it from cwd.                 |

`--all` and `--project` are mutually exclusive. JSON records retain source, description, `auto_clone`, environment, and
SDD-storage metadata while making `path` and `exists` describe the selected workspace context.

`sase repo open REPO -r "<reason>"` resolves `REPO` in three tiers: a host-project inventory name, another registered
SASE project name, then an external provider ref (`gh:owner/repo` or `owner/repo` GitHub shorthand). It materializes and
prepares the repo, prints only its path to stdout, records the per-run artifact markers used by ACE and the commit
finalizer, and appends an event to `~/.sase/projects/<project>/repo_opens.jsonl`. Run it inside a managed checkout to
infer the host project and workspace. Reopening a valid external clone preserves its current contents and records a new
open event.

| Open argument / flag | Description                                                                |
| -------------------- | -------------------------------------------------------------------------- |
| `REPO`               | Inventory name, registered project name, `gh:owner/repo`, or `owner/repo`. |
| `-p, --project`      | Select the host project instead of inferring it from cwd.                  |
| `-r, --reason`       | Required non-empty audit reason.                                           |
| `-w, --workspace`    | Select the host workspace number instead of inferring it from cwd.         |

`sase repo log` renders a project-scoped summary and per-repo rollup of durable open events. Repo, agent, or workspace
filters add agent and event drill-down panels; an event ID prefix shows one complete event. `--json` returns the same
filtered data deterministically.

| Log flag          | Description                                               |
| ----------------- | --------------------------------------------------------- |
| `-a, --agent`     | Filter by agent name or interactive user.                 |
| `-i, --id`        | Show one event by exact ID or unambiguous ID prefix.      |
| `-j, --json`      | Emit deterministic structured output.                     |
| `-p, --project`   | Select the host project instead of inferring it from cwd. |
| `-r, --repo`      | Filter by repository name.                                |
| `-w, --workspace` | Filter by host workspace number.                          |

### `sase revert`

| Flag   | Values | Default    | Description                       |
| ------ | ------ | ---------- | --------------------------------- |
| `name` | string | (required) | NAME of the ChangeSpec to revert. |

### `sase restore`

| Flag         | Values | Default | Description                                 |
| ------------ | ------ | ------- | ------------------------------------------- |
| `[name]`     | string | -       | NAME of the reverted ChangeSpec to restore. |
| `-l, --list` | flag   | -       | List all reverted ChangeSpecs.              |

### `sase run`

| Flag      | Values | Default | Description                                                                                                   |
| --------- | ------ | ------- | ------------------------------------------------------------------------------------------------------------- |
| `[query]` | string | -       | Prompt text, inline reference (`#name`), standalone workflow reference (`#!name`), or `.` for history picker. |

When invoked with no arguments, opens `$EDITOR` for composing a prompt interactively. When invoked with `.`, opens a
prompt history picker. All prompts launch as detached background agents, and multi-prompt queries (containing `---`
separators) are launched as sequential detached background agents.

### `sase repro`

`sase repro` captures and replays debugging bundles for narrow, reproducible TUI bug classes. The current target is the
Agents-tab loader/apply sequence used to diagnose row disappearance, reappearance, and duplicate workflow parents.

| Form                            | Flags                                                                     | Description                                                                                        |
| ------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `sase repro replay <path>`      | `--assert-stable`, `--json`, `--write-artifacts <dir>`, `--size`          | Replay a bundle JSON file or bundle directory through the headless TUI harness.                    |
| `sase repro capture agents-tab` | `--output <dir>`, `--commit-safe`, `--no-commit-safe`, `--size`, `--json` | Capture a baseline bundle from current filesystem state. `--commit-safe` redaction is the default. |

Use the in-TUI `,B` capture when a transient row-list bug has just happened in a live ACE session. The CLI capture path
is out-of-band: it loads current filesystem state and cannot reconstruct refreshes that already passed through the
running TUI.

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

No flags. Outputs a JSON array of all available xprompts with name, type, source, inputs, tags, `is_skill`, and preview.
Clients that insert references should prefer `kind`/`insertion` metadata when present so standalone workflows are
inserted as `#!name` and inline-capable entries, including markdown xprompt swarms, are inserted as `#name`. Slash skill
completion clients should filter to entries where `is_skill` is `true`.

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

Bare `sase init` is the onboarding coordinator for SASE-managed resources. It runs read-only planners for memory, SDD,
and skills, prints a grouped summary, and prompts once per initializer that needs work when stdin is interactive.
Non-interactive runs never prompt; they print the drift summary and ask the caller to rerun with `--yes`. That flag runs
needed initializers but cannot authorize creation of a missing GitHub SDD sidecar, which always requires its own
interactive `y`/`yes` response. The memory planner (which owns agent-document initialization) only generates managed
project `AGENTS.md` from bare `sase init` when the current project's own `sase/sase.yml` sets `is_sase_managed: true`.
The SDD planner uses that same local marker and skips unmanaged repositories before provider work. Neither planner
infers project ownership from `amd_h1_title`, existing memory notes, lifecycle state, or merged configuration.

`--all` applies that coordinator to every registered enabled main project from its recorded primary workspace, even when
the command starts outside a project. It excludes disabled projects, internal sibling backing records, `home`, and other
system-managed records, continues after per-project failures, and returns non-zero if any project has drift, is
unavailable, or fails. `--all --check` is read-only, while non-interactive apply still requires `--yes`. `--all` is
incompatible with `--enable-project-memory` and with explicit compatibility subcommands.

Advanced deploy controls stay on explicit subcommands such as `sase memory init --no-commit` and
`sase skill init --no-push`.

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

Creates or refreshes home memory and memory for SASE-managed projects. Project ownership requires
`is_sase_managed: true` in the project's own `sase/sase.yml`; `amd_h1_title` is optional title customization, with a
stable derived title otherwise. The retired `memory.enabled` key does not authorize management. It never creates or
alters an unmanaged project's root `AGENTS.md`. Independently, it overwrites each provider instruction file
(`CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md`) with a byte-for-byte copy of that root's `AGENTS.md` (legacy
`@AGENTS.md` / `*.md.tmpl` import shims are recognized and migrated to full copies). This copy applies to every existing
project-tree `AGENTS.md`; directories without one are untouched. For managed roots, memory init synchronizes memory:
short-term notes are inlined verbatim into the Tier 1 block of `AGENTS.md`, long-term notes are rendered as a
description-driven reference list, and missing long-memory `description` frontmatter is inserted. By default it also
tries to commit, rebase-pull, and push generated project-side files. `sase init memory` is a compatibility alias for
this command. Generated repository memory requires agents to use `/sase_repo` before reading or modifying any repo
outside their own workspace checkout. The rule covers linked repos, sidecars, different SASE projects, and unlinked
GitHub repos even when no linked repositories are configured.

| Flag                          | Values | Default | Description                                                                                             |
| ----------------------------- | ------ | ------- | ------------------------------------------------------------------------------------------------------- |
| `-c, --check`                 | flag   | -       | Report memory initialization drift without writing project or home files.                               |
| `-M, --enable-project-memory` | flag   | -       | Set `is_sase_managed: true`, enabling managed project memory; incompatible with `--check`.              |
| `-C, --no-commit`             | flag   | -       | Write files, but skip only the project git commit/pull/push path; home deployment still follows config. |

### `sase init repo`

`sase init repo` is an alias for `sase repo init`. For targets marked `is_sase_managed: true` in their own
`sase/sase.yml`, it initializes configured sidecars, creates or refreshes generated README files, ensures the managed
plans and research declarations, and maintains the root `/sase/repos/` ignore rule. Missing or false markers produce an
informative successful no-op, while invalid local configuration fails before provider or filesystem work. `--path`
always checks the target repository's marker. GitHub setup creates missing sidecars with their configured public/private
visibility. Bare-git projects refresh generated files automatically during repository setup and first SDD writes; the
explicit command remains useful for refreshes and `--check` audits.

When the GitHub sidecar is missing, this alias uses the same default-no repository-specific confirmation as
`sase repo init`. EOF, interruption, and any answer other than `y`/`yes` return nonzero before remote creation. Generic
`--yes` approval never authorizes repository creation; non-interactive bare onboarding instead reports the missing
remote and defers its creation.

| Flag          | Values | Default         | Description                                                        |
| ------------- | ------ | --------------- | ------------------------------------------------------------------ |
| `-c, --check` | flag   | -               | Report provider and generated-file work without writing files.     |
| `-p, --path`  | path   | current project | Project root whose provider-owned SDD store should be initialized. |

### `sase skill`

With no subcommand, `sase skill` defaults to the read-only `sase skill list` dashboard. It reports loaded skill sources,
provider targets, and deployed-file drift without writing files. `sase skill init` generates and deploys agent skill
files from xprompt sources marked with the `skill` field. Generated skill files begin with a `sase skill use` directive
so agent-side skill use can be audited and later summarized with `sase skill log`, unless the source sets
`log_skill_use: false`. See [xprompt.md — Skill Field](xprompt.md#skill-field) for the skill-source contract and
provider targets. Existing files are skipped in non-interactive runs unless `--force` is passed; interactive runs prompt
before overwriting. `sase init skills` is a compatibility alias for `sase skill init`.

| Form               | Flags                                                                   | Description                                                                                 |
| ------------------ | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `sase skill`       | -                                                                       | Show the same read-only dashboard as `sase skill list`.                                     |
| `sase skill list`  | -                                                                       | Inspect generated skill sources, provider targets, and deployed-file drift.                 |
| `sase skill init`  | `-f, --force`                                                           | Overwrite existing deployed skill files without confirmation.                               |
| `sase skill init`  | `-n, --dry-run`                                                         | Show what would be written without writing files.                                           |
| `sase skill init`  | `-p, --provider {claude,agy,codex,opencode,qwen}`                       | Deploy only for one provider.                                                               |
| `sase skill init`  | `-A, --no-apply`                                                        | With `use_chezmoi`, skip `chezmoi apply` after generated files are committed and pushed.    |
| `sase skill init`  | `-C, --no-commit`                                                       | With `use_chezmoi`, skip the entire git commit, push, and apply sequence.                   |
| `sase skill init`  | `-P, --no-push`                                                         | With `use_chezmoi`, commit generated files but skip pull/rebase, push, and `chezmoi apply`. |
| `sase skill log`   | `-a, --agent`; `-R, --runtime`; `-s, --skill`; `-i, --id`; `-j, --json` | Summarize or inspect audited generated skill-use events.                                    |
| `sase skill use`   | `-r, --reason <reason>` required                                        | Agent-side audit event recording that the current agent is using a generated skill.         |
| `sase init skills` | same as `sase skill init`                                               | Compatibility alias for `sase skill init`.                                                  |

### `sase repo init`

`sase repo init` declares the managed plans and research sidecars, initializes enabled configured sidecars, and ensures
the project root `.gitignore` contains `/sase/repos/`, protecting host-scoped repository clones durably. `-c, --check`
reports drift without writing, `-d, --diff` renders proposed full-file diffs, and `-C, --no-commit` writes project
config and ignore changes without the normal project commit/pull/push sequence. `sase init repo` is an alias; bare
`sase init` and `sase validate` include the same check for Git projects.

### `sase workspace`

Workspace commands inspect and maintain the managed checkout registry for the inferred project, or for the project named
by `-p/--project`. With no subcommand, `sase workspace` defaults to `sase workspace list` with default options. Use
`sase workspace list -p <project>`, `sase workspace list --all`, or `sase workspace list --json` when passing list
flags.

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

For built-in bare-git projects, `sase repo open` may initialize generated SDD guide files in the primary checkout before
materializing a numbered workspace. `sase workspace list` and `sase workspace path` remain read-only and do not run SDD
initialization.

### `sase bead`

With no subcommand, `sase bead` defaults to `sase bead list`.

| Flag         | Values                                                                                                                                     | Default | Description     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------ | ------- | --------------- |
| _subcommand_ | `init`, `create`, `list`, `show`, `ready`, `open`, `update`, `close`, `rm`, `dep`, `blocked`, `sync`, `stats`, `doctor`, `onboard`, `work` | `list`  | Bead subcommand |

#### `sase bead create`

| Flag                | Values                     | Default    | Description                                                                 |
| ------------------- | -------------------------- | ---------- | --------------------------------------------------------------------------- |
| `-t, --title`       | string                     | (required) | Issue title                                                                 |
| `-T, --type`        | string                     | (required) | Bead type: `plan(<file>)`, `plan(<file>,<parent>)`, or `phase(<parent_id>)` |
| `-d, --description` | string                     | -          | Issue description                                                           |
| `-a, --assignee`    | string                     | -          | Assignee name                                                               |
| `-m, --model`       | string                     | -          | Epic land-agent or phase-work model                                         |
| `-z, --size`        | `small`, `medium`, `large` | -          | Phase size; valid only for phase beads                                      |
| `--tier`            | `plan`, `epic`             | -          | Plan-bead tier                                                              |
| `-c, --changespec`  | ChangeSpec name            | -          | Attach ChangeSpec metadata to a plan bead                                   |
| `-b, --bug-id`      | string                     | -          | Bug ID for the attached ChangeSpec; requires `--changespec`                 |

#### `sase bead list`

| Flag           | Values                          | Default | Description                           |
| -------------- | ------------------------------- | ------- | ------------------------------------- |
| `-s, --status` | `open`, `in_progress`, `closed` | -       | Filter by status (repeatable)         |
| `-t, --type`   | `plan`, `phase`                 | -       | Filter by type (repeatable)           |
| `--tier`       | `plan`, `epic`                  | -       | Filter by plan-bead tier (repeatable) |

#### `sase bead search`

| Flag           | Values                          | Default     | Description                                                         |
| -------------- | ------------------------------- | ----------- | ------------------------------------------------------------------- |
| `query`        | string                          | (required)  | Literal non-empty text to search for                                |
| `-c, --color`  | `auto`, `always`, `never`       | `auto`      | Color mode for compact output                                       |
| `-f, --format` | `compact`, `json`, `full`       | `compact`   | Output format                                                       |
| `-n, --limit`  | non-negative integer            | (unlimited) | Maximum results to print; `0` also means unlimited                  |
| `-s, --status` | `open`, `in_progress`, `closed` | -           | Filter by status (repeatable); all statuses are searched by default |
| `--tier`       | `plan`, `epic`                  | -           | Filter by plan-bead tier (repeatable)                               |
| `-t, --type`   | `plan`, `phase`                 | -           | Filter by type (repeatable)                                         |

#### `sase bead show`

| Flag | Values | Default    | Description |
| ---- | ------ | ---------- | ----------- |
| `id` | string | (required) | Issue ID    |

#### `sase bead open`

| Flag | Values | Default    | Description        |
| ---- | ------ | ---------- | ------------------ |
| `id` | string | (required) | Issue ID to reopen |

#### `sase bead update`

| Flag                | Values                          | Default    | Description           |
| ------------------- | ------------------------------- | ---------- | --------------------- |
| `id`                | string                          | (required) | Issue ID to update    |
| `-s, --status`      | `open`, `in_progress`, `closed` | -          | Change status         |
| `-t, --title`       | string                          | -          | Change title          |
| `-d, --description` | string                          | -          | Change description    |
| `-n, --notes`       | string                          | -          | Change notes          |
| `-D, --design`      | path                            | -          | Change plan path      |
| `-a, --assignee`    | string                          | -          | Change assignee       |
| `-m, --model`       | string                          | -          | Change launch model   |
| `-z, --size`        | `small`, `medium`, `large`      | -          | Change phase size     |
| `--tier`            | `plan`, `epic`                  | -          | Change plan-bead tier |

#### `sase bead close`

| Flag           | Values | Default    | Description                |
| -------------- | ------ | ---------- | -------------------------- |
| `ids`          | string | (required) | One or more issue IDs      |
| `-r, --reason` | string | -          | Optional close reason text |

#### `sase bead rm`

| Flag | Values | Default    | Description        |
| ---- | ------ | ---------- | ------------------ |
| `id` | string | (required) | Issue ID to remove |

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

| Flag            | Values                 | Default    | Description                                                                 |
| --------------- | ---------------------- | ---------- | --------------------------------------------------------------------------- |
| `target`        | bead ID or plan path   | (required) | Existing epic bead to launch, or validated epic plan file to create/launch. |
| `-n, --dry-run` | flag                   | -          | Print the wave plan and rendered multi-prompt without mutating state.       |
| `-j, --json`    | flag                   | -          | Print one machine-readable result object.                                   |
| `-P, --no-push` | flag                   | -          | Commit launched bead state locally but skip the post-commit `git push`.     |
| `-p, --parent`  | bead ID or `top-level` | -          | Override a plan file's `parent_bead`, including forcing an unparented epic. |
| `-y, --yes`     | flag                   | -          | Skip the launch confirmation prompt when launching phase or epic agents.    |

### SDD repository and plan commands

SDD initialization/path resolution lives under `sase repo`; artifact browsing and prompt/plan link maintenance live
under `sase plan`. Link commands accept `-p/--path`, which may point at an SDD root or a project root. Bare
`sase plan links` defaults to its `list` child.

| Command                    | Flags                                                                       | Description                                                             |
| -------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `sase repo init`           | `-p/--path`, `-c/--check`, `-d/--diff`, `-C/--no-commit`                    | Initialize configured sidecars and repository wiring                    |
| `sase repo path REPO`      | `-e/--ensure`, `-p/--project`, `-w/--workspace`                             | Print a primary or sidecar path; optionally materialize it              |
| `sase plan links [list]`   | `-p/--path`, `-j/--json`                                                    | List prompt/plan artifact links and bidirectional status                |
| `sase plan links repair`   | `-p/--path`, `-w/--write`                                                   | Infer unambiguous prompt/plan pairs and optionally write fixes          |
| `sase plan links validate` | `-p/--path`, `-j/--json`, `-q/--quiet`, `-s/--strict`, `-W/--show-warnings` | Validate links; strict mode turns unpaired historical files into errors |
| `sase plan search`         | `-k/--kind`, `-o/--source`, `-f/--format`, plus query/date/status filters   | Search or browse tale, epic, prompt, and research artifacts             |

### `sase validate`

`sase validate` is the top-level portable SASE validation command. It runs the explicit `sase init memory --check`,
`sase init repo --check`, and `sase init skills --check` surfaces plus `sase plan links validate`, prints one status
line per check, and exits non-zero if any check fails. It deliberately leaves the machine-local Config planner to bare
`sase init --check` and `sase doctor`, so clean CI hosts do not need a synthetic machine identity. The command can still
fail on user/home memory or skill deployment drift even when repository-local SDD validation passes.

### `sase doctor`

Runs the read-only support diagnostics bundle for the active runtime, configuration, provider setup, project/workspace
state, bead store, agent index, and telemetry when configured. Default mode is bounded and safe to run before asking for
help; deep mode adds slower read-only checks.

| Flag                  | Values   | Default | Description                                                             |
| --------------------- | -------- | ------- | ----------------------------------------------------------------------- |
| `-j`, `--json`        | flag     | -       | Emit the `schema_version: 1` JSON support report.                       |
| `-v`, `--verbose`     | flag     | -       | Show every check plus bounded details in human output.                  |
| `-D`, `--deep`        | flag     | -       | Include slower read-only deep checks.                                   |
| `-s`, `--strict`      | flag     | -       | Exit non-zero for warnings as well as errors.                           |
| `-L`, `--list-checks` | flag     | -       | List registered default and deep check ids without running them.        |
| `-C`, `--check`       | id/group | repeat  | Run only the selected check id or group; may be passed multiple times.  |
| `-p`, `--project`     | string   | infer   | Inspect a named project when doctor cannot infer one from the checkout. |

Use `sase doctor -L` to list targeted check IDs. Useful focused checks include `runtime`, `llm.default`,
`plugins.resources`, `project.junk_directories`, `workspace.missing_checkouts`, and `config.model_xprompts`. The two
inventory checks report telemetry-only directories without ProjectSpecs and registered workspace paths missing from
disk; both are read-only and provide cleanup/repair guidance.

Default exit behavior is `0` for `OK`, `WARN`, and `SKIP`, and `1` for `ERROR`. Attach `sase doctor -v` or
`sase doctor -j` when asking for help.

### `sase version`

`sase version` reports the local runtime that the current `sase` process is using. It does not query PyPI, GitHub, or
latest available releases. The inventory always includes the host `sase` package and the required `sase-core-rs` Rust
core distribution, then adds installed SASE plugin packages discovered through SASE entry points, SASE console scripts,
or `sase-*` distribution names.

The default human output is a compact runtime panel plus a package table with role, effective version, and code
directory. Development checkouts use PEP 440 local versions such as `0.1.2+4.g26c39e004` or `0.1.2+0.g26c39e004.dirty`.
Editable installs prefer source metadata over stale installed distribution metadata, while `--verbose` and `--json`
expose both values for auditability.

| Flag            | Values | Default | Description                                                                   |
| --------------- | ------ | ------- | ----------------------------------------------------------------------------- |
| `-j, --json`    | flag   | -       | Emit a stable JSON object with `schema_version: 1`, runtime, and packages.    |
| `-v, --verbose` | flag   | -       | Include install type, dist/source versions, git metadata, and plugin signals. |

### `sase var`

`sase var set` attaches small named string values to the current SASE agent run by merging them into
`agent_meta.json["output_variables"]`. The command is agent-scoped and requires `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR`.
The variables appear in ACE's Agents-tab `OUTPUT VARIABLES` metadata panel and in Telegram agent-completion messages.
Later agents that wait on this agent with `%wait` load the stored strings when they start and can render them through
the `agents` Jinja dictionary in prompts and xprompt workflows.

| Form                           | Flags / arguments      | Description                                               |
| ------------------------------ | ---------------------- | --------------------------------------------------------- |
| `sase var set KEY=VALUE [...]` | positional assignments | Store one or more output variables for the current agent. |

Keys must be valid Jinja attribute identifiers (`[A-Za-z_][A-Za-z0-9_]*`). Values are strings split on the first `=`, so
values may contain additional equals signs. Multiple calls merge into the same variable map; later writes for the same
key replace earlier values. The command does not update prompts that have already started rendering, so write variables
before the producing agent completes and before dependent agents unblock. Downstream prompts read each producer's
variables from the single `agents` dictionary keyed by the producer's stable agent name, e.g.
`{{ agents["build"].report_path }}` (or `{{ agents.build.report_path }}` for identifier-safe names). Do not store
secrets; output variables are persisted in `agent_meta.json` and shown in ACE and Telegram completion messages.

`STOP` is a reserved output variable. `sase var set` stays generic and stores it like any other key, but repeat
orchestration interprets it: setting `STOP` (e.g. `sase var set STOP=1`) inside a `%repeat` / `%r` iteration stops the
remaining repeat slots, which finalize as successful skipped slots. Truthiness is conservative — `""`, `0`, `false`,
`no`, and `off` (case-insensitive) are not-stop; any other value stops the chain. `STOP` affects only repeat-chain
continuation; ordinary `%wait` consumers read it as a normal variable. See
[Repeat Directive](xprompt.md#repeat-directive) in the xprompt reference for the full cascade semantics.

### `sase telemetry`

With no subcommand, `sase telemetry` prints a delegation notice and runs `sase telemetry list`.

| Flag         | Values                                                      | Default | Description          |
| ------------ | ----------------------------------------------------------- | ------- | -------------------- |
| _subcommand_ | `cleanup-test-data`, `health`, `list`, `snapshot`, `status` | `list`  | Telemetry subcommand |

See [docs/telemetry.md](telemetry.md) for the full CLI reference including per-subcommand flags.

### `sase logs`

| Flag        | Values | Default    | Description                                                     |
| ----------- | ------ | ---------- | --------------------------------------------------------------- |
| `daterange` | string | (required) | Date range to collect (e.g., `-7d`, `260318`, `260315..260318`) |

Supported date range formats:

- **Absolute**: `YYmmdd` or `YYmmddHHMMSS`
- **Relative**: `-Nd` (days ago), `-Nh` (hours ago), `-Nm` (minutes ago), `0d` (today)
- **Ranges**: `START..END` (e.g., `-7d..0d`); single point means "from that point to now"

The run and event inputs at `~/.sase/logs/runs.jsonl` and `events.jsonl` rotate independently before appending a record
would make a non-empty file exceed 2 MiB. Rotation keeps one `.1` generation and replaces an older backup; set
`SASE_RUN_LOG_MAX_BYTES` to another byte limit, or `0` for no size rotation. The current `sase logs` collector reads
only the active `.jsonl` files and skips malformed lines there, so copy the matching `.1` files separately when a
support bundle must include records from the previous generation.

### `sase editor`

`sase editor` exposes JSON-over-stdin helper operations for editor integrations. It is intentionally a fixed-operation
bridge rather than a generic shell or filesystem API.

| Form                                         | Input                | Description                                                                                                      |
| -------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `sase editor helper-bridge agent-catalog`    | JSON object on stdin | Return active/recent agents and derived family, clan, and tribe prompt targets.                                  |
| `sase editor helper-bridge xprompt-catalog`  | JSON object on stdin | Return the structured xprompt catalog; accepts the same schema as the mobile `xprompt-catalog` helper operation. |
| `sase editor helper-bridge snippet-catalog`  | JSON object on stdin | Return the composed ACE snippet registry used by `sase lsp` and editor completion clients.                       |
| `sase editor helper-bridge vcs-repo-catalog` | JSON object on stdin | Return repository completion candidates for a VCS workflow and namespace.                                        |

The `agent-catalog` request is just `{"schema_version":1}`; it has no project filter and reads the cross-project agent
snapshot. Ordinary agent rows are de-duplicated by name and include `status` and `project`. When group metadata is
available, additive family, clan, and `@tribe` rows include `kind`, `member_count`, and display-ready `detail`; clan
rows also include aggregate `status`. The structured xprompt catalog includes insertion metadata (`insertion`,
`reference_prefix`, `kind`), typed argument metadata, display/source fields, and `definition_path` when SASE can resolve
a real file to jump to.

The snippet catalog uses the same source ordering as ACE: xprompts marked with `snippet` front matter plus user-defined
`ace.snippets`, with `ace.snippets` winning on trigger collisions.

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

Create a durable command-backed gate from a schema-version 3 JSON specification, or wait mechanically for a gate's
terminal result.

| Form               | Flags                                               | Description                                               |
| ------------------ | --------------------------------------------------- | --------------------------------------------------------- |
| `sase gate create` | `-s/--sender`, `-t/--tag`                           | Create a durable gate from a JSON specification on stdin  |
| `sase gate wait`   | `-i/--id`, `-j/--json`, `-k/--kind`, `-t/--timeout` | Wait for a gate; exits 0 answered, 3 cancelled, 4 timeout |

Gate creation accepts one option `query`, a required complete `primary_branch`, an `options` list with configurable
labels, icons, default selections, and feedback modes, plus optional `groups` metadata for AND-branch submit controls.
It returns a stable JSON descriptor with the request identity, owned paths, continuation/auto state, and hashes.
`sase gate wait -j` emits `status`, `selected_option_ids`, `feedback`, and `response_path`; a CLI timeout can shorten
but not extend the request timeout.

### `sase lsp`

Starts the xprompt language server over stdio for editor integrations. `SASE_XPROMPT_LSP_CMD` can override the server
command during development. Without that override, `sase lsp` uses the current Python environment's
`bin/sase-xprompt-lsp`, then `sase-xprompt-lsp` from `PATH`, then the newer debug/release binary from a sibling
`../sase-core` checkout, then falls back to `cargo run` from that sibling checkout when Cargo is available. Full
editable-install SASE updates reinstall the server into the uv-tool venv when pulled `sase-core` commits change.

| Flag              | Values | Default | Description                            |
| ----------------- | ------ | ------- | -------------------------------------- |
| `-V`, `--version` | flag   | -       | Print the xprompt LSP version and exit |

### `sase path`

| Flag   | Values                                                                           | Default    | Description         |
| ------ | -------------------------------------------------------------------------------- | ---------- | ------------------- |
| `name` | `xprompts-dir`, `xprompts-schema`, `xprompts-collection-schema`, `config-schema` | (required) | Which path to print |

### `sase notify`

With no subcommand, `sase notify` defaults to the compact `sase notify list` view. Use `sase notify list` for JSON,
limit, query, unread, dismissed, or the clearest sender/tag filtering form. Use `sase notify create` to write a raw,
non-privileged notification from stdin JSON. Use `sase gate create` and `sase gate wait` for command-backed gates.

| Form                 | Flags                                                                                         | Description                                                 |
| -------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `sase notify`        | `-s/--sender`, `-t/--tag`                                                                     | Shortcut for `sase notify list` with default compact output |
| `sase notify create` | `-s/--sender`, `-t/--tag`                                                                     | Create a raw notification from stdin JSON                   |
| `sase notify list`   | `-j/--json`, `-l/--limit`, `-q/--query`, `-t/--tag`, `-s/--sender`, `-u/--unread`, `-a/--all` | List recent notifications; `-j` emits the stable JSON shape |
| `sase notify show`   | `-i/--id`, `-f/--format` (`markdown` or `json`)                                               | Show one notification by id; defaults to markdown           |

Raw creation accepts JSON `icon`, `tags`, and `silent` fields plus repeatable `-t/--tag`; icons must be one emoji or
display glyph, and CLI tags are appended to JSON tags, then normalized and deduplicated. Raw creation cannot create a
registered privileged gate action. The query form, `sase notify list -q`, also matches tags, and
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

`sase plan list` prints a Rich dashboard by default and emits a stable JSON projection with `summary`, `proposed`,
`approved`, and `rejected` keys when `-j/--json` is set. Repeat `-s/--status` with `approved`, `proposed`, or `rejected`
to render or serialize only those sections; unrequested JSON section keys are omitted, while summary counts continue to
describe the full collected view. `-n/--limit` controls the maximum rows in each Approved and Rejected history section
(default `10`, with `0` meaning unlimited). Proposed rows are always shown in full. `-t/--tier` composes with both
filters. The JSON summary includes `status_filter`, `tier_filter`, and a non-default `limit` when applicable, plus
`approved_scan_truncated` if a finite artifact scan may have omitted older approvals.

Use the Proposed row's `id_prefix` as the selector for `sase plan approve` or `sase plan reject`; omitting the selector
is valid only when exactly one pending proposal exists. The Rejected rows are inferred from archived proposal files that
are not represented by current proposed or approved state, so they are useful for history but are not actionable
selectors. Omitting `--kind` uses the plan's authored tier; explicit choices override it and tale/epic targets are
validated before the proposal is consumed. Approval kind `approve` runs the coder without asking the runner to commit an
SDD plan, `tale` commits the plan as an SDD tale and then runs the coder, `epic` commits the matching SDD tier and
launches the bead follow-up, and `commit` records the approved plan in SDD without launching a coder. The `-m/--model`
flag applies to the follow-up agent; `-p/--prompt` adds extra coder instructions only for the `approve` and `tale`
paths. `sase plan reject` writes the rejection response first, then attempts the same durable cleanup path as TUI
no-feedback rejection when the matching planner row is still discoverable.

`sase plan search [query]` scans plans in the resolved SDD store (the `repo` source) and the machine-local
`~/.sase/plans/` archive. The query is a literal case-insensitive substring; omit it to browse and filter. `--format`
accepts `compact`, `full`, `json`, or `markdown`; `--kind` is repeatable and filters SDD-store plans to `tale`, `epic`,
`research`; `--status` is repeatable and filters frontmatter status to `wip` or `done`; `--source` selects `all`,
`repo`, or `local`; `--sort` selects `relevance`, `recent`, or `title` (defaulting to relevance with a query and recent
without one); `--since`/`--until` accept `YYYY-MM-DD`, `YYYY-MM`, `YYYYMM`, or relative durations such as `14d`; and
`--limit 0` prints all matches.

`sase plan validate <plan_file>` infers the validation schema from the authored `tier`; it no longer accepts
`-t/--tier`. `--explain` prints tier-specific authoring guidance before human results or adds it to the JSON envelope,
while `--quiet` suppresses only the successful human summary. See
[Plan Frontmatter Schema and Validation](sdd.md#plan-frontmatter-schema-and-validation) for diagnostics and exit codes.

### `sase artifact`

`sase artifact create` is intended for code agents running with `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR` set. It moves a
generated file into persistent SASE artifact storage and associates it with the current agent so the Agents tab can open
it with `A`, even after the agent has been dismissed and revived.

| Form                   | Flags                                  | Description                                       |
| ---------------------- | -------------------------------------- | ------------------------------------------------- |
| `sase artifact create` | `-p/--path`, `-n/--label`, `-k/--kind` | Store one explicit artifact for the current agent |

### `sase questions`

| Flag             | Values | Default    | Description                             |
| ---------------- | ------ | ---------- | --------------------------------------- |
| `questions_json` | string | (required) | JSON string containing questions to ask |

### `sase agent`

`sase agent` provides cross-project visibility into running agents. Subcommands:

| Subcommand  | Flags                                                                                                                     | Description                                                                                                                                                                                                                                                                                                                                                                     |
| ----------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list`      | `-a/--all`, `-j/--json`, `-p/--project`                                                                                   | List running agents. `-a` includes DONE/FAILED agents (capped at 50 per project). `-j` emits a JSON array with a stable schema. `-p` limits output to a single project.                                                                                                                                                                                                         |
| `show`      | `-n/--name`                                                                                                               | Render a full detail panel (prompt, reply, metadata) for a single agent by name.                                                                                                                                                                                                                                                                                                |
| `kill`      | `-n/--name`                                                                                                               | SIGTERM a running agent by name.                                                                                                                                                                                                                                                                                                                                                |
| `tribe`     | `set` / `unset` / `list`                                                                                                  | Manage the user-defined tribe on an agent (used by the Agents tab tribe side panels). `tribe set -n <agent> -t <tribe>` replaces any prior tribe; `tribe unset -n <agent>` clears it; `tribe list [-n <agent>]` prints tribes as JSON (filtered when given).                                                                                                                    |
| `archive`   | `rebuild-index` / `verify`                                                                                                | Maintain the dismissed-agent bundle summary index under `~/.sase/dismissed_bundles/`. `verify` exits non-zero if rows are stale or missing.                                                                                                                                                                                                                                     |
| `artifacts` | `layout status` / `migrate` / `verify` / `rollback`, `-P/--project`, `-p/--projects-root`, `-i/--index-path`, `-j/--json` | Inspect and migrate the physical `ace-run` artifact directory layout. `status` reports flat and sharded directory counts, `migrate` moves flat timestamp directories into day shards, `verify` checks current or manifest-backed state, and `rollback` reverses a manifest-backed migration.                                                                                    |
| `index`     | `status` / `rebuild` / `verify` / `gc`, `-i/--index-path`, `-p/--projects-root`, `-j/--json`                              | Maintain the persistent agent artifact index. Defaults are `~/.sase/agent_artifact_index.sqlite` and `~/.sase/projects`; `status` performs a lightweight visible-inbox check without scanning source artifacts, `verify` exits non-zero when the index diverges from source artifacts, and `gc` rebuilds the index from source artifacts and replaces the dismissed projection. |
| `names`     | `migrate-auto`, `-f/--force`, `-j/--json`                                                                                 | Maintain the permanent agent-name registry. `migrate-auto` runs the historical generated-name namespace migration; `--force` reruns it after the completion marker exists and `--json` emits a machine-readable summary.                                                                                                                                                        |

### `sase chat`

`sase chat` discovers and inspects saved agent chat transcripts. With no subcommand, it defaults to `sase chat list`.
Subcommands:

| Subcommand | Flags                                                     | Description                                                                                              |
| ---------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `list`     | `-j/--json`, `-l/--limit`, `-q/--query`                   | List recent transcripts. `-j` emits the stable JSON shape consumed by the `/sase_chats` skill.           |
| `show`     | `-n/--agent`, `-p/--path`, `-b/--basename`, `-f/--format` | Show one transcript by agent name, path, or basename. `--format` accepts `raw`, `resume`, or `response`. |

## Directory Sharding

Older SASE layouts wrote many agent artifacts (chat logs, notifications, workflow state, etc.) directly under
`~/.sase/<kind>/`. After a few months of heavy use those directories can accumulate tens of thousands of files, which
slows down filesystem walks and makes `ls`-style inspection painful.

Current high-volume writers use a `YYYYMM/` shard inside each managed artifact directory (keyed by the current month).
Readers transparently merge sharded and non-sharded files, so the layout is backwards-compatible - existing unsharded
files at the top level are still found and the layout is fully read/write compatible across both forms.

Prompt history uses its own monthly JSON shard directory, `~/.sase/prompt_history/YYMM.json`, because each shard stores
a bounded JSON list rather than one file per prompt. Entries whose last-used timestamp cannot be parsed are kept in
`unknown.json`. The legacy `~/.sase/prompt_history.json` file is migrated into that directory on first read or write
when the shard directory does not already exist, then preserved as a `legacy-imported-<timestamp>.json.bak` backup.

ACE run artifacts also support a day-sharded physical layout under each project's artifact root. Use
`sase agent artifacts layout status` to inspect flat versus sharded `ace-run` directories, `migrate` to move legacy flat
timestamp directories into shards while writing index aliases, `verify` to check the current or manifest-backed state,
and `rollback -m <manifest>` to reverse a migration when needed. Migration skips live artifact directories with
`running.json`, refuses existing targets, and can be previewed with `--dry-run`.
