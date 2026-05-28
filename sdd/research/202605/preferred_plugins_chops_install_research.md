# Preferred Plugin and Chop Installation Research

Date: 2026-05-28

## Question

How should SASE make it easy for a user to install SASE together with the SASE plugins and/or chops they actually want?

## Executive Summary

The best install story has two layers:

1. **Package layer:** install `sase` and selected plugin/chop packages into the same Python tool environment.
   SASE's plugin discovery depends on Python entry points, and script chops depend on executable entry points living
   beside the Python interpreter that runs `sase`.
2. **Activation layer:** write durable SASE config for user-selected chops and integration settings. Package installation
   alone is enough for passive entry-point plugins such as `sase-github`, but it is not enough for scheduled chops such
   as Telegram; AXE only runs chops that appear in merged `axe.lumberjacks` config.

Recommended user-facing install shape for public first-party packages:

```bash
uv tool install "sase[github,telegram]>=0.2,<0.3"
sase init --yes
sase plugin doctor
```

Equivalent explicit-package form, useful for third-party plugins not known to core SASE:

```bash
uv tool install "sase>=0.2,<0.3" \
  --with "sase-github>=0.2,<0.3" \
  --with "sase-telegram>=0.2,<0.3"
```

The CLI should then offer a SASE-native activation path:

```bash
sase install profile apply --plugins github,telegram --chops telegram
```

That command should be idempotent, write a managed overlay such as `~/.config/sase/sase_plugins.yml`, run `sase init`
for generated resources, and persist an install profile so `/update`, mobile update, and future self-update commands
can replay the same plugin set.

## Current Local Architecture

### Plugin Discovery

SASE currently discovers plugins through Python packaging entry points:

| Entry point group | Purpose |
| --- | --- |
| `sase_vcs` | VCS provider classes |
| `sase_workspace` | Workspace provider classes |
| `sase_llm` | LLM provider classes |
| `sase_xprompts` | Package modules contributing xprompts/workflows |
| `sase_config` | Package modules contributing `default_config.yml` |

Local source references:

- `pyproject.toml` declares built-in `sase_llm`, `sase_vcs`, and `sase_workspace` entry points.
- `src/sase/main/plugin_discovery.py` loads resource plugin modules from entry points.
- `src/sase/config/core.py` merges plugin `default_config.yml` files after bundled defaults and before user config.
- `docs/plugins.md` documents the plugin groups and authoring model.

The important operational rule is that plugins must be installed in the same environment as `sase`. Installing
`sase` as a `uv tool` and then installing `sase-github` in an unrelated project venv will not make `#gh` work.

### Config Merge Behavior

Merged config order:

1. Bundled `src/sase/default_config.yml`
2. Plugin `default_config.yml` from `sase_config` entry points
3. `~/.config/sase/sase.yml`
4. `~/.config/sase/sase_*.yml` overlays
5. Local `./sase.yml`

Plugin configs are the right place for safe package defaults. User selections should be written to an overlay, not
silently patched into the primary user config. That keeps installer-managed choices inspectable and reversible.

### Script Chops

AXE script chops are configured under `axe.lumberjacks.*.chops`. A script chop named `foo` resolves in this order:

1. Executable named `foo` in `axe.chop_script_dirs`
2. Executable named `sase_chop_foo` beside the running Python interpreter
3. Executable named `sase_chop_foo` on `PATH`

Local source references:

- `src/sase/axe/config.py` parses `axe.lumberjacks`, `chop_script_dirs`, `run_every`, `timeout`, and `env`.
- `src/sase/axe/chop_script_runner.py` implements script discovery and script invocation.
- `docs/axe.md` documents `sase axe chop list`, `sase axe chop run`, manual run behavior, and script chop output.

This is already a good packaging contract. A plugin package can expose `project.scripts` such as
`sase_chop_tg_outbound`, and SASE will find them from a `uv tool`/`pipx` venv even if the executable is not directly
linked onto the user's shell `PATH`.

## Sibling Package Findings

### `sase-github`

Workspace checked: `../sase-github` via `sase workspace open -p sase-github 10`.

Current facts:

