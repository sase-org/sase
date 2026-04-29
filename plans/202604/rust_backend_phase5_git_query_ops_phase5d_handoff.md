---
create_time: 2026-04-29 16:00:00
bead_id: sase-1a.4
status: complete
---
# Rust Backend Phase 5D Handoff: Facade Registration and Dual-Run

## Scope

Phase 5D wires the five Phase 5C `sase_core_rs` Git query bindings into
`sase.core.git_query_facade` via `sase.core.backend.dispatch`. After
this phase the facade behaves like the other shipped Rust operations
(parser, query, agent scan, status line/planner): under
`SASE_CORE_BACKEND=rust` every helper is served by Rust and a missing
binding raises `RustBackendUnavailableError`; under
`SASE_CORE_DUAL_RUN=1` both implementations run and the per-call
comparison record lands in `~/.sase/perf/core_dual_run.jsonl`. The Git
provider (`GitQueryOpsMixin`) is intentionally left untouched — Phase
5E swaps the inline parsing for facade calls.

## Files Changed (this repo)

- `src/sase/core/git_query_facade.py` — replaced the Phase 5B
  pure-Python helpers with backend-dispatched ones. Each public helper
  now:
  - probes `sase_core_rs` lazily via `load_rust_extension()` and
    registers the matching binding as `rust_impl` only when
    `hasattr(rust_module, "<name>")` succeeds;
  - hands off to `dispatch(operation=..., python_impl=..., rust_impl=...)`
    so the active backend / dual-run mode is the only thing that picks
    the implementation;
  - exposes the pure-Python implementation as `<name>_python` at module
    scope (so the dual-run comparator and parity tests can call it
    without going back through dispatch).
  The `parse_git_name_status_z` rust adapter
  (`_rust_parse_git_name_status_z_impl`) rehydrates the binding's
  `list[dict]` output via `git_name_status_entry_from_dict` and
  flattens to `list[tuple[str, str]]` so the public facade output is
  the same legacy tuple shape the Git provider already consumes.
- `tests/test_core_git_query.py` — appended a Phase 5D backend-dispatch
  section that covers:
  - default Python backend with no Rust extension (helpers stay
    Python);
  - default backend with a fake Rust module (Rust impl is never
    called);
  - `SASE_CORE_BACKEND=rust` with a fake module (every helper routes
    to Rust, including the dict→tuple rehydration for
    `parse_git_name_status_z`);
  - missing-binding scenarios under Rust mode (parametrized over all
    five helpers; each raises `RustBackendUnavailableError` mentioning
    its operation name);
  - partial-binding scenarios (a fake exposing only one binding still
    raises for the others under Rust mode);
  - `SASE_CORE_DUAL_RUN=1` match records (one record per helper, all
    `match=True`, `error_class=None`);
  - dual-run mismatch capture (a diverging Rust impl is logged as
    `match=False` while Python output is still returned);
  - real-extension parity guarded by
    `pytest.importorskip("sase_core_rs")` exercising every helper
    against a fixture set covering the same edge cases as the Phase 5B
    goldens (rename/copy paired-paths, detached-HEAD branch,
    SSH/path-like remotes, the pathological `.git`-only remote with a
    root fallback, blank-line stripping for conflicted files, and
    clean/dirty porcelain normalization).
