---
create_time: 2026-06-27 14:37:56
bead_id: sase-5c
tier: epic
status: done
prompt: sdd/prompts/202606/dev_version_support.md
---
# Dev-Version Support for `plugin list`, `update`, and the Admin Center "Updates" Tab

## Summary

SASE already derives and displays **dev versions** (PEP 440 local versions from git, e.g. `0.5.0+285.g80d5c47c1`) for
the `sase version` command. This work extends that to the three surfaces that show or act on versions:

1. **`sase plugin list`** — show the **current** dev version and the **latest** dev version (with an update indicator)
   for any editable package (core packages and plugins), in both human and `--json` output.
2. **`sase update`** — update editable installs to the **latest dev version** (when a dev version is in use), alongside
   the existing managed `uv tool` upgrade path.
3. **The "Updates" tab of the TUI "SASE Admin Center"** — the same display, the ability to update dev installs, and
   automatic restart afterward.

It also adds one cross-cutting behavior the user asked for explicitly: after **any** successful update that changed code
(dev _or_ regular), **automatically restart the TUI and restart axe** in the TUI context (and restart axe in the CLI
context), reusing the existing `Q`-keymap quit/restart machinery.

The hard, central question this plan answers precisely is **"what does it mean to update a dev install?"** The answer is
grounded in the _real_ install topology (verified below), not an assumed one.

## The Real Install Topology (this is the crux)

The canonical SASE development install — and the realistic target of this feature — is a **receipt-owned, uv-tool
editable install** of the tool named `sase`. Its `uv-receipt.toml` lists every package as an editable local checkout:

- `sase` (host) → its checkout
- `sase-core-rs` (core) → the `crates/sase_core_py` package dir inside the `sase-core` checkout
- first-party plugins (e.g. `sase-github`, `sase-telegram`) → their checkouts
- plus bare-index duplicate rows for some plugins (already deduped, editable row wins)

Two consequences drive the entire reconcile design:

- The running interpreter is the **uv-tool venv** (`<uv tool dir>/sase`), not any repo `.venv`. Therefore the refresh
  after a pull must target the **uv-tool venv**. (`just install` targets a repo `.venv` and is the _wrong_ target here —
  this is the trap both prior inspiration plans fell into.)
- **Editable Python packaging makes `.py` edits live on next process start, but it does NOT recompile the Rust extension
  and does NOT pick up dependency or entry-point changes.** So a dev update is "pull the source, then reconcile the
  uv-tool environment so importable code, compiled artifacts, dependencies, and entry points all match the pulled
  source."

This topology, the receipt-as-source-of-truth model, and the "Rust needs an explicit rebuild" fact are all corroborated
by `sdd/research/202606/uniform_sase_dev_install_consolidated.md` and
`sdd/research/202606/sase_update_dev_consolidated.md`.

## Goals

- For each **editable** package (host `sase`, core `sase-core-rs`, editable plugins), show the current dev version and
  the latest available dev version, and clearly indicate when an update is available — in `sase plugin list` (human +
  `--json`) and in the Admin Center "Updates" tab.
- `sase update` and the "Updates" tab update editable installs to the latest dev version, handling every edge case
  safely and legibly (dirty, diverged, detached HEAD, no upstream, offline, fetch failure, Rust-core rebuild).
- After any successful update that changed code, automatically restart: TUI + axe (TUI context) and axe (CLI context),
  reusing the existing restart code.
- Result is intuitive, reliable, and beautiful: glyphs/coloring consistent with the current catalog UI, honest status
  messaging for non-updatable cases, no silent or surprising behavior.
- Managed (`uv tool` / wheel / index) behavior is preserved; dev support is purely additive and gated on the install
  being editable.

## Non-Goals

- No change to `sase version` output (current dev versions already render there; "latest" is out of scope for it).
- No auto-merge / auto-rebase / stash / dirty-tree mutation. Updates are **fast-forward-only**; unsafe states are
  reported, not forced. (A future `--force` is out of scope.)
