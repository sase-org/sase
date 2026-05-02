---
create_time: 2026-04-29 16:02:50
status: done
bead_id: sase-1b
prompt: sdd/prompts/202604/rust_backend_phase6_default_rust.md
---
# Rust Backend Phase 6: Default Rust Backend Rollout

## Context

`sdd/research/202604/rust_backend_migration.md` says Phases 0-5 are complete:

- `src/sase/core/` is the Python facade with backend dispatch and dual-run parity logging.
- `../sase-core/` exposes the optional `sase_core_rs` PyO3 extension.
- The shipped Rust-backed operations are:
  - `parse_project_bytes`
  - `parse_query` and `evaluate_query_many`
  - `scan_agent_artifacts`
  - `read_status_from_lines`, `apply_status_update`, and `plan_status_transition`
  - `parse_git_name_status_z`, `parse_git_branch_name`, `derive_git_workspace_name`, `parse_git_conflicted_files`, and
    `parse_git_local_changes`
- Unported or intentionally Python-owned surfaces still exist:
  - query context/per-row evaluation helpers;
  - graph index construction;
  - full side-effecting status transitions;
  - plugin entry points, subprocess invocation, process liveness checks, filesystem mutation, and TUI rendering.

Phase 6 is the default-backend flip. This is mostly a release, packaging, and safety-rail project, not a new port. The
default must not change until the Rust extension can be installed from release artifacts on every supported platform and
the one known regression (`is_workflow_complete` through the snapshot path) has been resolved or explicitly pinned away
from Rust.

## Goal

Make Rust the default backend for shipped `sase.core` operations while preserving a documented Python escape hatch for
one release cycle:

- unset `SASE_CORE_BACKEND` means Rust;
- `SASE_CORE_BACKEND=python` remains supported through Phase 7;
- `SASE_CORE_BACKEND=rust` continues to mean strict Rust for shipped bindings and explicit Python fallback only for
  intentionally unported operations;
- release artifacts install a loadable `sase_core_rs` extension without requiring a local Rust toolchain;
- missing or broken Rust extension failures are clear and diagnosable;
- CI exercises both default Rust and explicit Python backends until Phase 8 removes the Python path;
- documentation and rollback instructions are current.

## Non-Goals

- Do not port additional business logic to Rust in Phase 6 unless it is the narrowest way to fix the
  `is_workflow_complete` regression.
- Do not remove Python implementations, the backend dispatcher, or dual-run logging. That is Phase 8.
- Do not rewrite the TUI, VCS provider, workspace provider, or plugin system.
- Do not silently fall back to Python when Rust is the selected/default backend and a shipped Rust binding is missing.
- Do not require normal users installing a released `sase` wheel to have `cargo`, `rustup`, or `maturin`.

## Rollout Decisions Locked By This Plan

1. **Distribution shape:** publish `sase_core_rs` as a separate Python distribution built from `../sase-core`, then make
   `sase` depend on that distribution for the Phase 6 release. This matches the current sibling-repo architecture and
   avoids vendoring Rust build steps into the Python package.
2. **Fallback policy:** keep the Python backend selectable with `SASE_CORE_BACKEND=python` through Phase 7. Default Rust
   must fail loudly if the Rust extension cannot be imported; explicit Python mode is the escape hatch.
3. **Known regression policy:** resolve `is_workflow_complete` before the default flip. The conservative first choice is
   to pin that operation to a targeted Python traversal that preserves the old short-circuit behavior. Only add a Rust
   early-exit API if measurement shows the pin is insufficient or creates worse code complexity.
4. **Dual-run semantics:** keep the existing dual-run behavior for Phase 6: both implementations run, comparison records
   are written, and the Python result is returned. Default Rust is exercised by the normal default-backend CI/release
   smoke path with dual-run disabled.
5. **Gate change:** Phase 6 uses the documented "measurable user-visible win, no regressions on hot paths" bar for
   defaulting an already-shipped port. The old 2x gate remains the bar for deciding whether to port new work.

