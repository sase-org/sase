---
create_time: 2026-06-25 07:11:10
status: wip
---
# Fix `install_sase_github` Failure From `sase-core-rs` Version Skew

## Problem

Running the chezmoi-managed installer fails in its initial `uv tool install` step:

```text
❯ install_sase_github -i && sase agent index gc && ace --restart-axe
>>> Repo sync complete.
    sase            up to date
    sase-core       up to date
    sase-github     up to date
    sase-telegram   up to date
>>> Installing sase via uv tool...
  × No solution found when resolving dependencies:
  ╰─▶ Because only sase==0.5.0 is available and sase==0.5.0 depends on sase-core-rs>=0.2.0,<0.3.0 ...
      And because only the following versions of sase-core-rs are available:
          sase-core-rs<0.2.0
          sase-core-rs>=0.3.0
      ... we can conclude that your requirements are unsatisfiable.
ERROR: install_sase_github failed; axe maintenance remains active ...
ERROR: Axe was left stopped because the uv-tool sase environment may be incomplete.
```

Because the failure happens _after_ `enter_axe_maintenance` + `stop_axe_if_running`, it also leaves **axe stopped**, the
`~/.sase/axe/maintenance.json` flag set, and the uv-tool `sase` environment pinned to its previous versions.

This is the **same class** of failure addressed earlier in `sdd/tales/202604/install_sase_github_core_rs.md`, but a
**different mechanism**: that fix added `--with-editable "sase-core-rs @ .../sase_core_py"` because the package was
_missing entirely_. The `--with-editable` flag is now present; the package is found, but its resolvable version is **out
of range**.

## Root Cause: version skew between `sase`'s constraint and the resolvable `sase-core-rs`

`sase/pyproject.toml` declares a hard runtime dependency `sase-core-rs>=0.2.0,<0.3.0`. The installer resolves this
against the local editable Rust binding (`--with-editable "sase-core-rs @ <sase-core>/crates/sase_core_py"`) plus PyPI.
The resolver could only find a `sase-core-rs` **below `0.2.0`**, so no candidate fell inside the required
`[0.2.0, 0.3.0)` window, and resolution failed.

Two clarifications that the raw error obscures:

- **There is no real `0.3.0`.** `sase-core-rs` exists only at `0.1.2 / 0.1.3 / 0.1.4 / 0.2.0` (PyPI) and `0.2.0`
  locally; the `sase-core` workspace has never been past `0.2.0`. The `sase-core-rs>=0.3.0` line is PubGrub's
  _complement_ notation for "nothing exists in your required `[0.2.0, 0.3.0)` window" — it is **not** a published
  release. So the whole conflict reduces to: _the only `sase-core-rs` the resolver had was `< 0.2.0`._
- **The skew is a release-ordering artifact.** On 2026-06-24 `sase-core` bumped `0.1.4 → 0.2.0` (10:14) and `sase`'s
  constraint bumped `>=0.1.1,<0.3.0 → >=0.2.0,<0.3.0` (14:23). The user's uv-tool env, however, was last built on
  2026-06-21 with `sase 0.4.0` + `sase-core-rs 0.1.4`. When `install_sase_github -i` re-ran `uv tool install --force`,
  the resolver reused the **already-installed editable `sase-core-rs 0.1.4`** as the candidate version for that path
  (rather than rebuilding the metadata from the now-`0.2.0` source). `0.1.4` no longer satisfies `>=0.2.0` → the error.

