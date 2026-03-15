# Plugin System

Sase uses a plugin architecture based on [pluggy](https://pluggy.readthedocs.io/) and Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/) to allow extending functionality via
installable packages. The core `sase` package provides the plugin infrastructure and a minimal set of built-in plugins;
additional functionality is available through optional plugin packages.

## Plugin Groups

Sase defines four entry point groups for plugin discovery:

| Entry Point Group | Purpose                                             | Example Plugin               |
| ----------------- | --------------------------------------------------- | ---------------------------- |
| `sase_vcs`        | VCS provider plugins (git, hg, etc.)                | `sase-github`                |
| `sase_workspace`  | Workspace provider plugins (ref resolution, submit) | `sase-github`                |
| `sase_xprompts`   | XPrompt templates and workflows                     | `sase-google`                |
| `sase_config`     | Default configuration (`default_config.yml`)        | `sase-google`, `sase-github` |

## Available Plugin Packages

| Package         | Description                                                                             | Entry Points                                                                 |
| --------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `sase` (core)   | BareGitPlugin for standard git operations                                               | `sase_vcs: bare_git`, `sase_workspace: bare_git`                             |
| `sase-github`   | GitHubPlugin with GitHub CLI (`gh`) PR operations                                       | `sase_vcs: github`, `sase_workspace: github`, `sase_config`, `sase_xprompts` |
| `sase-google`   | HgPlugin for Mercurial with `sase_hg_*` helper commands                                 | `sase_vcs: hg`, `sase_workspace: hg`, `sase_config`, `sase_xprompts`         |
| `sase-telegram` | Telegram integration via chop scripts (`sase_chop_tg_outbound`, `sase_chop_tg_inbound`) | CLI scripts (not pluggy)                                                     |
| `sase-nvim`     | Neovim integration (e.g., project spec syntax highlighting)                             | standalone (not pluggy)                                                      |

## Installation

```bash
# Core sase (includes BareGitPlugin for plain git repos)
pip install sase

# Add GitHub PR support
pip install sase-github

# Add Mercurial support
pip install sase-google
```

## How Plugins Are Discovered

Plugin discovery uses `importlib.metadata.entry_points()` to find installed packages that declare entry points in one of
sase's plugin groups. The shared discovery logic lives in `src/sase/plugin_discovery.py`.

For each group:

1. All entry points for the group are loaded and sorted by name (for determinism).
2. Each entry point is imported as a module.
3. Modules that fail to load are silently skipped (logged at debug level).

### VCS Plugins (pluggy)

VCS plugins use pluggy's hook system. The hook specification is defined in `VCSHookSpec`
(`src/sase/vcs_provider/_hookspec.py`). Each hook method uses `firstresult=True`, meaning the first plugin to return a
non-`None` result wins.

VCS plugins are loaded by `VCSPluginManager` which:

1. Creates a `pluggy.PluginManager` with the `"sase_vcs"` project name.
2. Registers the `VCSHookSpec`.
3. Loads plugins from the `sase_vcs` entry point group.

### Workspace Plugins (pluggy)

Workspace plugins use pluggy's hook system, similar to VCS plugins. The hook specification is defined in
`WorkspaceHookSpec` (`src/sase/workspace_provider/_hookspec.py`). Most hooks use `firstresult=True`; the exception is
`ws_get_workflow_metadata` which collects results from all plugins. All hook method names are prefixed with `ws_`.

Workspace plugins are loaded by `WorkspacePluginManager` which:

1. Creates a `pluggy.PluginManager` with the `"sase_workspace"` project name.
2. Registers the `WorkspaceHookSpec`.
3. Loads plugins from the `sase_workspace` entry point group.

See [docs/workspace.md](workspace.md) for the full workspace provider reference.

### XPrompt Plugins

Plugin packages can contribute xprompt templates by declaring a `sase_xprompts` entry point that points to a module. The
module's package directory is searched for `xprompts/*.md` and `xprompts/*.yml` files. Plugin xprompts are priority 7 in
the [discovery order](xprompt.md#discovery-order) (above built-in, below config-based).

### Config Plugins

Plugin packages can provide default configuration by declaring a `sase_config` entry point. The referenced module's
package must contain a `default_config.yml` file. Plugin configs are merged between the bundled package defaults and the
user's `sase.yml`. See the [Deep-Merge System](configuration.md#deep-merge-system) for details on the merge chain.

## Disabling Plugins

Plugins can be disabled via environment variables:

| Variable                        | Effect                         |
| ------------------------------- | ------------------------------ |
| `SASE_DISABLE_PLUGINS`          | Disable all plugin groups      |
| `SASE_DISABLE_PLUGIN_VCS`       | Disable VCS plugins only       |
| `SASE_DISABLE_PLUGIN_WORKSPACE` | Disable workspace plugins only |
| `SASE_DISABLE_PLUGIN_XPROMPTS`  | Disable xprompt plugins only   |
| `SASE_DISABLE_PLUGIN_CONFIG`    | Disable config plugins only    |

Any non-empty value enables the disable. This is useful for debugging or when a plugin causes issues.

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
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        # Implementation here
        ...

    @hookimpl
    def vcs_diff(self, cwd: str) -> tuple[bool, str | None]:
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