## Phase Split For Distinct Agent Instances

Each subphase below is intended for a different agent instance. Each agent should read this plan,
`sdd/research/202604/rust_backend_migration.md`, `docs/rust_backend.md`, and the previous subphase handoff before editing.
Agents should keep to their write scope and leave later phases alone.

### Phase 6A: Rust Wheel Packaging And Release Matrix

Purpose: make `sase_core_rs` installable from wheels on every supported platform before `sase` depends on it by default.

Write scope:

- `../sase-core/.github/workflows/` or the release workflow location chosen for the Rust repo.
- `../sase-core/crates/sase_core_py/pyproject.toml` if maturin metadata is missing.
- `../sase-core/crates/sase_core_py/Cargo.toml` only for package metadata, PyO3 features, or wheel compatibility.
- `../sase-core/Cargo.toml`, `../sase-core/Cargo.lock`, and `../sase-core/rust-toolchain.toml` if reproducibility needs
  tightening.
- `plans/202604/rust_backend_phase6_phase6a_handoff.md` in this repo.

Work:

- Define the Python distribution name for the extension. Prefer a stable package name such as `sase-core-rs` with import
  module `sase_core_rs`; document the distinction.
- Add or complete maturin package metadata for the PyO3 crate.
- Build wheels for the Phase 6 target matrix:
  - CPython 3.12+;
  - Linux x86_64;
  - Linux aarch64;
  - macOS universal2;
  - Windows x86_64.
- Investigate `abi3-py312` for normal CPython wheels. Do not assume it covers free-threaded Python 3.14; if the matrix
  includes free-threaded builds, produce explicit version-specific wheels or record why they are out of scope for this
  release.
- Add CI caching for Cargo and maturin builds.
- Add wheel smoke tests in fresh virtual environments:
  - `python -c "import sase_core_rs; print(sase_core_rs.__version__ if hasattr(sase_core_rs, '__version__') else 'ok')"`
  - `python -c "import sase_core_rs; sase_core_rs.parse_query('status:Ready')"`
  - a negative parse smoke such as `parse_query('!!!')` if that is the agreed health-check input.
- Verify `twine check` / metadata checks on the built artifacts.
- Record how wheels are published or attached for the Phase 6 `sase` release. If full PyPI publishing cannot be done by
  the agent, leave the exact manual release command and expected artifact list.

Exit criteria:

- A release workflow can produce installable `sase_core_rs` wheels for the supported matrix.
- The wheel smoke test proves the extension imports and at least one shipped binding works.
- The handoff records the distribution name, versioning policy, publish path, and any unsupported platform caveats.

### Phase 6B: `sase` Dependency And Source-Install Story

Purpose: make normal `sase` installs receive the Rust extension, while preserving an explicit source/development
fallback.

Write scope:

- `pyproject.toml`.
- `Justfile`.
- `.github/workflows/publish.yml` if `sase` release artifacts need to wait on or verify `sase_core_rs` wheels.
- `.github/workflows/ci.yml` only for install-smoke scaffolding, not the full backend matrix yet.
- `docs/rust_backend.md`.
- `plans/202604/rust_backend_phase6_phase6b_handoff.md`.

Work:

- Add the Phase 6 Rust extension dependency to `sase` once Phase 6A wheels exist. The dependency should be exact or
  compatibly pinned according to the Phase 6A versioning policy.
- Keep editable/source development practical:
  - if the dependency is already on PyPI, `just install` should install it like any other dependency;
  - if a sibling `../sase-core` checkout exists and the developer wants local Rust code, `just rust-install` remains the
    override path;
  - pure-Python development remains available by setting `SASE_CORE_BACKEND=python`.
- Add a release install smoke that builds `sase`, installs it into a fresh venv, imports `sase_core_rs`, and runs the
  backend health command added later in Phase 6D. If Phase 6D has not landed yet, leave the smoke as an import and
  binding-call check that Phase 6D can tighten.
