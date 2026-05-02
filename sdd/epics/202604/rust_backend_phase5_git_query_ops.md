---
create_time: 2026-04-29 14:19:17
bead_id: sase-1a
status: done
prompt: sdd/prompts/202604/rust_backend_phase5_git_query_ops.md
---
# Rust Backend Phase 5: Git Query Ops

## Context

`sdd/research/202604/rust_backend_migration.md` defines Phase 5 as the Git query-ops port and recommends option A: keep
shelling out to `git`, but parse command output in Rust unless profiling proves subprocess fork overhead is the real
bottleneck. Phases 0-4 are already complete:

- `src/sase/core/` is the Python facade with `SASE_CORE_BACKEND` dispatch and `SASE_CORE_DUAL_RUN` parity logging.
- The sibling `../sase-core/` Cargo workspace exposes the optional `sase_core_rs` PyO3 module.
- Parser, query, agent-scan, and status pure helpers/planner have Rust implementations available under
  `SASE_CORE_BACKEND=rust`.
- The default backend remains `python`; Rust is opt-in because earlier phases produced real but not decisive
  user-visible wins.

The current Git query surface is concentrated in `src/sase/vcs_provider/plugins/_git_query_ops.py`. It mixes several
kinds of work:

- Host services that should stay in Python: command execution through `CommandRunner._run`, timeouts, fetch fallback,
  filesystem checks, rebase state checks, and all mutating sync/reword operations.
- Pass-through command output that does not need Rust: diffs, patches, file contents, and commit messages.
- Small deterministic parsers that are suitable for `sase.core`: NUL-delimited `git diff --name-status -z`, branch-name
  stdout normalization, workspace-name derivation from remote URL or repo root, conflicted-file line parsing, local
  changes normalization, and possibly commit-message tag composition if the audit classifies it as query-adjacent.

Phase 5 should therefore be a narrow shared-core hygiene port, not a rewrite of the Git provider around `gix`.

## Goal

Move the deterministic parsing/normalization pieces used by Git query operations behind the Rust-backed `sase.core`
facade without changing the VCS provider contract:

- Python still invokes `git` and owns all filesystem/process behavior.
- Rust receives only strings/bytes and returns primitive wire-shaped values.
- The Git provider calls a stable Python facade, so default Python behavior is unchanged.
- `SASE_CORE_BACKEND=rust` routes shipped parser helpers through `sase_core_rs`.
- `SASE_CORE_DUAL_RUN=1` compares Python and Rust parser results before production code depends on Rust parity.
- The close-out handoff records whether Phase 5 produced enough benefit to influence Phase 6's default-backend decision.

## Non-Goals

- Do not replace `git` subprocesses with `gix` in the main implementation. If Phase 5A proves fork overhead dominates,
  record that as a separate Phase 5G or future Phase 10 plan.
- Do not move `CommandRunner`, timeout handling, fetch retries, checkout/rebase/sync, branch renames, commit/amend,
  archive/prune, stash/clean, or patch application into Rust.
- Do not change the pluggy VCS provider interface or return types.
- Do not flip `DEFAULT_BACKEND` to Rust.
- Do not remove Python parser implementations or the backend escape hatch.

## Target Rust API Surface

The exact names should be finalized in Phase 5A, but this is the expected shape:

```text
parse_git_name_status_z(stdout: str) -> list[{status: str, path: str}]
parse_git_branch_name(stdout: str) -> str | null
derive_git_workspace_name(remote_url: str | null, root_path: str | null) -> str | null
parse_git_conflicted_files(stdout: str) -> list[str]
parse_git_local_changes(stdout: str) -> str | null
```

Keep the Python-facing public API tuple-compatible with existing call sites where useful. For example,
`parse_git_name_status_z()` may return `list[tuple[str, str]]` from the Python facade while the Rust binding returns
`list[dict]` or `list[tuple]`; the facade should hide that detail.

The highest-value helper is `parse_git_name_status_z()`, because it already has custom parsing logic and integration
coverage under `tests/ace/deltas/test_diff_name_status_git.py`. The other helpers are cheap but useful for consolidating
the shared-core boundary and exercising the same parity pattern.

## Phase Split for Distinct Agent Instances

Each subphase below is designed for a separate agent instance. Later agents should read this plan, the current
`sdd/research/202604/rust_backend_migration.md`, `docs/rust_backend.md`, the prior subphase handoff, and only the files in
their write scope before editing.

### Phase 5A: Audit, Profiling, and Scope Lock

Purpose: prove exactly which Git query parsers are worth porting and avoid accidentally turning Phase 5 into a VCS
rewrite.

Write scope:

