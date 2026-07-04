---
create_time: 2026-07-04 07:42:25
status: wip
prompt: sdd/prompts/202607/install_mode_switch.md
---
# Plan: First-class switching between PyPI (managed) and Dev (editable) installs

## Problem

SASE already has two implicit install modes, but no way to move between them:

- **Managed (PyPI)** — the canonical `uv tool install sase` path. The uv receipt (`uv-receipt.toml`) records `sase` plus
  every injected plugin as index requirements; `sase update` runs `uv tool upgrade sase`.
- **Dev (editable)** — the same uv tool environment, but the receipt's requirements are editable specs pointing at local
  checkouts. `sase update` already routes editable records through the dev-update backend (`src/sase/dev_update/`): git
  fast-forward each checkout root, reinstall the editable set, and rebuild `sase-core-rs` into the uv tool venv via
  `just rust-install-uv-tool`.

Mode detection exists (`update_mode()` in `src/sase/main/update_routing.py` returns `managed`/`dev`/`mixed`, derived
purely from the receipt + PEP 610 `direct_url.json`), and both update pipelines exist. What's missing is the **switch**:
a user on published wheels who wants to hack on sase must hand-craft clones and a
`uv tool install --editable ... --with-editable ...` invocation; a dev user who wants to fall back to stable wheels has
no command at all. Neither direction shows what versions the user would land on.

This plan adds an explicit, confirmable, beautiful mode-switch operation to both the CLI (`sase update --to dev|pypi`)
and the TUI (Updates tab on the SASE Admin Center), covering `sase`, `sase-core-rs`, and every installed Python plugin
(e.g. `sase-github`, `sase-telegram`).

A key elegance of this design: **the uv receipt already _is_ the mode**. Switching = rewriting the receipt's requirement
specs (index ↔ editable) via one `uv tool install` invocation. No new mode state file is needed, and every existing
surface (dev-route detection, update indicator, incoming-commit previews, `sase version`) picks up the new mode
automatically after the switch.

## Goals

1. `sase update --to dev` / `sase update --to pypi` switches the whole package set in one confirmed operation, with a
   `-y|--yes` bypass, and composes with the existing `-n|--dry-run`, `-j|--json`, `-q|--quiet` flags.
2. Switching to dev **materializes checkouts at a consistent, configurable location** (default `~/projects/git/<repo>`,
   matching the existing bare-git primary-clone convention), reusing checkouts that already exist there.
3. The confirmation (CLI prompt and TUI modal) shows a **per-package version transition table** — every package's
   current version → target version, plus the repo action (clone/reuse) and the exact commands that will run.
4. The TUI Updates tab shows the **current mode at a glance** and offers the switch behind a keymap + confirm modal,
   with the run executing as a tracked background task and finishing with the standard restart + post-update toast.
5. Reliability: no side effects before confirmation, preflight checks that fail fast with actionable messages, a
   recovery breadcrumb if the uv invocation fails mid-switch, and user checkouts are never deleted or mutated beyond
   fetch/clone.

## Non-goals

- Changing what bare `sase update` does inside a mode (managed upgrade / dev fast-forward pipelines are untouched), and
  no new confirmation on bare `sase update`.
- Rust core (`sase-core`) changes. Install/receipt/restart machinery is process-level Python by established precedent
  (the plugin operations layer and update-restart machinery already live in `src/sase/plugins/operations.py` /
  `src/sase/main/update_restart.py`); no other frontend needs to share this logic through `sase_core_rs`.
- Managing non-Python companions (e.g. `sase-nvim` is a Neovim plugin, not a distribution in the uv tool env). Scope is
  the Python distributions in the environment: `sase` (host), `sase-core-rs` (core), and installed `sase-*` plugins.
- Deleting checkouts when switching back to PyPI (they stay on disk; the plan says so explicitly).
- Per-package partial switching (e.g. dev sase + published plugins beyond the unavoidable cases below). The command
  converges the whole set; `mixed` remains a state you can be _in_, not one we help you construct.

## Design

### Mode names

User-facing: **`pypi`** ("PyPI (managed)") and **`dev`** ("Dev (editable)"). These map onto the existing `update_mode()`
values `managed`/`dev`/`mixed`. `mixed` renders as "Mixed" and can be converged in either direction.

### CLI surface

Extend `sase update` (parser in `src/sase/main/parser_update.py`; options stay alphabetically sorted, every long option
keeps a short alias per the CLI rules):