- Update docs from "optional Rust backend" to "Rust backend is installed for release artifacts; source fallback is
  explicit Python mode."

Exit criteria:

- A fresh install of the `sase` package on a supported platform receives a loadable `sase_core_rs` wheel.
- A contributor without a local Rust toolchain has a documented path: use the published wheel or set
  `SASE_CORE_BACKEND=python` for pure-Python work.
- No default-backend change has landed yet.

### Phase 6C: Backend Contract Audit And Fallback Tests

Purpose: prove that default Rust can be strict for shipped operations without breaking intentionally unported facades.

Write scope:

- `src/sase/core/backend.py`.
- `src/sase/core/*_facade.py` only where fallback policy is ambiguous.
- Focused backend tests, especially `tests/test_core_backend.py` and facade-specific tests.
- `docs/rust_backend.md`.
- `plans/202604/rust_backend_phase6_phase6c_handoff.md`.

Work:

- Inventory every `dispatch(...)` call under `src/sase/core/` and classify it as:
  - shipped Rust binding, strict missing-binding failure;
  - intentionally unported Python fallback under Rust mode;
  - side-effecting Python operation that must never dual-run side effects.
- Add tests that assert both halves of the contract:
  - each shipped operation raises `RustBackendUnavailableError` when Rust is selected and the binding is absent or
    stale;
  - unported operations still execute Python under Rust mode with an explicit `rust_unavailable="python"` policy;
  - dual-run comparison remains no-op for operations without a Rust implementation;
  - no facade silently masks a missing shipped binding.
- Improve error text if needed so it names the operation, the extension module, and the escape hatch
  (`SASE_CORE_BACKEND=python`).
- Keep `DEFAULT_BACKEND` as Python in this phase.

Exit criteria:

- The shipped/unported backend contract is test-enforced before the default changes.
- The next agent can flip the default without discovering ambiguous fallback behavior.

### Phase 6D: Backend Health Check And User-Facing Diagnostics

Purpose: add one cheap, scriptable way to prove that the default Rust extension is loadable and compatible.

Write scope:

- `src/sase/core/backend.py` or a new small `src/sase/core/health.py`.
- CLI parser and handler files under `src/sase/main/`.
- Focused CLI tests under `tests/`.
- `docs/rust_backend.md`.
- `plans/202604/rust_backend_phase6_phase6d_handoff.md`.

Work:

- Add a backend health helper that:
  - imports `sase_core_rs`;
  - records module path, package version if exposed, Python version, platform tag or platform string, and selected
    backend;
  - calls a cheap shipped binding such as `parse_query("status:Ready")`;
  - calls a cheap negative input only if the expected error shape is stable.
- Expose it through a scriptable CLI command. Prefer a narrow command such as `sase core health --json` if adding a
  `core` command is acceptable; otherwise add the smallest existing-command extension that does not overload telemetry.
  Any arguments must have short options per repo convention.
- Ensure failures are actionable:
  - default Rust with missing/broken extension exits nonzero and says the Rust extension failed to load;
  - explicit `SASE_CORE_BACKEND=python` reports that Python mode is selected and does not require `sase_core_rs`;
  - misbuilt extension import failures are not swallowed.
- Add tests with fake import failures and fake extension modules.
- Wire the release smoke from Phase 6B to call this health command if that smoke already exists.

Exit criteria:

- Release jobs and users have one clear command for "is the Rust core active and healthy?"
- Missing extension errors no longer surface as raw `ImportError` from arbitrary facade calls.

### Phase 6E: Resolve `is_workflow_complete` Regression

Purpose: remove the single known hot-path regression before Rust becomes the default.

Write scope:

- `src/sase/agent/names/_lookup.py`.
- Focused tests around `is_workflow_complete`, currently `tests/test_agent_names_workflow.py`.
- Agent scan benchmark files under `tests/perf/` if measurement scaffolding needs a small update.
- `docs/rust_backend.md` if a pin is documented.
- `plans/202604/rust_backend_phase6_phase6e_handoff.md`.

