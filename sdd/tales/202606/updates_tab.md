---
create_time: 2026-06-26 19:01:28
status: done
prompt: sdd/prompts/202606/updates_tab.md
---
# Plan: SASE Admin Center — rename Plugins → Updates, add a SASE Core update surface

## Context

The **SASE Admin Center** is a full-screen `ModalScreen` (`ConfigCenterModal`) hosting six alphabetical tabs over a
`ContentSwitcher`: **Config, Logs, Plugins, Projects, Tasks, XPrompts**. It opens with `#` (remembering the last tab in
the session), digits `1`–`6` jump to a tab, and `[` / `]` cycle. The **Plugins** tab (`PluginsBrowserPane`) is a
master/detail catalog browser mirroring `sase plugin list` — it can install (`i`), update (`u`), update-all (`U`), and
uninstall (`x`) plugins, all routed through a confirm-preview modal and run as tracked background tasks.

Separately, SASE already has a complete, Python-only **uv-tool update engine** (`src/sase/uv_tool/`, epic decision _D6_:
frontend packaging behavior, no Rust `sase-core` involvement):

- `build_upgrade_all()` produces the exact argv `uv tool upgrade sase`, which re-resolves **sase core _and_ every
  installed plugin in one shot** (decision _D3_). This is precisely what the top-level `sase update` command runs.
- `run_uv()` executes it and parses the result into a `UvChangeSet`; `summarize_update()` merges that with the uv
  receipt into an `UpdateSummary` (what changed, old→new versions, what is already current).
- Detection (`probe_uv_tool_install()` → `UvToolInstall` / `NotUvToolInstall`) gates whether an upgrade is even possible
  (only a managed `uv tool install sase` can be upgraded; a dev checkout cannot).

