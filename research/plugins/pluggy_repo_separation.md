# Prior Art: Splitting Pluggy Plugins into Separate Repos/Packages

Research for extracting sase's VCS provider plugins (GitHub, Hg/Fig) into standalone packages while keeping the bare-git
plugin built-in.

## Current State in sase

- **Pluggy project name**: `"sase_vcs"`
- **Entry point group**: `"sase_vcs"`
- **Hookspec**: `src/sase/vcs_provider/_hookspec.py` -- 55 `@hookspec(firstresult=True)` methods, all prefixed `vcs_*`
- **Plugin manager**: `VCSPluginManager(VCSProvider)` wraps `pluggy.PluginManager`, delegates every ABC method to
  `self._pm.hook.vcs_*()`
- **Built-in plugins**: `GitHubPlugin`, `BareGitPlugin` (share `GitCommon` mixin), `HgPlugin`
- **Registration**: `pm.load_setuptools_entrypoints("sase_vcs")` + explicit `pm.register()` in factory functions
- **Entry points** (pyproject.toml):
  ```toml
  [project.entry-points."sase_vcs"]
  github = "sase.vcs_provider.plugins.github:GitHubPlugin"
  bare_git = "sase.vcs_provider.plugins.bare_git:BareGitPlugin"
  hg = "sase.vcs_provider.plugins.hg:HgPlugin"
  ```

---

## How Major Projects Handle This

### 1. pytest (canonical example)

| Aspect            | Value                     |
| ----------------- | ------------------------- |
| PM name           | `"pytest"`                |
| Entry point group | `pytest11`                |
| Package prefix    | `pytest-*`                |
| Hook prefix       | `pytest_*`                |
| Hookspec location | `src/_pytest/hookspec.py` |

**Architecture:**

- Core defines all hookspecs in one module with `HookspecMarker("pytest")`
- `PytestPluginManager` subclasses `pluggy.PluginManager` directly
- Three plugin tiers: built-in (`_pytest/` modules, registered programmatically), external (via `pytest11` entry
  points), and local (`conftest.py` files)

**External plugin pattern** (e.g., pytest-xdist):

```toml
# pytest-xdist/pyproject.toml
[project]
dependencies = ["execnet>2.1", "pytest>7.0.0"]

[project.entry-points.pytest11]
xdist = "xdist.plugin"
xdist.looponfail = "xdist.looponfail"
```

- Plugin lives in its own repo under the `pytest-dev` GitHub org
- Depends on `pytest` with a floor version, no upper bound
- Module contains `@pytest.hookimpl`-decorated functions

**Plugin author tooling:**

