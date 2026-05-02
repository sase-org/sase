---
create_time: 2026-04-29 12:39:59
bead_id: sase-19
status: done
prompt: sdd/prompts/202604/rust_backend_phase4_status_machine.md
---
# Rust Backend Phase 4: Status State Machine

## Context

`sdd/research/202604/rust_backend_migration.md` originally described Phase 4 as the Rust port of the ChangeSpec status state
machine. Phases 0-3 are complete:

- `sase.core` is the Python facade with `SASE_CORE_BACKEND` dispatch and `SASE_CORE_DUAL_RUN` parity logging.
- The sibling `../sase-core` Rust workspace exposes `sase_core_rs` through PyO3.
- `parse_project_bytes`, `parse_query` / `evaluate_query_many`, and `scan_agent_artifacts` are available through Rust
  under `SASE_CORE_BACKEND=rust`.
- The default backend remains `python`; Phase 3H measured a real but sub-threshold scan improvement and recommended
  re-profiling before committing to the status-machine port as the next highest-leverage task.

The current status-machine surface already has a facade in `src/sase/core/status_facade.py`:

- `read_status_from_lines(lines, changespec_name) -> str | None`
- `apply_status_update(lines, changespec_name, new_status) -> str`
- `transition_changespec_status(project_file, changespec_name, new_status, validate=True, console=None) -> tuple[...]`

The implementation lives in `src/sase/status_state_machine/`. It is mixed:

- Pure, Rust-friendly logic: status constants, transition validation, workspace-suffix stripping, reading/replacing
  `STATUS:` from raw lines, and transition decision rules.
- Host-side side effects: file locks, atomic writes, archive moves, timestamp recording, mentor flag mutation, suffix
  branch renames, parent-reference updates, RUNNING updates, and VCS operations.

Phase 4 should therefore port the pure decision engine first. Python should keep doing file mutation and all host
services until the Rust parser/source-span and side-effect boundary are proven.

## Goal

Move the status state machine's pure logic behind the Rust-backed `sase.core` facade without changing user-visible
behavior:

- Rust can validate transitions and produce a structured transition plan under `SASE_CORE_BACKEND=rust`.
- Python continues to own locks, writes, archive moves, timestamps, mentor flags, suffix rename side effects, sibling
  reverts, VCS interactions, and console output.
- Dual-run parity catches decision drift on real project data.
- The default backend remains `python` unless a later rollout plan changes the global policy.

## Non-Goals

- Do not rewrite `.gp` files in Rust.
- Do not move archive-file transfer, timestamp recording, mentor mutation, branch renaming, or VCS operations into Rust.
- Do not remove Python implementations or the `SASE_CORE_BACKEND=python` escape hatch.
- Do not flip the default backend in Phase 4.
- Do not use this phase to solve Phase 3's artifact-scan snapshot-size problem except for measurement context.

## Proposed Phase Split

Each subphase below is designed to be handled by a distinct agent instance. Later agents should read this plan, the
previous subphase handoff, `sdd/research/202604/rust_backend_migration.md`, `docs/rust_backend.md`, and any files listed in
their phase scope before editing.

### Phase 4A: Profiling and Scope Decision

Purpose: confirm whether the status state machine is worth porting now and pin the exact operation set for Phase 4.

Work:

- Add or extend a focused benchmark that measures status-machine cost separately from artifact scanning and TUI
  adaptation. Cover at least:
  - `is_valid_transition` / suffix normalization over representative status strings.
  - `read_status_from_lines` and `apply_status_update` over realistic `.gp` files from the golden corpus and a synthetic
    large project file.
  - `transition_changespec_status` with side effects mocked where practical, so pure decision cost is visible separately
    from locks, disk writes, archive moves, and timestamp writes.
- Run the benchmark under the current Python backend and, where useful, with `SASE_CORE_BACKEND=rust` for already-routed
  parser/scan dependencies.