```
sase update                    # unchanged: update within the current mode
sase update --to dev           # switch to editable checkouts (clone/reuse repos, editable install)
sase update --to pypi          # switch back to published wheels
sase update --to dev -n        # preview the switch plan; change nothing
sase update --to dev -y        # skip the confirmation prompt
sase update --to pypi -j -y    # machine-readable switch result
```

- `-t|--to {dev,pypi}` — target mode. Omitted → today's behavior, byte-for-byte.
- `-y|--yes` — skip the y/n prompt (only meaningful with `--to`; harmless otherwise).
- Already in the target mode → friendly no-op ("Already a dev (editable) install — run `sase update` to update it."),
  exit 0.
- Confirmation follows the established hand-rolled pattern (`src/sase/main/init_onboarding.py`,
  `src/sase/prompt/cli_maintenance.py`): `Proceed? [y/N]`, EOF/anything-but-yes = no; non-TTY without `--yes` refuses
  with "Re-run with --yes." and exit 1.

Rendered plan (Rich, in the spirit of the existing update/restart panels — the confirmation doubles as the dry-run,
exactly like `PluginActionConfirmModal` does in the TUI):

```
╭─ Switch install mode ────────────────────────────────────────────────╮
│  PyPI (managed)  ──▶  Dev (editable)          dev root ~/projects/git │
╰──────────────────────────────────────────────────────────────────────╯
 Package         Role     Current          Target                Source
 sase            host     0.7.1         →  0.8.0+3.g084a6a2      reuse ~/projects/git/sase
 sase-core-rs    core     0.3.1         →  0.3.1+1.gf00dfee      clone sase-org/sase-core
 sase-github     plugin   0.1.6         →  0.1.7+0.g9a8b7c6      clone sase-org/sase-github
 sase-telegram   plugin   0.2.0         →  0.2.0+2.g1a2b3c4      reuse ~/projects/git/sase-telegram

 Will run
   1. git clone https://github.com/sase-org/sase-core ~/projects/git/sase-core   (+1 more)
   2. uv tool install --force --reinstall -e ~/projects/git/sase
        --with-editable ~/projects/git/sase-github --with-editable ~/projects/git/sase-telegram
   3. just rust-install-uv-tool   (in ~/projects/git/sase — builds sase-core-rs into the uv tool venv)
   4. Restart the AXE daemon.

Proceed? [y/N]
```

Downgrades (common when leaving dev: `0.8.0+3.g084a6a2 → 0.7.1`) are flagged with a colored `↓` so the direction of
every transition is unmistakable. Warnings (dirty checkout reused as-is, cargo missing, plugin with no known repo)
render as a dim bulleted list under the table.

### Where dev checkouts live

New config key **`update.dev_root`** (new top-level `update:` section in `src/sase/default_config.yml` +
`src/sase/config/sase.schema.json`), default **`~/projects/git`** — the same convention the bare-git workspace plugin
already uses for primary clones (`src/sase/workspace_provider/plugins/bare_git_init.py`). Layout is one checkout per
repo: `<dev_root>/sase`, `<dev_root>/sase-core`, `<dev_root>/sase-github`, … Because `sase` and `sase-core` land as
siblings, the Justfile's default `../sase-core` resolution (and therefore `just rust-install-uv-tool` and the existing
dev-update reconcile step) works unmodified.

Repo resolution per package:

- `sase` → `sase-org/sase`; `sase-core-rs` → `sase-org/sase-core` (constants).
- Plugins → the plugin catalog (`src/sase/plugins/catalog.py` already carries `full_name`/`url` per plugin, sourced from
  the GitHub `sase-plugin` topic registry); fall back to `sase-org/<dist-name>` for builtin plugins when the catalog is
  unavailable.
- A plugin whose repo cannot be determined **stays managed** and is listed in the plan as "stays on PyPI (no known
  repo)" — the switch degrades explicitly instead of failing or guessing.

Existing checkouts at the target path are **reused, never reset**: we `git fetch` for freshness, use the working tree
as-is, and surface dirty/diverged/detached state as plan warnings (the same classifications
`src/sase/dev_update/plan.py` already computes).

### Planning: making the version change unambiguous

Planning is side-effect-free — nothing is cloned or installed before the user confirms.

- **Current versions**: the runtime version inventory (`collect_runtime_version_inventory`), same source as
  `sase version`.