- Python package: `sase-github==0.1.0`
- Dependency: `sase>=0.1.0`
- Entry points:
  - `sase_vcs: github`
  - `sase_workspace: github`
  - `sase_config: sase_github`
  - `sase_xprompts: sase_github`
- Requirements: `gh` CLI for GitHub operations.
- Current `default_config.yml` is effectively empty (`xprompts: {}`).

Install implication: this is a passive plugin. Once it is co-installed with `sase`, entry-point discovery makes `#gh`
and GitHub provider behavior available. It still needs `gh auth` diagnostics, but it does not need AXE activation.

### `sase-telegram`

Workspace checked: `../sase-telegram` via `sase workspace open -p sase-telegram 10`.

Current facts:

- Python package: `sase-telegram==0.1.0`
- Dependency: `sase>=0.1.0`, `python-telegram-bot>=21.0`
- Console scripts:
  - `sase_chop_tg_outbound`
  - `sase_chop_tg_inbound`
- No `sase_config` entry point today.
- No default AXE lumberjack/chop config today.
- Requires credentials from `pass show telegram_sase_bot_token` plus `SASE_TELEGRAM_BOT_CHAT_ID` and
  `SASE_TELEGRAM_BOT_USERNAME`.

Install implication: installing the package only makes the scripts discoverable. It does not schedule them. A user must
still configure AXE with chops named `tg_outbound` and `tg_inbound`, or SASE needs an activation command that writes
that config.

### `sase-nvim`

Workspace checked: `../sase-nvim` via `sase workspace open -p sase-nvim 10`.

Current facts:

- Neovim plugin, not a Python package.
- Installed through Neovim plugin managers (`lazy.nvim`, `packer.nvim`, `vim-plug`).
- Depends on `sase` being on `PATH` for picker fallback, schema discovery, and `sase lsp`.

Install implication: this should appear in SASE's install profile as an editor integration recommendation, not as a
Python `--with` package. A future command can print editor-manager snippets, but it should not pretend `uv tool install`
can install it.

## External Packaging Research

Relevant current official docs:

- uv tools: https://docs.astral.sh/uv/guides/tools/
- pipx injection: https://pipx.pypa.io/stable/how-to/inject-packages/
- PyPA entry points: https://packaging.python.org/en/latest/specifications/entry-points/
- PyPA `pyproject.toml` metadata and optional dependencies:
  https://packaging.python.org/en/latest/specifications/pyproject-toml/

Packaging conclusions:

- `uv tool install` is the best primary public install path. It creates a persistent isolated tool environment, installs
  executables for the selected tool, and supports additional packages with `--with`.
- `pipx` remains the best fallback. `pipx inject sase <plugin>` installs plugins into the existing SASE venv.
  `--include-apps` is only needed when the user wants injected package commands linked onto shell `PATH`; SASE itself
  can find injected chop scripts beside `sys.executable`.
- PyPA entry points are the correct plugin-discovery mechanism for SASE's current Python host. They are specifically
  intended for installed distributions to advertise plugin components and console commands.
- Core package extras are a good fit for first-party install bundles:

```toml
[project.optional-dependencies]
github = ["sase-github>=0.2,<0.3"]
telegram = ["sase-telegram>=0.2,<0.3"]
recommended = ["sase-github>=0.2,<0.3"]
full = ["sase-github>=0.2,<0.3", "sase-telegram>=0.2,<0.3"]
```

Extras are less suitable for unknown third-party plugins; those should use `uv tool install sase --with <plugin>`.

## Current Registry State

Checked PyPI JSON endpoints on 2026-05-28:

| Package | PyPI status | Latest public version | Notes |
| --- | --- | --- | --- |
| `sase` | present | `0.1.0` | Uploaded 2026-02-23; public metadata predates current local dependencies. |
| `sase-github` | present | `0.1.0` | Uploaded 2026-02-23; dependency is still `sase>=0.1.0`. |
| `sase-telegram` | 404 | none | Must be published before public bundle install works. |
| `sase-core-rs` | 404 | none | Must be published before current `sase` can install cleanly from PyPI. |

This means public one-command install should target a coordinated `0.2.0` release line, not the existing `0.1.0`
packages.

## Gaps To Close

### 1. No User-Facing Install Profiles

Today users must know:

- Which packages exist.
- Which packages must be co-installed with `sase`.
- Which external tools are required (`gh`, `pass`, Telegram credentials).
- Which AXE chops must be configured after package installation.

Recommendation: add an install profile model:

```yaml
install:
  manager: uv-tool
  package: "sase>=0.2,<0.3"
  with:
    - "sase-github>=0.2,<0.3"
    - "sase-telegram>=0.2,<0.3"
  plugins:
    - github
    - telegram
  enabled_chops:
    - telegram
```

Persist it under `~/.config/sase/install.yml` or an installer-managed SASE overlay. Use it for diagnostics, re-install,
and chat/mobile updates.

### 2. No Plugin Inventory or Doctor

Prior release research already noted the missing `sase plugin list`. This becomes more important once users install
bundles.

Recommended commands:

```bash
sase plugin list
sase plugin list --json
sase plugin doctor
```

Doctor should report:

- Installed distributions contributing each SASE entry point group.
- Load failures that normal resource discovery currently logs only at debug level.
- Missing external binaries (`gh`, `pass`, `telegram` credentials, provider CLIs).
- Config resources loaded from plugins.
- Xprompt/workflow resources loaded from plugins.
- Chops configured but missing executable scripts.
- Chop scripts installed but not configured.

### 3. Chops Lack A Manifest And Activation Surface

Script discovery can find installed chop scripts, but it cannot answer:

- Which package owns this chop?
- What lumberjack should it run under?
- What interval and `run_every` should it use?
- What credentials or environment variables are required?
- Is it safe to auto-enable?

Recommendation: add a manifest entry point, separate from the existing functional plugin entry points:

```toml
[project.entry-points."sase_plugins"]
telegram = "sase_telegram"
```

The module can expose a static manifest, preferably as package data to avoid importing heavy provider libraries during
simple inventory:

```yaml
schema_version: 1
name: telegram
package: sase-telegram
description: Telegram notification and remote-control integration.
provides:
  chops:
    - name: tg_outbound
      script: sase_chop_tg_outbound
      default_lumberjack: telegram
      description: Send pending SASE notifications to Telegram.
      safe_auto_enable: false
      required_env:
        - SASE_TELEGRAM_BOT_CHAT_ID
        - SASE_TELEGRAM_BOT_USERNAME
      required_commands:
        - pass
    - name: tg_inbound
      script: sase_chop_tg_inbound
      default_lumberjack: telegram
      description: Poll Telegram for user responses.
      safe_auto_enable: false
```

Then add:

```bash
sase chop available
sase chop enable telegram
sase chop disable telegram
```

For Telegram, `sase chop enable telegram` should write something like this to a managed overlay:

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

Do not auto-enable credentialed chops just because the package is installed. That would turn missing credentials into
repeated AXE errors.

### 4. `chat_install.command` Is Too Raw For Package Users

Current `chat_install.command` is a free-form shell command. That is flexible for development checkouts but weak for
packaged users because `/update` cannot know which plugins were selected.

Recommendation:

```bash
sase self update
```

`sase self update` should read the persisted install profile and execute the appropriate package-manager command:

- `uv tool install --force "sase[github,telegram]>=0.2,<0.3"` for uv-tool installs.
- `pipx reinstall sase` plus `pipx inject` for pipx installs.
- `python -m pip install --upgrade ...` for normal venv installs.
- For developer checkouts, leave `chat_install.command` customizable (`just install`, `git pull && just install`, etc.).

Then `chat_install.command` can become:

```yaml
chat_install:
  command: "sase self update"
```

### 5. Version Constraints Need A Coordinated Public Release

Before advertising first-party bundles:

- Publish `sase-core-rs`.
- Bump `sase` to `0.2.0`.
- Bump `sase-github` to `0.2.0` and depend on `sase>=0.2,<0.3`.
- Publish `sase-telegram==0.2.0` with `sase>=0.2,<0.3`.
- Add SASE core extras for first-party plugins.

Otherwise `pip install sase-github` can resolve stale `sase==0.1.0`, and public install docs will be unreliable.

### 6. Some CLI Filters Are Hard-Coded

