# Installing SASE

The recommended way to install SASE is as a [uv](https://docs.astral.sh/uv/)-managed
tool:

```bash
uv tool install sase
```

Then verify the install:

```bash
sase version       # inspect the exact SASE packages loaded by this environment
sase doctor        # readiness gate: install, config, provider, and state report
sase core health   # confirm the required Rust core extension loaded
sase agent-cli      # inventory supported provider CLIs and their install/update state
```

The `uv tool install sase` path is more than a convenience: `sase update`,
`sase plugin install`, and the SASE Admin Center **Updates** tab all manage the install
through `uv tool` and its `uv-receipt.toml`. Installs made with pip or pipx cannot use
those update workflows (they fail fast with an actionable message), so treat
`pip install sase` as an escape hatch for non-managed or library-style environments
only.

## What you need before installing

These must be available for `uv tool install sase` to succeed:

| Requirement           | Notes                                                                                                                                                                              |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `uv`                  | Install per the [uv docs](https://docs.astral.sh/uv/getting-started/installation/).                                                                                                |
| Python 3.12+          | SASE requires Python 3.12 or newer. `uv` resolves this automatically and can download a managed CPython when the system Python is too old; pass `--python 3.12` to pin explicitly. |
| A supported platform  | Prebuilt `sase-core-rs` wheels ship for CPython 3.12+ on Linux x86_64, Linux aarch64, and macOS. SASE itself targets POSIX systems (Linux and macOS).                              |
| Rust toolchain (rare) | Only needed when no prebuilt `sase-core-rs` wheel exists for your platform, in which case `cargo` must be on `PATH` so the extension can build from source.                        |

No other build tooling is required — `sase` and its Python dependencies install as
wheels, and the required Rust core (`sase-core-rs`) is a hard dependency that is pulled
automatically. There is no pure-Python fallback for ported core operations, which is why
`sase core health` is the canonical install check.

## Installing plugins

Plugins (for example `sase-github` for GitHub PR workflows, or `sase-telegram` for
chat-driven notifications and remote control) must live in the **same** `uv tool`
environment as `sase` so their entry points are discovered.

### Recommended: the SASE Admin Center Updates tab

If SASE is already installed, install plugins interactively from the TUI:

1. Run `sase ace`.
2. Press `#` to open the **SASE Admin Center**.
3. Switch to the **Updates** tab (press `6` or select it in the numbered tab strip).
4. Highlight the plugin (`j` / `k`, or `/` to filter the list).
5. Press `i` to install and confirm the preview modal. The preview shows the exact `uv`
   command and the resolved package set before anything runs.

The install runs as a tracked background task (watch it on the **Tasks** tab). When the
install actually changes the package set, SASE automatically restarts the axe daemon
(and shows a post-restart toast in ACE) so the plugin's entry points are picked up
immediately. The same tab uninstalls plugins with `x`.

The CLI equivalents are `sase plugin list`, `sase plugin show <plugin>`,
`sase plugin install <plugin>`, and `sase plugin uninstall <plugin>` — see
[docs/plugins.md](docs/plugins.md). Note that browsing the plugin catalog (in the
Updates tab or via `sase plugin list`) requires an authenticated GitHub CLI (`gh`),
since the catalog is fetched from the GitHub `sase--plugin` repository topic.

### Alternative: install SASE and plugins in one command

To install SASE together with one or more plugins from the start, add `--with`:

```bash
# SASE + GitHub PR support
uv tool install sase --with sase-github

# SASE + GitHub + Telegram
uv tool install sase --with sase-github --with sase-telegram
```

Add `--force` to replace an existing tool install. Be aware that uv's `--with`
**replaces** the injected plugin set rather than appending to it — to add a plugin to an
existing install, prefer the Updates tab or `sase plugin install`, which reconstruct the
full plugin set from uv's receipt for you.

`sase-nvim` is the exception: it is a Neovim plugin, installed through your Neovim
plugin manager (lazy.nvim, packer, vim-plug) rather than into the Python environment.
See the [sase-nvim README](https://github.com/sase-org/sase-nvim).

## Keeping SASE up to date

### Recommended: the SASE Admin Center Updates tab

The **Updates** tab (press `#` in `sase ace`, then `6`) is also the recommended way to
keep SASE current:

- The tab leads with a **SASE Core** panel showing the installed and latest versions of
  the `sase` and `sase-core-rs` packages, with an `↑` marker when a newer version is
  available. ACE also surfaces startup and top-bar update signals when SASE or an
  installed plugin is behind.
- Press `u` to update SASE core **plus every installed plugin together** (the TUI analog
  of `sase update`, which delegates to `uv tool upgrade sase`).
- Press `U` to update only the highlighted installed plugin when its row shows an update
  available (SASE core stays pinned).
- Press `r` to refresh the catalog and latest-version data, and `o` to toggle offline
  (cache-only) mode.
- Press `m` to switch the install mode between managed PyPI wheels and dev (editable)
  checkouts — the TUI analog of `sase update --to dev|pypi`.
- Every mutation previews first: the confirm modal shows the exact `uv` command (or the
  git fast-forward plan for editable dev checkouts) before anything changes. The
  confirmation _is_ the dry run.
- A successful update that changed code automatically restarts ACE and the axe daemon so
  running surfaces pick up the new code; no-op and failed updates leave everything
  running.

### CLI equivalent

```bash
sase update            # update sase + all installed plugins together
sase update -n         # dry run: preview the exact plan, change nothing
sase update -t dev     # switch the install to dev (editable) checkouts
sase update -t pypi    # switch the install back to managed PyPI wheels
sase plugin update -a  # upgrade every installed plugin, leaving sase core pinned
```

Both paths require the canonical `uv tool install sase` install method. See
[docs/plugins.md](docs/plugins.md#updating-sase-and-plugins-sase-update) for details,
including how editable / dev checkouts are updated and how install-mode switching works.

## System commands SASE uses at runtime

`sase doctor` audits the required commands and `sase doctor -D` (deep mode) reports the
optional ones, so the doctor output is always the authoritative check for your machine.
The lists below describe what each command is for.

### Required

| Command              | Used for                                                                                                                                                                                                                                                                                                                                                                              |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git`                | All core VCS operations: workspace clones, status/diff/commit flows, bead sync, and updates. `sase doctor` also verifies your `user.name` / `user.email` identity is configured.                                                                                                                                                                                                      |
| One coding-agent CLI | SASE orchestrates an existing provider CLI. At least one of `claude` (Claude Code), `codex` (Codex), `agy` (Antigravity CLI), `qwen` (Qwen Code), `opencode` (OpenCode), `muse` (Muse Code; explicit provider/model selection required), or `grok` (Grok Build; explicit provider/model selection required) must be installed **and authenticated**. `sase doctor` reports readiness. |
| A text editor        | Commit-message editing uses `$EDITOR`, falling back to `nvim`, then `vim`.                                                                                                                                                                                                                                                                                                            |

For per-provider install and authentication commands, see
[Installing & Authenticating Agent Providers](docs/agent_providers.md). Among SASE's
built-in providers, Muse Code is the one SASE can currently install itself: preview the
exact HTTPS-fetched script, digest, command, and target with
`sase agent-cli install muse --dry-run`, then run `sase agent-cli install muse` and
confirm. Other built-in providers retain their vendor installation flows.

### Recommended / optional

Missing tools degrade the specific feature listed; everything else keeps working.
`sase doctor -D` reports exactly which of these are missing on your machine.

| Command                                       | Feature that needs it                                                                                                                |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `gh` (authenticated)                          | The plugin catalog (Updates tab and `sase plugin list`), GitHub PR operations via the `sase-github` plugin, and mentor/PR workflows. |
| `tmux`                                        | ACE tmux windows and artifact panes.                                                                                                 |
| `bat`                                         | Syntax-highlighted file previews (falls back to plain output).                                                                       |
| `dict`                                        | Prompt word definitions when pressing `K` on a plain word.                                                                           |
| `aspell`                                      | Prompt spellcheck fixes when pressing `K` on a misspelled word. Debian also needs `aspell-en`; Homebrew bundles English.             |
| `fzf`                                         | Interactive prompt-history browsing and selection.                                                                                   |
| `rg` (ripgrep)                                | Fast file-reference search in prompt and commit workflows.                                                                           |
| `delta`                                       | Syntax-highlighted diffs in commit/accept workflows.                                                                                 |
| `pandoc`                                      | Markdown-to-PDF artifact rendering.                                                                                                  |
| One of `wkhtmltopdf` / `xelatex` / `pdflatex` | PDF rendering from Markdown and xprompt catalogs.                                                                                    |
| `pdftoppm` (poppler)                          | PDF and Markdown artifact paging in the TUI.                                                                                         |
| `kitten` (kitty)                              | Terminal image artifact display.                                                                                                     |
| `prettier`                                    | Prompt and generated-Markdown formatting.                                                                                            |
| A clipboard helper                            | Copy actions in ACE: `pbcopy` (macOS, preinstalled), `wl-copy` (Wayland), or `xclip` / `xsel` (X11).                                 |
| `pass`                                        | Only for the `sase-telegram` plugin's bot-token retrieval.                                                                           |
| `node` / `npm`                                | Only to install npm-distributed provider CLIs (Claude Code, Codex, Qwen Code).                                                       |

## Uninstalling

```bash
uv tool uninstall sase
```

This removes SASE and every plugin injected into its tool environment. Durable state
(projects, Patches, prompt history, beads) lives under `~/.sase/` and platform state
directories and is not removed.