- `tests/perf/bench_git_query_ops.py` or equivalent.
- `Justfile` only if adding a `just bench-git-query-ops` alias.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5a_handoff.md`.

Work:

- Inventory every method in `GitQueryOpsMixin` and classify it as:
  - command execution only;
  - command output parsing/normalization;
  - filesystem/process state;
  - mutation/sync/reword behavior.
- Add a benchmark that separates command time from parse time where practical:
  - direct `_parse_git_name_status_z()` on synthetic NUL streams with small, medium, and large entry counts;
  - end-to-end `vcs_diff_name_status()` on a temporary repo with added/modified/deleted/renamed files;
  - branch-name, workspace-name, conflicted-file, and local-changes normalization microbenchmarks;
  - dual-run overhead once later phases wire dispatch, if the harness can support placeholder measurements.
- Run enough existing tests to confirm the benchmark scaffolding did not perturb behavior.
- Decide the final Phase 5 parser set. The default recommendation is to port `parse_git_name_status_z` plus the small
  normalizers listed above. Exclude pass-through diff/content/message operations.
- Explicitly decide whether `gix` is out of scope. It should remain out of scope unless measurements show subprocess
  fork/setup is the dominant cost on a realistic workload.

Exit criteria:

- The next agent has a concrete parser list and sample benchmark numbers.
- A handoff document records whether Phase 5 remains recommendation A or should stop/replan around `gix`.
- No production behavior is routed through new code yet.

### Phase 5B: Python Facade, Wire Contract, and Golden Tests

Purpose: create the stable Python seam before implementing Rust.

Write scope:

- `src/sase/core/git_query_wire.py` if a record module is needed.
- `src/sase/core/git_query_facade.py`.
- `src/sase/core/__init__.py` only for public exports if existing patterns call for it.
- Focused tests under `tests/`, preferably `tests/test_core_git_query.py`.
- `docs/rust_backend.md` roadmap/API notes.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5b_handoff.md`.

Work:

- Implement Python parser helpers matching the Phase 5A parser list. Start by moving or wrapping
  `_parse_git_name_status_z()` semantics without changing `GitQueryOpsMixin` yet.
- Define explicit wire-shaped records only where tuples are too implicit. For name-status rows, a tiny dataclass such as
  `GitNameStatusEntryWire(status: str, path: str)` is acceptable, but avoid overbuilding a broad Git model.
- Add golden tests covering:
  - empty NUL streams;
  - trailing NUL;
  - simple statuses `A`, `M`, `D`, `T`, `U`;
  - rename/copy statuses with scores (`R100`, `C75`) and paired paths encoded as `old\tnew`;
  - malformed/truncated streams, preserving the current Python behavior unless Phase 5A identifies a bug to fix;
  - branch stdout `"HEAD\n"`, empty stdout, and normal branch names;
  - remote URLs with and without `.git`, SSH-style URLs, path-like remotes, and fallback root paths;
  - conflicted-file parsing with blank lines;
  - local-changes stdout normalization.
- Keep all helpers on the Python implementation in this phase. Do not import `sase_core_rs` yet.

Exit criteria:

- Python-only tests pin the parser contract.
- The Rust agent can implement against concrete examples instead of inferring behavior from the Git provider.

### Phase 5C: Rust Pure Git Parser Module and PyO3 Bindings

Purpose: implement the pure parser helpers in `../sase-core` without changing production Python routing.

Write scope:

- `../sase-core/crates/sase_core/src/git_query/` or equivalent module.
- `../sase-core/crates/sase_core/src/lib.rs`.
- `../sase-core/crates/sase_core/tests/`.
- `../sase-core/crates/sase_core_py/src/lib.rs`.
- `../sase-core/README.md` only if the binding list is maintained there.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5c_handoff.md` in this repo.

Work:

- Mirror the Phase 5B contract in Rust with serde-compatible output types where records are used.
- Implement the selected parsers as pure functions. They must not run `git`, read config, inspect `.git`, or touch the
  filesystem.
- Expose PyO3 functions with names matching the facade's expected binding names.
- Convert results to plain Python primitives/dicts/lists. Keep errors boring: malformed input should either preserve the
  Python helper's forgiving behavior or raise `ValueError` if Phase 5B deliberately made that part of the contract.
- Add Rust unit tests and fixture/parity tests for the same edge cases as the Python golden tests.

Exit criteria:

- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`
  pass in `../sase-core`.
- After `just rust-install`, the new functions are importable from `sase_core_rs`.
- No production Python caller uses the Rust functions yet.

### Phase 5D: Facade Registration and Dual-Run

Purpose: route the new `sase.core.git_query_facade` helpers through the backend dispatcher.

Write scope:

- `src/sase/core/git_query_facade.py`.
- `tests/test_core_git_query.py` or focused backend-dispatch tests.
- `docs/rust_backend.md`.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5d_handoff.md`.

Work:

- Register Rust implementations only when `sase_core_rs` exposes the Phase 5C bindings.
- Classify the helpers as shipped Rust operations once registered: under `SASE_CORE_BACKEND=rust`, missing bindings
  should raise `RustBackendUnavailableError` rather than silently falling back.
- Add tests with a fake `sase_core_rs` module proving:
  - default backend calls Python;
  - Rust backend calls Rust;
  - missing Rust binding fails clearly in Rust mode;
  - dual-run returns Python output and writes comparison records.
- Add real-extension parity tests guarded by `pytest.importorskip("sase_core_rs")`.
- Keep `GitQueryOpsMixin` unchanged in this phase unless Phase 5B already introduced non-production wrappers.

Exit criteria:

- The parser facade behaves like other shipped Rust operations.
- Dual-run can compare Python and Rust parser output independently of actual Git commands.

### Phase 5E: Git Provider Integration and End-to-End Verification

Purpose: make the Git provider consume the new facade while preserving the pluggy contract and existing behavior.

Write scope:

- `src/sase/vcs_provider/plugins/_git_query_ops.py`.
- Focused VCS tests:
  - `tests/ace/deltas/test_diff_name_status_git.py`;
  - `tests/test_vcs_provider_git_query.py`;
  - `tests/test_vcs_provider_git_sync.py` if conflicted-file parsing is routed;
  - any new integration tests needed for workspace/branch/local-change normalization.
- `tests/perf/bench_git_query_ops.py` if updating measured scenarios.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5e_handoff.md`.

Work:

- Replace direct parser logic in `GitQueryOpsMixin` with calls to `sase.core.git_query_facade`.
- Preserve public return shapes:
  - `vcs_diff_name_status()` still returns `list[tuple[str, str]]`;
  - `vcs_get_branch_name()` still returns `(True, None)` for detached HEAD;
  - `vcs_get_workspace_name()` keeps remote URL priority and root fallback;
  - `vcs_get_conflicted_files()` still returns `[]` on command failure;
  - `vcs_has_local_changes()` still returns `(True, None)` for clean output and `(True, text)` for dirty output.
- Do not change command arguments, timeout behavior, error messages, or exception types except where tests prove the old
  behavior was only an artifact of duplicated parsing.
- Run focused tests under both default backend and `SASE_CORE_BACKEND=rust` when the extension is installed.
- Re-run the Phase 5A benchmark and record Python-facade, Rust-facade, and dual-run numbers.

Exit criteria:

- Existing Git provider tests and delta integration tests pass.
- `SASE_CORE_BACKEND=rust` exercises Rust parsing for Git query helpers with no behavior drift.
- Benchmarks show whether the Rust parser matters once subprocess cost is included.

### Phase 5F: Close-Out, Documentation, and Rollout Decision

Purpose: finish Phase 5 with a clear evidence-backed handoff for Phase 6.

Write scope:

- `sdd/research/202604/rust_backend_migration.md`.
- `docs/rust_backend.md`.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5f_handoff.md`.
- CI or Justfile updates only if Phase 5 added durable commands that should stay.

Work:

- Run the full verification set expected after repo changes:
  - `just install`;
  - `just rust-install`;
  - `just rust-check`;
  - focused Git/core tests under default backend;
  - focused Git/core tests under `SASE_CORE_BACKEND=rust`;
  - `just check`.
- Update docs to list the new Git query helpers as opt-in Rust-backed operations.
- Update the migration research file's Phase 5 section with:
  - what was ported;
  - what stayed Python and why;
  - benchmark medians and workload sizes;
  - default-backend decision;
  - whether `gix` should be reconsidered later.
- Record dual-run results, including mismatch count and the path to any `core_dual_run.jsonl` sample used.
- State the rollback plan. While Python helpers remain, rollback is to restore the Git provider to Python facade/default
  behavior or temporarily mark the helpers as Python fallback under Rust mode if a release-blocking binding bug appears.

Exit criteria:

- Phase 5 is documented as complete or explicitly stopped with evidence.
- The default backend remains `python` unless a separate Phase 6 plan changes global rollout policy.
- Future Phase 6 readers know whether Git query parsing strengthens, weakens, or is neutral to the default-Rust case.

## Cross-Phase Guardrails

- Treat all supported runtimes uniformly; do not add Claude/Gemini/Codex-specific behavior.
- Keep Rust functions host-service free. No global config, no Python plugin calls, no filesystem reads, no subprocesses.
- Prefer boring primitive wire shapes over rich Rust/Python object graphs.
- Preserve exact error and return semantics at the VCS provider boundary.
- If an agent encounters unrelated dirty worktree changes, work around them and do not revert them.
- Every subphase that edits this repo should run `just install` first and `just check` before handoff. Every subphase
  that edits `../sase-core` should also run the Rust check commands listed in that subphase.
