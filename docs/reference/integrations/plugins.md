---
title: Plugins
description: Look up plugin groups, the catalog, installation, and disable switches.
---

# Plugins

This page describes plugin groups, the catalog, installation, and disable switches.

Sase uses Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/) to
discover optional functionality installed in the same Python environment as `sase`.
Runtime providers use [pluggy](https://pluggy.readthedocs.io/) hooks; resource plugins
expose package data such as macro files and `default_config.yml`.

The core `sase` package provides the plugin infrastructure, the built-in LLM providers,
and local git/directory workspace support. Extra packages add hosted VCS workflows,
internal workflows, or integrations without changing the core package.

## Plugin Groups

Sase defines thirteen entry point groups:

| Entry Point Group      | Entry Point Value | Purpose                                             | Example Plugin                  |
| ---------------------- | ----------------- | --------------------------------------------------- | ------------------------------- |
| `sase_artifact_refs`   | Provider class    | Declarative document artifact-reference providers   | third-party document provider   |
| `sase_dispatch`        | Provider class    | Remote dispatch machine-access providers            | built-in or third-party         |
| `sase_file_hooks`      | Provider class    | Reusable declarative file-hook templates            | third-party integration         |
| `sase_finalizers`      | Provider class    | Turn-finalizer providers (metadata-only inventory)  | third-party finalizer packages  |
| `sase_task_types`      | Hook class        | Declarative task-type specs for typed task beads    | `sase-github` (`github`)        |
| `sase_vcs`             | Provider class    | VCS provider plugins (git, hg, etc.)                | `sase-github`                   |
| `sase_workspace`       | Provider class    | Workspace provider plugins (ref resolution, submit) | `sase-github`                   |
| `sase_llm`             | Provider class    | LLM provider plugins                                | built-in or third-party         |
| `sase_macros`          | Package module    | Macro templates and workflows                       | `my_sase_plugin`                |
| `sase_config`          | Package module    | Default configuration (`default_config.yml`)        | `sase-github`, `my_sase_plugin` |
| `sase_plugin_manifest` | Package module    | Plugin metadata resource used by diagnostics        | third-party plugin packages     |
| `sase_commands`        | Command module    | Top-level `sase <name>` commands                    | `sase-listen` (`listen`)        |
| `sase_pager_history`   | Provider factory  | Section-history providers for the pager             | third-party memory provider     |

Provider-class entry points resolve to a class that is instantiated and registered with
pluggy. Package-module entry points resolve to a module whose package resources are read
by Sase. Third-party `sase_dispatch` providers are inventoried from entry point metadata
only: their provider ref is `<normalized-distribution>@<entry-point-name>`, and provider
code is imported later in an isolated helper subprocess only for the selected discovery
or connection-plan operation.

An `sase_macros` package may provide ordinary templates in `macros/`.

## Available Plugin Packages

| Package                   | Description                                                                                                 | Entry Points                                                                                                                                                          |
| ------------------------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sase` (core)             | Bare-git VCS/workspaces, built-in LLMs, and the plan reference provider                                     | `sase_vcs: bare_git`, `sase_workspace: bare_git`, `sase_artifact_refs: builtin`, `sase_dispatch: builtin`, `sase_llm: agy, claude, codex, grok, muse, opencode, qwen` |
| `sase-github`             | GitHub VCS and workspace support, including GitHub CLI (`gh`) PR operations                                 | `sase_vcs: github`, `sase_workspace: github`, `sase_config: sase_github`, `sase_macros: sase_github`, `sase_task_types: github`                                       |
| `sase-telegram`           | Telegram integration via job scripts (`sase_job_tg_outbound`, `sase_job_tg_inbound`)                        | CLI scripts (not pluggy entry points)                                                                                                                                 |
| `sase-nvim`               | Neovim integration, including project spec syntax and prompt helpers                                        | standalone Neovim plugin files (not Python entry points)                                                                                                              |
| `sase-listen`             | Markdown-to-MP3 audio editions; ships `sase listen`, which behaves like the standalone `sase-listen` binary | `sase_commands: listen`                                                                                                                                               |
| `sase-research-artifacts` | Research audio macros, artifact references, and file-hook templates                                         | `sase_macros: sase_research_artifacts`, `sase_artifact_refs: research`, `sase_file_hooks: research-highlights`, `sase_config: sase_research_artifacts`                |

`sase-nvim` carries no `sase--plugin` catalog topic, so it never appears in the catalog
listing; install it from its repository instead of `sase plugin install`.

## Installation

```bash
# Core SASE (installs the sase tool)
uv tool install "sase>=0.18"

# Core SASE + GitHub PR support in one command
uv tool install "sase>=0.18" --with sase-github
```

The recommended way to add a plugin to an existing managed install is the
[**Updates** tab of the SASE Admin Center](../tui/admin-center.md#updates-tab): press
`#` inside `sase tui`, switch to the **Updates** tab, highlight the plugin, and press
`i` to install. To install several plugins from sase's TUI, mark installable rows with
`I` / `Space`, then press `i` once; sase's TUI previews one combined `uv` operation
before changing the environment. A single-plugin preview offers both an explicit git
variant and the default-source variant; when public PyPI definitively lacks the
distribution the default variant already resolves to git automatically, so no redundant
duplicate variant is offered. Otherwise press `g` in the confirmation modal to switch to
the git variant before confirming. Install confirmations show the exact `uv` command and
selected source; a batch preview also lists every included or skipped plugin, each with
its own resolved source. Use `Ctrl+D` / `Ctrl+U` when a preview overflows. Install
previews do not fetch incoming commit subjects—the repository-grouped commit pane is
available on update confirmations when sase's TUI has an installed commit range to
compare. The equivalent CLI for one plugin is `sase plugin install github`.

## Plugin Catalog (`sase plugin list` / `sase plugin show`)

`sase plugin` is a discovery surface for the whole SASE plugin ecosystem — not just what
is installed locally. It treats the GitHub `sase--plugin` repository topic as the
canonical registry, so the catalog always reflects reality: a repo gains or loses a
listing purely by gaining or losing the topic, with no code change.

> The same browse / install / update / uninstall operations are available interactively
> in the
> [**Updates** tab of the `sase tui` SASE Admin Center modal](../tui/admin-center.md#updates-tab)
> (`#`), which reuses this catalog and these renderers for CLI parity and adds a SASE
> Core panel for `sase update`.

```bash
# Catalog of every known plugin (built-in and community)
sase plugin list
sase plugin list -v          # add stars, last-updated, and the full topic list
sase plugin list -j          # stable machine-readable JSON
sase plugin list -o          # use cached catalog/latest-version data only
sase plugin list -A          # also probe latest for uninstalled plugins

# Detailed view of a single plugin
sase plugin show github
sase plugin show sase-github # short name, repo, or owner/repo all match
sase plugin show github -j   # stable machine-readable JSON
sase plugin show github -o   # use caches only; do not check GitHub/PyPI

# Bypass caches and refetch from GitHub/PyPI
sase plugin list -r
sase plugin show github -r
```

- `sase plugin` with no subcommand defaults to `sase plugin list`.
- **`list`** renders two clearly-labeled sections — **built-in** (published under the
  official `sase-org` org) first, then **community** (third-party, shown with a warning)
  — and marks installed versions, latest available versions, and updates. Status uses a
  glyph plus a legend (`●` installed, `○` available, `↑` update available) so the output
  is legible with no color. An installed index plugin behind PyPI renders as
  `vOLD → vNEW` with a `↑` and a footer hint to run `sase plugin update --all`. An
  editable checkout renders its current dev version and, when its upstream tracking
  branch is ahead, `current → latest` with a dim `dev` tag.
- **`show`** renders a detail panel: description, installed status and contributed entry
  points, a **Commands** row for installed declarations or a known upstream command
  preview, latest available version, repository, homepage, topics, stars, last update,
  and license. Community plugins lead with a prominent third-party warning. An unknown
  `<plugin_name>` prints ranked `did you mean…?` suggestions and exits non-zero. See
  [Where a command shows up](plugins-commands.md#where-a-command-shows-up) for the chip
  and preview rules.
- Built-in vs. community is decided by the owning org: `sase-org` (case-insensitive) is
  built-in; anything else is community. Archived repos are surfaced with an archived
  marker rather than hidden.
- For a managed `uv tool` install, every package explicitly injected in `sase`'s
  `uv-receipt.toml` is authoritative installed membership for the catalog and Admin
  Center. Its version comes from live distribution metadata. SASE entry points and
  recognized console-script / `sase-*` distribution naming remain the discovery fallback
  for unmanaged environments and the source of contributed entry-point-group metadata. A
  catalogued package absent from both paths (for example a Neovim-only integration)
  correctly shows as not installed.
- Latest available versions for index installs come from PyPI's package JSON
  (`info.version`), which matches what `sase plugin update` would actually install.
  `sase plugin list` probes latest versions for installed plugins only (update markers
  and counts still match); pass `-A|--all-latest` to restore a full-catalog probe.
  `sase plugin show` always fetches latest for the requested plugin. The Updates >
  Plugins highlighted row fetches uninstalled latest lazily through the detail
  debouncer. Editable checkouts derive their latest dev version from the upstream
  tracking ref after a best-effort fetch, carry a lowercase `dev` source marker, and
  base update availability on git ancestry rather than PEP 440 string comparison. A
  local checkout can surface an `↑ dev update available` hint that recommends
  `sase update` rather than `sase plugin update`. Direct-git installs are labeled as
  `git` and are not compared against PyPI, so an immutable VCS install never gets a
  false update prompt.
- Blocked editable checkout states are shown as a dim reason instead of an update arrow:
  `dev · local changes`, `dev · diverged`, `dev · detached HEAD`, `dev · no upstream`,
  `dev · offline`, or an unavailable/fetch-failed reason. Fix the checkout manually,
  then rerun `sase plugin list` or refresh the Admin Center Updates tab.
- `sase plugin list -j` emits `schema_version: 3`. Each entry includes `install_type`,
  `current_version`, an `installed` object with `entry_point_groups` and the mounted
  `commands` the plugin provides, and a `latest` object with `version`,
  `update_available`, `state`, and `reason` so automation can distinguish index updates
  from editable-checkout dev states without parsing table text.

### Catalog fetching and cache

The catalog and latest-version probes are cached separately, so repeat runs are instant
and bounded:

- The data comes from explicit `gh api` pages of
  `search/repositories?q=topic:sase--plugin&per_page=100`, which returns topics, owner,
  description, stars, license, and timestamps inline — no per-repo follow-up lookups.
  Each page has its own timeout. When GitHub's 1000-result search cap would truncate the
  catalog, the fetch shards the topic query on stable `stars:` (then `created:`) ranges
  and unions the results. Truncation or `incomplete_results` surface as catalog warnings
  rather than silent drops.
- The cache lives at `~/.sase/plugins/catalog_cache.json` and is written atomically. The
  first run fetches and writes it; later runs read it and only touch the network when
  `-r|--refresh` is passed. A cache older than the soft staleness threshold is still
  used, but the footer warns more loudly.
- Index latest-version results live at `~/.sase/plugins/latest_cache.json` with a short
  TTL. Cache misses are fetched from PyPI concurrently with short timeouts; any timeout,
  parse failure, or package missing from PyPI renders as "latest unknown" and the
  command still exits successfully. Editable checkout probes are not written to this
  PyPI cache.
- `-o|--offline` makes `list` and `show` use caches only and make zero GitHub or PyPI
  calls. If the catalog cache is missing or was populated from a different GitHub topic
  query, offline mode fails with an actionable message; missing latest-version cache
  entries render as unknown. Editable checkouts do not fetch in offline mode; they use
  already-known git metadata when available or render `dev · offline`.
- If `gh` runs but the call fails (network error, non-zero exit, or an
  unauthenticated/auth error), SASE falls back to a compatible existing cache with a
  loud "stale cached data" warning, or — when there is no compatible cache — re-raises
  the error.
- A missing `gh` (not on `PATH`) is always a hard error, even when a cache exists: SASE
  never silently serves stale data while the CLI it needs is absent, and instead prints
  the same actionable `gh` install / `gh auth login` hint that `sase doctor` uses. This
  mirrors `src/sase/doctor/checks_plugins.py`.

### Related plugin diagnostics

The catalog answers "what exists and what do I have installed." For deeper install and
configuration diagnostics, use the commands that already own each concern:

```bash
# Installed runtime and plugin packages
sase version -v
sase version -j

# Resource entry-point loading and GitHub provider prerequisites
sase doctor -C plugins.resources
sase doctor -C plugins.github

# Configured jobs, discoverable scripts, and Telegram job setup
sase axe job list --available
sase axe job doctor
sase doctor -C axe.jobs
```

- `sase version -v` / `-j` inventories the installed `sase` host, the `sase-core-rs`
  core, and SASE plugin packages discovered through entry points, console scripts, or
  `sase-*` distribution names.
- `sase doctor -C plugins.resources` reports resource entry-point load failures and any
  resource-plugin disable environment variables (`ERROR` on a load failure, `WARN` when
  loading is disabled). `sase doctor -C plugins.github` probes the GitHub CLI and
  `gh auth status` when a GitHub provider plugin is installed.
- `sase axe job list` shows configured jobs with status; add `--available` to include
  discoverable executable job scripts. `sase axe job doctor` checks for missing
  configured script jobs (`ERROR`), unconfigured available scripts (`WARN`), and
  Telegram job `pass`/environment prerequisites (`WARN`). It also reports which Telegram
  job entrypoints are in use: the canonical `sase_job_tg_inbound` and
  `sase_job_tg_outbound` scripts are `OK`, while an install or config that only has the
  compatibility `sase_chop_tg_inbound` / `sase_chop_tg_outbound` names still work but
  get a `WARN` to upgrade `sase-telegram` and switch the configured job scripts. The
  same job diagnostics are mirrored by `sase doctor -C axe.jobs`.

## Disabling Plugins

Third-party plugin resources and declarative artifact-provider entry points can be
disabled via environment variables:

See the generated
[environment-variable reference](../environment-variables.md#plugin-system) for the
disable switches and their effects.

Any non-empty value enables the disable. The VCS, workspace, and LLM provider registries
load their provider entry points directly and do not consult these switches. These
switches also do not remove the core built-in `plan` reference provider.

## Related

- [Command plugins](plugins-commands.md) — mounted `sase <name>` commands.
- [Installing and updating plugins](plugins-update.md) — `sase update` and plugin
  install.
- [Plugin API](../../contribute/plugin-api.md) — writing and discovering plugins.
- [Integrations](index.md) — other integration pages.
