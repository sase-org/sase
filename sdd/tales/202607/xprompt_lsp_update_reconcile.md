---
create_time: 2026-07-07 14:04:56
status: done
prompt: sdd/prompts/202607/xprompt_lsp_update_reconcile.md
---
# Rebuild and Reinstall the xprompt LSP Server During `sase update`

## Problem

When the user runs a full SASE update (the `u` keymap on the "Updates" tab of the SASE Admin Center, or the
`sase update` CLI), new sase-core commits are pulled into the editable core checkout and the `sase-core-rs` PyO3
extension is rebuilt — but the `sase-xprompt-lsp` language server binary is **never** re-compiled or re-installed. New
LSP functionality that landed in the pulled sase-core commits is silently unavailable: the next `sase lsp` launch keeps
resolving to whatever stale binary happens to win the launcher's search order.

This is not hypothetical. On the primary user machine today:

- `sase-xprompt-lsp` on `PATH` (a one-off `cargo install` artifact in `~/.cargo/bin`) reports **v0.3.3** while the
  sase-core checkout is at **v0.3.4** — and the `PATH` copy wins resolution.
- The checkout's `target/debug/sase-xprompt-lsp` is two weeks older than `target/release/`, yet the launcher prefers
  debug over release unconditionally, so even a fresh release build can be shadowed by a stale debug build.

## Current Behavior (verified)

**Update flow.** Both entry points share one engine:

- TUI: `action_update_sase` in `src/sase/ace/tui/modals/plugins_browser_sase_update.py` → `make_sase_dev_update_preview`
  (`plugins_browser_dev_update.py`) → `plan_dev_update` / `execute_dev_update`.
- CLI: `handle_update_command` in `src/sase/main/update_handler.py` → same `plan_dev_update` / `execute_dev_update`.

**Reconcile steps** (`_reconcile_steps` in `src/sase/dev_update/plan.py`) after fast-forwarding checkouts:

1. `uv_tool_install` — reinstall editable Python packages from the uv-tool receipt (when non-core packages changed).
2. `rust_install_uv_tool` — `just rust-install-uv-tool` in the host checkout (when the core checkout changed); this runs
   `maturin develop --release` for the `sase_core_py` crate only.
3. `rust_health_check` — verify `sase_core_rs` imports, with a wheel-restore repair path.

No step builds or installs the `sase-xprompt-lsp` binary. The `Justfile` has no LSP-related recipe at all.

