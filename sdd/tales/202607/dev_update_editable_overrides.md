---
create_time: 2026-07-07 13:49:41
status: done
prompt: sdd/prompts/202607/dev_update_editable_overrides.md
---
# Fix dev update failure: editable reinstall breaks when a plugin's sase floor exceeds the checkout's static version

## Problem

Pressing `u` on the "Updates" tab of the SASE Admin Center (and confirming with `y`) fails with:

```
dev update failed: Reinstall uv-tool editable Python packages failed:
× No solution found when resolving dependencies:
  ╰─▶ Because only sase<0.11.0 is available and sase-github==0.1.7 depends on
      sase>=0.11.0, we can conclude that sase-github==0.1.7 cannot be used.
      And because only sase-github==0.1.7 is available and you require
      sase-github, we can conclude that your requirements are unsatisfiable.
```

## Root cause (confirmed empirically)

The dev update flow (`plan_dev_update` → reconcile step "Reinstall uv-tool editable Python packages") rebuilds the uv
tool environment from the receipt at `~/.local/share/uv/tools/sase/uv-receipt.toml` via:

```
uv tool install --editable <sase checkout> \
    --with-editable <sase-github checkout> \
    --with-editable <sase-telegram checkout>
```

`uv` performs **strict dependency resolution against static pyproject metadata**:

- The `sase` checkout's `pyproject.toml` carries the _last released_ version (`0.10.2`), even though the checkout is
  ~100 commits ahead of that tag. release-please only bumps the version field when a release is cut.
- The `sase-github` checkout was fast-forwarded (by this very dev update — the `~/.sase/logs/dev_update.jsonl` journal
  shows the ff-merge to the `0.1.7` release commit succeeding) to a commit that declares
  `dependencies = ["sase>=0.11.0"]` (commit "build(deps): raise sase floor for github plugin"), a floor pointing at the
  _next_ sase release.
- `0.10.2 < 0.11.0` → unsatisfiable → the reconcile step exits 1, after the git merges already landed.

This is structural, not a one-off bad state: **any plugin that raises its sase floor past the latest sase release breaks
every editable reinstall until the next sase release ships**, even though the editable sase checkout actually contains
the required code. The floor is release-management metadata that protects _managed_ (PyPI) installs; for dev installs
the local checkouts are the source of truth and the floor is meaningless.

### Blast radius

The same receipt-driven `uv tool install` reconstruction is used by every plugin-management flow, so with the current
checkout state all of these fail with the same resolution error, not just `u`:

- Dev update reconcile — `src/sase/dev_update/plan.py` (`build_install`); this covers the TUI Updates-tab action, the
  plugin dev-update flow, and the `sase update` CLI (all funnel through `plan_dev_update`).
- Plugin install — `src/sase/plugins/_operations_install.py` (`build_install(add=...)`, `build_install_many`).
- Plugin update — `src/sase/plugins/_operations_update.py` (`build_upgrade_packages`).
- Plugin uninstall — `src/sase/plugins/_operations_uninstall.py` (`build_uninstall`).
- Managed↔dev mode switch — `src/sase/mode_switch/plan.py` (`build_reinstall_set`).

### Repro + fix mechanism (verified with uv 0.11.24)

- `uv pip compile` over the three `-e` checkout entries reproduces the exact resolution error.
- `uv tool install` / `uv pip compile` accept `--overrides <file>` (env: `UV_OVERRIDE`). Overrides _replace_ every
  declared requirement on a package during resolution.
- An overrides file containing `-e /path/to/sase` makes resolution succeed **and** keeps sase installed from the local
  editable checkout.
- ⚠️ A bare-name override (`sase` with no source) also resolves, but silently switches sase to the PyPI wheel
  (`sase==0.10.2` from the registry) — the editable source is dropped. The `-e <path>` form is the only safe content.

## Design

**When a `uv tool install` argv is reconstructed from a requirement set that contains editable entries, write an
overrides file with one `-e <path>` line per editable entry and append `--overrides <path>` to the argv.**

Editable entries are exactly the packages whose code is the local checkout, so neutralizing declared version floors _on
those names_ is correct by definition in dev mode. Managed installs (no editable entries) produce no overrides file and
are completely unchanged — floors keep protecting them.

### Components