The runtime version inventory (`src/sase/version/`) already names the two packages we care about:
`HOST_DISTRIBUTION_NAME = "sase"` and `CORE_DISTRIBUTION_NAME = "sase-core-rs"` (the Rust core's PyO3 wheel). Installed
versions come from `importlib.metadata.version(...)`; "latest available" is fetched from PyPI exactly as the plugin
catalog already does it — `fetch_latest_version()` (`src/sase/plugins/pypi_source.py`) plus PEP-440 `is_newer()`
(`src/sase/plugins/latest.py`).

This work turns the Plugins tab into a true **Updates** tab: a single home for keeping SASE current — both its core
(sase + sase-core) and its plugins — that is intuitive, reliable, and beautiful.

### Key source touch-points (repo-relative)

- `src/sase/ace/tui/modals/config_center_modal.py` — tab order/labels/colors, numbered strip, digit jumps, docstring.
- `src/sase/ace/tui/modals/plugins_browser_pane.py` + siblings (`plugins_browser_rendering.py`,
  `plugins_browser_loading.py`, `plugins_browser_update.py`) — the pane that becomes the Updates tab.
- `src/sase/ace/tui/modals/plugin_action_confirm_modal.py` — the reusable "show the exact `uv` argv, confirm" modal.
- `src/sase/ace/tui/actions/task_actions.py` — `_submit_tracked_task(...)`, the tracked background-task API (live output
  in the Tasks tab, completion callback, dedup).
- `src/sase/uv_tool/` — the update engine (`build_upgrade_all`, `run_uv`, `summarize_update`) and detection.
- `src/sase/plugins/{pypi_source,latest}.py` — PyPI latest lookup + PEP-440 comparison.
- `tests/ace/tui/` (unit, integration, `_plugins_browser_pane_helpers.py`, and the `visual/` PNG snapshots).

## Goals

1. **Rename the "Plugins" tab to "Updates"** and move it to position 5 — immediately before **XPrompts**, after
   **Tasks**. Renumber the digit hotkeys to match.
2. **Add a "SASE Core" surface at the top of the Updates tab** showing the **installed → latest** versions of `sase` and
   `sase-core`, with a clear "update available" / "up to date" status.
3. **Add a new keymap that runs `sase update`** from the Updates tab in a way that is pleasant in a TUI: a confirm
   preview of the exact `uv` command, then a non-blocking, tracked background run with live output in the Tasks tab, a
   success/fail toast, and the version surface refreshing in place.
4. **Keep the full plugin browser** (browse / install / update / uninstall) — nothing is removed (answer to Q1: _Keep +
   augment_).
5. Lead the design; make it intuitive, reliable, and beautiful.

## Design

### Decision 1 — Rename + reorder preserves the alphabetical invariant

The current order is alphabetical by visible label (the invariant established by the prior Admin Center work). Renaming
**Plugins → Updates** and placing it before XPrompts is _not_ an exception to that rule — it **upholds** it, because
"updates" sorts between "tasks" and "xprompts":

| #   | tab id     | label    | change                          |
| --- | ---------- | -------- | ------------------------------- |
| 1   | `config`   | Config   | —                               |
| 2   | `logs`     | Logs     | —                               |
| 3   | `projects` | Projects | digit 4 → **3**                 |
| 4   | `tasks`    | Tasks    | digit 5 → **4**                 |
| 5   | `updates`  | Updates  | was `plugins` (digit 3) → **5** |
| 6   | `xprompts` | XPrompts | —                               |

Implementation: in `config_center_modal.py`, reorder the single source of truth `_TAB_ORDER` / `_TAB_LABELS` to the
sequence above, rename the `plugins` tab **id → `updates`** and label → **"Updates"**, rekey `_TAB_COLORS` (`updates`
keeps the existing accent `#AF87FF`), and reorder the `compose()` yields to match. Numbering stays position-derived
("tab N" is always `_TAB_ORDER[N-1]`), so the strip auto-renumbers and there is no parallel table to drift. Update the
module docstring (order + the per-tab numbers).

**Rename the tab _id_, not the pane internals.** The Admin Center keeps its clean invariant of _tab id == lowercased
label_, so the id becomes `updates` (the `ContentSwitcher` child id and `PluginsBrowserPane(id="updates")`).
Deliberately **out of scope**: renaming the `PluginsBrowserPane` class, the `plugins_browser_*` module files, the
internal widget ids (`#plugins-list`, `#plugins-summary`, …), or the `plugin__` option-id prefix — those are
implementation details, the pane _is_ still the plugin browser at its core, and a sweeping rename would be large churn
for no user-visible gain. The only id consumers outside the modal are the shared test helper (`initial_tab="plugins"` /
`#plugins`) and two direct-assertion tests, all updated to `updates`. Default open tab stays `config`, so plain `#` is
unchanged on a fresh session.

### Decision 2 — A beautiful, compact "SASE Core" panel at the top of the Updates tab

Add a `Static` (`#sase-core-versions`) as the first child of the pane (above the existing counts summary). It renders a
single titled Rich `Panel` ("SASE Core", border in the tab accent), reusing the exact grammar of the `sase update`
result renderer (`src/sase/uv_tool/render.py`): a glyph, the name, an installed→latest version transition, and a dim
note — so color enhances but is never load-bearing.

```
╭─ SASE Core ──────────────────────────────────────────────╮
│  ↑  sase        v0.5.0 → v0.6.0   update available        │
│  ·  sase-core   v1.4.2            up to date              │
│                                                          │
│  S  run `sase update`  ·  upgrades sase core + all plugins│
╰──────────────────────────────────────────────────────────╯
```

Row states (per package), mirroring `render.py`'s glyph legend and `_version_cell`:

- **Update available** (`is_newer(latest, installed)`): cyan `↑`, `v{installed} → v{latest}` (new in cyan), note "update
  available".
- **Up to date**: dim `·`, `v{installed}`, note "up to date".
- **Latest unknown** (offline / PyPI miss / core not on a public index): dim `·`, `v{installed}`, dim note "latest
  unknown" — never a false "update available".
- **Checking** (latest fetch in flight): `v{installed}`, dim "checking latest…".

The CTA line advertises the new key and the precise scope ("upgrades sase core + all plugins"). When sase is **not** a
managed `uv tool` install, the panel drops the CTA and shows the same actionable warning the plugin browser already uses
("`sase update` unavailable — sase is not a `uv tool` install."), so the surface degrades honestly to an
installed-versions display.

### Decision 3 — `S` runs `sase update` as a tracked background task (the Q2 "pleasant" flow)

Add one pane-level binding **`S` → `action_update_sase`** ("**S**ase update"). `S` is chosen because it is the only
free, memorable, capital-consistent key (the established `u` = update one plugin, `U` = update all plugins are left
intact, giving a natural escalation `u → U → S` = one plugin → all plugins → sase core + everything), and because the
panel's CTA literally reads "run `sase update`", making the key self-documenting. It is scoped to the Updates pane (like
`u`/`U`), so it fires only when the Updates tab's list has focus (typing `S` into the filter input still types a letter,
exactly as `u`/`U` already behave).

