# SASE Plugin Architecture: Beyond VCS

Analysis of sase's plugin requirements in light of the [pluggy repo separation research](./pluggy_repo_separation.md),
extended to cover the full range of extension points that user plugins need to supply.

## The Problem

The pluggy repo separation doc focuses exclusively on VCS provider plugins -- a single, well-scoped pluggy hookspec
(`sase_vcs`) with `firstresult=True` semantics. But sase's actual plugin surface is much wider. A user plugin like
`sase-some-user-plugin` needs to be able to contribute:

1. **XPrompts and workflows** -- `.md` and `.yml` files discoverable via `#name` syntax
2. **Config defaults** -- `sase.yml`-style defaults (lumberjack definitions, axe settings, etc.)
3. **Chop scripts** -- executables for the axe scheduler system
4. **Metahook scripts** -- executables triggered by failing hook patterns

None of these fit the pluggy hookspec/hookimpl pattern. They're **resource contributions**, not **callback
implementations**.

---

## Current Discovery Mechanisms

### XPrompts and Workflows

**Code**: `src/sase/xprompt/loader.py`, `src/sase/xprompt/workflow_loader.py`

Discovery is purely filesystem-based, scanning directories in priority order:

| Priority    | Location                             | Type             |
| ----------- | ------------------------------------ | ---------------- |
| 1 (highest) | `.xprompts/` (CWD)                   | File-based       |
| 2           | `xprompts/` (CWD)                    | File-based       |
| 3           | `~/.xprompts/`                       | File-based       |
| 4           | `~/xprompts/`                        | File-based       |
| 5           | `~/.config/sase/xprompts/{project}/` | Project-specific |
| 6           | `sase.yml` `xprompts:` section       | Config-based     |
| 7 (lowest)  | `<sase_package>/xprompts/`           | Internal         |

XPrompts are `.md` files (with optional YAML front matter for inputs). Workflows are `.yml`/`.yaml` files with
multi-step definitions. First occurrence of a name wins.

**Gap**: There is no entry-point-based discovery. An installed `sase-foo` package cannot contribute xprompts unless the
user manually symlinks or copies files into one of the search paths.

### Config (sase.yml)

**Code**: `src/sase/config.py`

Three-layer merge:

1. `default_config.yml` (bundled in `sase` package via `importlib.resources`)
2. `~/.config/sase/sase.yml` (user config -- lists **replace**)
3. `~/.config/sase/sase_*.yml` overlays (sorted alphabetically -- lists **concatenate**)

**Gap**: No mechanism for an installed package to inject a config layer. A plugin wanting to provide lumberjack defaults
would need to instruct users to manually create an overlay file.

### Chop Scripts

**Code**: `src/sase/axe/chop_script_runner.py`

Two-stage discovery:

1. Search `axe.chop_script_dirs` (configured list) for an executable matching the chop name
2. Fall back to `shutil.which("sase_chop_<name>")` on `$PATH`

**Partial solution**: Chop scripts CAN already be contributed by installed packages via `[project.scripts]` entry points
(e.g., `sase_chop_hook_checks = "sase.scripts:sase_chop_hook_checks"`). Any pip-installed package that exposes a
`sase_chop_*` script will be found by `shutil.which`. This works today without changes.

**Gap**: The chop must also be referenced in a lumberjack definition to actually run. A plugin can install the script,
but can't register it with a lumberjack without also contributing config.

### Metahook Scripts

**Code**: `src/sase/metahook_config.py`, metahook scripts via `[project.scripts]`

Metahooks have two parts:

1. **Config** (`metahooks:` section in `sase.yml`): defines `name`, `hook_command` substring, and `output_regex`
2. **Script** (`sase_metahook_<name>` on `$PATH`): executed when config matches

Like chops, the script part already works via `[project.scripts]`. The config part does not -- a plugin can install
`sase_metahook_foo` but can't register the matching rule without contributing config.

---

## What User Plugins Need

A user plugin (`sase-some-user-plugin`) installed alongside `sase` should be able to:

| Capability                 | Current state                         | What's needed                           |
| -------------------------- | ------------------------------------- | --------------------------------------- |
| Add xprompts/workflows     | Not possible (filesystem only)        | Entry-point or resource-based discovery |
| Override xprompts          | Not possible for installed packages   | Priority-aware merge from plugins       |
| Provide config defaults    | Not possible                          | Plugin config layer in merge chain      |
| Add chop scripts           | Works (via `sase_chop_*` on PATH)     | Also needs config contribution          |
| Add metahook scripts       | Works (via `sase_metahook_*` on PATH) | Also needs config contribution          |
| Add lumberjack definitions | Not possible                          | Via config contribution                 |

---

## Analysis of Approaches

### Approach A: Pluggy Hooks for Everything

Extend the pluggy system with new hookspecs for each resource type:

```python
class SasePluginSpec:
    @hookspec
    def sase_get_xprompts(self) -> dict[str, XPrompt]: ...

    @hookspec
    def sase_get_config_defaults(self) -> dict[str, Any]: ...

    @hookspec
    def sase_get_metahooks(self) -> list[MetahookConfig]: ...
```

**Pros**: Uniform plugin interface, full programmatic control, familiar to pluggy users.

**Cons**: Overkill for static resource contribution. Most plugins just want to ship files, not write Python classes.
Forces every xprompt contributor to write a Python hookimpl returning data that could just be YAML on disk. The VCS
hookspec works because plugins genuinely implement different _behavior_; xprompts and config are just _data_.

### Approach B: Entry-Point Resource Discovery

Use Python packaging entry points to point to directories or files within installed packages, letting the existing
filesystem-based loaders pick them up:

```toml
# sase-some-user-plugin/pyproject.toml
[project.entry-points."sase_xprompts"]
my_plugin = "sase_some_user_plugin:xprompts"  # points to a package directory

[project.entry-points."sase_config"]
my_plugin = "sase_some_user_plugin:default_config.yml"  # points to a YAML resource
```

**Pros**: Plugin authors just ship files in their package (`.md`, `.yml`). No Python code needed for pure resource
plugins. Natural extension of the existing file-based discovery.

**Cons**: Entry points pointing to directories require `importlib.resources` traversal. Resource files inside packages
need `importlib.resources` (not plain `Path`) for zip-safe compatibility. Slightly more complex than a single hookimpl.

### Approach C: Hybrid (Recommended)

Use **entry points for resource discovery** (xprompts, config, metahook config) and keep **pluggy hookspecs for
behavioral plugins** (VCS, and potentially future behavioral extension points). This matches the nature of each
extension type:

- **Behavioral** (VCS providers, future LLM providers): pluggy hookspec/hookimpl
- **Resource** (xprompts, workflows, config defaults, metahook rules): entry-point resource discovery

This is exactly what Datasette does: pluggy hooks for behavioral extension, but `--plugins-dir` and
`DATASETTE_LOAD_PLUGINS` for resource/file-based plugins.

---

## Recommended Architecture

### 1. XPrompt/Workflow Plugin Discovery

Add a new entry point group `"sase_xprompts"` for packages that contribute xprompts and workflows.

**Plugin side** (`sase-some-user-plugin/pyproject.toml`):

```toml
[project.entry-points."sase_xprompts"]
my_plugin = "sase_some_user_plugin"
```

The entry point value is a Python package (importable module). The loader uses `importlib.resources` to find an
`xprompts/` subdirectory within that package, then scans it for `.md` and `.yml` files using the same parsing logic
already in `loader.py` and `workflow_loader.py`.

**Plugin package layout**:

```
sase-some-user-plugin/
  src/sase_some_user_plugin/
    __init__.py
    xprompts/
      my_prompt.md          # xprompt part
      my_workflow.yml        # xprompt workflow
```

**Core changes** (`loader.py` and `workflow_loader.py`):

Add a new loader function that sits between config-based and internal xprompts in the priority chain:

```
Priority 1-4: Filesystem (CWD, home) -- unchanged
Priority 5:   Project-specific -- unchanged
Priority 6:   Config (sase.yml xprompts:) -- unchanged
Priority 7:   ** NEW: Installed plugin xprompts (via sase_xprompts entry points) **
Priority 8:   Internal sase package xprompts -- unchanged (was priority 7)
```

This means:

- User's local xprompts always win (priorities 1-6)
- Plugin xprompts are available by default (priority 7)
- Sase's built-in xprompts have lowest priority (priority 8)
- A user can override any plugin xprompt by placing a same-named file in their xprompts dir

**Implementation sketch** (new function in `loader.py`):

```python
def _load_xprompts_from_plugins() -> dict[str, XPrompt]:
    """Load xprompts from installed plugin packages.

    Discovers packages registered under the 'sase_xprompts' entry point
    group and scans their bundled xprompts/ directories.
    """
    from importlib.metadata import entry_points
    import importlib.resources

    xprompts: dict[str, XPrompt] = {}

    for ep in entry_points(group="sase_xprompts"):
        try:
            module = ep.load()
            xprompts_dir = importlib.resources.files(module) / "xprompts"
            # Iterate over .md files in the resource directory
            for resource in xprompts_dir.iterdir():
                if resource.name.endswith(".md"):
                    content = resource.read_text(encoding="utf-8")
                    xprompt = _parse_xprompt_content(resource.name, content)
                    if xprompt and xprompt.name not in xprompts:
                        xprompts[xprompt.name] = xprompt
        except Exception:
            log.debug("Failed to load xprompts from plugin %s", ep.name, exc_info=True)

    return xprompts
```

The same pattern applies to workflows (scan for `.yml`/`.yaml` in the same `xprompts/` directory).

### 2. Config Defaults from Plugins

Add a new entry point group `"sase_config"` for packages that contribute config defaults.

**Plugin side**:

```toml
[project.entry-points."sase_config"]
my_plugin = "sase_some_user_plugin"
```

The loader uses `importlib.resources` to find a `default_config.yml` within the plugin package.

**Plugin package layout**:

```
sase-some-user-plugin/
  src/sase_some_user_plugin/
    __init__.py
    default_config.yml      # plugin's config defaults
    xprompts/
      ...
```

**Config merge chain** (extended):

```
1. sase default_config.yml (bundled package defaults)
2. ** NEW: Plugin default_config.yml files (via sase_config entry points, sorted by EP name) **
3. ~/.config/sase/sase.yml (user config -- lists replace)
4. ~/.config/sase/sase_*.yml overlays (sorted -- lists concatenate)
```

Plugin configs are merged with **list concatenation** semantics (like overlays), and are applied in entry-point-name
sorted order for determinism. User config always wins because it comes later in the chain.

This lets a plugin define:

```yaml
# sase_some_user_plugin/default_config.yml
axe:
  lumberjacks:
    my_custom_scheduler:
      interval: 60
      chops:
        - name: my_custom_chop
          description: "Run my plugin's custom check"

metahooks:
  - name: my_tool
    hook_command: "my-tool check"
    output_regex: "FAIL:.*"
```

When installed, the lumberjack and metahook definitions merge into the user's config automatically.

**Implementation sketch** (changes to `config.py`):

```python
def _load_plugin_configs() -> list[dict[str, Any]]:
    """Load default configs from installed plugin packages."""
    from importlib.metadata import entry_points
    import importlib.resources

    configs = []
    for ep in sorted(entry_points(group="sase_config"), key=lambda e: e.name):
        try:
            module = ep.load()
            ref = importlib.resources.files(module).joinpath("default_config.yml")
            text = ref.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                configs.append(data)
        except Exception:
            log.debug("Failed to load config from plugin %s", ep.name, exc_info=True)
    return configs


def load_merged_config() -> dict[str, Any]:
    result = _load_default_config()

    # NEW: Plugin config defaults (concatenate lists)
    for plugin_config in _load_plugin_configs():
        result = _deep_merge(result, plugin_config)

    # User config (lists replace)
    base_path = CONFIG_DIR / "sase.yml"
    user_base = _load_yaml_file(base_path)
    if user_base:
        result = _deep_merge(result, user_base, list_strategy="replace")

    # Overlays (lists concatenate)
    for overlay_path in _get_overlay_paths():
        overlay = _load_yaml_file(overlay_path)
        if overlay:
            result = _deep_merge(result, overlay)

    return result
```