- Re-run enough of the Phase 3 agent-scan benchmark to keep the status work honest against the dominant refresh cost.
- Produce a handoff document under `plans/202604/` with:
  - median timings, sample sizes, workload sizes, and workstation details;
  - a go/no-go recommendation for the rest of Phase 4;
  - the chosen Rust API surface for Phase 4B-4E.

Expected deliverables:

- `tests/perf/bench_status_state_machine.py` or equivalent.
- A `just bench-status-state-machine` alias if the Justfile pattern supports it.
- `plans/202604/rust_backend_phase4_status_machine_phase4a_handoff.md`.

Exit criteria:

- The next agent can see exactly which operations are being ported and why.
- If the benchmark shows status logic is not worth porting, the handoff should recommend stopping Phase 4 and opening a
  separate plan for the higher-leverage bottleneck. If it is still worth porting for correctness/shared-core reasons,
  say that explicitly and proceed with the scoped plan below.

### Phase 4B: Wire Contract and Golden Parity Corpus

Purpose: define a stable cross-language contract before writing Rust status logic.

Work:

- Add Python wire dataclasses or TypedDict-style records in `src/sase/core/` for status operations. Suggested records:
  - `StatusTransitionRequestWire`: current status, target status, changespec name, optional parent status, child
    statuses, sibling summary, validation flag, and any name/suffix facts needed by the decision engine.
  - `StatusTransitionPlanWire`: success flag, old status, error message, status update target, suffix action (`none`,
    `strip`, `append`), mentor draft action, archive movement classification, and timestamp event.
  - `StatusFieldUpdateWire` if needed for line-based helpers.
- Keep wire records free of host objects: no `Path`, `Console`, `ChangeSpec`, VCS provider, lock, or callable fields.
- Add conversion helpers that build the request wire from the existing Python `ChangeSpec` / parsed project-file data.
  These helpers may call existing Python parsers; the Rust boundary should receive only primitive wire values.
- Add golden tests for:
  - valid and invalid transition pairs;
  - workspace suffix stripping and legacy READY TO MAIL suffix stripping;
  - parent/child constraints;
  - Ready -> Draft suffix append planning;
  - Draft/WIP -> Ready suffix strip planning;
  - terminal statuses;
  - `validate=False` behavior;
  - `read_status_from_lines` and `apply_status_update` line behavior.
- Do not route production calls to new Rust code in this phase.

Expected deliverables:

- `src/sase/core/status_wire.py` and focused converters if needed.
- Golden/parity tests near `tests/test_status_state_machine_*.py` or a new `tests/test_core_status_*.py`.
- Documentation note in `docs/rust_backend.md` describing the planned Phase 4 status wire surface.
- `plans/202604/rust_backend_phase4_status_machine_phase4b_handoff.md`.

Exit criteria:

- Python-only tests lock down the status wire shape and expected transition plans.
- The Rust agent for Phase 4C can implement against a concrete schema instead of inferring from side-effect-heavy Python
  handlers.

### Phase 4C: Rust Pure Status Module and PyO3 Bindings

Purpose: implement the pure status logic in `../sase-core` and expose it to Python without changing production routing.

Work in `../sase-core`:

- Add a `status` module in `crates/sase_core/src/`.
- Implement Rust equivalents for:
  - valid status constants and archive-status classification;
  - workspace/legacy suffix normalization;
  - transition validation;
  - `read_status_from_lines`;
  - `apply_status_update`;
  - `plan_status_transition(request) -> StatusTransitionPlanWire`.
- Keep the Rust code deterministic and side-effect free.
- Add serde-compatible wire structs matching Phase 4B's Python records.
- Add Rust unit tests and parity fixtures based on the Python golden corpus.

Work in `../sase-core/crates/sase_core_py`:

- Expose PyO3 functions for the pure helpers:
  - `remove_workspace_suffix(status: str) -> str` if useful for tests/debugging.
  - `is_valid_status_transition(from_status: str, to_status: str) -> bool`.
  - `read_status_from_lines(lines: list[str], changespec_name: str) -> str | None`.
  - `apply_status_update(lines: list[str], changespec_name: str, new_status: str) -> str`.
  - `plan_status_transition(request: dict) -> dict`.
