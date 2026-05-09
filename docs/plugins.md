# Plugin System

Sase uses Python [entry points](https://packaging.python.org/en/latest/specifications/entry-points/) to discover
optional functionality installed in the same Python environment as `sase`. Runtime providers use
[pluggy](https://pluggy.readthedocs.io/) hooks; resource plugins expose package data such as xprompt files and
`default_config.yml`.

The core `sase` package provides the plugin infrastructure, the built-in LLM providers, and local git/directory
workspace support. Extra packages add hosted VCS workflows, internal workflows, or integrations without changing the
core package.

## Plugin Groups

Sase defines five entry point groups:

| Entry Point Group | Entry Point Value | Purpose                                             | Example Plugin               |
| ----------------- | ----------------- | --------------------------------------------------- | ---------------------------- |
| `sase_vcs`        | Provider class    | VCS provider plugins (git, hg, etc.)                | `sase-github`                |
| `sase_workspace`  | Provider class    | Workspace provider plugins (ref resolution, submit) | `sase-github`                |
| `sase_llm`        | Provider class    | LLM provider plugins                                | built-in providers, Jetski   |
| `sase_xprompts`   | Package module    | XPrompt templates and workflows                     | `sase-google`                |
| `sase_config`     | Package module    | Default configuration (`default_config.yml`)        | `sase-google`, `sase-github` |

Provider-class entry points resolve to a class that is instantiated and registered with pluggy. Package-module entry
points resolve to a module whose package resources are read by Sase.

## Available Plugin Packages

| Package         | Description                                                                             | Entry Points                                                                                                       |
| --------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `sase` (core)   | Bare-git VCS, bare-git and `#cd` workspaces, and built-in LLM providers                 | `sase_vcs: bare_git`, `sase_workspace: bare_git, cd`, `sase_llm: claude, codex, gemini, opencode, qwen`            |
| `sase-github`   | GitHub VCS and workspace support, including GitHub CLI (`gh`) PR operations             | `sase_vcs: github`, `sase_workspace: github`, `sase_config: sase_github`, `sase_xprompts: sase_github`             |
| `sase-google`   | Mercurial VCS/workspace support, Jetski LLM provider, helper scripts, config, xprompts  | `sase_llm: jetski`, `sase_vcs: hg`, `sase_workspace: hg`, `sase_config: sase_google`, `sase_xprompts: sase_google` |
| `sase-telegram` | Telegram integration via chop scripts (`sase_chop_tg_outbound`, `sase_chop_tg_inbound`) | CLI scripts (not pluggy entry points)                                                                              |
| `sase-nvim`     | Neovim integration, including project spec syntax and prompt helpers                    | standalone Neovim plugin files (not Python entry points)                                                           |

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

Plugin discovery uses `importlib.metadata.entry_points()` to find installed packages that declare one of Sase's entry
point groups.

There are two discovery paths:

1. **Provider classes**: `sase_vcs`, `sase_workspace`, and `sase_llm` entry points resolve to classes. The relevant
   registry loads the class, instantiates it, and registers the instance with a pluggy `PluginManager`.
2. **Package resources**: `sase_xprompts` and `sase_config` entry points resolve to modules. The shared helper in
   `src/sase/main/plugin_discovery.py` sorts those entry points by name, loads the modules, and skips module load
   failures after logging them at debug level.

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

Core Sase ships Claude, Codex, Gemini, Qwen, and OpenCode providers as built-in entry points. Additional providers
belong in external plugin packages that declare `sase_llm` entry points and provide their own metadata hooks. The
`sase-google` package currently contributes a `jetski` provider.

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