**Evidence this is the mechanism (and that today's tree is otherwise healthy):**

- A clean reproduction of the _exact_
  `uv tool install --force --editable "sase @ ..." --with-editable "sase-core-rs @ ..." ...` command into an **isolated,
  empty** tool dir **succeeds** today, installing `sase==0.5.0` + `sase-core-rs==0.2.0`. The only material difference
  from the failing run is that the user's run reinstalled _over an existing env that already had `sase-core-rs 0.1.4`_.
- Building the local `sase_core_py` from source (maturin) yields `0.2.0`, matching `sase-core/Cargo.toml`
  `[workspace.package] version = "0.2.0"`; PyPI's `sase-core-rs 0.2.0` ships a macOS `universal2`/arm64 wheel, so it is
  installable on this MacBook.
- The currently-installed uv-tool env (`~/.local/share/uv/tools/sase`) is still `sase 0.4.0` / `sase_core_rs 0.1.4`,
  confirming the reinstall never completed.

### Why this keeps biting

The system has a **fragile, manual coupling**: `sase`'s `sase-core-rs` constraint must be kept in lockstep with the
independently-versioned `sase-core` repo, and the uv-tool env must rebuild the editable from the current source on every
reinstall. Whenever either drifts — a constraint bumped ahead of the installed/published core, a `sase-core` checkout
left behind, or a stale editable reused by uv — the install fails with this same cryptic resolver error **and** strands
axe. The repeated `chore: Fix version constraint with sase-core-rs` commits show this is recurring. `sase`'s existing
`tools/validate_sase_core_rs` guard validates _bindings_, never the _version_, so nothing catches the skew early.

> Keep the `<0.3.0` upper bound. It is a deliberate minor-version API/ABI compatibility guard; loosening it would let an
> incompatible core satisfy resolution and mask real breakage. The fix is better **enforcement and rebuild discipline**,
> not weaker constraints.

## Goals

1. Make `install_sase_github` resolve correctly across a `sase` / `sase-core` version bump, instead of reusing a stale
   `sase-core-rs`.
2. When a genuine version mismatch _does_ exist, fail **fast and legibly** — before stopping axe or entering maintenance
   — with a message that names the exact remediation.
3. Add a reusable, tested version-consistency guard so the skew is caught in both the installer and local dev.

## Implementation Plan

### Part A — Force a fresh editable rebuild during `uv tool install` (the direct fix)

In the chezmoi-managed `install_sase_github`, change the initial `uv tool install` so uv cannot resolve against an
already-installed or cached `sase-core-rs`. Force the local editables' metadata to be rebuilt from current source — e.g.
add `--reinstall` (simplest, rebuilds all editables) or scope it with `--reinstall-package sase-core-rs` (plus the other
local editables) alongside the existing `--force`. This alone would have produced `sase-core-rs 0.2.0` from the bumped
source and resolved cleanly.

Apply the **same change to sibling installers that share the `uv tool install --with-editable "sase-core-rs @ ..."`
shape** (e.g. `install_sase_google`), mirroring how the prior `core_rs` tale also patched its sibling installer.

### Part B — Pre-flight version-consistency gate (fail fast, keep axe alive)

Add a guard that runs in `install_sase_github` **before** `enter_axe_maintenance` / `stop_axe_if_running` (i.e. in the
same early, non-destructive phase as the repo-sync gate). It compares the local `sase-core` **source** version against
`sase`'s declared `sase-core-rs` specifier and aborts early — without touching axe or the uv-tool env — when they don't
intersect, printing exactly what to do ("`sase-core` checkout is behind: built version `X` does not satisfy `sase`'s
`sase-core-rs <specifier>`; pull/rebuild `sase-core`" or "bump the `sase-core-rs` constraint in `sase/pyproject.toml`").

Implement the comparison as a small, unit-tested repo tool in `sase`, following the existing `tools/validate_*` pattern
(e.g. `tools/validate_sase_core_rs_version`):

- Read `[workspace.package] version` from the `sase-core` `Cargo.toml` (path via argument/env).
- Read the `sase-core-rs` specifier from `sase/pyproject.toml` `[project] dependencies`.
- Verify the source version satisfies the specifier; exit non-zero with an actionable message otherwise.
- Use stdlib only (`tomllib`) plus a minimal bound check, so it runs under a plain `python3` regardless of which venv is
  active during pre-flight.

Wire the same tool into `just rust-install` (and/or `_setup`) so local-dev installs hit the identical early failure
instead of a later cryptic build/resolve error. The installer keeps its existing post-install
`just rust-install-uv-tool` (maturin `develop --release`) and `probe_uv_tool_health` steps unchanged.

### Out of scope / non-goals

- Do **not** loosen or remove the `<0.3.0` upper bound (see note above).
- Do **not** change the deliberate behavior of leaving axe stopped for _post-maintenance_ failures unrelated to this
  skew; Part B only prevents the **resolution-skew** case from ever reaching maintenance.
- No changes to `sase-core` versioning or the release-plz flow.

## Testing & Validation

- Unit tests for `tools/validate_sase_core_rs_version`: in-range (pass), source-behind-floor (fail), source-at-or-above
  upper bound (fail), malformed/missing inputs (clear error). Run via `just check`.
- Manual / scripted check that re-running the installer across a simulated bump no longer reuses a stale `sase-core-rs`
  (clean isolated `uv tool install` already verified to resolve `sase-core-rs==0.2.0`).
- Confirm the pre-flight gate aborts **before** axe is stopped when the source version is out of range.

## Immediate recovery (operational, no code change required)

The working tree is already consistent (`sase-core 0.2.0` everywhere) and a fresh editable `sase-core-rs 0.2.0` build is
now warm in the uv cache, so **re-running `install_sase_github -i` succeeds today** — it rebuilds the uv-tool env to
`sase 0.5.0` / `sase-core-rs 0.2.0`, runs `sase axe start`, and clears `~/.sase/axe/maintenance.json`. The code changes
above prevent the failure from recurring on the next version bump.