`sase skills init --provider` currently has hard-coded choices (`claude`, `gemini`, `codex`, `opencode`, `qwen`) even
though provider discovery is entry-point based. A third-party LLM provider plugin can be installed but cannot be passed
to this filter without a core code change.

Recommendation: make provider filters validate dynamically against registered `sase_llm` providers, or accept any
string and let the inventory return "no matching provider" when appropriate.

## Recommended UX

### Public First-Party Install

```bash
uv tool install "sase[github]>=0.2,<0.3"
sase init --yes
sase plugin doctor
```

With Telegram:

```bash
uv tool install "sase[github,telegram]>=0.2,<0.3"
sase init --yes
sase chop enable telegram
sase plugin doctor
```

### Third-Party Plugin Install

```bash
uv tool install "sase>=0.2,<0.3" --with "sase-some-plugin>=1,<2"
sase plugin doctor
```

### pipx Alternative

```bash
pipx install "sase[github]>=0.2,<0.3"
pipx inject sase "sase-telegram>=0.2,<0.3"
sase chop enable telegram
```

Use `pipx inject --include-apps` only when the user wants injected chop commands callable directly from the shell.

### Developer Checkout

```bash
just install
uv pip install -e ../sase-github -e ../sase-telegram
sase plugin doctor
```

Developer installs should remain explicit because local path selection is project-specific.

## Implementation Plan

### Phase 1: Make Existing Packages Easy To Co-Install

- Add first-party extras to `sase` for `github`, `telegram`, `recommended`, and `full`.
- Update first-party plugin dependency bounds to `sase>=0.2,<0.3`.
- Publish coordinated `0.2.0` packages.
- Add docs and site command snippets for `uv tool`, `pipx`, and developer checkout installs.
- Add smoke tests that install built wheels with extras and with explicit `--with` packages, then run:
  - `sase core health --json`
  - `sase xprompt list`
  - `sase skills list`
  - future `sase plugin list`

### Phase 2: Add Inventory And Doctor

- Add `sase plugin list --json`.
- Add `sase plugin doctor`.
- Surface resource plugin load failures instead of hiding them behind debug logs.
- Report installed-but-inactive chop scripts and configured-but-missing chop scripts.
- Include external requirement checks from plugin manifests when available.

### Phase 3: Add Manifests And Activation

- Add `sase_plugins` manifest entry point.
- Add `sase chop available`, `sase chop enable`, and `sase chop disable`.
- Store generated activation config in a managed overlay.
- Add tests for config overlay idempotence and for active AXE config after enabling Telegram.
- Add `enabled` support to lumberjack/chop config only if the manifest approach still needs dormant plugin defaults.

### Phase 4: Add Reproducible Self-Update

- Persist install profile at install/activation time.
- Add `sase self update --dry-run` and `sase self update --yes`.
- Teach chat/mobile update flows to default to `sase self update` for package installs.
- Keep raw `chat_install.command` as the escape hatch for developer checkout workflows.

## Decision Matrix

| Option | Pros | Cons | Recommendation |
| --- | --- | --- | --- |
| `uv tool install sase --with plugin` | Works for first-party and third-party plugins; matches SASE entry-point model. | Users must know package names and activation steps. | Support as the explicit universal path. |
| Core extras (`sase[github,telegram]`) | Cleanest one-command first-party install. | Core package must track first-party plugin constraints. | Use for public first-party bundles. |
| Separate meta-package (`sase-full`) | Decouples bundle updates from core releases. | More package names and another release artifact. | Defer until bundle churn justifies it. |
| Auto-enable all installed chops | Zero config after package install. | Credentialed integrations can fail repeatedly; user intent is unclear. | Avoid. Require explicit chop enable/profile apply. |
| `sase install apply` runs package manager | Best user experience after SASE is present. | Needs careful install-manager detection and self-update handling. | Add after profile model exists. |
| Shell-only installer script | Enables true one-liner from zero. | More OS/package-manager maintenance; harder to audit. | Site command generator first, script later if demand appears. |

## Bottom Line

Use Python package co-installation for discovery, but do not stop there. The missing product layer is a SASE-owned
install profile plus plugin/chop manifest system. First-party extras solve the public "one command" package problem;
`sase plugin doctor` and `sase chop enable` solve the "did it actually become usable?" problem.