**The LSP binary is a separate artifact.** `sase_xprompt_lsp` is its own bin crate in the sase-core workspace. It is not
part of the `sase-core-rs` wheel (the wheel is only the PyO3 extension) and it is never published (`release = false` in
sase-core's `release-plz.toml`). The only way to get or refresh it is building from a sase-core checkout.

**Launcher resolution** (`_resolve_xprompt_lsp_command` in `src/sase/integrations/xprompt_lsp.py`):

1. `SASE_XPROMPT_LSP_CMD` env override.
2. `sase-xprompt-lsp` on `PATH`.
3. Sibling-checkout `target/debug/` then `target/release/` binaries (debug always preferred).
4. `cargo run -p sase_xprompt_lsp` fallback.

Steps 2 and 3 both favor artifacts the update flow does not manage, so even adding a rebuild step alone would not fix
the user-visible staleness.

## Goals

1. After a confirmed full SASE update (TUI `u` action or `sase update` CLI) that pulls new sase-core commits, the next
   `sase lsp` launch runs a server built from those commits — with no manual rebuild step.
2. The rebuild/reinstall is visible in the update confirm modal's operation list and in task logs, and its failure is
   attributed clearly (not conflated with the `sase-core-rs` extension rebuild).
3. The launcher prefers the update-managed binary over unmanaged stale copies, while keeping `SASE_XPROMPT_LSP_CMD` as
   the top-priority developer override.

## Non-Goals

- **Managed (non-editable) installs.** `uv tool upgrade sase` consumes published wheels; the LSP binary has no
  publication channel today. Giving managed installs an LSP (e.g. a second maturin `bin` wheel that `sase` depends on)
  is a separate distribution project and is explicitly out of scope. This plan covers the editable/dev-update path,
  which is the scenario in the stated concern (commits pulled during update).
- **Restarting already-running LSP sessions.** An editor session that already spawned the server keeps its process; new
  sessions pick up the new binary. (ACE itself restarts after updates; the TUI does not embed the LSP.)
- **Wiring the LSP build into `just install` / `_setup`.** Ephemeral workspaces run `just install` constantly; adding an
  LSP build there would slow every workspace bootstrap for a binary those environments rarely need (the launcher's
  sibling-target/cargo-run fallbacks still serve dev checkouts). The new recipe stays callable manually for anyone who
  wants it.

## Design

### 1. New Justfile recipes: `rust-lsp-install` and `rust-lsp-install-uv-tool`

Mirror the existing `rust-install` / `rust-install-uv-tool` pair in the host repo `Justfile`:

- `rust-lsp-install VENV=venv_dir_abs`:
  - No-op with a message when the configured `sase_core_dir` checkout is absent (same guard style as `rust-install`);
    fail with a clear message when `cargo` is missing or the target venv is invalid.
  - `cargo build --release -p sase_xprompt_lsp` inside `sase_core_dir` (reuses the workspace `target/` dir already
    warmed by `maturin develop --release`, so the incremental cost after the extension rebuild is small).
  - Install the built binary into `{{ VENV }}/bin/sase-xprompt-lsp` atomically (copy to a temp name in the same
    directory, `chmod +x`, rename over the destination) so a concurrent editor launch never sees a truncated binary.
- `rust-lsp-install-uv-tool`: resolve `$(uv tool dir)/sase` exactly like `rust-install-uv-tool` and delegate to
  `rust-lsp-install` with that venv.

Reusing the `Justfile` keeps sase-core checkout resolution (`SASE_CORE_DIR`, `SASE_LINKED_REPO_SASE_CORE_DIR`, legacy
fallbacks, `../sase-core` default) in the one place it already lives.

### 2. New dev-update reconcile step: `rust_lsp_install`

In `src/sase/dev_update/`:

- `models.py`: extend `DevReconcileStepKind` with `"rust_lsp_install"`.
- `plan.py` (`_reconcile_steps`): when the core checkout changed (same `core_changed` condition that plans
  `rust_install_uv_tool`), append a `rust_lsp_install` step **after** `rust_install_uv_tool` and `rust_health_check`:
  - command `("just", "rust-lsp-install-uv-tool")`, cwd = host checkout source root;
  - unavailable (with reason) when the host source root is unknown — mirroring the existing rust step.
  - Ordering rationale: all venv-mutating steps (uv reinstall, maturin develop, wheel-restore repair) run first, so the
    binary lands in the venv's final `bin/` state.
- `execute.py` (`_run_reconcile_steps`): the new step needs no special-case; it runs through the generic step path.
  Failure semantics: a failed LSP build fails the update with the step's labeled error (consistent with other reconcile
  steps) — the git fast-forwards have already happened, and the clear failure message tells the user the LSP
  specifically is stale.

Because the confirm modal (`dev_update_preview_details` in `src/sase/ace/tui/modals/plugins_browser_dev_update.py`) and
the CLI renderer already render reconcile steps generically (label + command line), the new step becomes visible in the
`u`-keymap confirm preview and in `sase update` output with no renderer changes (verify; adjust only if a kind-specific
branch exists).

### 3. Launcher resolution order fix (`src/sase/integrations/xprompt_lsp.py`)

New order in `_resolve_xprompt_lsp_command`:

1. `SASE_XPROMPT_LSP_CMD` (unchanged — explicit developer override always wins).
2. **NEW: the sase-managed venv binary** — `Path(sys.executable).parent / "sase-xprompt-lsp"` (plus `.exe` awareness on
   Windows). This is exactly where step 2 of the design installs it, so the copy the update flow manages always beats
   unmanaged artifacts. It also works when a developer runs `just rust-lsp-install` against a repo `.venv` by hand.
3. `sase-xprompt-lsp` on `PATH` (demoted to a fallback for machines that never ran the reconcile step).
4. Sibling-checkout target binaries — **pick the newer mtime of `target/debug` vs `target/release`** instead of
   debug-always-first, so a fresh debug build still wins during active LSP development but a stale debug build no longer
   shadows a freshly reconciled release build.
5. `cargo run -p sase_xprompt_lsp` fallback (unchanged).

### 4. Optional hardening: version-skew warning at launch