- **Target for `--to pypi`**: latest from PyPI via the existing `fetch_latest_version` / latest-cache machinery.
- **Target for `--to dev`**:
  - checkout already on disk → exact display version via the existing `probe_git_metadata_at_ref` +
    `derive_display_version` helpers (e.g. `0.8.0+3.g084a6a2`, `.dirty` suffix included);
  - repo not yet cloned → best-effort remote probe (`git ls-remote` HEAD + catalog/PyPI base version), rendered as
    `0.1.7+0.g9a8b7c6` or, when the probe fails, `dev @ main (will clone)` — and the post-switch result/toast always
    reports the exact versions actually installed.

### Execution

A new shared operations package **`src/sase/mode_switch/`** (`models.py`, `repos.py`, `plan.py`, `execute.py`),
mirroring the `dev_update` package shape: pure planning + argv building, injectable command runners
(`ProbeFn`/`RunUvFn`-style, per `src/sase/main/update_types.py`) so everything is unit-testable without touching a real
environment. Both the CLI handler and the TUI mixin call this one layer, like `src/sase/plugins/operations.py` does for
plugin actions.

**Preflight (both directions):** uv-tool probe (`probe_uv_tool_install` — the existing `NotAUvToolInstallError`
rendering applies: pip/pipx/checkout-venv installs fail fast, actionably), `git` on PATH (dev), network reachability for
the resolves/clones that will be needed. `cargo` missing is a _warning_, not a failure: `sase-core-rs` then stays on the
published wheel — the exact fallback `just install` already implements — and the plan row says so.

**`--to dev`:**

1. Clone missing repos into `<dev_root>/` (a partial clone we created is removed on failure; pre-existing directories
   are never deleted).
2. One atomic uv invocation, built by a new pure builder in `src/sase/uv_tool/commands.py` alongside
   `build_install`/`build_uninstall`: `uv tool install --force --reinstall -e <dev_root>/sase` +
   `--with-editable <path>` per plugin (+ plain `--with` for any stays-managed plugin). uv rewrites the receipt, which
   _is_ the mode change.
3. Rebuild the Rust core into the tool venv: `just rust-install-uv-tool` in `<dev_root>/sase` (cargo + checkout present;
   the recipe already validates `sase-core-rs` version compatibility via `tools/validate_sase_core_rs_version`).

**`--to pypi`:** one `uv tool install --force --reinstall sase --with <plugin> …` built from the receipt reconstruction
with editable specs swapped for index specs. `--reinstall` guarantees the locally built `sase-core-rs` wheel is replaced
by the published one. Checkouts remain on disk untouched.

**Recovery breadcrumb:** before mutating, persist the current receipt's reconstructed install argv to
`~/.sase/update/mode_switch_backup.json`. If the uv step fails, the error rendering prints the exact restore command
(and the breadcrumb lets a future `sase doctor` check spot a half-switched env). This is a printed escape hatch, not an
automatic rollback — uv's `--force` install is close enough to atomic that auto-rollback machinery isn't warranted.

**Post-switch (shared):** the standard changed-update path — CLI restarts AXE inline via `restart_after_update`; the TUI
writes a post-update toast receipt and restarts TUI + AXE (below). `-j|--json` gains an additive `switch` object
(direction, dev root, per-package transitions with repo actions, warnings, restart info) on the existing
schema-versioned payload.

### TUI: Updates tab

All heavy work follows the TUI perf rules: planning runs in a threaded worker (like the existing `sase-update-plan`
worker group), execution goes through `_submit_tracked_task` with phased progress, and no handler blocks the event loop.

1. **Mode at a glance.** The `#sase-core-versions` "SASE Core" panel (`plugins_browser_rendering.py`) gains a mode badge
   line rendered in the Updates accent (`#AF87FF`): `Mode  PyPI (managed)` / `Mode  Dev (editable · ~/projects/git)` /
   `Mode  Mixed`, with a dim trailing hint (`m  switch`). Plugin rows already carry editable/index source
   classification; no per-row change needed.
2. **`m` — switch mode.** New binding on `PluginsBrowserPane` (`m` is free; hints line and the Admin Center help/`?`
   content updated in the same change). Direction is inferred: managed → dev, dev → pypi; in `mixed` mode the modal
   opens with both directions available on a toggle (the same `g`-style variant toggle `PluginActionConfirmModal`
   already uses for install-from-index vs git).
3. **`ModeSwitchConfirmModal`** — a sibling of `PluginActionConfirmModal` (y/n/esc bindings) but purpose-built to be the
   beautiful centerpiece: direction header (`PyPI (managed) ──▶ Dev (editable)`), the per-package transition table
   (current dim, target bold, `↓` on downgrades), repo actions (clone/reuse + path), warnings, and the exact command
   sequence — the modal shows precisely what `--dry-run` would print, so TUI and CLI previews can never drift (both
   render the same `SwitchPlan`).