- Return plain Python dict/list/string/bool values matching the established wire records.
- Release the GIL only where it actually matters; these functions are expected to be CPU-light.

Expected deliverables:

- Rust status module and PyO3 bindings.
- Rust tests under `../sase-core/crates/sase_core/tests/` or module tests.
- README or docs update in `../sase-core` if the public binding list is maintained there.
- `plans/202604/rust_backend_phase4_status_machine_phase4c_handoff.md` in the Python repo, summarizing Rust files
  changed and the commands run.

Exit criteria:

- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`
  pass in `../sase-core`.
- The bindings import after `just rust-install`.
- No production Python caller uses the Rust status functions yet.

### Phase 4D: Facade Registration, Dual-Run, and Pure Helper Routing

Purpose: route the low-risk pure helpers through the existing backend dispatcher.

Work:

- Register Rust implementations in `src/sase/core/status_facade.py` only when `sase_core_rs` exposes the Phase 4C
  functions.
- Route `read_status_from_lines` and `apply_status_update` through Rust when `SASE_CORE_BACKEND=rust`.
- Preserve Python fallback for these intentionally unported or unavailable operations according to the existing hybrid
  backend policy. If these helpers are classified as shipped Rust operations after this phase, missing bindings under
  `SASE_CORE_BACKEND=rust` should fail clearly and tests should assert that policy.
- Add dual-run comparison records for the routed helpers. Use stable operation names such as `read_status_from_lines`
  and `apply_status_update`.
- Keep `transition_changespec_status` on Python for now.

Expected deliverables:

- Python facade registration changes.
- Tests with fake `sase_core_rs` functions for backend selection and dual-run logging.
- Real-extension parity tests that skip cleanly when `sase_core_rs` is not installed.
- Docs update in `docs/rust_backend.md`.
- `plans/202604/rust_backend_phase4_status_machine_phase4d_handoff.md`.

Exit criteria:

- Default Python behavior is unchanged.
- `SASE_CORE_BACKEND=rust` uses Rust for the pure line helpers when the extension is installed.
- `SASE_CORE_DUAL_RUN=1` logs matches/mismatches and returns the Python result.
- Focused status/core tests pass under default backend and Rust backend where the extension is installed.

### Phase 4E: Transition Decision Plan Integration

Purpose: use Rust to validate and plan transitions while keeping Python responsible for side effects.

Work:

- Refactor `transition_changespec_status_python` enough to separate:
  - input gathering under lock;
  - pure transition decision;
  - side-effect execution;
  - post-lock suffix/VCS/timestamp/archive effects.
- Add a Python implementation of `plan_status_transition_python(request)` that mirrors the current decision behavior.
- Register `plan_status_transition` in the facade with Rust support.
- Under `SASE_CORE_BACKEND=rust`, call the Rust planner for the pure decision step, then execute the returned plan using
  existing Python side-effect helpers.
- Under `SASE_CORE_DUAL_RUN=1`, compare Python and Rust plans, return/use the Python plan, and log mismatches.
- Do not let Rust perform file writes, archive moves, timestamp writes, mentor flag changes, suffix rename operations,
  or VCS calls.
- Be careful with dynamic global queries currently embedded in handlers:
  - `handle_draft_transition` calls `find_all_changespecs()`;
  - `handle_ready_transition` parses the current project file and checks siblings;
  - sibling child checks depend on project context. These inputs must be gathered in Python and passed into the request
    wire before calling Rust.

Expected deliverables:

- A pure transition planner in Python and Rust.
- Production integration for planner selection through the status facade.
- Tests proving side effects still happen exactly once and in the same order-visible places as before.
- Tests covering failure paths where Rust rejects a transition before writes occur.
- `plans/202604/rust_backend_phase4_status_machine_phase4e_handoff.md`.

Exit criteria:

- Existing transition tests pass unchanged or with only expectation updates justified by bug fixes.
- New tests prove Rust-backed planning and Python-backed side effects work together.
- Dual-run catches plan drift without duplicating side effects.

### Phase 4F: Verification, Performance Decision, and Roadmap Update

Purpose: close Phase 4 with evidence and a clear default-backend decision.

Work:

- Run the full verification set:
  - `just install`
  - `just rust-install`
  - `just rust-check`
  - focused status/core tests under the default backend
  - focused status/core tests under `SASE_CORE_BACKEND=rust`
  - `just check`
- Re-run the Phase 4A benchmark and record before/after numbers.
- Review `~/.sase/perf/core_dual_run.jsonl` from local real-project runs if available; mismatch count must be zero
  before declaring the Rust status path stable.
- Decide whether any status operation should default to Rust. The expected answer is still "no global default flip";
  only recommend a per-operation default if the operation is shipped, packaged, parity-clean, and user-visible.
- Update:
  - `sdd/research/202604/rust_backend_migration.md` Phase 4 status;
  - `docs/rust_backend.md` roadmap and operation list;
  - any benchmark docs/runbook entries touched by Phase 4A.
- Write a final handoff with commands, results, known limits, and follow-up recommendations.

Expected deliverables:

- `plans/202604/rust_backend_phase4_status_machine_phase4f_handoff.md`.
- Updated docs/research.
- Recorded benchmark artifacts or paths to them.

Exit criteria:

- Phase 4 is either complete and shipped as an opt-in Rust-backed status planner, or explicitly stopped with evidence
  that another bottleneck should be prioritized.
- No production code path depends on Rust for side effects.
- Python fallback remains available and tested.

## Cross-Phase Dependency Order

1. Phase 4A must land first; it decides whether Phase 4 proceeds as scoped.
2. Phase 4B must land before Rust implementation so the schema is stable.
3. Phase 4C can change only `../sase-core` plus its handoff doc; it should not route Python production calls.
4. Phase 4D depends on Phase 4C bindings and routes only pure line helpers.
5. Phase 4E depends on Phase 4B-4D and is the riskiest integration phase.
6. Phase 4F lands last and should not be combined with feature work.

## Verification Matrix

Minimum focused tests for implementation phases:

```bash
just install
just rust-install
just rust-check
.venv/bin/pytest tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_backend.py \
  tests/test_core_dual_run.py