In the `sase lsp` wrapper, before `exec`, compare the resolved server's `--version` output against the installed
`sase-core-rs` distribution version and print a one-line stderr warning on mismatch (never block startup; skip silently
when either probe fails). This catches any remaining shadowing path (e.g. a user re-pins `SASE_XPROMPT_LSP_CMD` at a
stale binary) with today's exact symptom (0.3.3 binary vs 0.3.4 core). This phase is optional and separable; drop it if
the extra `--version` subprocess per editor session is judged not worth it.

## Phases

### Phase 1 — Justfile recipes

- `Justfile`: add `rust-lsp-install` and `rust-lsp-install-uv-tool` as described, adjacent to
  `rust-install`/`rust-install-uv-tool` with the same guard/exit conventions.

### Phase 2 — Dev-update reconcile step

- `src/sase/dev_update/models.py`: extend `DevReconcileStepKind`.
- `src/sase/dev_update/plan.py`: plan the `rust_lsp_install` step when core changed; unavailable-reason case.
- Verify generic rendering paths (TUI preview details, CLI plan/result rendering, journal) need no changes.
- Tests: `tests/dev_update/test_plan.py` (step planned when core actionable, ordered last, absent when only non-core
  packages changed, unavailable without host source root); `tests/dev_update/test_execute.py` (step executed with host
  cwd; failure surfaces the step label); TUI-side coverage in `tests/ace/tui/test_plugins_browser_pane_sase_update.py`
  if preview-detail assertions exist there.

### Phase 3 — Launcher resolution order

- `src/sase/integrations/xprompt_lsp.py`: insert the venv-bin candidate; mtime-based debug/release pick; Windows
  executable-suffix handling.
- Tests: `tests/main/test_lsp_handler.py` — venv-bin candidate beats PATH; PATH still used when venv copy is absent;
  newer release beats older debug and vice versa; env override still wins over everything.

### Phase 4 — Docs

- `docs/xprompt.md` and `docs/editor.md`: update the resolution-order lists (both currently document
  PATH-then-debug-first) and the troubleshooting row; mention that a full SASE update reinstalls the server into the
  tool venv for editable installs.
- `docs/configuration.md`: the LSP resolution paragraph (~line 1869).
- `docs/updates.md` / update-flow docs if they enumerate reconcile steps (check while implementing).

### Phase 5 (optional) — Version-skew warning

- `src/sase/integrations/xprompt_lsp.py` + tests in `tests/main/test_lsp_handler.py`.

## Risks and Mitigations

- **Cold-build time.** The first LSP build after a long gap compiles tokio/tower-lsp-server and may be slow;
  `run_dev_update_command` has a 300s default timeout. Mitigation: the step runs after `maturin develop --release` has
  warmed shared workspace dependencies, and the recipe builds only `-p sase_xprompt_lsp`. If timeouts are observed in
  practice, pass a larger per-step timeout for this step (the runner already accepts one) rather than raising the global
  default.
- **`uv` venv recreation.** `uv tool install`-style reconcile steps may rewrite the venv `bin/` directory, which is why
  the LSP install is ordered last among reconcile steps.
- **Behavior change for PATH users.** Users who deliberately run a custom `PATH` binary lose priority to the venv copy;
  the documented escape hatch is `SASE_XPROMPT_LSP_CMD`, which remains top priority. Call this out in the docs update.
- **Uninstalled-core environments.** When the sase-core checkout is absent the recipe no-ops (editable core can't be
  "changed" without a checkout, so the reconcile step won't be planned in that state anyway).

## Alternatives Considered

- **Fold the LSP build into the existing `rust-install` recipe.** Fewer moving parts, but it entangles failure
  attribution (an LSP build failure would fail the extension-rebuild step and trigger its wheel-restore repair logic)
  and silently slows every `just install`-driven workspace bootstrap. Rejected in favor of a separate,
  separately-labeled step.
- **Refresh `~/.cargo/bin` via `cargo install --path`.** Matches one user's current layout but mutates a global,
  sase-unmanaged location, and `cargo install` does not reuse the workspace target dir (slower builds). The venv `bin/`
  is the sase-owned location that the launcher can deterministically prefer.
- **Only fix the resolution order (prefer newest mtime everywhere, no rebuild step).** Cheaper, but the update would
  still not produce any fresh binary; the launcher would just pick the least-stale artifact and the `cargo run` fallback
  only triggers when no binary exists at all.
