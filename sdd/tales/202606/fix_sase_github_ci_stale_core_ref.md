---
create_time: 2026-06-29 21:36:51
status: done
---
# Fix `sase-github` GitHub Actions CI failures

## Summary

The `CI` workflow on `sase-org/sase-github` is red on the latest `master` commit (`chore(master): release 0.1.3`). All
three jobs fail or are cancelled:

- `lint` — fails
- `test (3.12)` — fails
- `test (3.13)` — cancelled by fail-fast after a sibling job failed

Failing run: <https://github.com/sase-org/sase-github/actions/runs/28412894444>

The failure is the visible tip of a **two-layer version-skew problem** introduced by the cross-repo "project display
names" feature that landed in `sase-core`, `sase`, and `sase-github` on 2026-06-29. Fixing only the obviously-broken pin
in `sase-github` makes `lint` pass but leaves the test jobs red, so the plan addresses both layers.

## Root cause analysis

### How `sase-github` CI consumes `sase`

`sase-github` is a plugin for `sase`. Its CI does **not** vendor `sase`; instead `.github/workflows/ci.yml` (and
`publish.yml`) check out `sase-org/sase` at a pinned git ref into `.ci/sase` and install it editable before installing
the plugin:

```yaml
env:
  SASE_CORE_REF: v0.1.3 # <-- pinned ref of the sase repo
  SASE_CORE_PATH: .ci/sase
```

The `Justfile` `install` recipe then runs `uv pip install -e "${SASE_CORE_PATH}"` followed by
`uv pip install -e ".[dev]"`. Crucially, the Rust binding package `sase-core-rs` is **not** built from source in
`sase-github` CI — it is resolved from PyPI according to whatever `sase` pins. (Contrast with the `sase` repo's own
`just install`, which builds `sase_core_rs` editable from a local `../sase-core` checkout when present, masking the
second bug below.)

### Layer 1 — `sase-github` pins a stale `sase` ref (the visible failure)

The "project display names" work renamed the project-alias API in `sase`:

- `allocate_project_alias` → `allocate_project_name`
- `ensure_project_alias_locked` → `ensure_project_name_locked`

`sase-github`'s `src/sase_github/workspace_plugin.py` was updated to import the new names. But CI still pins
`SASE_CORE_REF: v0.1.3`, a `sase` version that predates the rename and only exports the old names. Result:

- `test` jobs: `ImportError: cannot import name 'allocate_project_name' from 'sase.project_aliases'`
- `lint` job: two mypy `attr-defined` errors on the same import (`maybe "allocate_project_alias"?`)

The renamed functions first appear in `sase` **v0.6.0**; `sase` is currently at v0.6.0 while `sase-github`'s pinned ref
is still the long-stale v0.1.3.

### Layer 2 — `sase` v0.6.0 pins an incompatible `sase-core-rs` (latent failure)

The new code path (`ensure_project_name_locked` → the Rust core) calls the `sase_core_rs` binding
`apply_project_name_update`. That binding only exists in **`sase-core-rs` 0.3.0** (added in `sase-core` and published as
0.3.0). The published 0.2.0 wheel does **not** expose it.

However, `sase` v0.6.0's `pyproject.toml` still pins:

```toml
"sase-core-rs>=0.2.0,<0.3.0",
```

which **excludes** the 0.3.0 it actually needs. A from-PyPI install of `sase` v0.6.0 (exactly what `sase-github` CI
does) therefore resolves `sase-core-rs` 0.2.0, and the project-name path raises:

```
AttributeError: sase_core_rs is importable but does not expose binding
'apply_project_name_update'; the installed wheel is stale ...
```

This is masked in `sase`'s own CI because that build compiles `sase_core_rs` editable from local `../sase-core` source
(which is 0.3.0). It is unmasked the moment `sase-github` bumps its ref to v0.6.0.

### Why both layers must be fixed together

Verified empirically against the current sources:

| Scenario                                 | lint                 | tests                       |
| ---------------------------------------- | -------------------- | --------------------------- |
| `sase` v0.1.3 (current)                  | ❌ mypy attr-defined | ❌ ImportError              |
| `sase` v0.6.0, `sase-core-rs` 0.2.0      | ✅                   | ❌ AttributeError (binding) |
| `sase` v0.6.0 code, `sase-core-rs` 0.3.0 | ✅                   | ✅ 63 passed                |

A "force-install `sase-core-rs` 0.3.0" stopgap in CI was also tested and rejected: the subsequent
`uv pip install -e ".[dev]"` re-resolves and **downgrades** back to 0.2.0 because `sase` still pins `<0.3.0`. The pin is
the real constraint and must be corrected at the source.

## Goals

- `sase-github` `CI` workflow (lint + both test matrix jobs) green on `master`.
- The fix is robust (survives `just install`) rather than a stopgap.
- The underlying `sase` packaging bug (pin excludes the `sase-core-rs` it needs) is corrected so any from-PyPI consumer
  of `sase` — not just `sase-github` CI — works on the project-name path.