### 3. Chop and Metahook Scripts

These already work via `[project.scripts]` entry points. A plugin just needs:

```toml
[project.scripts]
sase_chop_my_check = "sase_some_user_plugin.scripts:my_check"
sase_metahook_my_tool = "sase_some_user_plugin.scripts:my_tool_metahook"
```

The scripts land on `$PATH` after `pip install` and are found by `shutil.which("sase_chop_my_check")` and
`shutil.which("sase_metahook_my_tool")` respectively.

**Combined with config contribution** (section 2 above), a plugin can both install the script AND register it with a
lumberjack or metahook rule, making the chop/metahook fully functional on install with zero user configuration.

### 4. Entry Point Groups Summary

| Group           | Purpose                | Entry point value | Resource discovered               |
| --------------- | ---------------------- | ----------------- | --------------------------------- |
| `sase_vcs`      | VCS provider plugins   | Plugin class      | Pluggy hookimpl (behavioral)      |
| `sase_xprompts` | XPrompts and workflows | Python package    | `xprompts/*.md`, `xprompts/*.yml` |
| `sase_config`   | Config defaults        | Python package    | `default_config.yml`              |

Scripts (`sase_chop_*`, `sase_metahook_*`) use standard `[project.scripts]` -- no custom entry point group needed.

### 5. Plugin Disable Mechanism

For debugging, add env vars to suppress plugin auto-loading:

```python
SASE_DISABLE_PLUGINS=1          # Disable ALL plugin entry points
SASE_DISABLE_PLUGIN_XPROMPTS=1  # Disable only xprompt plugins
SASE_DISABLE_PLUGIN_CONFIG=1    # Disable only config plugins
SASE_DISABLE_PLUGIN_VCS=1       # Disable only VCS plugins
```

### 6. Example: Complete User Plugin

```
sase-my-tools/
  pyproject.toml
  src/sase_my_tools/
    __init__.py
    default_config.yml
    xprompts/
      review.md             # adds #review xprompt
      deploy.yml            # adds #deploy workflow
    scripts.py              # chop + metahook entry points
```

```toml
# pyproject.toml
[project]
name = "sase-my-tools"
dependencies = ["sase>=1.0"]

[project.scripts]
sase_chop_deploy_check = "sase_my_tools.scripts:deploy_check"
sase_metahook_deploy = "sase_my_tools.scripts:deploy_metahook"

[project.entry-points."sase_xprompts"]
my_tools = "sase_my_tools"

[project.entry-points."sase_config"]
my_tools = "sase_my_tools"
```

After `pip install sase-my-tools`:

- `#review` and `#deploy` are available in agent prompts
- The `deploy_check` chop runs on the schedule defined in `default_config.yml`
- The `deploy` metahook intercepts matching failing hooks
- The user can override `#review` by placing their own `review.md` in `.xprompts/`
- The user can override config by setting values in `~/.config/sase/sase.yml`

### 7. Migration Path

1. **Phase 1 -- Plugin xprompts**: Add `sase_xprompts` entry point scanning to `loader.py` and `workflow_loader.py`.
   This is the highest-value change since xprompts are sase's primary extension surface.

2. **Phase 2 -- Plugin config**: Add `sase_config` entry point scanning to `config.py`. This unlocks chop and metahook
   registration from plugins.

3. **Phase 3 -- VCS extraction**: Move VCS plugins to separate packages per the repo separation doc. This is lower
   priority since VCS plugins are already internal.

4. **Phase 4 -- Plugin tooling**: Cookiecutter template, `sase plugins` introspection command, documentation for plugin
   authors.