The run reuses the **existing plugin-update flow verbatim** (answer to Q2: _Tracked background task_):

1. **Gate**: if `self._uv_tool` is `NotUvToolInstall`, toast the actionable `NotAUvToolInstallError` message and stop —
   identical to the plugin-update gate.
2. **Confirm preview**: reuse `PluginActionConfirmModal` with a single
   `PluginActionVariant(key="update-sase", label="sase update", argv=("uv","tool","upgrade","sase"), summary="Upgrades sase core + every installed plugin")`,
   titled "Update SASE". The modal shows the **exact** `uv` command and the scope, then asks to confirm — the
   confirmation _is_ the dry-run (decision _D5_).
3. **Run (non-blocking)**: on confirm,
   `self.app._submit_tracked_task("sase-update", "sase", "", task, display_name="sase update", dedup_key="sase-update", duplicate_message="A sase update is already running.", on_complete=…, reload_on_complete=False, notify_on_complete=False)`.
   The task body runs `run_uv(build_upgrade_all(color="never"))`, then
   `summarize_update(change_set, receipt, current_version=importlib.metadata.version)`, returning a `TrackedTaskResult`
   (success + a concise CLI-flavored message + the `UpdateSummary` payload; `UvToolError` → failure). The task runs in a
   worker thread with stdout/stderr captured to a live buffer **watchable in the Tasks tab** (tab 4), and the top-bar
   task indicator ticks up.
4. **Completion**: `on_complete` toasts the outcome (e.g. "Updated sase + 3 plugins in 12s", or "Already up to date.",
   or "sase update failed: …") and, on success, reloads the pane in place (`_start_load(force=False)`) so the SASE Core
   panel and every plugin row reflect the new installed versions. After a successful core/plugin upgrade the panel also
   surfaces the engine's standing advice as a dim line: "Restart running sase agents to pick up the new version."

This mirrors `plugins_browser_update.py` exactly, so there is no new task/streaming machinery — only a new action that
targets `uv tool upgrade sase` instead of `--upgrade-package`.

### Decision 4 — Version data: installed instantly, latest off-thread, one refresh path

Versions load in two phases so the panel is never blank and never blocks:

- **Installed** (`importlib.metadata.version` for `"sase"` and `"sase-core-rs"`) is local and instant — rendered on
  `on_mount`, before any network.
- **Latest** is fetched off-thread from PyPI (`fetch_latest_version`, 2s timeout each, best-effort) and folded into the
  **existing catalog-load worker** (`plugins_browser_loading.py`), which already does the network round-trip for plugin
  latest. This gives one unified refresh path: `r` refresh re-checks core latest too; the `o` offline toggle renders
  core latest as "unknown"; the post-`sase update` reload refreshes both. No second "loading" state, no second worker.

A new pure, injectable backend module **`src/sase/uv_tool/versions.py`** holds the data model and logic
(`CorePackageVersion` / `CoreVersions`, `collect_installed_core_versions(version_fn=…)`, and an enrich step that takes
**injected** `fetch_fn` and `is_newer` callables). Keeping the fetch/compare callables injected means `uv_tool` gains
**no import dependency on `sase.plugins`** (avoiding any cycle); the TUI seam supplies `fetch_latest_version` /
`is_newer` from `sase.plugins`. The module is fully unit-testable without touching the network, consistent with the rest
of `uv_tool`.

