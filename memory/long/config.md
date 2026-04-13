---
keywords: [config, configuration, sase.yml, schema, merge, default_config, overlay, plugin config, local config]
---

# Configuration System

## 5-Layer Merge Chain

Config is built by merging five layers in order (later layers override earlier ones):

1. **Default** (`default_config.yml` bundled in package)
2. **Plugin** (`default_config.yml` from each `sase_config` entry-point plugin)
3. **User** (`~/.config/sase/sase.yml`)
4. **Overlays** (`~/.config/sase/sase_*.yml`, sorted alphabetically)
5. **Local** (`./sase.yml` in the current working directory)

All merging happens in `config/core.py:load_merged_config()`.

## Dual List Merge Strategies

The user config layer (layer 3) merges lists with the **`replace`** strategy -- it wipes default/plugin lists entirely.
All other layers (default, plugin, overlays, local) use the **`concatenate`** strategy -- they extend existing lists.

This is the #1 gotcha. Do not assume uniform list merge behavior across layers. Example: a user's `sase.yml` with
`mentor_profiles: [x]` replaces all default profiles, but a local `./sase.yml` with `mentor_profiles: [y]` adds `y` to
whatever the user already has.

The merge logic lives in `config/core.py:_deep_merge()`.

## Schema File: Informational Only

`config/sase.schema.json` provides IDE autocompletion and validation. It is **NOT** enforced at runtime -- no code
validates config against it.

**IMPORTANT:** The schema file **MUST** be updated whenever config fields are added, removed, or modified so that IDE
validation stays accurate. Forgetting this is a common mistake.

## Local Config Disabled for TUI

`main/ace_handler.py` calls `set_include_local_config(False)` before starting the TUI. This prevents repo-level
`sase.yml` from affecting the TUI. Agent runs are separate processes and keep local config enabled.

If you modify TUI startup code, you must preserve this call. Moving or removing it will cause repo-level config to leak
into the TUI.

## Per-Subsystem Validation

There is no centralized schema enforcement at runtime. Each subsystem (mentor profiles, metahooks, etc.) extracts its
own section from the merged config dict and validates with custom logic. Invalid config in one subsystem doesn't break
others -- errors are logged as warnings and the invalid entry is skipped.

When adding a new config section, you must add validation in the consuming subsystem. There is no framework that does
this for you.

## Mentor Profile Auto-Scoping

Profiles defined in local `./sase.yml` are automatically tagged with the detected project name if no explicit `projects`
list is provided. This means a local profile applies only to ChangeSpecs in that project without manual configuration.

Setting `projects: []` (explicit empty list) disables auto-scoping -- the profile matches no ChangeSpec. This is
intentional: explicit values always win over auto-detection.

The logic is in `config/mentor.py:_parse_single_profile()`.

## XPrompt Alias Resolution Order

Aliases (`xprompt_aliases` in config) are raw string substitutions that run **before** any other xprompt processing.
They can introduce syntax needed by later processors (e.g., `#gh_sase` -> `#gh:sase` for directory-switching).

Because aliases run first, an alias target can contain any valid xprompt syntax and it will be processed normally.
Aliases that depend on other aliases are not supported -- only one pass is made.

The resolution happens in `xprompt/processor.py:resolve_xprompt_aliases()`, called as the first step of
`process_xprompt_references()`.

## Environment Variables That Affect Config

Only three `SASE_*` env vars affect config loading:

- `SASE_WORKSPACE_ROOT` -- overrides `vcs_provider.workspace_root`
- `SASE_VCS_PROVIDER` -- set from `--vcs-provider` CLI flag, selects the VCS provider
- `SASE_DISABLE_PLUGINS` -- prevents plugin configs from loading

All other `SASE_*` env vars (e.g., `SASE_AGENT_*`, `SASE_PLAN`, `SASE_ARTIFACTS_DIR`) are for agent workflow
communication between processes. They do not affect config loading.