1. **New module `src/sase/uv_tool/overrides.py`** (pure logic + one writer):
   - `editable_override_lines(requirements) -> tuple[str, ...]` — one `-e <path>` line per editable `Requirement`,
     deduped by normalized name, receipt order preserved. Pure and unit-testable.
   - `write_editable_overrides(requirements, *, path=None) -> Path | None` — returns `None` when there are no editable
     entries; otherwise writes the lines to a stable, bounded location (default `~/.sase/uv/editable-overrides.txt` via
     `ensure_sase_directory("uv")`) and returns the path. A single rewritten file — no sharding concerns per the
     `src/sase/core/paths.py` criteria.

2. **`src/sase/uv_tool/commands.py`** — builders stay pure (never touch the filesystem): add an optional
   `overrides: str | None = None` keyword to `build_install`, `build_install_many`, `build_uninstall`,
   `build_upgrade_packages` (pass-through to `build_install`), and `build_reinstall_set`; when set, append
   `["--overrides", overrides]`.

3. **Wire the call sites** (each writes the file from the requirement set it is about to install, then passes the path):
   - `src/sase/dev_update/plan.py` `_reconcile_steps` — derive from `receipt.requirements` (**the fix for the reported
     bug**; fixes the TUI `u` action, plugin dev-update, and `sase update` CLI in one place).
   - `src/sase/plugins/_operations_install.py` — both install paths, deriving from the reconstructed set _including_ the
     additions (an added editable plugin gets covered too).
   - `src/sase/plugins/_operations_update.py`.
   - `src/sase/plugins/_operations_uninstall.py` — derive from the set _after_ removal.
   - `src/sase/mode_switch/plan.py` — derive from the explicit `primary`/`plugins` set passed to `build_reinstall_set`
     (the target state of the switch, not the receipt's current state).

4. **Failure handling**: if writing the overrides file raises `OSError`, degrade gracefully — build the command without
   `--overrides` (identical to today's behavior) rather than blocking the operation. Overrides are an enabler, not a
   correctness gate.

Notes:

- Paths in the overrides file are stable across the dev update's ff-merges (checkout paths don't move), so writing at
  plan/build time is safe even though execution happens after the merges.
- The confirm-modal command previews and the dev-update journal will show the `--overrides <path>` flag verbatim — the
  change stays transparent/auditable.
- No Rust core boundary crossing: this is uv-tool install management local to this repo's Python packaging glue
  (`sase.uv_tool`, `sase.dev_update`, `sase.plugins`, `sase.mode_switch`).
- No new CLI subcommands or options.

## Tests

- **New `tests/uv_tool/test_overrides.py`**: line generation (editable-only filtering, dedup, ordering), `None` for
  no-editable sets, file writing + rewrite-in-place, OSError degradation.
- **`tests/uv_tool/test_commands.py`**: each builder appends `--overrides <path>` when given and omits it otherwise
  (existing argv expectations stay valid — proves managed flows are untouched).
- **`tests/dev_update/test_plan.py`**: the `uv_tool_install` reconcile step's command includes `--overrides`, and the
  written file contains the `-e` lines for the receipt's editable checkouts (point the writer at `tmp_path`).
- **Plugin operations + mode-switch tests**: extend the existing suites for the wiring (overrides present exactly when
  the target set has editables).
- **`tests/uv_tool/test_real_uv_harness.py`** (investigate feasibility): a real-uv resolution test with two tiny local
  packages where the dependent's floor exceeds the primary's static version — fails without overrides, succeeds with.
  Skip if the harness can't express it cheaply.

## Verification

1. `just install && just check`.
2. End-to-end on the real environment: re-run the previously failing reconcile command with the generated overrides file
   appended —
   `uv tool install --color never --editable <sase checkout> --with-editable <sase-github checkout> --with-editable <sase-telegram checkout> --overrides ~/.sase/uv/editable-overrides.txt`
   — and confirm it succeeds with sase still editable (`uv tool list` / `sase --version`). This also repairs the user's
   currently-wedged tool env.
3. In the TUI: `u` on the Updates tab now reports "already current" (checkouts were already fast-forwarded by the failed
   run) instead of erroring; a later real update completes end-to-end.

## Alternatives rejected

- **Bump the sase checkout's pyproject version between releases** (e.g. to `0.11.0`): fights release-please-owned
  versioning and makes the checkout claim a release that doesn't exist; PEP 440 dev/local variants (`0.11.0.dev*`,
  `0.10.2+g*`) still don't satisfy `>=0.11.0` anyway.
- **Bare-name overrides**: verified to silently swap the editable sase for the PyPI wheel — unacceptable.
- **Lower/delay plugin floors until the sase release exists**: floors are the only protection managed installs have; dev
  tooling should tolerate them, not weaken them.
- **Preflight resolution check with a friendlier error**: better UX but the update still fails; could be a follow-up,
  not this fix.