- No new keymap and **no new CLI flags**. Editable installs naturally update as dev installs. Reuse existing
  `-n/--dry-run`, `-j/--json`, `-q/--quiet`, the existing update keymaps, and the `Q` restart logic.
- No support for plain repo-`.venv` editable installs in `sase update` (it already, intentionally, rejects non-uv-tool
  installs; contributors refresh those with `just install` + `git pull`). Direct non-editable `git+...` installs are NOT
  treated as local dev checkouts.
- Adding dev support to the `sase plugin update` CLI subcommand is out of scope (the user scoped three surfaces). The
  backend is per-package capable so the TUI per-plugin action can reuse it, but no new `sase plugin update` dev path.
- Moving this subsystem into the Rust core (see "Architecture & boundary" below).

## Architecture & Boundary Decision (flagging for review)

The repo's Rust-core boundary rule says shared backend/domain logic belongs in `../sase-core`. However, the **entire
existing version/update subsystem is already Python** (`src/sase/version`, `src/sase/plugins`, `src/sase/uv_tool`,
`src/sase/main/update_handler.py`), and this feature is local-environment orchestration over git, maturin, and uv on the
developer's own checkouts. To stay consistent with that established subsystem and avoid a cross-repo build/release
dependency, **this feature extends the Python subsystem** and adds no Rust-core APIs. If we'd rather model dev-version
detection in `sase-core` for reuse by other frontends, that is a larger restructure to agree on before Phase 1.

## Design Decisions (calling these out for review)

1. **"Latest dev version" = the upstream tracking ref after fetch.** For an editable checkout we resolve `@{upstream}`
   (e.g. `origin/master`), `git fetch` it (unless offline), and render the dev version _at that ref_ via the existing
   `derive_display_version`. "Update available" is decided by **git ancestry** (`git rev-list --count HEAD..@{u} > 0`),
   **not** PEP 440 comparison — dev local-version segments do not order reliably, so ancestry is the trustworthy signal.

2. **Updates are fast-forward-only and never destructive.** We update only when a checkout is clean **and** strictly
   behind upstream (`git merge --ff-only @{u}`). Dirty, diverged, detached-HEAD, and no-upstream states are surfaced
   with a clear reason and **skipped**, never forced. Preflight all requested roots first; never leave a half-pulled
   root.

3. **Reconcile targets the uv-tool environment (the real topology), and the Rust core gets an explicit release
   rebuild.** After safe fast-forwards (deduped by git root):
   - **Python editable packages (host + plugins):** re-run the **receipt-reconstructed `uv tool install`** so changed
     dependencies and entry points apply (reusing the existing `src/sase/uv_tool` receipt/command machinery —
     `ToolReceipt.reconstruct` / `build_install`). The implementing agent must verify the exact reinstall flags against
     the local `uv` so an editable source whose version string is unchanged is actually reinstalled.
   - **Rust core (`sase-core-rs`):** rebuild the compiled extension **into the uv-tool venv** via the maintained
     `just rust-install-uv-tool` recipe (run with cwd = the host checkout's `source_root`; it does
     `maturin develop --release` + version validation + stale-extension purge). Fall back to a direct
     `maturin develop --release` in `<core_root>/crates/sase_core_py` against the uv-tool venv only if `just`/cargo is
     unavailable, and surface that clearly.
   - **Batch and sequence** to avoid a redundant Rust rebuild (don't compile the extension twice across the uv reinstall
     and the `just` rebuild). The plan defines the contract; the implementer pins the exact sequence after verifying uv
     behavior locally.

4. **Restart after update (reuse the `Q` machinery).**
   - **TUI:** after any successful update that changed code (dev _or_ regular), call `_restart_tui(restart_axe=True)`
     (`src/sase/ace/tui/actions/axe.py`) — the same path the `Q` "Restart TUI & axe" choice uses. Surface the existing
     running-task warning UX (as in `QuitOptionsModal`). No restart on a no-op or failed update.
   - **CLI `sase update`:** there is no in-process TUI; restart the **axe daemon** via `restart_axe_daemon_result()`
     when axe is running and the update changed code (the long-lived daemon would otherwise run stale code; the next CLI
     invocation is fresh automatically). No restart on no-op/failure.