- `pytester` fixture for integration-testing plugins (spawns isolated pytest runs)
- [cookiecutter-pytest-plugin](https://github.com/pytest-dev/cookiecutter-pytest-plugin) template
- PyPI classifier: `Framework :: Pytest`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD` env var to suppress entry point loading

**Versioning strategy:**

- Hook signatures are stable; new optional parameters added in backwards-compatible ways
- Deprecated features kept for at least two minor releases
- Breaking changes only in major versions

---

### 2. tox

| Aspect            | Value        |
| ----------------- | ------------ |
| PM name           | `"tox"`      |
| Entry point group | `tox`        |
| Package prefix    | `tox-*`      |
| Hook prefix       | `tox_*`      |
| Local plugin      | `toxfile.py` |

**Plugin pattern** (e.g., tox-uv):

```toml
# tox-uv/pyproject.toml
[project]
dependencies = ["tox<5,>4.34.1"]

[project.entry-points.tox]
tox-uv = "tox_uv.plugin"
```

- Pins floor AND ceiling on tox (`tox<5,>=4.34.1`)
- Uses `from tox.plugin import impl` (re-exported hookimpl marker)
- Notable plugins: tox-uv, tox-gh-actions, tox-docker

---

### 3. devpi (most instructive for multi-package split)

| Aspect            | Value           |
| ----------------- | --------------- |
| PM name           | `"devpiserver"` |
| Entry point group | `devpi_server`  |
| Package prefix    | `devpi-*`       |
| Hook prefix       | `devpiserver_*` |

**Architecture -- monorepo with separate packages:**

```
devpi/devpi/          # Single Git repo
  server/             # devpi-server (core, defines hookspecs)
  client/             # devpi-client (CLI tool)
  web/                # devpi-web (UI plugin for devpi-server)
```

- Three packages live in subdirectories of one repo
- `devpi-web` registers as a `devpi_server` entry point and is auto-discovered when installed alongside `devpi-server`
- Third-party plugins (devpi-ldap, devpi-postgresql) live in separate repos

**Plugin implementation** (from devpi-ldap):

```python
from pluggy import HookimplMarker
server_hookimpl = HookimplMarker("devpiserver")

@server_hookimpl
def devpiserver_add_parser_options(parser):
    ...

@server_hookimpl(trylast=True)
def devpiserver_auth_request(request):
    ...
```

**Key detail:** PM name (`"devpiserver"`) differs from entry point group (`"devpi_server"`). This works because
`HookimplMarker` uses the PM name, while `load_setuptools_entrypoints()` uses the entry point group.

---

### 4. Datasette

| Aspect            | Value         |
| ----------------- | ------------- |
| PM name           | `"datasette"` |
| Entry point group | `datasette`   |
| Package prefix    | `datasette-*` |
| Hook prefix       | none          |

**Built-in plugin registration (most relevant pattern):**

```python
DEFAULT_PLUGINS = (
    "datasette.publish.heroku",
    "datasette.publish.cloudrun",
    "datasette.facets",
    "datasette.filters",
    # ...
)

for plugin in DEFAULT_PLUGINS:
    mod = importlib.import_module(plugin)
    pm.register(mod, plugin)
```

Built-in plugins are imported and registered with `pm.register()`. External plugins use
`pm.load_setuptools_entrypoints("datasette")`.

**Plugin management features:**

- `datasette install <plugin>` wraps pip
- `--plugins-dir=plugins/` for local `.py` file plugins
- `DATASETTE_LOAD_PLUGINS` env var for selective loading
- `datasette plugins` / `/-/plugins.json` for introspection
- [cookiecutter-datasette-plugin](https://github.com/simonw/datasette-plugin) template
- [datasette-test](https://github.com/datasette/datasette-test) package with test utilities

---

### 5. Hypothesis (simpler approach -- no pluggy hooks)

| Aspect            | Value          |
| ----------------- | -------------- |
| Entry point group | `hypothesis`   |
| Package prefix    | `hypothesis-*` |

Uses raw `importlib.metadata.entry_points(group="hypothesis")` without pluggy's hookspec/hookimpl pattern. Plugins are
just callables invoked at startup. `HYPOTHESIS_NO_PLUGINS` env var to disable.

---

## Cross-Project Pattern Summary

| Pattern            | pytest               | tox               | devpi                 | Datasette              |
| ------------------ | -------------------- | ----------------- | --------------------- | ---------------------- |
| Separate repos     | Yes (pytest-dev org) | Yes (tox-dev org) | Monorepo + separate   | Yes (datasette org)    |
| Plugin dep on core | `pytest>7.0.0`       | `tox<5,>4.34.1`   | `devpi-server>=2.1.0` | `datasette>=0.64`      |
| Dep upper bound?   | No                   | Yes (major)       | No                    | No                     |
| Built-in plugins   | `_pytest/` modules   | Internal          | In-repo packages      | `DEFAULT_PLUGINS` list |
| Cookiecutter       | Yes                  | No                | No                    | Yes                    |
| Test utilities     | `pytester` fixture   | --                | --                    | `datasette.client`     |
| Plugin disable     | Env var              | --                | Constructor param     | Env var                |
| PyPI classifier    | Yes                  | No                | No                    | No                     |

---

## Recommendations for sase

### Package Naming

Follow the `<project>-<plugin>` convention:

| Plugin              | Package name      | Import path                          |
| ------------------- | ----------------- | ------------------------------------ |
| GitHub VCS          | `sase-vcs-github` | `sase_vcs_github`                    |
| Hg/Fig VCS          | `sase-vcs-hg`     | `sase_vcs_hg`                        |
| Bare Git (built-in) | stays in `sase`   | `sase.vcs_provider.plugins.bare_git` |

### Entry Points

Each external plugin registers under the same `"sase_vcs"` group:

```toml
# sase-vcs-github/pyproject.toml
[project.entry-points."sase_vcs"]
github = "sase_vcs_github:GitHubPlugin"
```

```toml
# sase-vcs-hg/pyproject.toml
[project.entry-points."sase_vcs"]
hg = "sase_vcs_hg:HgPlugin"
```

```toml
# sase/pyproject.toml (core, only bare_git remains)
[project.entry-points."sase_vcs"]
bare_git = "sase.vcs_provider.plugins.bare_git:BareGitPlugin"
```

### What to Export from Core

The core `sase` package needs to export everything plugin authors need:

1. **`hookimpl` marker** -- so plugins can decorate methods without importing pluggy directly
2. **`CommandRunner` mixin** -- shared subprocess helpers (`_run`, `_run_shell`, `_to_result`)
3. **`CommandOutput` dataclass** -- return type of `_run` methods
4. **`VCSHookSpec`** -- for reference/documentation, not typically needed by plugin code

Recommended public API surface:

```python
# sase.vcs_provider (or a new sase.vcs_provider.api module)
from sase.vcs_provider._hookspec import hookimpl
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._types import CommandOutput
```

### Dependency Management

External plugins should depend on `sase` with a floor version:

```toml
dependencies = ["sase>=<version-where-plugin-api-stabilized>"]
```

Follow pytest's pattern: floor version, no upper bound. Only cap at the next major version if you expect breaking
changes.

### Built-in Plugin Registration

Use the Datasette pattern -- register `BareGitPlugin` explicitly while also loading entry points:

```python
def _create_plugin_manager() -> pluggy.PluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)

    # Built-in plugin (always available)
    from sase.vcs_provider.plugins.bare_git import BareGitPlugin
    pm.register(BareGitPlugin(), "bare_git")

    # External plugins (discovered from installed packages)
    pm.load_setuptools_entrypoints("sase_vcs")

    return pm