- The `publish.yml` workflow (which has the same stale ref) is fixed in lockstep.

## Non-goals

- No changes to the project-display-name feature behavior itself.
- No re-architecting of how `sase-github` CI obtains `sase` / `sase-core-rs` (e.g. building Rust from source in plugin
  CI) — out of scope.

## Plan

This is an ordered, cross-repo change. Layer 2 (in `sase`) must land first so that there exists a `sase` ref that
`sase-github` can point at which both exports the renamed API **and** pins a compatible `sase-core-rs`.

### Step 1 — Fix the `sase-core-rs` pin in the `sase` repo

In `sase`'s `pyproject.toml`, bump the dependency:

```toml
-    "sase-core-rs>=0.2.0,<0.3.0",
+    "sase-core-rs>=0.3.0,<0.4.0",
```

Rationale: the shipped code requires the `apply_project_name_update` binding, which is only present from `sase-core-rs`
0.3.0. The local `sase-core` source is already at 0.3.0, so `tools/validate_sase_core_rs_version` (which checks the pin
against the local core version) will be satisfied by the new range.

Verification in `sase`:

- `just install` then `just check` (lint + tests) pass.
- `tools/validate_sase_core_rs_version` passes against the 0.3.0 core.

Land this on `sase` `master`. Because `sase` releases via release-please, merging the fix will produce a release PR
that, when merged, cuts the next `sase` patch release (anticipated **v0.6.1**) carrying the corrected pin.

### Step 2 — Point `sase-github` at the fixed `sase` and bump its floor

Once `sase` v0.6.1 is released (the ref that has both the renamed API and the corrected `sase-core-rs` pin):

1. `.github/workflows/ci.yml` — bump the ref:
   ```yaml
   -  SASE_CORE_REF: v0.1.3
   +  SASE_CORE_REF: v0.6.1
   ```
2. `.github/workflows/publish.yml` — bump the identical `SASE_CORE_REF` env var (its `install-smoke` job uses the same
   checkout pattern).
3. `pyproject.toml` — bump the declared dependency floor to reflect the real requirement so PyPI consumers of
   `sase-github` also get a working `sase`:
   ```toml
   -dependencies = ["sase>=0.1.3"]
   +dependencies = ["sase>=0.6.1"]
   ```
   (The renamed API requires `sase>=0.6.0`; the corrected transitive `sase-core-rs` pin requires `sase>=0.6.1`. The
   floor is set to 0.6.1 so that an end-user install of `sase-github` cannot pull a `sase` that drags in the
   binding-less `sase-core-rs` 0.2.0.)

Verification in `sase-github`: run the CI recipes with the new ref (`SASE_CORE_PATH` pointing at the v0.6.1 checkout) —
`just install`, `just lint`, `just test` all pass; the full 63-test suite is green and mypy is clean. (This was already
validated end-to-end with v0.6.0 code + `sase-core-rs` 0.3.0.)

### Sequencing / dependency

Step 2 depends on Step 1 having landed and a `sase` release being cut. If a release cannot be cut promptly, an
acceptable interim is to point `SASE_CORE_REF` at `master` (which carries the fix as soon as Step 1 merges, since
`sase-github` consumes `sase` from a git ref and `sase-core-rs` 0.3.0 is already on PyPI) and set the `sase-github`
floor to `sase>=0.6.0`. The tag-pinned form (v0.6.1) is preferred for reproducibility and is the recommended end state.

## Risks & mitigations

- **Other API drift between v0.1.3 and v0.6.0/0.6.1.** `sase-github`'s `master` code was authored against current
  `sase`, and the full plugin suite passes against v0.6.0 + `sase-core-rs` 0.3.0, so no further drift is expected.
  Mitigation: the test matrix (3.12 + 3.13) is the gate.
- **Release coordination.** Step 2's tag bump must wait for the `sase` release. Mitigation: the documented `master`-ref
  interim unblocks CI immediately if needed.
- **`sase` consumers relying on `sase-core-rs` 0.2.x.** The pin widens forward (`>=0.3.0,<0.4.0`); 0.2.x is
  intentionally dropped because the code cannot run on it. This is a correctness fix, not a regression.

## Verification checklist

- [ ] `sase`: `just check` green; `validate_sase_core_rs_version` passes with the new pin.
- [ ] `sase` release cut (v0.6.1) carrying the corrected pin.
- [ ] `sase-github`: `SASE_CORE_REF` bumped in `ci.yml` and `publish.yml`; `pyproject.toml` floor bumped.
- [ ] `sase-github` CI green on `master`: `lint`, `test (3.12)`, `test (3.13)`.
- [ ] `actstat --only-failures` no longer reports `sase-org/sase-github`.
