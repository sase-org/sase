# Plugin System

Sase uses Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/) to
discover optional functionality installed in the same Python environment as `sase`.
Runtime providers use [pluggy](https://pluggy.readthedocs.io/) hooks; resource plugins
expose package data such as xprompt files and `default_config.yml`.

The core `sase` package provides the plugin infrastructure, the built-in LLM providers,
and local git/directory workspace support. Extra packages add hosted VCS workflows,
internal workflows, or integrations without changing the core package.

## Plugin Groups

Sase defines eight entry point groups:

| Entry Point Group      | Entry Point Value | Purpose                                             | Example Plugin                  |
| ---------------------- | ----------------- | --------------------------------------------------- | ------------------------------- |
| `sase_artifact_refs`   | Provider class    | Declarative document artifact-reference providers   | third-party document provider   |
| `sase_file_hooks`      | Provider class    | Reusable declarative file-hook templates            | third-party integration         |
| `sase_vcs`             | Provider class    | VCS provider plugins (git, hg, etc.)                | `sase-github`                   |
| `sase_workspace`       | Provider class    | Workspace provider plugins (ref resolution, submit) | `sase-github`                   |
| `sase_llm`             | Provider class    | LLM provider plugins                                | built-in or third-party         |
| `sase_xprompts`        | Package module    | XPrompt templates and workflows                     | `my_sase_plugin`                |
| `sase_config`          | Package module    | Default configuration (`default_config.yml`)        | `sase-github`, `my_sase_plugin` |
| `sase_plugin_manifest` | Package module    | Plugin metadata resource used by diagnostics        | third-party plugin packages     |

Provider-class entry points resolve to a class that is instantiated and registered with
pluggy. Package-module entry points resolve to a module whose package resources are read
by Sase.

An `sase_xprompts` package may provide ordinary templates in `xprompts/`.

## Available Plugin Packages

| Package         | Description                                                                             | Entry Points                                                                                                                                |
| --------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `sase` (core)   | Bare-git VCS/workspaces, built-in LLMs, and the plan reference provider                 | `sase_vcs: bare_git`, `sase_workspace: bare_git`, `sase_artifact_refs: builtin`, `sase_llm: agy, claude, codex, grok, muse, opencode, qwen` |
| `sase-github`   | GitHub VCS and workspace support, including GitHub CLI (`gh`) PR operations             | `sase_vcs: github`, `sase_workspace: github`, `sase_config: sase_github`, `sase_xprompts: sase_github`                                      |
| `sase-telegram` | Telegram integration via chop scripts (`sase_chop_tg_outbound`, `sase_chop_tg_inbound`) | CLI scripts (not pluggy entry points)                                                                                                       |
| `sase-nvim`     | Neovim integration, including project spec syntax and prompt helpers                    | standalone Neovim plugin files (not Python entry points)                                                                                    |

## Installation

```bash
# Core SASE (installs the sase tool)
uv tool install sase

# Core SASE + GitHub PR support in one command
uv tool install sase --with sase-github
```

The recommended way to add a plugin to an existing managed install is the
[**Updates** tab of the SASE Admin Center](configuration.md#updates-tab): press `#`
inside `sase ace`, switch to the **Updates** tab, highlight the plugin, and press `i` to
install. To install several plugins from ACE, mark installable rows with `I` / `Space`,
then press `i` once; ACE previews one combined `uv` operation before changing the
environment. For a single-plugin install preview that offers both index and git sources,
press `g` in the confirmation modal to switch variants before confirming. Install
confirmations show the exact `uv` command and selected source; a batch preview also
lists every included or skipped plugin. Use `Ctrl+D` / `Ctrl+U` when a preview
overflows. Install previews do not fetch incoming commit subjects—the repository-grouped
commit pane is available on update confirmations when ACE has an installed commit range
to compare. The equivalent CLI for one plugin is `sase plugin install github`.

## Plugin Catalog (`sase plugin list` / `sase plugin show`)

`sase plugin` is a discovery surface for the whole SASE plugin ecosystem — not just what
is installed locally. It treats the GitHub `sase--plugin` repository topic as the
canonical registry, so the catalog always reflects reality: a repo gains or loses a
listing purely by gaining or losing the topic, with no code change.

> The same browse / install / update / uninstall operations are available interactively
> in the
> [**Updates** tab of the `sase ace` SASE Admin Center modal](configuration.md#updates-tab)
> (`#`), which reuses this catalog and these renderers for CLI parity and adds a SASE
> Core panel for `sase update`.

```bash
# Catalog of every known plugin (built-in and community)
sase plugin list
sase plugin list -v          # add stars, last-updated, and the full topic list
sase plugin list -j          # stable machine-readable JSON
sase plugin list -o          # use cached catalog/latest-version data only

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
  points, latest available version, repository, homepage, topics, stars, last update,
  and license. Community plugins lead with a prominent third-party warning. An unknown
  `<plugin_name>` prints ranked `did you mean…?` suggestions and exits non-zero.
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
  Editable checkouts derive their latest dev version from the upstream tracking ref
  after a best-effort fetch, carry a lowercase `dev` source marker, and base update
  availability on git ancestry rather than PEP 440 string comparison. A local checkout
  can surface an `↑ dev update available` hint that recommends `sase update` rather than
  `sase plugin update`. Direct-git installs are labeled as `git` and are not compared
  against PyPI, so an immutable VCS install never gets a false update prompt.
- Blocked editable checkout states are shown as a dim reason instead of an update arrow:
  `dev · local changes`, `dev · diverged`, `dev · detached HEAD`, `dev · no upstream`,
  `dev · offline`, or an unavailable/fetch-failed reason. Fix the checkout manually,
  then rerun `sase plugin list` or refresh the Admin Center Updates tab.
- `sase plugin list -j` emits `schema_version: 3`. Each entry includes `install_type`,
  `current_version`, and a `latest` object with `version`, `update_available`, `state`,
  and `reason` so automation can distinguish index updates from editable-checkout dev
  states without parsing table text.

### Catalog fetching and cache

The catalog and latest-version probes are cached separately, so repeat runs are instant
and bounded:

- The data comes from
  `gh api --paginate -X GET "search/repositories?q=topic:sase--plugin&per_page=100"`,
  which returns topics, owner, description, stars, license, and timestamps inline — no
  per-repo follow-up lookups.
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

# Configured chops, discoverable scripts, and Telegram chop setup
sase axe chop list --available
sase axe chop doctor
sase doctor -C axe.chops
```

- `sase version -v` / `-j` inventories the installed `sase` host, the `sase-core-rs`
  core, and SASE plugin packages discovered through entry points, console scripts, or
  `sase-*` distribution names.
- `sase doctor -C plugins.resources` reports resource entry-point load failures and any
  resource-plugin disable environment variables (`ERROR` on a load failure, `WARN` when
  loading is disabled). `sase doctor -C plugins.github` probes the GitHub CLI and
  `gh auth status` when a GitHub provider plugin is installed.
- `sase axe chop list` shows configured chops with status; add `--available` to include
  discoverable executable chop scripts. `sase axe chop doctor` checks for missing
  configured script chops (`ERROR`), unconfigured available scripts (`WARN`), and
  Telegram chop `pass`/environment prerequisites (`WARN`). The same chop diagnostics are
  mirrored by `sase doctor -C axe.chops`.

## Updating sase and plugins (`sase update`)

`sase update` updates `sase` **and every installed sase plugin together** from the
canonical uv-tool environment. For a managed install it delegates to
`uv tool upgrade sase`, re-resolving SASE core and injected plugins in one shot so they
move forward as a coherent set. Receipt-owned editable / dev components of the same uv
tool environment are detected from the receipt, updated from git, and reconciled so
Python entry points, dependencies, and compiled Rust artifacts match the checked-out
source (see [Dev / editable installs](#dev-editable-installs) below). Dev-update timing
baselines can be summarized from the local journal with `tools/dev_update_timings`.

```bash
sase update            # update sase + all plugins
sase update -n         # dry run: preview the uv or dev-update plan, change nothing
sase update -q         # quiet: print only a one-line summary
sase update -j         # stable machine-readable JSON
sase update -t dev     # switch the install to dev (editable) mode; see below
sase update -t pypi    # switch the install back to managed PyPI mode
```

Typical output highlights what changed, marks what was already current, and reminds you
to restart long-running agents:

```text
✓ sase           0.5.0 → 0.6.1
✓ sase-github    0.3.2 → 0.4.0
· sase-telegram  0.1.0   (already current)

Updated sase + 1 plugin in 4.2s · 1 already current
Axe restarted (pid 12345) to load the updated code.
```

- **Install method is required.** `sase update` only works when sase was installed with
  `uv tool install sase` (the canonical install path). When it is run from a pip/pipx
  install or from a dev checkout's virtualenv, it **fails fast with an actionable
  message** and a non-zero exit code instead of touching the environment. The check is
  strict: `uv` must be on `PATH`, the running interpreter's `sys.prefix` must resolve to
  `<uv tool dir>/sase`, and that directory must contain a `uv-receipt.toml`.
- **Managed installs** use `uv tool upgrade sase`, re-resolving sase core and all
  injected plugins in a single shot so they move forward as a coherent set rather than
  drifting out of sync.
- **Editable checkouts** update only when they are clean and strictly behind their
  upstream tracking branch. SASE fetches the upstream, fast-forwards the checkout,
  reconstructs the uv-tool install from the receipt for editable Python packages, and
  rebuilds `sase-core-rs` into the uv-tool venv when the Rust core checkout changed.
  Multiple packages in one git root are deduped.
- **Blocked editable states are non-destructive.** Dirty, diverged, detached-HEAD,
  no-upstream, offline, and fetch-failed checkouts are skipped with a reason. Commit or
  stash local changes, resolve divergence manually, check out a branch with an upstream,
  or rerun online; `sase update` never rebases, merges non-fast-forward, stashes, or
  discards local work.
- **Mixed installs** update editable packages through the dev path and managed packages
  through uv in one run, with one combined result. This includes the common contributor
  layout where `sase` and every plugin are editable but `sase-core-rs` remains a
  published wheel: the comprehensive update reconstructs the editable receipt and
  explicitly re-resolves the compatible core wheel without replacing or dropping those
  editable sources.
- **Restart behavior is automatic after real code changes.** In the CLI, SASE restarts
  axe when it is running so the daemon loads the new code. In the Admin Center Updates
  tab, SASE restarts ACE and axe through the same restart path as the `Q` restart
  action. No-op and failed updates do not restart anything.
- **The Admin Center mirrors the split.** In the Updates tab's **Plugins** sub-tab, `U`
  updates the highlighted installed plugin and `m` switches install mode. Pane-wide `u`
  still runs only the SASE core + plugins update, while pane-wide `A` deliberately
  targets the current supported agent-CLI inventory. Global `,U` is snapshot-gated: it
  includes only provider names from the latest completed automatic check, revalidates
  them live, and then previews one comprehensive tracked update. Manual-only providers
  are guidance, never guessed or privileged commands.
- **`-n|--dry-run`** prints the exact `uv` command or editable-checkout plan that would
  run and exits `0` without changing anything. uv itself has no dry-run, so sase
  resolves and prints the managed plan itself.
- **`-j|--json`** emits `schema_version: 2` with a stable, sorted payload. Managed
  outcomes are reported under `managed`; editable-checkout plans/results are reported
  under `dev`; `mode` is `managed`, `dev`, or `mixed`; `restart` reports whether axe was
  restarted, skipped, or failed. The dry-run JSON reports `dry_run: true`, the planned
  command or dev plan, and each package's current version.
- **Installed shell-completion scripts can be refreshed after the upgrade**, so a
  stamped script does not drift behind the CLI it completes. This is gated behind the
  `completion_refresh_on_update` beta feature flag (default off); with the flag on, a
  successful update regenerates, `zcompile`s, and re-stamps every previously installed
  script, adds a `completion_refresh` object to the JSON payload, and reports failures
  without failing the update itself. See
  [Shell Completion](completion.md#refresh-on-update).
- A no-op run (nothing to upgrade) renders a clean "Already up to date" state and still
  exits `0`.
- The authoritative record of what is in sase's environment is uv's own
  `uv-receipt.toml`, not anything sase stores. `sase update` moves the whole environment
  forward at once; to install or upgrade individual plugins, use
  [`sase plugin install` / `sase plugin update`](#installing-and-updating-plugins-sase-plugin-install-sase-plugin-update).

### Dev / editable installs

When sase or a plugin is present in the uv tool environment as an **editable / dev
install** (for example `uv tool install -e` against a local git checkout),
`uv tool upgrade` cannot move it forward. `sase update` detects those editable
requirements from the receipt and upgrades each one in place from git instead:

- The run computes a mode of `managed` (only registry packages), `dev` (only editable
  checkouts), or `mixed` (both), and handles each part with the matching backend.
- For every editable checkout it runs `git fetch`, then a preflight: a checkout is
  **actionable** only when it is clean and strictly behind its upstream. Checkouts that
  are dirty, diverged, detached, ahead, or have no upstream are skipped with a printed
  reason instead of being touched.
- Actionable checkouts are advanced with `git merge --ff-only`, then reconciled into the
  environment — `uv tool install` for Python packages and `just rust-install-uv-tool`
  for the Rust core (`sase-core-rs`).
- A wheel-installed `sase-core-rs` is reconciled as managed work even though it is a
  transitive dependency rather than a top-level uv receipt requirement. Current or
  safely skipped editable checkouts stay visible in the plan but do not block that
  core-wheel update.
- After any changed update (managed or dev), `sase update` restarts the axe daemon so
  the new code is picked up by background work.

A normal `uv tool install sase` user is unaffected by this path, while a contributor
running editable installs gets the same one-command update. `-n|--dry-run` previews the
planned git/uv commands for both modes, and the `-j|--json` payload (schema version `2`)
reports per-root dev outcomes alongside the managed package outcomes.

#### The code-swap lock

Fast-forwarding an editable checkout swaps the source tree out from under anything
already importing from it. A process that has imported some modules and not yet imported
others can end up mixing pre-swap and post-swap code. SASE guards that with an advisory
lock at `~/.sase/locks/code-swap.lock`, with per-holder records under
`~/.sase/locks/code-swap.holders/`. It has two kinds of holder, and the distinction
matters:

- **Blocking readers.** `sase bead work` takes a shared lock for its whole run. While it
  holds one, `sase update` cannot take the exclusive lock its editable swap needs, so
  the update stops before touching anything. Each actionable editable package is
  reported with status `failed` and a reason that begins `deferred:`, and the command
  exits non-zero without having changed anything — re-run it later rather than treating
  it as a broken checkout:

  ```text
  deferred: <holder> is running against this checkout; re-run `sase update` when it finishes
  ```

  In the Admin Center's Updates tab the same condition disables the update instead:

  ```text
  A sase bead work is running against this checkout (<holder>). Re-run the update after it finishes.
  ```

  Symmetrically, starting `sase bead work` while a swap is already in progress exits
  non-zero without starting any work, rather than importing a torn tree.

- **Advisory readers.** A long-lived agent runner registers as advisory for the lifetime
  of its execution loop. Advisory holders never take the shared lock, so they can never
  defer a swap and are never counted as blocking one. Instead, `sase update` and the
  Admin Center's update preview print an informational line —
  `N agent runner(s) are running from this checkout and a swap now can break their deferred imports.`
  — so you can decide whether to wait. A runner is deliberately not allowed to block an
  update indefinitely.

Both sides are non-blocking and fail fast rather than queueing: a waiting reader may
already hold pre-swap imports, and a waiting writer would stall ACE. Set
`SASE_DISABLE_CODE_SWAP_LOCK=1` to bypass the mechanism entirely (both the barrier and
the warning). One residual race is accepted by design: a reader that starts while a swap
is already underway can import torn modules before it reaches the lock. Closing that
fully would require re-execing readers.

### Install mode switching

`sase update -t/--to dev|pypi` switches the whole install between the two modes instead
of updating within one:

- **`--to dev`** establishes the dev (editable) state for you: it clones (or
  fast-forwards) the SASE checkouts, runs the editable reinstall, and rebuilds the local
  `sase-core-rs` extension. Dev checkouts materialize owner-nested under the
  `update.dev_root` config key (default `~/projects/github`) as
  `<dev_root>/<owner>/<repo>` — for example `~/projects/github/sase-org/sase` — cloned
  via SSH URLs. Legacy flat `~/projects/git/<repo>` checkouts are no longer reused; SASE
  warns about them, and you can either set `update.dev_root` or move the tree into the
  owner-nested layout.
- **`--to pypi`** returns the install to managed mode, reinstalling published wheels
  through `uv`.
- Switching to the mode you are already in is a no-op. `-n|--dry-run` previews the plan;
  without `-y|--yes` an interactive confirmation is required, and cancelling exits
  non-zero. A changed switch restarts axe (and ACE plus axe when driven from the Updates
  tab) through the shared restart path.
- **In the Admin Center Updates tab's Plugins sub-tab, press `m`** to switch mode
  interactively: it shows the current mode and dev root, confirms, runs the switch as a
  proc, and shows a restart toast.

## Installing and updating plugins (`sase plugin install` / `sase plugin update`)

`sase plugin install <plugin>` adds a plugin to the **same** uv tool environment as
`sase`, so its entry points are discovered the next time `sase` runs.
`sase plugin update <plugin>` upgrades one already-installed plugin (and `-a|--all`
upgrades every installed plugin), leaving `sase` core pinned. Both build on the same
`uv tool` engine as `sase update` and share its install-method requirement and
beautiful, copy-pasteable output.

```bash
# Install (resolved through the GitHub catalog)
sase plugin install github          # `github` -> the `sase-github` distribution
sase plugin install sase-github     # repo name also works
sase plugin install github -g       # install from the plugin's git repository
sase plugin install github -n       # dry run: preview the uv command, change nothing
sase plugin install 'sase-foo==1.2' # a raw requirement / git URL / path is passed through verbatim

# Update
sase plugin update github           # upgrade one installed plugin (sase core stays pinned)
sase plugin update -a               # upgrade every installed plugin
sase plugin update github -n        # dry run
sase plugin install github -j       # stable machine-readable JSON (also on update)
```

- **Name resolution.** A bare `<plugin>` is resolved through the catalog (`github` →
  `sase-github`), so the short name, repo, or `owner/repo` full name all work. By
  default the plugin is installed from its published distribution (PyPI); pass
  `-g|--git` to install from its repository instead. A value that already looks like a
  requirement, git URL, or local path (`==`, `git+…`, `…://…`, `/path`) is passed
  through to uv verbatim. An unknown name prints ranked `did you mean…?` suggestions and
  exits non-zero.
- **The receipt is the source of truth.** uv's `--with X` _replaces_ the injected set
  rather than appending to it, so both commands reconstruct the **full** `--with` set
  from sase's `uv-receipt.toml` — faithfully preserving existing plugins, editable/dev
  installs, version specifiers, and extras — before re-running `uv tool install`.
  `update` additionally passes `--upgrade-package <name>` per target so only those
  plugins move while everything else is pinned; this is why "update plugins" never
  silently bumps `sase` core (use the comprehensive `sase update`, which also
  re-resolves a managed core wheel in editable/dev mode, for that).
- **Install method is required**, exactly as for `sase update`: the commands only work
  when sase was installed with `uv tool install sase`, and otherwise fail fast with an
  actionable message instead of touching the environment.
- **Idempotent install.** Installing a plugin that is already injected prints "already
  installed" and points at `sase plugin update <plugin>` rather than re-running uv.
  Updating a plugin that is **not** installed points at `sase plugin install <plugin>`
  instead.
- **`-n|--dry-run`** prints the exact `uv` command (and, for install, the resulting
  plugin set) and exits `0` without changing anything. **`-j|--json`** emits a stable,
  sorted payload with `schema_version`, the resolved `command`, and per-package
  outcomes; **`-r|--refresh`** refetches the catalog before resolving a name.
- **Restart after real package changes.** Like `sase update`, `sase plugin install`,
  `update`, and `uninstall` restart the axe daemon from the CLI when uv actually changed
  installed packages, and show an operation-specific post-restart toast when driven from
  ACE. The JSON payload carries the same restart status shape as `sase update`.

### Removing a plugin (`sase plugin uninstall`)

`sase plugin uninstall <plugin>` removes one installed plugin from the **same** uv tool
environment as `sase`, so its entry points are no longer discovered the next time `sase`
runs. It reconstructs uv's `--with` set from the receipt with the target omitted, so
sase core and every other plugin (including editable/dev installs) are preserved.

```bash
sase plugin uninstall github        # resolve the target straight from the receipt
sase plugin uninstall sase-github   # repo name also works
sase plugin uninstall github -n     # dry run: preview the uv command, change nothing
sase plugin uninstall github -j     # stable machine-readable JSON
```

- **Receipt-first resolution.** Unlike `install`, the target is resolved straight from
  sase's `uv-receipt.toml`, so an installed community plugin that is absent from the
  catalog still resolves with no network call. (Pass `-r|--refresh` to refetch the
  catalog when you want catalog-based name resolution.) There is no `-g|--git` flag.
- **No-op success.** Uninstalling a plugin that is **not** installed is a no-op that
  still exits `0` — explicitly unlike `update`, which points a not-installed target at
  `sase plugin install`. An unknown name still prints ranked `did you mean…?`
  suggestions and exits non-zero.
- **Install method is required**, exactly as for `sase update` and the other
  `sase plugin` mutations: it only works when sase was installed with
  `uv tool install sase`, and otherwise fails fast with an actionable message.

## How Plugins Are Discovered

For catalog and Admin Center installed status, a managed uv tool receipt is
authoritative: each explicitly-injected requirement is matched to its live
`importlib.metadata` distribution by PEP 503-normalized name. Receipt inspection is best
effort, so unmanaged environments or a temporarily unavailable receipt retain the
generic discovery behavior.

Generic plugin discovery uses `importlib.metadata.entry_points()` plus recognized
console-script and distribution naming to find installed packages. It is also what
supplies the contributed entry-point groups displayed by `sase plugin show`.

There are two discovery paths:

1. **Provider classes**: `sase_artifact_refs`, `sase_file_hooks`, `sase_vcs`,
   `sase_workspace`, and `sase_llm` entry points resolve to classes. The relevant
   registry loads the class, instantiates it, and registers the instance with a pluggy
   `PluginManager`.
2. **Package resources**: `sase_xprompts`, `sase_config`, and `sase_plugin_manifest`
   entry points resolve to modules. The shared helper in
   `src/sase/main/plugin_discovery.py` sorts config and xprompt entry points by name,
   loads the modules, and skips module load failures after logging them at debug level.
   `sase doctor -C plugins.resources` loads resource entry points directly so packaging
   problems are visible as diagnostics instead of only debug logs.

### VCS Plugins (pluggy)

VCS plugins use pluggy's hook system. The hook specification is defined in `VCSHookSpec`
(`src/sase/vcs_provider/_hookspec.py`). Each hook method uses `firstresult=True`,
meaning the first plugin to return a non-`None` result wins.

The VCS registry (`src/sase/vcs_provider/_registry.py`) uses `sase_vcs` entry points in
two ways:

1. Detection/classification builds a pluggy manager containing all registered VCS
   plugins.
2. Runtime operations create a `VCSPluginManager` for the selected provider name, such
   as `bare_git`, `github`, or `hg`.

### Workspace Plugins (pluggy)

Workspace plugins use pluggy's hook system, similar to VCS plugins. The hook
specification is defined in `WorkspaceHookSpec`
(`src/sase/workspace_provider/_hookspec.py`). Most hooks use `firstresult=True`; the
exception is `ws_get_workflow_metadata` which collects results from all plugins. All
hook method names are prefixed with `ws_`.

The workspace registry (`src/sase/workspace_provider/_registry.py`) creates a singleton
`WorkspacePluginManager`, registers `WorkspaceHookSpec`, and loads all `sase_workspace`
provider classes from entry points. This is why all workspace metadata can be listed at
once while hook dispatch still lets a single plugin handle each operation.

See [docs/workspace.md](workspace.md) for the full workspace provider reference.

### LLM Plugins (pluggy)

LLM provider plugins use pluggy's hook system. The hook specification is defined in
`LLMHookSpec` (`src/sase/llm_provider/_hookspec.py`). Core dispatch hooks (`llm_invoke`,
`llm_resolve_model_name`) use `firstresult=True` so the first matching plugin handles a
call; metadata hooks (`llm_provider_name`, `llm_known_model_names`,
`llm_skill_template_context`, `llm_skill_deploy_subpath`, `llm_cli_status_color`,
`llm_autodetect_priority`, `llm_autodetect_cli_name`, `llm_default_retry_config`,
`llm_install_metadata`, `llm_model_advisories`) are invoked per-plugin by the registry
so each provider contributes its own metadata. All hook method names are prefixed with
`llm_`.

Core Sase ships Claude, Codex, Antigravity (`agy`), Qwen, OpenCode, Meta's Muse Code,
and xAI's Grok Build providers as built-in entry points. Additional providers belong in
external plugin packages that declare `sase_llm` entry points and provide their own
metadata hooks.

#### LLM Provider Install Metadata and Advisories

`llm_install_metadata()` describes how a provider's CLI is installed, versioned, and
updated, and drives [`sase agent-cli`](agent_providers.md#inventory-and-updates). Every
key is optional and every one defaults to today's behavior, so an existing plugin needs
no changes.

| Key                         | Purpose                                                                                                           |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `manager`                   | `npm`, `homebrew`, `bundled`, or `script` (installed by a remote install script).                                 |
| `package` / `brew_package`  | Package identity for the npm and Homebrew managers.                                                               |
| `display_name` / `docs_url` | Human-facing name and canonical vendor docs link.                                                                 |
| `version_argv`              | Argv used to probe the installed version (default `["--version"]`).                                               |
| `version_regex`             | Regex with a `version` group, when the CLI's version output is not plain semver.                                  |
| `latest_version_package`    | npm package whose `latest` dist-tag is the newest known version.                                                  |
| `latest_version_url`        | HTTPS JSON endpoint serving the newest version, for channel-versioned CLIs distributed outside npm.               |
| `latest_version_json_field` | Field to read from that endpoint's JSON body (default `version`).                                                 |
| `version_compare`           | `pep440` (default) or `exact`. Use `exact` when release ids are not valid PEP 440 versions.                       |
| `self_update_argv`          | The CLI's own update command; declaring one classifies the CLI as self-managed.                                   |
| `self_update_env`           | Environment overlay applied to that update command, for CLIs whose update is env-driven rather than a subcommand. |
| `install_script_url`        | HTTPS install script `sase agent-cli install` fetches, digests, and runs without a shell.                         |
| `install_env`               | Environment overlay applied to that install script.                                                               |
| `install_dir`               | Where the installer writes the binary, so SASE can name the target and find it afterwards.                        |
| `install_dir_env`           | Environment variable that overrides `install_dir`.                                                                |

`llm_model_advisories()` returns a per-model map of terms a user should see when they
choose a model — a discounted tier that trains on its inputs, a preview model with no
stability guarantee, and so on:

```python
@hookimpl
def llm_model_advisories(self) -> dict[str, dict[str, str]]:
    return {
        "vendor-model-discounted": {
            "severity": "warn",  # or "info"
            "label": "trains on your data",
            "detail": "One sentence the user reads before agreeing to this.",
        }
    }
```

Omitting the hook means no advisories, and non-conforming values are dropped rather than
raising, so third-party providers stay compatible. The registry normalizes the map and
every render site reads from it, so a new advisory needs no new render site. See
[LLM Providers — Model advisories](llms.md#model-advisories) for where advisories
surface.

See [docs/llms.md](llms.md) for the full LLM provider reference, including authoring new
providers with `@hookimpl`.

### XPrompt Plugins

Plugin packages can contribute xprompt templates by declaring a `sase_xprompts` entry
point that points to a module. The module's package directory is searched for
`xprompts/*.md` files and `xprompts/*.yml` / `xprompts/*.yaml` workflow files. Plugin
xprompts are priority 8 in the [discovery order](xprompt.md#discovery-order) (above
built-in files and below config-based xprompts).

### Config Plugins

Plugin packages can provide default configuration by declaring a `sase_config` entry
point. The referenced module's package must contain a `default_config.yml` file. Plugin
configs are merged between the bundled package defaults and the user's `sase.yml`. See
the [Deep-Merge System](configuration.md#deep-merge-system) for details on the merge
chain.

### Artifact Reference and File-Hook Providers

The `sase_artifact_refs` and `sase_file_hooks` groups share the declarative artifact
provider host. A provider class can implement either or both hooks:

- `artifact_ref_provider_specs()` returns one mapping or an iterable of mappings. Each
  schema-versioned specification has a unique provider ID and `ref.kind`, plus its
  Artifacts tab `ref.icon`, expansion, metadata, inventory, identity, and publication
  policy. A sidecar selects it with `ref: {use: <plugin>@<provider-id>}`; local sidecar
  fields deep-merge over the base. During the compatibility window, a ref provider spec
  without `ref.icon` is admitted with a generic mark and a warning diagnostic.
- `artifact_file_hook_provider_specs()` returns schema-versioned file-hook templates.
  Each template has a unique provider ID, a `file_hook` mapping, and an optional list of
  required fields. A configured hook selects it with `use: <plugin>@<provider-id>` and
  supplies the required values.

SASE validates all returned specifications before adding them to the registry. Duplicate
provider IDs, duplicate reference kinds, reserved kinds, invalid schemas, load errors,
and hook failures are diagnosed rather than silently taking precedence. The core package
always registers the built-in `plan` reference provider through the same schema and
registry path, even when third-party provider entry points are disabled. Run
`sase doctor -C config.repos` for sidecar provider problems and `sase file-hook list`
for configured file hooks.

### Chop Script Packages

Chop scripts are installed console scripts, not a pluggy entry-point group. Axe resolves
the exact configured `script` name from `axe.chop_script_dirs`, the running
interpreter's bin directory, then `$PATH`; it never adds a `sase_chop_` prefix. A
package may also expose a `sase_config` resource when it wants to contribute
disabled-by-default or ready-to-patch lumberjack configuration. Exact-name chop packages
do not need to rename their public scripts to `sase_chop_*` merely to appear installed
in the catalog: when Sase injects them into its managed uv tool environment, receipt
membership provides that installed identity.

Proposal-emitting packages should depend on `sase` and use the public `sase.chops` SDK.
Scripts read `--context`, write their versioned result atomically to
`SASE_CHOP_RESULT_FILE`, and emit structured launch proposals. They must not call
`sase run` themselves, and proposal prompts cannot contain standalone `#!workflow`
references. Axe validates and launches proposals so dry runs remain side-effect free and
action lifecycle stays observable.

Packages can group proposals in one runner-owned clan by passing the same template to
`clan` and a member ID to `agent_name`. The runner allocates one concrete clan, makes
the first accepted proposal its declarer, assigns the `chop` tribe at clan level, and
resolves `wait_on` to full member names. Authors may also pass a literal Rich
`clan_summary`; repeat the identical value on every member that shares the raw clan
template. Axe remains the sole owner of concrete clan allocation and emits the summary
only on the surviving declarer's `%clan` directive. Do not combine `clan` with `tribe`.

A member ID may itself end in (or contain) one `@` auto-name marker, so `clan` and
`agent_name` carry at most one marker each. Axe picks the clan token for the whole group
first and then allocates each templated member inside that concrete clan, so
`clan="toobig-@"` with `agent_name="split_file.src.pkg.large.@"` becomes
`toobig-0.split_file.src.pkg.large.0`. Prefer a trailing `.@` over hashing a
discriminator into the member ID: two members that would otherwise collide land on `.0`
and `.1` instead of failing the run. See
[Axe launch proposals](axe.md#structured-results-and-launch-proposals) for the full
allocation rule.

## Disabling Plugins

Third-party plugin resources and declarative artifact-provider entry points can be
disabled via environment variables:

| Variable                            | Effect                                                      |
| ----------------------------------- | ----------------------------------------------------------- |
| `SASE_DISABLE_PLUGINS`              | Disable resource plugins and third-party artifact providers |
| `SASE_DISABLE_PLUGIN_XPROMPTS`      | Disable xprompt/workflow resource plugins only              |
| `SASE_DISABLE_PLUGIN_CONFIG`        | Disable plugin `default_config.yml` resource loading only   |
| `SASE_DISABLE_PLUGIN_ARTIFACT_REFS` | Disable artifact-reference provider entry points only       |
| `SASE_DISABLE_PLUGIN_FILE_HOOKS`    | Disable file-hook provider entry points only                |

Any non-empty value enables the disable. The VCS, workspace, and LLM provider registries
load their provider entry points directly and do not consult these switches. These
switches also do not remove the core built-in `plan` reference provider.

## Writing a Plugin

A sase plugin is a standard Python package that declares entry points in
`pyproject.toml`.

### Example: VCS Plugin

```toml
# pyproject.toml
[project.entry-points."sase_vcs"]
my_vcs = "my_sase_plugin.vcs:MyVCSPlugin"

[project.entry-points."sase_config"]
my_vcs = "my_sase_plugin"
```

The VCS plugin class implements hooks from `VCSHookSpec` using the `@hookimpl`
decorator:

```python
from sase.vcs_provider._hookspec import hookimpl

class MyVCSPlugin:
    @hookimpl
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None] | None:
        # Implementation here
        ...

    @hookimpl
    def vcs_diff(self, cwd: str) -> tuple[bool, str | None] | None:
        # Implementation here
        ...
```

Methods should return `None` (implicitly or explicitly) for operations they don't
support, allowing other plugins to handle them.

### Example: Workspace Plugin

```toml
# pyproject.toml
[project.entry-points."sase_workspace"]
my_workspace = "my_sase_plugin.workspace:MyWorkspacePlugin"
```

The workspace plugin class implements hooks from `WorkspaceHookSpec` using the
`@hookimpl` decorator:

```python
from sase.workspace_provider._hookspec import WorkflowMetadata, hookimpl

class MyWorkspacePlugin:
    @hookimpl
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
        return WorkflowMetadata(
            workflow_type="my_vcs",
            ref_pattern=r"#my_vcs:(\w+)",
            display_name="My VCS",
            pre_allocated_env_prefix="SASE_MYVCS",
            vcs_family="git",
            vcs_provider_name="my_vcs",
        )

    @hookimpl
    def ws_detect_workflow_type(self, project_file: str) -> str | None:
        # Return workflow type if this plugin handles the project
        ...
```

### Example: XPrompt Plugin

Place xprompt files in your package's `xprompts/` directory and register the module:

```toml
[project.entry-points."sase_xprompts"]
my_plugin = "my_sase_plugin"
```

```
my_sase_plugin/
├── __init__.py
└── xprompts/
    ├── my_template.md
    └── my_workflow.yml
```

Use `.md` for prompt templates and `.yml` / `.yaml` for workflow definitions.

### Example: Config Plugin

Place a `default_config.yml` alongside your module and register it:

```toml
[project.entry-points."sase_config"]
my_plugin = "my_sase_plugin"
```

```
my_sase_plugin/
├── __init__.py
└── default_config.yml
```

Plugin configs are merged using the
[deep-merge system](configuration.md#deep-merge-system). User config in `sase.yml` takes
precedence over plugin defaults.

### Example: Declarative Artifact Providers

Register artifact-reference and file-hook providers separately. Each class implements
only the hook for its entry-point group:

```toml
[project.entry-points."sase_artifact_refs"]
my_docs = "my_sase_plugin.artifacts:DocumentProviders"

[project.entry-points."sase_file_hooks"]
my_hooks = "my_sase_plugin.artifacts:FileHookProviders"
```

```python
import pluggy


hookimpl = pluggy.HookimplMarker("sase_artifact")


class DocumentProviders:
    @hookimpl
    def artifact_ref_provider_specs(self):
        return ({
            "schema_version": 1,
            "provider": "design",
            "ref": {
                "kind": "design",
                "expansion_format": "@{checkout_path}",
                "properties": {},
                "detail": {},
                "identity": {},
                "inventory": {"globs": ["**/*.md", "!drafts/**"]},
                "publication": {
                    "link": "vcs_permalink",
                    "referenced_by": "markdown_table",
                },
            },
        },)


class FileHookProviders:
    @hookimpl
    def artifact_file_hook_provider_specs(self):
        return ({
            "schema_version": 1,
            "provider": "research-highlights",
            "required": ["command"],
            "file_hook": {
                "description": "Render new research reports into Highlights PDFs.",
                "filters": {"sidecars": ["research"], "ops": ["ADD"]},
                "timeout": "120s",
            },
        },)
```

The direct pluggy marker above is equivalent to SASE's public `hookimpl`. In the current
release, importing `hookimpl` from `sase.artifact_providers` before another SASE module
has initialized configuration can hit a circular import, so a plugin module loaded as an
entry point should construct the marker directly.

The project can then select the document provider with
`repos.sidecar.custom.design.ref.use: my_sase_plugin@design` and instantiate the hook
with a `file_hooks` entry containing `use: my_sase_plugin@research-highlights` plus its
required `command`. Provider and kind names must not collide with another installed
provider or a reserved built-in kind. Use `sase doctor -C config.repos`,
`sase doctor -C config.file_hooks`, and `sase file-hook list` to verify the effective
configuration.

### Example: Chop Script Package

Declare each executable by its full public name:

```toml
[project]
dependencies = ["sase"]

[project.scripts]
my_chop_audit = "my_sase_plugin.chops.audit:main"
```

Use the SDK to load the runner context and write a validated result:

```python
from sase.chops import ChopResultBuilder, load_chop_invocation


def main() -> None:
    invocation = load_chop_invocation(description="Audit one target project")
    target = invocation.context.target or {}
    workspace = str(target["workspace"])
    result = ChopResultBuilder(
        summary="audit: targets=1 proposals=2",
        counters={"targets": 1, "proposals": 2},
    )
    clan_summary = "[bold]Project audit[/bold]"
    result.propose(
        "Audit recent changes and fix confirmed correctness bugs only.",
        workspace,
        proposal_id="audit",
        agent_name="audit",
        clan="project-audit-@",
        clan_summary=clan_summary,
    )
    result.propose(
        "Review the audit fixes and add focused regression tests.",
        workspace,
        agent_name="review",
        clan="project-audit-@",
        clan_summary=clan_summary,
        wait_on="audit",
    )
    result.write(context=invocation.context)
```

Configure the exact script name and debug it through the runner:

```yaml
axe:
  lumberjacks:
    audits:
      description: Run project audits every five minutes
      interval: 300
      chops:
        project_audit:
          description: Audit enabled projects for actionable improvements
          script: my_chop_audit
          for_each: { source: projects }
```

```bash
sase axe chop run 'project_audit[sase]' -L audits --dry-run --chop-verbose
```

Third-party packages can opt into `sase plugin list` by adding the `sase--plugin`
repository topic. See [Axe](axe.md#structured-results-and-launch-proposals) for the
result contract, proposal fields, trigger/guard policy, and lifecycle statuses.

### Example: LLM Provider Plugin

LLM providers declare a `sase_llm` provider class:

```toml
[project.entry-points."sase_llm"]
my_llm = "my_sase_plugin.llm:MyLLMProvider"
```

The provider implements hooks from `LLMHookSpec` using `@hookimpl`, including
`llm_invoke()` for execution and metadata hooks such as `llm_provider_name()`,
`llm_known_model_names()`, and `llm_autodetect_priority()`. See
[docs/llms.md](llms.md#external-provider-plugins) for the full provider contract.