5. **Everything keys off the version inventory's recorded `source_root`** (from PEP 610 `direct_url.json`), so behavior
   is correct regardless of the cwd `sase` was invoked from. Git ops run at the git root; the Rust rebuild runs at the
   host checkout; the maturin package dir is `<core_root>/crates/sase_core_py`.

6. **Gated strictly on editable installs.** Dev detection/update applies to a package only when
   `install_type == "editable"`. Managed packages keep PyPI/uv behavior. Mixed environments are handled per-package.
   Multiple packages sharing one git root are deduped (probe/fetch/ff that root once, map the result back to each).

## Phasing Overview

Five phases. Phase 1 is the foundation. Phases 2 and 3 depend only on Phase 1 and are independent of each other. Phase 4
depends on Phases 1 and 2. Phase 5 is the final repo-wide consolidation.

| Phase | Title                                                | Depends on | Primary surface                                                                              |
| ----- | ---------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------- |
| 1     | Dev-update backend service (detect + plan + execute) | —          | new `src/sase/dev_update/`; extend `src/sase/version/_git.py`                                |
| 2     | `sase plugin list` + core-versions dev display       | 1          | `plugins/latest.py`, `catalog.py`, `render_catalog.py`, `cli_list.py`, `uv_tool/versions.py` |
| 3     | `sase update` dev execution + axe restart            | 1          | `main/update_handler.py` (+ render); axe restart                                             |
| 4     | "Updates" tab: dev display + update + auto-restart   | 1, 2       | `ace/tui/modals/plugins_browser_*`; visual snapshots                                         |
| 5     | Consolidation: docs, skills/CLI sync, validate, gate | 1–4        | docs, generated skills, `sase validate`, final `just check`                                  |

Each phase MUST run `just install` then `just check` before handoff (per repo rules). Known pre-existing failures
(`llm_provider`/`default_effort`, and any `sase validate` freshness drift reconciled in Phase 5) are not regressions.

---

## Phase 1 — Dev-Update Backend Service (`src/sase/dev_update/`)

**Goal.** A pure, fully unit-tested Python service that, given the existing version inventory, (a) detects the latest
dev version and update-availability for each editable package, and (b) plans and executes a safe dev update (pull +
reconcile). No UI/CLI changes. This is the single source of truth consumed by Phases 2–4, so its public API must be
designed from those consumers' needs (display-only in Phase 2; plan + execute in Phases 3–4).

**Ref-aware git probing.** Extend `src/sase/version/_git.py` with the new operations (keep the `run_git` pattern and
short timeouts; add injectable network/mutating ops so tests need no real git):