Work:

- Re-run the focused benchmark for `is_workflow_complete` under Python, Rust, and dual-run modes to confirm the current
  regression still exists on the current code.
- Prefer the conservative fix:
  - add a private targeted Python traversal for `is_workflow_complete`;
  - scan only `~/.sase/projects/*/artifacts/ace-run/*` records needed for the named workflow;
  - preserve existing semantics for missing roots, root dead-without-done, child liveness, and dismissed/finished cases;
  - use this targeted path regardless of `SASE_CORE_BACKEND`, with a comment pointing to the Phase 3H structural
    snapshot regression.
- If the targeted Python path cannot preserve behavior cleanly, add a Rust early-exit binding in `../sase-core` instead.
  Keep the API predicate-specific rather than broad streaming unless measurement proves a reusable primitive is worth
  it.
- Add regression tests proving:
  - no workflow returns `None`;
  - running root returns `False`;
  - done root plus all children done/dead returns `True`;
  - any live child without done returns `False`;
  - root without `done.json` and no children returns `False`;
  - root without `done.json` but dead with all children complete can resolve `True`;
  - backend selection does not route this operation through the slower snapshot path.
- Record benchmark numbers after the fix.

Exit criteria:

- `is_workflow_complete` is no slower under default Rust than the documented Python path, or it is explicitly pinned
  with benchmark evidence and a code comment.
- The handoff states whether a Rust early-exit API is still worth considering in a future phase.

### Phase 6F: Flip Default Backend To Rust

Purpose: make unset `SASE_CORE_BACKEND` select Rust after all prerequisites are in place.

Write scope:

- `src/sase/core/backend.py`.
- Tests that assert default backend/display behavior.
- TUI backend indicator tests if labels or colors need updates.
- `docs/rust_backend.md`.
- `plans/202604/rust_backend_phase6_phase6f_handoff.md`.

Work:

- Change `DEFAULT_BACKEND` to `Backend.RUST`.
- Update module docstrings and user-facing docs that still say Python is the default.
- Update tests:
  - unset backend is Rust;
  - explicit `SASE_CORE_BACKEND=python` still selects Python;
  - explicit `SASE_CORE_BACKEND=rust` still selects Rust;
  - invalid values still fail clearly;
  - backend display and TUI indicator reflect Rust by default.
- Verify that default Rust fails clearly if `sase_core_rs` is missing and a shipped operation is invoked.
- Verify that explicit Python mode works without `sase_core_rs`.
- Do not remove dual-run, Python implementations, or fallback policy.

Exit criteria:

- With `SASE_CORE_BACKEND` unset and `sase_core_rs` installed, shipped operations run through Rust by default.
- With `SASE_CORE_BACKEND=python`, the same focused tests pass without requiring `sase_core_rs`.

### Phase 6G: CI Matrix, Parity Gate, And Release Smoke

Purpose: make the new default durable in automation.

Write scope:

- `.github/workflows/ci.yml`.
- `.github/workflows/publish.yml`.
- `Justfile` only if new convenience targets are needed.
- Focused tests or fixture scripts for the sanitized home-tree parity check.
- `plans/202604/rust_backend_phase6_phase6g_handoff.md`.

Work:

- Run the Python test suite under both backend modes until Phase 8:
  - default backend job with `SASE_CORE_BACKEND` unset and `sase_core_rs` installed;
  - explicit Python job with `SASE_CORE_BACKEND=python`.
- Keep the Python-version matrix practical. If the full cross product is too expensive, run full coverage on the default
  backend and a focused/faster explicit-Python job on the supported oldest and newest Python versions. Record the choice
  in the handoff.
- Add a dual-run parity job for the golden corpus and a sanitized home-tree fixture:
  - set `SASE_CORE_DUAL_RUN=1`;
  - exercise parser, query, agent scan, status planner, and Git query parser paths;
  - fail if any comparison record for these operations has `match: false`;
  - archive the JSONL or summarized counts as CI output.
