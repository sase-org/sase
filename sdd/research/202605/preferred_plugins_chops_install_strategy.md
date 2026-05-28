# Preferred Plugin and Chop Install Strategy

Date: 2026-05-28

## Question

How should SASE make it easy for a user to install `sase` together with the plugins and chops they prefer, without
requiring them to know Python packaging internals?

## Summary

The install story needs two layers:

1. **Package co-installation:** `sase` and Python plugin/chop packages must be installed into the same Python tool
   environment. SASE discovers provider and resource plugins through Python entry points, so installing `sase` as a
   `uv tool` and then installing `sase-github` into an unrelated project venv silently does nothing.
2. **SASE activation:** some installed packages are usable immediately, but scheduled chops also need SASE config. A
   chop script being present is not enough; AXE only runs chops registered under `axe.lumberjacks`.

Recommended public first-party install shape after a coordinated `0.2.0` release:

```bash
uv tool install "sase[github]>=0.2,<0.3"
sase init --yes
sase plugin doctor
```

For credentialed chop integrations such as Telegram:

```bash
uv tool install "sase[github,telegram]>=0.2,<0.3"
sase init --yes
sase chop enable telegram
sase plugin doctor
```

The strongest path is staged:

1. Add first-party PyPI extras: `sase[github]`, `sase[telegram]`, `sase[recommended]`, `sase[all]`.
2. Add `sase plugin list` and `sase plugin doctor`.
3. Add `sase plugin add/remove` that installs into the same environment as the running `sase`.
4. Add a declarative preferred-set manifest plus `sase plugin sync`.
5. Add chop manifests and explicit `sase chop enable/disable` for integrations that should not auto-run when installed.
6. Defer `sase-full` and `curl | sh`; extras and `uv tool install --with ...` cover the high-value cases with less
   release and security surface.

## Current Architecture

### Plugins

`pyproject.toml` currently declares built-in entry points for:

- `sase_llm`
- `sase_vcs`
- `sase_workspace`

Installed packages can contribute resource defaults through:

- `sase_xprompts`
- `sase_config`

`src/sase/main/plugin_discovery.py` loads resource entry points with `importlib.metadata.entry_points(group=...)`,
sorted by entry-point name. Failed resource plugin loads are skipped and logged at debug level, so users currently lack
a CLI diagnostic when a plugin is installed but not active.

`src/sase/config/core.py` merges config in this order:

1. Bundled `src/sase/default_config.yml`
2. Plugin `default_config.yml` files from `sase_config`
3. `~/.config/sase/sase.yml` with list replacement
4. `~/.config/sase/sase_*.yml` overlays with list concatenation
5. Local `./sase.yml` with list concatenation

This makes plugin config a good place for safe defaults. It is not enough for credentialed recurring integrations where
package install should not automatically schedule repeated failing work.

### Chops

AXE runs configured chops from `axe.lumberjacks.*.chops`. For script chops,
`src/sase/axe/chop_script_runner.py` resolves a chop named `foo` as:

1. executable `foo` in `axe.chop_script_dirs`
2. executable `sase_chop_foo` beside the running Python interpreter
3. executable `sase_chop_foo` on `PATH`

That is a good packaging contract. A Python plugin package can expose `[project.scripts]` entries such as
`sase_chop_tg_outbound`, and SASE can find them from the same `uv tool` or `pipx` environment even when those commands
are not linked onto the user's shell `PATH`.

The missing part is activation and inventory. SASE cannot currently answer which package owns a chop, whether the chop
is installed but inactive, what credentials it needs, or whether it is safe to auto-enable.

## Current First-Party Package State

Verified locally on 2026-05-28:

| Package | Current local facts | Install implication |
| --- | --- | --- |
| `sase` | `0.1.0`; depends on `sase-core-rs>=0.1.1,<0.2.0`; no plugin extras today. | Needs first-party extras and coordinated public release metadata before advertising one-command bundles. |
| `sase-github` | `0.1.0`; depends on `sase>=0.1.0`; contributes `sase_vcs`, `sase_workspace`, `sase_config`, and `sase_xprompts`; default config is currently `xprompts: {}`. | Passive plugin. Co-installation is enough for discovery, but `gh`/`gh auth` should be checked by doctor. |
| `sase-telegram` | `0.1.0`; depends on `sase>=0.1.0`; exposes `sase_chop_tg_outbound` and `sase_chop_tg_inbound`; has no `sase_config` entry point today. | Package install makes scripts available, but nothing schedules them. Needs explicit activation and credential diagnostics. |
| `sase-nvim` | Neovim plugin files, not a Python package. Depends on `sase` being on `PATH`. | Treat as an editor integration recommendation, not a `uv tool --with` package. |

Verified via PyPI JSON on 2026-05-28:

| Package | PyPI status | Latest public version | Notes |
| --- | --- | --- | --- |
| `sase` | present | `0.1.0` | Uploaded 2026-02-23. |
| `sase-github` | present | `0.1.0` | Uploaded 2026-02-23. |
| `sase-telegram` | 404 | none | Must be published before public bundle install works. |
| `sase-core-rs` | 404 | none | Must be published before current `sase` can install cleanly from PyPI. |

The public docs should target a new coordinated line, e.g. `sase>=0.2,<0.3`,
`sase-github>=0.2,<0.3`, and `sase-telegram>=0.2,<0.3`.

## Recommended UX

### First-party bundles

Add optional dependencies to `sase`:

```toml
[project.optional-dependencies]
github = ["sase-github>=0.2,<0.3"]
telegram = ["sase-telegram>=0.2,<0.3"]
recommended = ["sase-github>=0.2,<0.3"]
all = ["sase-github>=0.2,<0.3", "sase-telegram>=0.2,<0.3"]
```

This solves the same-environment footgun for curated first-party plugins because extras are resolved in the same install
transaction:

```bash
uv tool install "sase[recommended]>=0.2,<0.3"
pipx install "sase[github]>=0.2,<0.3"
python -m pip install "sase[github]>=0.2,<0.3"
```

Extras should be the public quickstart for first-party packages. They are not enough for private or third-party plugins.

### Third-party/private plugins

Keep the explicit package path:

```bash
uv tool install "sase>=0.2,<0.3" --with "sase-some-plugin>=1,<2"
```

For pipx:

```bash
pipx install "sase>=0.2,<0.3"
pipx inject sase "sase-some-plugin>=1,<2"
```

`pipx inject --include-apps` is only needed when the injected package's commands should be exposed directly on shell
`PATH`. AXE can find injected chop scripts from the SASE venv's script directory when SASE is running from that venv.

### Post-install lifecycle

Add:

```bash
sase plugin list
sase plugin list --json
sase plugin doctor
sase plugin add sase-github
sase plugin remove sase-telegram
```

`sase plugin add/remove` should detect the running install method from the running interpreter, not from ambient `pip`:

| Running install | Add/remove behavior |
| --- | --- |
| uv tool | Re-render the tool environment by re-running `uv tool install` with the selected `--with` packages from the saved install profile. Use `uv tool upgrade` only to refresh an already-recorded profile; do not assume it can add new `--with` packages. |
| pipx | Use `pipx inject`, `pipx uninject`, and `pipx upgrade --include-injected` where appropriate. |
| ordinary venv | Use `sys.executable -m pip install/uninstall`. |
| editable dev checkout | Warn or refuse by default; local path installs are project-specific. |

Doctor should report:

- distributions contributing each SASE entry point group
- loaded versus failed entry points
- plugin config and xprompt resources
- configured chops whose scripts cannot be resolved
- installed chop scripts that are not configured
- external requirements such as `gh`, `gh auth`, `pass`, and Telegram env vars

## Preferred-Set Manifest

The user request is specifically about preferred plugins/chops, not only first install. That needs a portable manifest:

```toml
# ~/.config/sase/plugins.toml
[plugins]
sase-github = ">=0.2,<0.3"
sase-telegram = ">=0.2,<0.3"
"my-private-chop" = { git = "https://github.com/me/my-private-chop" }

[chops]
enabled = ["telegram"]
```

Then:

```bash
sase plugin sync
sase plugin add --save sase-github
sase chop enable telegram --save
```

The manifest should be syncable through the same home-file/chezmoi path that `sase init` already uses. Before inventing
too much format, check whether `uv tool install ... --with-requirements` or a constraints-file pattern can carry the
package portion; SASE still needs to own activation state and diagnostics either way.

## Chop Activation

Resolve the apparent conflict between "plugin config can self-register chops" and "do not auto-enable credentialed
chops" with a safety rule:

- Safe, non-credentialed packaged chops may self-register through `sase_config` defaults.
- Credentialed, networked, or potentially noisy integrations should ship a manifest and require explicit
  `sase chop enable <name>`.

Add a static plugin/chop manifest entry point, following the existing `sase_*` naming convention:

```toml
[project.entry-points."sase_plugin_manifest"]
telegram = "sase_telegram"
```

The manifest should be package data so inventory can avoid importing heavy provider libraries:

```yaml
schema_version: 1
name: telegram
package: sase-telegram
provides:
  chops:
    - name: tg_outbound
      script: sase_chop_tg_outbound
      default_lumberjack: telegram
      safe_auto_enable: false
      required_commands: ["pass"]
      required_env:
        - SASE_TELEGRAM_BOT_CHAT_ID
        - SASE_TELEGRAM_BOT_USERNAME
    - name: tg_inbound
      script: sase_chop_tg_inbound
      default_lumberjack: telegram
      safe_auto_enable: false
```

