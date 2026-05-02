---
create_time: 2026-04-29 19:15:00
bead_id: sase-1a.5
status: complete
---
# Rust Backend Phase 5E Handoff: Git Provider Integration and End-to-End Verification

## Scope

Phase 5E swaps the inline parsing in
`sase.vcs_provider.plugins._git_query_ops.GitQueryOpsMixin` for calls
into `sase.core.git_query_facade`. After this phase the Git provider's
five query helpers (`vcs_diff_name_status`, `vcs_get_branch_name`,
`vcs_get_workspace_name`, `vcs_get_conflicted_files`,
`vcs_has_local_changes`) get their parsed output from the facade, so
they automatically pick up `SASE_CORE_BACKEND=rust` and
`SASE_CORE_DUAL_RUN=1` without any further plumbing. The Phase 5D
dispatch contract is unchanged; this phase is a pure consumer wiring.

## Files Changed (this repo)

- `src/sase/vcs_provider/plugins/_git_query_ops.py` — replaced the
  inline parsing/normalization in the five query helpers with calls
  into `sase.core.git_query_facade`:
  - `vcs_diff_name_status` calls `parse_git_name_status_z(stdout)`
    (return shape `list[tuple[str, str]]`, with rename/copy paths
    encoded as `"<old>\t<new>"` exactly as before).
  - `vcs_get_branch_name` calls `parse_git_branch_name(stdout)` after
    the `git rev-parse --abbrev-ref HEAD` shell-out and returns
    `(True, <name|None>)`. Detached HEAD (`"HEAD\n"`) and empty stdout
    still map to `None`.
  - `vcs_get_workspace_name` keeps the remote-URL-first / root-path
    fallback by branching in Python and calling
    `derive_git_workspace_name(remote_url, None)` or
    `derive_git_workspace_name(None, root_path)` accordingly. The
    facade does the basename split and `.git` suffix strip; the soft
    failure path (`(False, "Could not determine workspace name")`) is
    unchanged.
  - `vcs_get_conflicted_files` calls
    `parse_git_conflicted_files(stdout)` and still returns `[]` on a
    failed `git diff` invocation.
  - `vcs_has_local_changes` calls `parse_git_local_changes(stdout)`
    and re-attaches the `(True, ...)` success flag the public contract
    promises (`(True, None)` for clean, `(True, text)` for dirty).
  - The local `_parse_git_name_status_z` helper is removed; the facade
    is the single source of truth for the parser.
- `tests/ace/deltas/test_diff_name_status_git.py` — updated the parser
  unit tests to import `parse_git_name_status_z` from
  `sase.core.git_query_facade` (the integration tests against a real
  git repo are unchanged and continue to exercise the public hookimpl).
- `tests/perf/bench_git_query_ops.py` — switched to importing
  `parse_git_name_status_z`, `parse_git_branch_name`,
  `derive_git_workspace_name`, `parse_git_conflicted_files`, and
  `parse_git_local_changes` from `sase.core.git_query_facade`. The
  inline normalizer reimplementations from the Phase 5A baseline are
  gone — the bench now reflects the production code path under the
  active backend (default Python, `SASE_CORE_BACKEND=rust`, or
  `SASE_CORE_DUAL_RUN=1`).
- `plans/202604/perf_artifacts/bench_git_query_ops_phase5e.json` — new
  artifact bundling three runs of the bench (Python facade, Rust
  facade, dual-run) so Phase 5F has the comparison data for its
  rollout decision.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5e_handoff.md`
  (this file).

## Public Contract Preservation

| hookimpl                   | shape                              | preserved behavior                                             |
| -------------------------- | ---------------------------------- | -------------------------------------------------------------- |
| `vcs_diff_name_status`     | `list[tuple[str, str]]`            | rename/copy still encoded as `"<old>\t<new>"`; raises `VCSOperationError` on `git diff` failure |
| `vcs_get_branch_name`      | `tuple[bool, str \| None]`         | `(True, None)` for detached HEAD or empty stdout; `(False, ...)` on subprocess failure |
| `vcs_get_workspace_name`   | `tuple[bool, str \| None]`         | remote URL takes priority over the toplevel root; `.git` suffix stripped; soft `(False, "Could not determine workspace name")` when both unavailable |
| `vcs_get_conflicted_files` | `list[str]`                        | `[]` on subprocess failure; blank lines dropped                |
| `vcs_has_local_changes`    | `tuple[bool, str \| None]`         | `(True, None)` for clean tree, `(True, text)` for dirty, `(False, ...)` on subprocess failure |

No command arguments, timeouts, or exception types changed.

## Verification

- `just install` and `just rust-install` ran cleanly in this workspace
  (CPython 3.14, `sase_core_rs` built via `maturin develop --release`).
- `just test tests/ace/deltas/test_diff_name_status_git.py
  tests/test_vcs_provider_git_query.py
  tests/test_vcs_provider_git_sync.py tests/test_core_git_query.py` —
  75 passed under default Python backend.
- `SASE_CORE_BACKEND=rust just test ...` (same four files) — 75 passed
  under Rust backend with the real `sase_core_rs` extension installed.
- `just check` — green (fmt, ruff, mypy, pyvision, full pytest suite).
- Bench runs (recorded in
  `plans/202604/perf_artifacts/bench_git_query_ops_phase5e.json`):
  - Python facade: `parse_git_name_status_z` median ~9 ms on
    synthetic_large (~10k entries); end-to-end_500 median ~722 us on
    parse vs ~10.5 ms subprocess-only — fork still dominates.
  - Rust facade: `parse_git_name_status_z` median ~9 ms on
    synthetic_large (no significant speedup over Python at this
    workload); end-to-end_500 parse-only median ~705 us; the Rust
    binding shaves a few percent off end-to-end_50 parse cost
    (~37 us vs ~73 us median) but is dwarfed by the ~2.7-ms
    subprocess cost.
  - Dual-run: ~2x parse cost as expected (both implementations run
    plus the comparison and JSONL append). 3460 records logged across
    the bench; mismatches = 0.
- Dual-run sample location: `~/.sase/perf/core_dual_run.jsonl`
  (records from this session start at timestamp `2026-04-29T19:10:59Z`
  and earlier).

## Hand-off Notes for Phase 5F

- Phase 5 ports five deterministic Git output parsers behind the
  `sase.core` facade; the Git provider now consumes them. Default
  backend is still `python`; Rust mode is opt-in.
- Benchmark numbers continue to support the Phase 5A finding that
  subprocess fork+exec dominates Git query cost. The Rust port did
  not move the needle on the workloads measured here. Phase 5F should
  weigh this evidence and decide whether Phase 6 (default-backend
  rollout) gets a push or a pause from the Git query helpers.
- The dispatch wiring (Phase 5D) and the parser implementations
  (Phase 5B/5C) are intact and need no changes for Phase 5F.
- Documentation updates (`docs/rust_backend.md` roadmap and the
  migration research file Phase 5 section) are deferred to Phase 5F
  per the original plan.
- Rollback path: Python helpers remain as `*_python` exports in the
  facade. If a binding bug surfaces in production, set
  `SASE_CORE_BACKEND=python` (the default) to restore pure-Python
  behavior with no provider-side change.