- Probe metadata **at an arbitrary ref** (generalize the existing `probe_git_metadata` so it can target `@{u}`): tag via
  `git describe`, distance via `git rev-list --count <tag>..<ref>`, short commit via `git rev-parse --short=9 <ref>`. (A
  remote ref is clean by definition; reading the base version at the ref via
  `git show <ref>:pyproject.toml`/`Cargo.toml` is a rare fallback only needed when there's no tag at the ref.)
- Resolve upstream and classify HEAD vs upstream: detached HEAD, no-upstream, behind/ahead counts, diverged, dirty.
- New mutating ops: `git fetch --quiet <remote> <branch>` and `git merge --ff-only <upstream-ref>`.

**Public API (design from the consumers).**

- `detect_dev_latest(record, *, offline) -> DevLatest`: for one editable `VersionPackageRecord`, resolve upstream, fetch
  unless offline (best-effort; fall back to the cached remote-tracking ref on failure), compute `latest_version` at
  upstream, and classify a **state** with a human reason: `current`, `update_available`, `dirty`, `diverged`,
  `detached`, `no_upstream`, `offline`, `fetch_failed`, `unavailable`. Carries an explicit ancestry-based
  `update_available: bool`.
- `plan_dev_update(records, *, host_record) -> DevUpdatePlan`: dedupe records by git root; partition into **actionable**
  (clean + strictly behind) and **skipped** (with reasons); compute the **deduped reconcile steps** (receipt-based
  `uv tool install` for the Python set when host/plugins changed; `just rust-install-uv-tool` for the core when the core
  changed), batched per Decision 3.
- `execute_dev_update(plan, *, run) -> DevUpdateResult`: preflight, then for each actionable root fetch (fresh) +
  `git merge --ff-only`, then run the batched reconcile steps; collect per-package outcomes (old/new dev version, status
  `updated`/`skipped`/`failed`, reason) and an overall `changed` flag. All subprocess invocation goes through an
  **injectable runner** so tests need no real git/maturin/uv.

**Edge cases (all covered by tests):** dirty (skip), diverged (skip, ff-only refused), detached HEAD (skip), no upstream
(skip), already current (no-op), offline (no fetch; use remote-tracking ref; never mutate), fetch/network failure (skip,
clear reason), ff-only failure (failed, surfaced), missing `just`/cargo (fallback or clear failure), core rebuild vs
host-only refresh chosen correctly, multiple editable packages sharing one git root (probe/fetch/ff once, reconcile
batched, no redundant Rust rebuild), unknown `source_root` (skip with reason), receipt absent/malformed (degrade
clearly).

**Files.** New `src/sase/dev_update/` (`detect.py`, `plan.py`, `execute.py`, `models.py`, `__init__.py`); extend
`src/sase/version/_git.py`. New tests under `tests/dev_update/` using a fake git/subprocess runner and synthetic
`VersionPackageRecord`s, mirroring the existing `tests/_version_inventory_helpers.py` patterns.

**Acceptance.** The public API and result dataclasses are importable and unit-tested across all edge cases above; no
behavior change to any command/UI yet; `just check` passes (modulo known pre-existing failures).

---

## Phase 2 — `sase plugin list` + Core-Versions Dev Display

**Goal.** Show current **and** latest dev versions plus an update indicator for editable core packages and editable
plugins — in `sase plugin list` (human + `--json`) and in the shared core-versions data the Admin Center reuses. Depends
on Phase 1's `detect_dev_latest`. Read-only; no update execution.

**Key changes.**

- **`src/sase/plugins/latest.py`.** Replace the editable short-circuit (today returns `error="non-index install"` with
  no version) with a call into Phase 1 dev detection for editable dists. Extend `LatestInfo` to carry the latest dev
  `version`, an explicit `update_available` flag, and the dev `state`/reason. Resolve each editable dist's `source_root`
  and git metadata from the version inventory (build a normalized-dist-name → `VersionPackageRecord` lookup and inject
  it, rather than re-reading `direct_url.json`). Respect `offline`.
- **`src/sase/plugins/catalog.py`.** Make `update_available` true for `source == "index"` (unchanged) **and** for
  editable installs when dev detection reports an available update.
- **`src/sase/uv_tool/versions.py`.** Make `enrich_core_versions_latest` dev-aware: for editable `sase`/`sase-core-rs`,
  populate latest + `update_available` from Phase 1 dev detection instead of PyPI. (This module feeds the Admin Center
  core panel, so Phase 4 inherits it.)
- **`src/sase/plugins/render_catalog.py`.** Render dev versions beautifully and consistently with the existing glyph
  language (`●`/`○`/`↑`): for an updatable dev install show `current → latest` with `↑` and a dim `dev` tag; for
  non-actionable dev states show a dim parenthetical reason (e.g. `dev · local changes`, `dev · diverged`,
  `dev · no upstream`, `dev · offline`) instead of a misleading arrow. Keep colors aligned with the current palette.
  Apply the same in `plugin show` detail rendering.
- **JSON.** Bump `LIST_JSON_SCHEMA_VERSION` (2 → 3); add per-entry `install_type`, `current_version`, latest dev
  `version`, dev `update_available`, and dev `state` fields.

**Edge cases.** Offline (no fetch; show "offline"); non-editable packages unchanged (still PyPI/index); dev install with
no upstream / dirty / diverged shows an honest non-update state, never a misleading arrow; missing `source_root`
degrades gracefully (display must never crash list/show — keep the existing defensive `except` posture).

**Files.** `src/sase/plugins/latest.py`, `catalog.py`, `render_catalog.py`, `cli_list.py` (JSON), `uv_tool/versions.py`;
tests in `tests/test_plugin_cli_list.py`, `tests/test_plugin_latest.py`, and `tests/uv_tool/test_versions.py` with new
dev fixtures.

**Acceptance.** `sase plugin list`/`show` display current+latest dev versions and an update indicator for editable
core/plugins; `--json` reflects the new schema; offline and non-actionable dev states render honestly; non-editable
behavior is unchanged; `just check` passes.

---

## Phase 3 — `sase update` Dev Execution + Axe Restart

**Goal.** `sase update` updates editable installs to the latest dev version (when dev versions are in use), in addition
to the existing managed `uv tool` path, and restarts axe after a successful changed update (dev or regular). Depends on
Phase 1.

**Key changes.**

- **`src/sase/main/update_handler.py`.** Before requiring a uv-tool receipt only for the managed path, gather the
  editable package set from the version inventory and route:
  - editable packages present → **dev path**: `plan_dev_update` + `execute_dev_update`, rendered beautifully
    (per-package `old → new` dev version, skipped packages with actionable reasons, reconcile steps run).
  - managed `uv tool` install, no editable packages → **existing path**, unchanged.
  - mixed → run the dev path for editable packages and the managed path for the rest; present one unified result.
  - neither updatable → clear, friendly message.
- **Dry-run.** Reuse `-n/--dry-run` to print the dev plan (what would be fetched / fast-forwarded / reconciled) without
  mutating, alongside the existing managed dry-run preview.
- **Restart.** After a successful update that changed code, restart the **axe daemon** via `restart_axe_daemon_result()`
  when axe is running, with clear output (and an honest note when running agents will be interrupted). No new flag.
- **JSON.** Bump `UPDATE_JSON_SCHEMA_VERSION` (1 → 2); add dev per-package outcomes and restart info.

**Edge cases.** All Phase-1 dev states surfaced as skipped-with-reason; core rebuild reported as a distinct reconcile
step; axe-not-running → no restart attempted; ff-merge/rebuild failures reported clearly with a non-misleading exit
status; managed-only behavior byte-for-byte preserved.

**Files.** `src/sase/main/update_handler.py` (+ its render module); tests in `tests/main/test_update_command.py` (reuse
the existing `_DEV_RECEIPT` editable fixture; mock Phase-1 detect/execute and the axe-restart call).

**Acceptance.** `sase update` updates a dev install (mocked) and restarts axe; managed-install behavior is unchanged;
dry-run shows the plan; `--json` reflects the new schema; help stays clean/sorted/colored; `just check` passes.

---

## Phase 4 — "Updates" Tab: Dev Display + Update + Auto-Restart

**Goal.** Bring the Admin Center "Updates" tab to parity: show dev versions (current → latest) for editable
core/plugins, update editable targets via the Phase-1 backend, and **automatically restart TUI + axe after any
successful update that changed code** (dev or regular) by reusing the `Q`-keymap restart logic. Depends on Phases 1, 2.

**Key changes.**

- **Display.** `plugins_browser_pane.py` core-versions panel inherits the dev-aware `CoreVersions` (Phase 2); the
  catalog list/detail reuse the Phase-2 dev rendering so the tab matches `sase plugin list` (current → latest, `↑`,
  `dev` tag, honest non-actionable states). Keep all git/package probing inside the existing off-thread load worker —
  never block the Textual event loop.
- **Update actions.** Route the `S` (sase update) action — and, for editable targets, the per-plugin `u`/`U` actions —
  through the Phase-1 dev backend, run inside the existing tracked-task system. The `PluginActionConfirmModal` shows the
  dev operation (fetch + fast-forward + reconcile/rebuild) and disables/explains unsafe targets
  (dirty/diverged/no-upstream) with their reason.
- **Auto-restart.** Replace the manual `_sase_update_restart_hint` with automatic restart: in the tracked-task
  `on_complete` callback (which runs on the UI thread, like the `Q` callback), if the update succeeded and changed code,
  call `_restart_tui(restart_axe=True)`. UX: a brief, beautiful notice ("Updated <name> — restarting ACE to load new
  code…") then restart; surface the existing running-task warning when tracked tasks/agents are running. No restart on
  no-op/failure. Use `reload_on_complete=False` for update tasks that will restart.
- **Visual snapshots.** Add/refresh PNG goldens in `tests/ace/tui/visual/snapshots/png/` for: dev versions displayed,
  dev update-available state, and the restart notice. Use `--sase-update-visual-snapshots` only for intentional changes.

**Edge cases.** Update-available dev vs non-actionable dev rendering; auto-restart only on real change; running-task
warning path; offline tab behavior; core rebuild surfaced in the task/result; the restart re-exec preserves the uv-tool
venv and original flags (already handled by the reused machinery).

**Files.** `src/sase/ace/tui/modals/plugins_browser_pane.py`, `plugins_browser_rendering.py`,
`plugins_browser_sase_update.py`, `plugins_browser_update.py`, `plugin_action_confirm_modal.py` as needed, `styles.tcss`
if needed; tests in `tests/ace/tui/test_plugins_browser_pane_update.py` and the visual suite.

**Acceptance.** The "Updates" tab shows and updates dev versions and auto-restarts TUI+axe after a successful changed
update; regular updates also auto-restart; no-op/failed updates do not restart; visual snapshots updated and pass;
`just check` and `just test-visual` pass.

---

## Phase 5 — Consolidation: Docs, Generated Skills, Validation, Final Gate

**Goal.** Make the feature coherent and finish the regression net repo-wide.

**Scope.**

- Update user docs for dev-version display and update semantics (CLI + Admin Center), including the blocked dev states
  (dirty/diverged/detached/no-upstream/offline) and the manual fixes users should apply.
- Audit output copy for consistency: use "dev" / "editable checkout" consistently; keep tables compact at normal
  terminal/TUI widths; don't make color the only signal.
- Regenerate any drifted generated docs/skills and reconcile the CLI/skill contract (`sase skill init --force` then
  `chezmoi apply`, per `memory/generated_skills.md`), and reconcile the `sase validate` freshness gate caused by
  renderer/CLI changes across earlier phases.
- Confirm JSON schema bumps (`plugin list` 2→3, `update` 1→2) are documented and asserted by tests.
- Final verification: `just install`, then `just check` and `just test-visual`; confirm the only remaining failures are
  the known pre-existing ones, not regressions.

**Acceptance.** Docs and generated artifacts are in sync; `just check`, `just test-visual`, and `sase validate` are
green (modulo known pre-existing failures); the feature is coherent across all three surfaces.

## Cross-Phase Risks & Mitigations

- **Reconcile targets the wrong environment** (refreshing a repo `.venv` instead of the uv-tool venv) — mitigated by
  Decision 3 and keying everything off the inventory's `source_root` + the receipt; the Rust core uses
  `just rust-install-uv-tool` (uv-tool venv), never `just install` (repo `.venv`).
- **Stale Rust core after a pull** (running old `.so`) — mitigated by the mandatory release rebuild in the reconcile
  step via the maintained recipe.
- **uv reinstall semantics for unchanged-version editable sources** — the implementer must verify exact flags against
  the local `uv` so a same-version editable source is actually reinstalled (dep/entry-point changes applied) without a
  redundant double Rust build.
- **Destroying local work** — mitigated by fast-forward-only updates and hard skips on dirty/diverged (Decision 2).
- **Misleading "update available"** — mitigated by ancestry-based detection, not PEP 440 string comparison (Decision 1).
- **Restart interrupts running agents** — the reused `Q` "restart TUI & axe" path already surfaces a running-task
  warning; the CLI prints an honest notice before bouncing axe. This is the behavior the user asked to reuse.
- **Docs/skill freshness drift from renderer/CLI changes** — expected; reconciled in Phase 5. Earlier phases may go red
  on the freshness gate until then (known).
- **Terminal/venv correctness on restart** — inherited from the already-hardened `Q`-keymap re-exec path; no new
  mechanism introduced.