4. **Execution as a tracked task** (`_submit_mode_switch_task`, patterned on `_submit_sase_update_task` /
   `_submit_dev_update_task`): phases "Cloning repos…", "Installing editable set…" / "Installing published set…",
   "Rebuilding sase-core-rs…"; visible in the task indicator/Task Queue; counted by quit-confirmation.
5. **Finish like every other code update:** on a changed successful switch, write an update receipt and
   `_restart_after_update` → TUI + AXE restart → post-update toast. The receipt/toast layer
   (`src/sase/ace/update_receipt.py`, `post_update_toast.py`) gains a mode-switch flavor: title **"✓ Switched to Dev
   (editable)"** / **"✓ Switched to PyPI (managed)"** with the usual per-package `old → new` transitions (the on-disk
   format already tolerates optional fields; this is additive).

### Coherence after the switch

No follow-up wiring is needed: once the receipt holds editable (or index) specs, `sase update`, the update indicator,
incoming-commit previews, `sase version`, and the Updates tab all already branch correctly on the new mode. That's the
main reason to implement the switch as a receipt rewrite rather than a parallel install pathway.

## Testing

- **Unit (pure):** `mode_switch` planning — mode/direction inference, repo resolution (catalog, fallback, unknown-repo
  degradation), transition computation incl. downgrades and `.dirty`, argv builders (both directions, cargo-missing
  fallback, stays-managed plugins), preflight classification. Injected probes throughout; no real env.
- **CLI:** `tests/` handler tests with fake runners mirroring `test_plugin_cli_*.py` / update-handler tests: prompt
  accepted/declined/EOF, non-TTY refusal, `--yes`, `--dry-run` (no runner calls), `--to` current-mode no-op, JSON
  payload shape, breadcrumb written before mutation, restore hint on failure, AXE restart invoked only on change.
- **TUI:** pane tests alongside `test_plugins_browser_pane_*.py`: `m` opens the modal with a computed plan; cancel is a
  no-op; confirm submits the tracked task; success writes a receipt and calls `_restart_tui(restart_axe=True)` (existing
  monkeypatch pattern); failure surfaces the restore hint without restarting.
- **Receipt/toast:** round-trip the mode-switch receipt flavor; toast title/wording tests in
  `test_post_update_toast.py`.
- **Visual snapshots** (`just test-visual`, new goldens): mode badge in managed and dev states, the switch confirm modal
  in both directions, and the post-switch toast.
- Full `just check` after implementation.

## Risks / edge cases

- **uv failure mid-switch** leaves the env on whatever uv left behind; mitigated by the breadcrumb + printed restore
  argv (and uv tool installs are effectively rebuild-from-scratch, so a retry is always safe).
- **Downgrade surprises** when leaving dev (dev version > published): explicitly flagged in the plan table.
- **Dirty/diverged checkouts** reused for dev: surfaced as warnings pre-confirm; we never touch the working tree.
- **cargo absent**: core silently staying on the published wheel would be confusing — hence the explicit plan-row note
  and warning (matches the `just install` fallback users already have).
- **Catalog/PyPI offline**: `--to pypi` needs the network to resolve anyway; `--to dev` previews degrade to "will clone
  @ main" labels, and missing-clone execution fails preflight with an actionable message.
- **Version-pin skew** (`sase` pins `sase-core-rs>=0.3.0,<0.4.0`): enforced by the existing validation inside
  `just rust-install-uv-tool` before building.
- **Switching from inside the TUI kills running tracked tasks** on restart: the existing pre-restart warning covers
  this, and the modal mentions the restart so it's never a surprise.

## Sequencing

1. `src/sase/mode_switch/` package: models, repo resolution, pure planning + argv builders (+ the new
   `uv_tool/commands.py` builder) + unit tests.
2. Execute layer: clone/reuse, uv invocation, core rebuild, breadcrumb — injectable runners + tests.
3. CLI: `-t|--to` + `-y|--yes` on `sase update`, prompt, Rich plan rendering, JSON, help text/examples + handler tests.
4. TUI: mode badge, `m` binding, `ModeSwitchConfirmModal`, tracked task, receipt/toast flavor, restart wiring + pane and
   receipt/toast tests; hints + Admin Center help text.
5. Visual snapshot goldens (badge, modal ×2, toast) via `just test-visual`.
6. Docs & config: `default_config.yml` + `sase.schema.json` (`update.dev_root`), INSTALL.md dev-mode section,
   `sase update` help; final `just check`.