- Update publish workflow to smoke-test built `sase` artifacts in a fresh venv:
  - install the built wheel/sdist;
  - run the backend health command with backend unset;
  - run a minimal `SASE_CORE_BACKEND=python` smoke;
  - report extension package/version/platform details on failure.
- Ensure CI does not rely on a developer's sibling checkout unless that checkout is explicitly part of the job. Released
  wheel installs should prove the package dependency story from Phase 6B.

Exit criteria:

- CI protects both default Rust and explicit Python modes.
- Dual-run parity has a zero-mismatch gate for the operations Phase 6 defaults to Rust.
- Publish workflow proves release artifacts install and start without a local Rust toolchain.

### Phase 6H: Documentation, Rollback Plan, And Close-Out

Purpose: close Phase 6 with an evidence-backed rollout record and handoff to Phase 7.

Write scope:

- `docs/rust_backend.md`.
- `sdd/research/202604/rust_backend_migration.md`.
- `plans/202604/rust_backend_phase6_phase6h_handoff.md`.
- Optional small release notes file if the repo has one by then.

Work:

- Rewrite docs so they no longer describe Rust as optional/opt-in:
  - Rust is the default for shipped core operations;
  - `SASE_CORE_BACKEND=python` is the temporary opt-out;
  - `SASE_CORE_DUAL_RUN=1` is a parity/safety rail;
  - health-check command and failure modes are documented;
  - source-development and local `../sase-core` override workflows are documented.
- Update the research document:
  - mark Phase 6 complete;
  - record the packaging decision;
  - record CI/backend matrix status;
  - record `is_workflow_complete` fix/pin decision and benchmark;
  - restate the Phase 7 measurement work.
- Produce a rollback plan:
  - before Phase 8, rollback is a patch release restoring `DEFAULT_BACKEND=python` and keeping the Rust dependency
    harmless;
  - after Phase 8, rollback is a wheel/package fix because the Python implementation will no longer exist;
  - list exactly which env var users can set for immediate local mitigation during the Phase 6/7 cycle.
- Summarize verification commands and parity counts:
  - source checks (`just check`);
  - Rust checks (`just rust-check`) if the sibling checkout is available;
  - default-backend focused tests;
  - explicit-Python focused tests;
  - dual-run mismatch counts;
  - release install smoke.

Exit criteria:

- `sdd/research/202604/rust_backend_migration.md` says Phase 6 is complete and Phase 7 can begin.
- `docs/rust_backend.md` matches actual runtime behavior.
- The handoff tells a future agent exactly how to roll back during the Phase 6/7 release cycle.

## Cross-Phase Verification Expectations

Every code-changing subphase should run the focused tests it touched. Any subphase that edits this repo should finish
with:

```bash
just install
just check
```

Subphases touching `../sase-core` should additionally run:

```bash
just rust-check
just rust-install
```

After Phase 6F, focused Python tests should be run in both modes where practical:

```bash
.venv/bin/pytest <focused tests>
SASE_CORE_BACKEND=python .venv/bin/pytest <focused tests>
```

After Phase 6G, CI is the source of truth for the full matrix.

## Risks And Guardrails

- **Wheel availability is the hard gate.** Do not flip `DEFAULT_BACKEND` until install-from-artifact succeeds on the
  supported matrix.
- **Do not mask extension failures.** Default Rust with a missing shipped binding must fail clearly; only explicit
  Python mode is the fallback.
- **Keep plugin/process boundaries in Python.** Rust remains below plugin entry points and subprocess execution.
- **Avoid expanding Phase 6 into new ports.** The default flip is already large. New Rust APIs are justified only for
  the `is_workflow_complete` regression if the targeted Python pin is not enough.
- **Preserve rollback.** Python implementations stay through Phase 7 so a patch release can restore the old default if
  real-world parity or packaging problems appear.