```

Alternatively, keep `bare_git` registered via the `sase` package's own entry point (current approach). Both work;
explicit registration avoids a setuptools round-trip but entry points are more uniform.

### Plugin Disable Mechanism

Add an env var for disabling auto-loaded plugins (useful for debugging):

```python
if not os.environ.get("SASE_DISABLE_VCS_PLUGINS"):
    pm.load_setuptools_entrypoints("sase_vcs")
```

### Repo Organization Options

**Option A: Separate repos (pytest model)**

```
github.com/bbugyi200/sase           # core + bare_git
github.com/bbugyi200/sase-vcs-github
github.com/bbugyi200/sase-vcs-hg
```

- Clean separation, independent release cycles
- Used by pytest-dev, datasette

**Option B: Monorepo with separate packages (devpi model)**

```
github.com/bbugyi200/sase/
  src/sase/                          # core + bare_git
  plugins/sase-vcs-github/           # separate package
  plugins/sase-vcs-hg/              # separate package
```

- Easier to make cross-cutting changes, single CI pipeline
- Used by devpi

**Recommendation:** Start with the monorepo approach (Option B). It's easier to iterate on the plugin API when hookspecs
and implementations live in the same repo. Migrate to separate repos later if the plugins attract external contributors
or the monorepo becomes unwieldy.

### GitCommon Mixin Strategy

`GitCommon` is shared between `GitHubPlugin` (external) and `BareGitPlugin` (built-in). Three options:

1. **Keep in core**: Export `GitCommon` from `sase.vcs_provider.plugins._git_common`. The GitHub plugin imports it from
   the core package. Simple but creates a tighter coupling.

2. **Duplicate**: Copy the shared code into each plugin. Avoids coupling but creates maintenance burden (40+ methods).

3. **Extract to a shared package**: Create `sase-vcs-git-common` as a lightweight dependency. Clean but adds another
   package to manage.

**Recommendation:** Option 1 (keep in core). `GitCommon` is part of the plugin API surface -- it's reasonable for the
core package to provide base classes that plugins build on. This is analogous to how Django provides base classes for
third-party apps.

### Testing Utilities

Consider providing a test fixture or helper for plugin authors:

```python
# sase.vcs_provider.testing
def make_plugin_manager(*plugins) -> VCSPluginManager:
    """Create a VCSPluginManager with the given plugins for testing."""
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        pm.register(plugin)
    return VCSPluginManager(pm)
```

### Migration Checklist

1. Stabilize the hookspec API (add versioning or commit to the current signatures)
2. Define the public plugin-author API surface (`hookimpl`, `CommandRunner`, `CommandOutput`, `GitCommon`)
3. Export these from a stable module path (e.g., `sase.vcs_provider.api`)
4. Create the external plugin packages with their own pyproject.toml, entry points, and tests
5. Remove the extracted plugins from core's pyproject.toml entry points
6. Update core's `_create_plugin_manager()` to rely on `load_setuptools_entrypoints()` for external plugins
7. Add plugin disable env var
8. Document the plugin authoring process
9. Consider a cookiecutter template if you expect community plugins
