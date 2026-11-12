---
title: "Configuration files and merging"
description:
  "Configuration file locations, owner identity, merge precedence, and storage layout."
---

# Configuration files and merging

Configuration file locations, owner identity, merge precedence, and storage layout.

This document is the central reference for all sase configuration: config files, YAML
sections, environment variables, and CLI flags.

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
[layout compatibility window](../upgrading/content-layout.md#compatibility-and-collisions);
if both files exist, SASE reports a collision instead of merging them. sase's TUI
deliberately disables project-local config loading for its own process so opening
`sase tui` inside a repo does not inherit that repo's agent-run settings. See
[Deep-Merge System](#deep-merge-system) below.

## Project-Local Command Trust

Use `sase config trust status [PATH]` to inspect the command-bearing part of a project's
selected config. `PATH` can be a checkout or its selected `sase.yml`; it defaults to the
current checkout. Add `--json` for structured status. The command is read-only and does
not create the trust store.

Run `sase config trust allow [PATH]` to review the canonical projection and digest, then
type `allow` in the foreground terminal to record that review.
`sase config trust revoke [PATH]` removes the project's record after a separate `revoke`
confirmation. Both commands refuse to change trust from agents and monitors, and neither
accepts a non-interactive confirmation.

The record is machine-local at `$SASE_HOME/local_config_trust/records.json` (normally
`~/.sase/local_config_trust/records.json`). Registered projects use the host project
record and canonical primary checkout as their identity; a managed checkout shares that
identity only when the host workspace registry contains it. An unregistered or ambiguous
checkout gets checkout-scoped trust. Project display names, remotes, and checkout
markers alone do not grant another checkout's record.

The digest covers the normalized local `commit_hooks`, file-hook entries, and
command-bearing macro/workflow definitions, plus the selected logical config location
(`sase/sase.yml` or the root `sase.yml` fallback). YAML comments, whitespace, and
mapping order do not change it. Edits to ordinary local settings do not change this
digest. Referenced scripts, binaries, and standalone macro files are not hashed; review
changes to those files separately.

Enforcement is active under the `local_config_command_trust` sunset flag (default on).
When enabled, unacknowledged local `commit_hooks` are omitted before merging, local
file-hook entries are omitted from the independent file-hook loader, and executable
local config macros are omitted from the ordinary and namespaced macro loaders.
Prompt-only local macros still load. Before/after commit hooks, explicit-project rebase
gates, file-hook execution, and bash/python workflow steps re-resolve trust
synchronously. User, overlay, and non-command local values still merge; blocked rebase
hooks report skipped, never passed. An explicit request for a blocked local macro raises
a trust error rather than an unknown-macro miss or a lower-priority namesake. A warning
names the config path and `sase config trust allow PATH`. With the flag off, local
commands run in compatibility mode, visibly marked in `status`, and no trust records are
created.

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
discovers machine overlays by nested `id.machine_name` first, with top-level
`machine_name` accepted only as migration input. See
[Configuration migration notes](../upgrading/configuration.md#machine-identity). Foreign
machine overlays do not contribute runtime settings, Config inventory layers, or
config-defined macros. Ordinary overlays still participate.

Only the selected raw machine overlay can own provenance. An `id` value in bundled
defaults, plugins, `~/.config/sase/sase.yml`, ordinary overlays, or project-local config
is ignored by runtime merging and cannot change the owner for one project. The selected
raw `id` object remains visible in merged configuration for inspection.

The initializer lists declared machines, suggests a schema-safe hostname when a machine
must be chosen, and requires an explicit valid username unless exactly one existing
username is clearly confirmed for reuse. It never chooses among conflicting usernames.
Creation and migration minimally set `id.username` and `id.machine_name` in the same
overlay, remove its top-level key, preserve unrelated YAML/comments, and then write the
selector. With `use_chezmoi: true`, the overlay edit is made in the chezmoi source tree.
Direct `sase config init` uses the normal commit/push/apply deployment; bare `sase init`
combines the edit with deferred chezmoi deployment. The initializer also adds a hostname
guard to the chezmoi source `.chezmoiignore`, staging it in the same commit as the new
overlay:

```text
{{ if ne .chezmoi.hostname "<chezmoi-hostname>" }}
.config/sase/sase_<machine>.yml
{{ end }}
```

The guard uses chezmoi's hostname, which may differ from the SASE machine name, so the
overlay is applied only on the machine where it was initialized. If `.chezmoiignore`
already contains an entry for that overlay, the existing guard is left unchanged. The
same hostname guards are required when a machine overlay declares `memory.h1_title` so
`sase memory init` can emit a per-hostname H1 in the chezmoi `AGENTS.md.tmpl` source.

Prompting requires a TTY. `sase config init --check`, bare `sase init --check`, and
`sase doctor` report missing usernames, migration input, invalid values, selector
mismatches, duplicate overlays, and identity conflicts without writing. Config
inspection, help, initialization, doctor, and historical run records remain available
while identity is incomplete. Actual agent process creation, new commit provenance, and
agents-sidecar mutations require both identity fields and fail with the actionable
`sase config init` instruction.

There is intentionally no bundled identity default.

Machine hoods also provide stable ownership for the hidden agents sidecar. See
[Agent Hood Synchronization](../agents/index.md) for privacy controls, package contents,
import/publication commands, and recovery.

## Deep-Merge System

Sase builds a merged configuration through five layers, each merged on top of the
previous:

1. **`default_config.yml`** — bundled package defaults
2. **Plugin `default_config.yml` files** — from installed plugin packages (via
   `sase_config` entry points), sorted by entry-point name; lists concatenate
3. **`sase.yml`** — user config (`~/.config/sase/sase.yml`); lists **replace** defaults
   (not concatenate)
4. **Selected `sase_*.yml` overlays** — ordinary overlays plus only the machine overlay
   whose nested `id.machine_name` (or top-level compatibility fallback) matches
   `~/.sase/machine_name`, sorted alphabetically; lists **concatenate**
5. **Local `sase/sase.yml`** — project-level config at the detected project root (or the
   root `sase.yml` compatibility fallback); lists **concatenate** (highest priority)

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

The `axe` block is the one exception to plain dictionary merging: after the layers are
combined, SASE recomposes it from the same layer chain so that keyed routine and job
entries merge by identity and AXE compatibility aliases (see
[axe](scheduler-behavior.md#axe)) normalize to one effective shape.

Source: `src/sase/config/core.py`, `src/sase/config/loading.py`

## Directory Sharding

High-volume state writers use a `YYYYMM/` shard inside each managed artifact directory
(keyed by the current month). Readers merge sharded and unsharded files, so top-level
files remain visible and both layouts support reads and writes.

Prompt history and TUI artifact layout migration are described in
[Local state migration](../upgrading/local-state.md#history-and-artifact-layout-migration).

## Related

- [Configuration reference](index.md) — generated keys and defaults.
- [Configure the essentials](../../guides/configure-essentials.md) — common setup
  values.