SASE_CORE_BACKEND=rust .venv/bin/pytest tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py
just check
```

Adjust the focused selector as new `tests/test_core_status_*.py` files are added. If a globally set Rust backend trips
tests that intentionally exercise missing-binding behavior, document the exception in the handoff rather than weakening
the backend contract.

## Risks and Guardrails

- The status transition code is not purely computational today. Any Rust API that accepts a `project_file` and performs
  writes is too broad for Phase 4.
- Dual-run must compare plans before executing side effects. Never call both Python and Rust full transition functions
  if either one can write files, rename branches, move archives, or record timestamps.
- Error message strings are user-visible in tests and CLI/TUI output. Golden tests should either lock them down exactly
  or define a deliberate normalized error contract.
- `validate=False` is a real behavior used by tests and archive restore flows. Rust must not silently enforce validation
  when Python currently skips it.
- Existing hybrid backend policy matters: `SASE_CORE_BACKEND=rust` means Rust for shipped operations and Python for
  intentionally unported facades. Phase handoffs must classify every status facade operation accordingly.
- Cross-repo work requires attention to two worktrees: `sase_100` and sibling `../sase-core`.

## Completion Definition

Phase 4 is complete when:

- the status wire contract is documented and parity-tested;
- Rust implements the pure status decision logic;
- Python routes eligible status helpers/planner calls through Rust under `SASE_CORE_BACKEND=rust`;
- side effects remain in Python;
- dual-run works without duplicating side effects;
- benchmark and parity evidence are recorded; and
- docs/research clearly state whether Phase 4 changed the default-backend recommendation.
