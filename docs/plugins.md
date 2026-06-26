# Plugin System

Sase uses Python [entry points](https://packaging.python.org/en/latest/specifications/entry-points/) to discover
optional functionality installed in the same Python environment as `sase`. Runtime providers use
[pluggy](https://pluggy.readthedocs.io/) hooks; resource plugins expose package data such as xprompt files and
`default_config.yml`.

The core `sase` package provides the plugin infrastructure, the built-in LLM providers, and local git/directory
workspace support. Extra packages add hosted VCS workflows, internal workflows, or integrations without changing the
core package.

## Plugin Groups

Sase defines six entry point groups:

| Entry Point Group      | Entry Point Value | Purpose                                             | Example Plugin                  |
| ---------------------- | ----------------- | --------------------------------------------------- | ------------------------------- |
| `sase_vcs`             | Provider class    | VCS provider plugins (git, hg, etc.)                | `sase-github`                   |
| `sase_workspace`       | Provider class    | Workspace provider plugins (ref resolution, submit) | `sase-github`                   |
| `sase_llm`             | Provider class    | LLM provider plugins                                | built-in or third-party         |
| `sase_xprompts`        | Package module    | XPrompt templates and workflows                     | `my_sase_plugin`                |
| `sase_config`          | Package module    | Default configuration (`default_config.yml`)        | `sase-github`, `my_sase_plugin` |
| `sase_plugin_manifest` | Package module    | Plugin metadata resource used by diagnostics        | third-party plugin packages     |

Provider-class entry points resolve to a class that is instantiated and registered with pluggy. Package-module entry
points resolve to a module whose package resources are read by Sase.

## Available Plugin Packages

| Package         | Description                                                                             | Entry Points                                                                                           |
| --------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `sase` (core)   | Bare-git VCS, bare-git and `#cd` workspaces, and built-in LLM providers                 | `sase_vcs: bare_git`, `sase_workspace: bare_git, cd`, `sase_llm: agy, claude, codex, opencode, qwen`   |
| `sase-github`   | GitHub VCS and workspace support, including GitHub CLI (`gh`) PR operations             | `sase_vcs: github`, `sase_workspace: github`, `sase_config: sase_github`, `sase_xprompts: sase_github` |
| `sase-telegram` | Telegram integration via chop scripts (`sase_chop_tg_outbound`, `sase_chop_tg_inbound`) | CLI scripts (not pluggy entry points)                                                                  |
| `sase-nvim`     | Neovim integration, including project spec syntax and prompt helpers                    | standalone Neovim plugin files (not Python entry points)                                               |

## Installation

```bash
# Core sase (includes BareGitPlugin for plain git repos)
pip install sase

# Add GitHub PR support
pip install sase-github
```

## Plugin Catalog (`sase plugin list` / `sase plugin show`)

`sase plugin` is a discovery surface for the whole SASE plugin ecosystem — not just what is installed locally. It treats
the GitHub `sase-plugin` repository topic as the canonical registry, so the catalog always reflects reality: a repo
gains or loses a listing purely by gaining or losing the topic, with no code change.

```bash
# Catalog of every known plugin (built-in and community)
sase plugin list
sase plugin list -v          # add stars, last-updated, and the full topic list
sase plugin list -j          # stable machine-readable JSON

# Detailed view of a single plugin
sase plugin show github
sase plugin show sase-github # short name, repo, or owner/repo all match
sase plugin show github -j   # stable machine-readable JSON

# Bypass the cache and refetch from GitHub
sase plugin list -r
sase plugin show github -r
```

- `sase plugin` with no subcommand defaults to `sase plugin list`.
- **`list`** renders two clearly-labeled sections — **built-in** (published under the official `sase-org` org) first,
  then **community** (third-party, shown with a warning) — and marks which plugins are installed and at what version.
  Status uses a glyph plus a legend (`●` installed, `○` available) so the output is legible with no color. The footer
  shows the cache age and the exact `--refresh` command.
- **`show`** renders a detail panel: description, installed status and contributed entry points, repository, homepage,
  topics, stars, last update, and license. Community plugins lead with a prominent third-party warning. An unknown
  `<plugin_name>` prints ranked `did you mean…?` suggestions and exits non-zero.
- Built-in vs. community is decided by the owning org: `sase-org` (case-insensitive) is built-in; anything else is
  community. Archived repos are surfaced with an archived marker rather than hidden.
- Installed status, version, and contributed entry-point groups come from merging the catalog with the live
  [plugin inventory](#how-plugins-are-discovered). Plugins that carry the topic but contribute no Python entry points
  (for example a Neovim-only integration) correctly show as not installed.

### Catalog fetching and cache

The catalog is fetched once with a single authenticated GitHub CLI search call and then cached, so repeat runs are
instant and never make a surprise network call:

- The data comes from `gh api --paginate -X GET "search/repositories?q=topic:sase-plugin&per_page=100"`, which returns
  topics, owner, description, stars, license, and timestamps inline — no per-repo follow-up lookups.
- The cache lives at `~/.sase/plugins/catalog_cache.json` and is written atomically. The first run fetches and writes
  it; later runs read it and only touch the network when `-r|--refresh` is passed. A cache older than the soft staleness
  threshold is still used, but the footer warns more loudly.
- If `gh` runs but the call fails (network error, non-zero exit, or an unauthenticated/auth error), SASE falls back to
  the existing cache with a loud "stale cached data" warning, or — when there is no cache — re-raises the error.
- A missing `gh` (not on `PATH`) is always a hard error, even when a cache exists: SASE never silently serves stale data
  while the CLI it needs is absent, and instead prints the same actionable `gh` install / `gh auth login` hint that
  `sase doctor` uses. This mirrors `src/sase/doctor/checks_plugins.py`.

### Related plugin diagnostics

The catalog answers "what exists and what do I have installed." For deeper install and configuration diagnostics, use
the commands that already own each concern:

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

- `sase version -v` / `-j` inventories the installed `sase` host, the `sase-core-rs` core, and SASE plugin packages
  discovered through entry points, console scripts, or `sase-*` distribution names.
- `sase doctor -C plugins.resources` reports resource entry-point load failures and any resource-plugin disable
  environment variables (`ERROR` on a load failure, `WARN` when loading is disabled). `sase doctor -C plugins.github`
  probes the GitHub CLI and `gh auth status` when a GitHub provider plugin is installed.
- `sase axe chop list` shows configured chops with status; add `--available` to include discoverable executable chop
  scripts. `sase axe chop doctor` checks for missing configured script chops (`ERROR`), unconfigured available scripts
  (`WARN`), and Telegram chop `pass`/environment prerequisites (`WARN`). The same chop diagnostics are mirrored by
  `sase doctor -C axe.chops`.

## Updating sase and plugins (`sase update`)

`sase update` upgrades `sase` **and every installed sase plugin together**, in one atomic operation, by delegating to
`uv tool upgrade sase`. uv re-resolves sase core and all injected plugins in a single shot, so they always move forward
as a coherent set rather than drifting out of sync.

```bash
sase update            # upgrade sase + all plugins
sase update -n         # dry run: preview the uv command and package set, change nothing
sase update -q         # quiet: print only a one-line summary
sase update -j         # stable machine-readable JSON
```

Typical output highlights what changed, marks what was already current, and reminds you to restart long-running agents:

```text
✓ sase           0.5.0 → 0.6.1
✓ sase-github    0.3.2 → 0.4.0
· sase-telegram  0.1.0   (already current)

Updated sase + 1 plugin in 4.2s · 1 already current
Restart running sase agents to pick up the new version.
```

- **Install method is required.** `sase update` only works when sase was installed with `uv tool install sase` (the
  canonical install path). When it is run from a pip/pipx install or from a dev checkout's virtualenv, it **fails fast
  with an actionable message** and a non-zero exit code instead of touching the environment. The check is strict: `uv`
  must be on `PATH`, the running interpreter's `sys.prefix` must resolve to `<uv tool dir>/sase`, and that directory
  must contain a `uv-receipt.toml`.
- **`-n|--dry-run`** prints the exact `uv` command that would run plus the current package set (sase core and each
  injected plugin, with versions) and exits `0` without changing anything. uv itself has no dry-run, so sase resolves
  and prints the plan.
- **`-j|--json`** emits a stable, sorted payload with `schema_version`, the resolved `command`, per-package outcomes
  (`kind` of `upgraded`/`added`/`removed`/`unchanged` with `old_version`/`new_version`), and `counts`. The dry-run JSON
  reports `dry_run: true`, the planned `command`, and each package's `current_version`.
- A no-op run (nothing to upgrade) renders a clean "Already up to date" state and still exits `0`.
- The authoritative record of what is in sase's environment is uv's own `uv-receipt.toml`, not anything sase stores.
  `sase update` moves the whole environment forward at once; per-plugin install and upgrade commands are a planned
  follow-up.

## How Plugins Are Discovered

Plugin discovery uses `importlib.metadata.entry_points()` to find installed packages that declare one of Sase's entry
point groups.

There are two discovery paths:

1. **Provider classes**: `sase_vcs`, `sase_workspace`, and `sase_llm` entry points resolve to classes. The relevant
   registry loads the class, instantiates it, and registers the instance with a pluggy `PluginManager`.
2. **Package resources**: `sase_xprompts`, `sase_config`, and `sase_plugin_manifest` entry points resolve to modules.
   The shared helper in `src/sase/main/plugin_discovery.py` sorts config and xprompt entry points by name, loads the
   modules, and skips module load failures after logging them at debug level. `sase doctor -C plugins.resources` loads
   resource entry points directly so packaging problems are visible as diagnostics instead of only debug logs.

### VCS Plugins (pluggy)

VCS plugins use pluggy's hook system. The hook specification is defined in `VCSHookSpec`
(`src/sase/vcs_provider/_hookspec.py`). Each hook method uses `firstresult=True`, meaning the first plugin to return a
non-`None` result wins.

The VCS registry (`src/sase/vcs_provider/_registry.py`) uses `sase_vcs` entry points in two ways:

1. Detection/classification builds a pluggy manager containing all registered VCS plugins.
2. Runtime operations create a `VCSPluginManager` for the selected provider name, such as `bare_git`, `github`, or `hg`.

### Workspace Plugins (pluggy)

Workspace plugins use pluggy's hook system, similar to VCS plugins. The hook specification is defined in
`WorkspaceHookSpec` (`src/sase/workspace_provider/_hookspec.py`). Most hooks use `firstresult=True`; the exception is
`ws_get_workflow_metadata` which collects results from all plugins. All hook method names are prefixed with `ws_`.

The workspace registry (`src/sase/workspace_provider/_registry.py`) creates a singleton `WorkspacePluginManager`,
registers `WorkspaceHookSpec`, and loads all `sase_workspace` provider classes from entry points. This is why all
workspace metadata can be listed at once while hook dispatch still lets a single plugin handle each operation.

See [docs/workspace.md](workspace.md) for the full workspace provider reference.

### LLM Plugins (pluggy)

LLM provider plugins use pluggy's hook system. The hook specification is defined in `LLMHookSpec`
(`src/sase/llm_provider/_hookspec.py`). Core dispatch hooks (`llm_invoke`, `llm_resolve_model_name`) use
`firstresult=True` so the first matching plugin handles a call; metadata hooks (`llm_provider_name`,
`llm_known_model_names`, `llm_skill_template_context`, `llm_skill_deploy_subpath`, `llm_cli_status_color`,
`llm_autodetect_priority`, `llm_autodetect_cli_name`, `llm_default_retry_config`) are invoked per-plugin by the registry
so each provider contributes its own metadata. All hook method names are prefixed with `llm_`.

Core Sase ships Claude, Codex, Antigravity (`agy`), Qwen, and OpenCode providers as built-in entry points. Additional
providers belong in external plugin packages that declare `sase_llm` entry points and provide their own metadata hooks.

See [docs/llms.md](llms.md) for the full LLM provider reference, including authoring new providers with `@hookimpl`.

### XPrompt Plugins

Plugin packages can contribute xprompt templates by declaring a `sase_xprompts` entry point that points to a module. The
module's package directory is searched for `xprompts/*.md` files and `xprompts/*.yml` / `xprompts/*.yaml` workflow
files. Plugin xprompts are priority 8 in the [discovery order](xprompt.md#discovery-order) (above built-in files and
below config-based xprompts).

### Config Plugins

Plugin packages can provide default configuration by declaring a `sase_config` entry point. The referenced module's
package must contain a `default_config.yml` file. Plugin configs are merged between the bundled package defaults and the
user's `sase.yml`. See the [Deep-Merge System](configuration.md#deep-merge-system) for details on the merge chain.

## Disabling Plugins

Resource plugins can be disabled via environment variables:

| Variable                       | Effect                                                    |
| ------------------------------ | --------------------------------------------------------- |
| `SASE_DISABLE_PLUGINS`         | Disable resource plugin loading for config and xprompts   |
| `SASE_DISABLE_PLUGIN_XPROMPTS` | Disable xprompt/workflow resource plugins only            |
| `SASE_DISABLE_PLUGIN_CONFIG`   | Disable plugin `default_config.yml` resource loading only |

Any non-empty value enables the disable. The VCS, workspace, and LLM provider registries currently load their provider
entry points directly and do not consult these resource-plugin disable switches.

## Writing a Plugin

A sase plugin is a standard Python package that declares entry points in `pyproject.toml`.

### Example: VCS Plugin

```toml
# pyproject.toml
[project.entry-points."sase_vcs"]
my_vcs = "my_sase_plugin.vcs:MyVCSPlugin"

[project.entry-points."sase_config"]
my_vcs = "my_sase_plugin"
```

The VCS plugin class implements hooks from `VCSHookSpec` using the `@hookimpl` decorator:

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

Methods should return `None` (implicitly or explicitly) for operations they don't support, allowing other plugins to
handle them.

### Example: Workspace Plugin

```toml
# pyproject.toml
[project.entry-points."sase_workspace"]
my_workspace = "my_sase_plugin.workspace:MyWorkspacePlugin"
```

The workspace plugin class implements hooks from `WorkspaceHookSpec` using the `@hookimpl` decorator:

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

Plugin configs are merged using the [deep-merge system](configuration.md#deep-merge-system). User config in `sase.yml`
takes precedence over plugin defaults.

### Example: LLM Provider Plugin

LLM providers declare a `sase_llm` provider class:

```toml
[project.entry-points."sase_llm"]
my_llm = "my_sase_plugin.llm:MyLLMProvider"
```

The provider implements hooks from `LLMHookSpec` using `@hookimpl`, including `llm_invoke()` for execution and metadata
hooks such as `llm_provider_name()`, `llm_known_model_names()`, and `llm_autodetect_priority()`. See
[docs/llms.md](llms.md#external-provider-plugins) for the full provider contract.