- `docs/rust_backend.md` — added the five Git query bindings to the
  shipped Rust operations list, the `SASE_CORE_BACKEND=rust`
  binding-required list, and added Phase 5C and Phase 5D entries to
  the roadmap.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5d_handoff.md`
  (this file).

## Dispatch Contract

| operation                       | python_impl                            | rust_impl present when                                                                  | rust_unavailable |
| ------------------------------- | -------------------------------------- | --------------------------------------------------------------------------------------- | ---------------- |
| `parse_git_name_status_z`       | `parse_git_name_status_z_python`       | `sase_core_rs` is importable AND exposes `parse_git_name_status_z`                      | `raise` (default)|
| `parse_git_branch_name`         | `parse_git_branch_name_python`         | `sase_core_rs` is importable AND exposes `parse_git_branch_name`                        | `raise`          |
| `derive_git_workspace_name`     | `derive_git_workspace_name_python`     | `sase_core_rs` is importable AND exposes `derive_git_workspace_name`                    | `raise`          |
| `parse_git_conflicted_files`    | `parse_git_conflicted_files_python`    | `sase_core_rs` is importable AND exposes `parse_git_conflicted_files`                   | `raise`          |
| `parse_git_local_changes`       | `parse_git_local_changes_python`       | `sase_core_rs` is importable AND exposes `parse_git_local_changes`                      | `raise`          |

All five helpers use the dispatcher's default `rust_unavailable="raise"`
so a stale or partially-built `sase_core_rs` cannot make Rust mode
appear to exercise Rust without producing identical output.

The `parse_git_name_status_z` rust adapter is the only one that does
non-trivial shape work: it accepts the wire `list[dict]` from PyO3 and
flattens it to `list[tuple[str, str]]` before returning. As a result,
dual-run comparison for `parse_git_name_status_z` runs over the public
tuple shape — the same shape the call site sees — so a divergence in
the rename/copy `"<old>\t<new>"` encoding shows up as a single
mismatch record without a wire-vs-public distinction. The other four
helpers cross the wire as primitives and need no adapter beyond the
"extension still importable at call time" check.

## Out of Scope (Phase 5D)

- `GitQueryOpsMixin` is unchanged. Phase 5E replaces the inline
  parsing in `_git_query_ops.py` with calls to the facade and re-runs
  the Phase 5A benchmark with Python-facade, Rust-facade, and dual-run
  numbers.
- No new wire records, no schema-version bump, no changes to
  `git_query_wire.py`. The Phase 5B contract (`schema_version=1`)
  stays intact.
- No changes to default backend selection. The Phase 5A decision
  stands: Rust is opt-in because subprocess fork dominates Git query
  cost. Phase 5F will weigh the close-out evidence and revisit
  default-backend rollout for Phase 6.

## Verification

- `just install` and `just rust-install` ran cleanly in this workspace
  (CPython 3.14, `sase_core_rs` built via `maturin develop --release`).
- `pytest tests/test_core_git_query.py` — all 45 tests pass (golden
  Phase 5B suite + new Phase 5D dispatch suite, including the
  real-extension parity test against the Phase 5C bindings).
- `just check` — green (fmt, ruff, mypy, pyvision, full pytest suite).
- Smoke check via the Rust-mode environment:

  ```text
  SASE_CORE_BACKEND=rust python -c "from sase.core.git_query_facade import parse_git_name_status_z; \
      print(parse_git_name_status_z('M\\0a.py\\0R100\\0old.py\\0new.py\\0'))"
    → [('M', 'a.py'), ('R100', 'old.py\tnew.py')]
  ```

## Hand-off Notes for Phase 5E

- `GitQueryOpsMixin` is the only remaining caller. Replace the inline
  parsing with calls into `sase.core.git_query_facade`:
  - `_parse_git_name_status_z` → `parse_git_name_status_z`
    (already same return shape).
  - `vcs_get_branch_name` → call `parse_git_branch_name(stdout)` after
    the `git rev-parse --abbrev-ref HEAD` shell-out.
  - `vcs_get_workspace_name` → call
    `derive_git_workspace_name(remote_url, root_path)` after the
    remote / root lookups.
  - `vcs_get_conflicted_files` → call
    `parse_git_conflicted_files(stdout)` after the `git diff
    --name-only --diff-filter=U` shell-out.
  - `vcs_has_local_changes` → call `parse_git_local_changes(stdout)`
    and re-attach the `(True, ...)` success flag the public contract
    promises.
- Public return shapes must be preserved exactly:
  - `vcs_diff_name_status` → `list[tuple[str, str]]`;
  - `vcs_get_branch_name` → `(True, None)` for detached HEAD;
  - `vcs_get_workspace_name` → remote URL priority and root fallback;
  - `vcs_get_conflicted_files` → `[]` on command failure;
  - `vcs_has_local_changes` → `(True, None)` for clean,
    `(True, text)` for dirty.
- Run focused VCS tests under both backends (default Python and
  `SASE_CORE_BACKEND=rust` once the extension is installed). The
  affected test files are `tests/ace/deltas/test_diff_name_status_git.py`,
  `tests/test_vcs_provider_git_query.py`, and
  `tests/test_vcs_provider_git_sync.py` (only the conflicted-file path
  routes here in Phase 5E; the sync mutation surface stays Python).
- Re-run `just bench-git-query-ops` and record Python-facade,
  Rust-facade, and dual-run numbers in
  `plans/202604/perf_artifacts/bench_git_query_ops_phase5e.json` for
  the Phase 5F close-out.
- Do not alter the dispatch wiring introduced here unless Phase 5E
  surfaces a missing edge case in the facade contract; any such change
  must come with a matching edit in
  `tests/test_core_git_query.py` so the dispatch tests fail before the
  Git provider does.