### Boundary & non-goals

- **No Rust `sase-core` change.** Showing installed/latest versions, the PyPI "latest" lookup, and running
  `uv tool upgrade sase` are all _frontend-specific packaging behavior_, explicitly Python-only by the existing design
  of `uv_tool` (decision _D6_), `plugins.latest`, and the `version` inventory. The core-backend litmus test points the
  same way: any other frontend asking "is there a sase update?" would call this same Python packaging layer — there is
  no shared SASE _domain_ behavior here for Rust to own.
- **No new persistence.** Versions are recomputed per session/refresh; nothing is stored across `sase ace` restarts.
- **No "core-only" upgrade.** `uv tool upgrade sase` re-resolves the whole tool environment (core + plugins) as one
  unit; there is no meaningful "upgrade core but not plugins", so a single `S` action covers both version rows. The
  per-plugin `u`/`U` actions remain for plugin-only scopes.
- **The `sase update` CLI is unchanged** and reused as-is (same engine, same argv).

## Implementation outline

1. **`config_center_modal.py`** — reorder `_TAB_ORDER`/`_TAB_LABELS` to the alphabetical sequence; rename the `plugins`
   tab id → `updates`, label → "Updates", rekey `_TAB_COLORS`; reorder the `compose()` yields and set
   `PluginsBrowserPane(id="updates")`; update the docstring (order + per-tab numbers).
2. **`src/sase/uv_tool/versions.py`** (new) — `CorePackageVersion`/`CoreVersions` data model,
   `collect_installed_core_versions(...)` (installed-only, instant), and
   `enrich_core_versions_latest(..., *, fetch_fn, is_newer)` (best-effort latest + update-available). Pure and
   injectable; `__all__` exported.
3. **`plugins_browser_loading.py`** — extend the load result + loader to also collect installed core versions and enrich
   them with latest (passing `fetch_latest_version` / `is_newer`), honoring the `offline` / `refresh` flags.
4. **`plugins_browser_pane.py`** — store `self._core_versions`; yield `Static(id="sase-core-versions")` as the first
   child; render installed versions on `on_mount`, then the enriched panel when the load lands; add the `S` binding; mix
   in the new update-sase action.
5. **`plugins_browser_sase_update.py`** (new, sibling of `plugins_browser_update.py`) — `SaseUpdateActionsMixin`:
   `action_update_sase` (gate → confirm modal → `_submit_tracked_task`) and `_on_sase_update_complete` (toast + in-place
   reload). Mixed into `PluginsBrowserPane`.
6. **`plugins_browser_rendering.py`** — a render helper that builds the "SASE Core" panel from `CoreVersions` and the
   uv-tool state (loading / up-to-date / update-available / unknown / not-a-uv-tool); add `S sase-update` to the pane
   `_hints()` (gated on a uv-tool install, like `u`/`U`); update the pane/module docstring to "Updates tab".
7. **Tests/helpers** — update `_plugins_browser_pane_helpers.py` (`initial_tab="updates"`, `#updates`); update the
   direct-assertion tests; add the new coverage below.
8. **Help/command surfaces** — the help-popup `#` row ("Admin Center: 1-6 jumps to tab") stays valid (still six tabs);
   optionally add an "updates" alias to the command-palette `open_config_center` entry (`commands/_app_metadata.py`).
   Verify the `src/sase/ace/AGENTS.md` help-popup, footer, and docstring rules stay in sync.

## Testing

### Unit / integration (`tests/ace/tui/`, `tests/`)

- **Order/rename**: assert `_TAB_ORDER == ("config","logs","projects","tasks","updates","xprompts")` and that it is
  sorted by label; assert the strip renders `5 Updates` (and no longer `Plugins`). Update `test_log_panel_keymap.py`
  (`_TAB_ORDER` assertion, any `_admin_center_tab`/`_active_tab == "plugins"` → `"updates"`).