`sase chop enable telegram` should write an idempotent managed overlay, e.g. `~/.config/sase/sase_plugins.yml`, rather
than patching the user's primary config:

```yaml
axe:
  lumberjacks:
    telegram:
      interval: 5
      chop_timeout: "60s"
      chops:
        - name: tg_outbound
          description: "Send pending SASE notifications to Telegram"
          run_every: "15s"
        - name: tg_inbound
          description: "Poll Telegram for user responses"
          run_every: "5s"
```

Also add:

```bash
sase chop available
sase chop enable telegram
sase chop disable telegram
```

For local user-written scripts, add a separate `sase chop add` scaffolder that registers a script directory, appends the
chop to a selected lumberjack, verifies resolution with the same discovery logic AXE uses, and optionally runs a one-shot
smoke test. Do not make local chop scaffolding carry the packaged-plugin lifecycle.

## Release and Implementation Sequence

1. **Package metadata and docs**
   - Publish `sase-core-rs`.
   - Bump `sase`, `sase-github`, and `sase-telegram` to a coordinated public line.
   - Add first-party extras to `sase`.
   - Update plugin docs to lead with `uv tool install "sase[recommended]>=0.2,<0.3"` and state the same-environment rule.

2. **Inventory and diagnostics**
   - Add `sase plugin list --json`.
   - Add `sase plugin doctor`.
   - Surface resource-plugin load failures outside debug logs.
   - Include chop script resolution and external requirement checks.

3. **Lifecycle commands**
   - Add `sase plugin add/remove`.
   - Detect uv-tool, pipx, venv, and editable checkout installs.
   - Verify discovery after installation and print concrete remediation on failure.

4. **Manifests and activation**
   - Add preferred-set manifest support and `sase plugin sync`.
   - Add `sase_plugin_manifest` package metadata.
   - Add `sase chop enable/disable/available`.
   - Store activation in a managed overlay and make operations idempotent.

5. **Self-update**
   - Persist the install profile so `/update`, mobile update, and future `sase self update` can replay the user's chosen
     package set.
   - Keep raw `chat_install.command` as the escape hatch for developer checkouts.

## Decisions

| Option | Decision |
| --- | --- |
| First-party extras | Ship. They are the cheapest one-command path and solve same-env installs for curated bundles. |
| `uv tool install --with ...` | Keep as the universal explicit path for third-party/private plugins. |
| `sase plugin list/doctor` | Build early. Diagnostics are currently the biggest support gap. |
| `sase plugin add/remove` | Build after list/doctor. It removes the most common post-install footgun. |
| Preferred-set manifest | Build after lifecycle commands. This is what makes a user kit portable. |
| Auto-enable all installed chops | Avoid. Use explicit activation unless a chop is demonstrably safe and non-credentialed. |
| `sase-full` package | Defer. `sase[all]` gives the same result without a new distribution. |
| `curl | sh` bootstrap | Defer. Revisit only if users fail before they reach `uv tool install`. |

## Sources

Local code and docs:

- `pyproject.toml`
- `src/sase/main/plugin_discovery.py`
- `src/sase/config/core.py`
- `src/sase/axe/chop_script_runner.py`
- `src/sase/axe/config.py`
- `src/sase/default_config.yml`
- `docs/plugins.md`
- `docs/axe.md`
- `docs/configuration.md`
- `sase-github` workspace `pyproject.toml` and `src/sase_github/default_config.yml`
- `sase-telegram` workspace `pyproject.toml` and README
- `sase-nvim` workspace README

Related research:

- [public_release_process_and_install_research.md](./public_release_process_and_install_research.md)
- [sase_chops_rust_repo_research.md](./sase_chops_rust_repo_research.md)
- [sase_plugin_specifics.md](../202602/sase_plugin_specifics.md)
- [sase_init_onboarding.md](./sase_init_onboarding.md)

External references checked on 2026-05-28:

- [uv tools guide](https://docs.astral.sh/uv/guides/tools/)
- [pipx inject docs](https://pipx.pypa.io/stable/docs/#pipx-inject)
- [PyPA entry points specification](https://packaging.python.org/en/latest/specifications/entry-points/)
- [PyPA pyproject.toml specification](https://packaging.python.org/en/latest/specifications/pyproject-toml/)
- PyPI JSON endpoints for [`sase`](https://pypi.org/pypi/sase/json),
  [`sase-github`](https://pypi.org/pypi/sase-github/json),
  [`sase-telegram`](https://pypi.org/pypi/sase-telegram/json), and
  [`sase-core-rs`](https://pypi.org/pypi/sase-core-rs/json)