- **Digit jumps / `#N`**: pressing `3` → `projects`, `4` → `tasks`, `5` → `updates`; `#5` composition opens on
  `updates`; `7` is still a no-op. Update `test_config_center_tabs.py` accordingly.
- **`[` / `]` cycle**: update `test_projects_pane.py` — from Config, `]` now visits Logs → Projects → Tasks → Updates →
  XPrompts.
- **Helper + plugin-browser suite**: update `_open_plugins_pane` to `initial_tab="updates"` / `#updates`; confirm the
  existing install/update/uninstall/detail tests still pass against the renamed tab.
- **Core versions (new, `tests/uv_tool/`)**: `collect_installed_core_versions` with an injected `version_fn` returns
  `sase` + `sase-core` with the right dist names; enrich with injected `fetch_fn`/`is_newer` yields `update_available`
  correctly (newer, equal, missing-latest, and not-installed cases); offline path → latest unknown, never a false
  update.
- **`action_update_sase` (new)**: opens `PluginActionConfirmModal` previewing `uv tool upgrade sase` with the
  sase-core-+-plugins summary; gated off (toast) when `NotUvToolInstall`; on confirm, submits a tracked task with
  `dedup_key="sase-update"`; the success completion toasts and triggers an in-place reload (mirror the existing
  plugin-update action tests).
- **Core panel render (new)**: the panel shows installed versions immediately on mount; shows the `↑ update available`
  marker when latest is newer; shows the not-a-uv-tool warning and drops the CTA when `NotUvToolInstall`.

### PNG visual snapshots (`tests/ace/tui/visual/`)

The numbered, reordered tab strip is the shared header of every Admin Center snapshot, and the Updates tab now carries
the new SASE Core panel, so the `config_center_*` goldens change (config, edit, logs, projects, tasks, xprompts, and the
former `plugins` / `plugin_actions` sets — which now show the Updates tab + core panel). Plan:

- Run `just test-visual`; inspect `.pytest_cache/sase-visual/` actual/expected/diff to confirm the renamed/reordered
  strip and the new core panel render cleanly.
- Regenerate goldens with `--sase-update-visual-snapshots` **only after** visually confirming the change is intended,
  then re-run green. Add a focused snapshot for the core-panel "update available" and "not-a-uv-tool" states to lock the
  new UI (keeping existing `config_center_plugins_*` golden/test names to limit churn).

### Gate

Run `just install` then `just check` and `just test-visual`. Keep the ace help popup, footer, and docstrings in sync per
`src/sase/ace/AGENTS.md`.

## Reliability / edge cases

- **Not a `uv tool` install (dev checkout)**: installed versions still shown; `S` gated off with the actionable toast;
  panel shows the "not a `uv tool` install" note and no CTA. Same gate as plugin mutations.
- **PyPI failure / `sase-core` not on a public index**: latest degrades to "unknown"; never a false "update available";
  `S` still works (the actual upgrade is resolved by uv, independent of the display lookup), and after the run the
  installed versions refresh to truth.
- **Offline display toggle (`o`)**: core latest renders "unknown"; `S` remains available (running an upgrade is a real
  action, not a display concern — consistent with how `u`/`U` ignore the offline display toggle).
- **Duplicate run**: `dedup_key="sase-update"` → the duplicate-message toast; no second task.
- **Long upgrade / navigation away**: the run is a worker-thread tracked task, so the UI never freezes; the completion
  handler tolerates an unmounted pane (guarded, like `_on_update_complete`). `run_uv`'s 300s timeout caps a stuck run.
- **Version lookups never crash the UI**: all installed/latest lookups swallow exceptions (mirroring the engine's
  `_installed_version` and the catalog's `_safe_fetch`).
- **Fresh session**: plain `#` still lands on Config (tab 1); the Updates tab is reachable via `#5`, `]`, or a click.
