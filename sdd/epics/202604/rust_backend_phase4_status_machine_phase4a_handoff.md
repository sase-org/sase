---
create_time: 2026-04-29
status: done
bead_id: sase-19.1
---

# Rust Backend Phase 4A — Profiling and Scope Decision

Closes Phase 4A of `plans/202604/rust_backend_phase4_status_machine.md`.
Lands a focused status state machine benchmark, records timings against
the Python backend (and routed-through-Rust where applicable), compares
the result against the dominant Phase 3 refresh cost, and proposes the
Rust API surface for Phase 4B–4E.

## Decision: PROCEED with Phase 4 at reduced scope, motivated by shared-core hygiene rather than raw speed.

The status state machine's pure decision logic costs **single-digit
microseconds** per call and the line-based helpers cost **<300 µs** even
on a 200-spec synthetic project file. The whole orchestrator is
dominated by side effects (`parse_project_file`, `find_all_changespecs`,
file lock, atomic write, timestamp recording) that Phase 4 explicitly
keeps in Python. A Rust port will not move user-perceived latency.

However, Phase 4 should still land for the reasons the plan calls out
in `## Goal`:

- it locks down a stable cross-language wire contract for a state
  machine (not just data parsing), exercising the pattern we will need
  for any future Rust-side ChangeSpec mutation work;
- it brings the validation/decision rules into the same shared-core
  module that other Rust callers (`sase-core`, future plugins) can
  consume directly without re-implementing the rules in Rust;
- it removes a class of drift bugs where Python and Rust disagree on
  what a "valid" transition is.

The performance bar to clear is therefore **parity, not speedup**.
Phase 4F should not measure success in milliseconds saved.

If the team's bottleneck is user-perceived latency, the next-highest
leverage is still **agent-scan cold cost on the home project**, which
Phase 3H measured at ~817 ms (Rust facade) on the real
`~/.sase/projects` tree. Status transitions are not on that critical
path.

## Workstation and environment

- Host: `athena` (Linux 6.12, x86_64)
- CPU: AMD Ryzen Threadripper 3970X 32-Core
- Python: 3.14.3 (default `.venv`)
- Rust extension: `sase_core_rs` built via `just rust-install`
  (PyO3 0.22, release profile)
- `SASE_CORE_BACKEND=rust` available; no Rust impl registered for any
  status-facade operation today, so the "rust" rows below exercise the
  dispatcher fallback to Python (`rust_unavailable="python"`).

Benchmark script: `tests/perf/bench_status_state_machine.py`
(`just bench-status-state-machine`). Raw report:
`plans/202604/perf_artifacts/bench_status_state_machine_phase4a.json`.
Phase 3 recap: `plans/202604/perf_artifacts/bench_agent_scan_phase4a_recap.json`.

Commands to reproduce:

```bash
just install
just rust-install
just bench-status-state-machine \
  --runs 200 --warmup 30 --num-specs 200 --transition-runs 30 \
  --output plans/202604/perf_artifacts/bench_status_state_machine_phase4a.json
just bench-agent-scan \
  --projects 4 --per-project 40 --runs 5 --warmup 2 \
  --output plans/202604/perf_artifacts/bench_agent_scan_phase4a_recap.json
```

## Bench evidence

Median values; see the JSON artifacts for min/p95/max and sample sizes.

### Pure helpers — golden corpus (`tests/core_golden/myproj.gp`, 1019 bytes, 4 specs)

| scenario                  | python       | rust-backend |
| ------------------------- | ------------ | ------------ |
| `is_valid_transition`     |  3.4 µs      | n/a (1)      |
| `remove_workspace_suffix` |  1.1 µs      | n/a (1)      |
| `read_status_from_lines`  |  2.5 µs      |  2.5 µs      |
| `apply_status_update`     |  4.2 µs      |  4.2 µs      |

(1) Not currently routed through `sase.core.dispatch`; Phase 4D should
register them.

### Pure helpers — synthetic 200 specs (128 808 bytes)

| scenario                  | python       | rust-backend |
| ------------------------- | ------------ | ------------ |
| `is_valid_transition`     |  3.4 µs      | n/a          |
| `remove_workspace_suffix` |  1.1 µs      | n/a          |
| `read_status_from_lines`  |  179 µs      |  185 µs      |
| `apply_status_update`     |  254 µs      |  254 µs      |

`read_status_from_lines` and `apply_status_update` walk the line list
linearly; they hit the worst case here (target = last spec). The
"rust-backend" column matches Python because the dispatcher falls
back to Python while no Rust impl is registered. The match is the
intended baseline for Phase 4D/4E parity logging.

### Transition orchestrator — golden corpus

| scenario                                    | python  | rust-backend |
| ------------------------------------------- | ------- | ------------ |
| `transition_changespec_status` (WIP→Draft)  | 215 µs  | 225 µs       |
| `transition_changespec_status` (WIP→Ready)  | 371 µs  | 368 µs       |

WIP→Ready costs more than WIP→Draft because `handle_ready_transition`
parses the project file (parent-constraint check) and the orchestrator
records a TIMESTAMPS entry that requires a second locked write.

### Transition orchestrator — synthetic 200 specs

| scenario                                    | python    | rust-backend |
| ------------------------------------------- | --------- | ------------ |
| `transition_changespec_status` (WIP→Draft)  | 1.71 ms   | 1.67 ms      |
| `transition_changespec_status` (WIP→Ready)  | 12.50 ms  | 12.48 ms     |

The synthetic name avoids
`sase.core.changespec.has_suffix` (`"spec-N"` with a hyphen) so the
`handle_suffix_strip` / `revert_sibling_draft_changespecs` path does
not fire. The 12.5 ms WIP→Ready cost is dominated by:

- `parse_project_file` (parent-constraint check): linear scan + parse;
- `find_all_changespecs` (called from the WIP→Draft draft handler;
  unrelated here but timed in WIP→Draft);
- two locked `write_changespec_atomic` calls (status update +
  TIMESTAMPS entry);
- the `apply_status_update` line walk (~254 µs).

The pure decision component (validation + planning) is **<10 µs** of
that 12.5 ms — well under 0.1 % of the wall clock.

### Phase 3 recap — agent-scan still dominates refresh cost

Synthetic 4 projects × 40 artifacts = 160 records:

| scenario                  | median ms |
| ------------------------- | --------- |
| `scan_python_facade`      | 20.1 ms   |
| `scan_python_facade_no_prompt_steps` | 14.0 ms |
| `scan_rust_facade`        | 13.6 ms   |
| `find_named_agent`        | 187 ms    |
| `tui_artifact_load`       | 0.20 ms   |

Even at this small workload the agent-scan facade is ~1.5× more
expensive than the worst status transition; on Phase 3H's
`~/.sase/projects` workload the gap is roughly two orders of
magnitude. Status state machine cost is not on the dominant
refresh path.

## Scoping for Phase 4

The Phase 4 plan already separates "pure decision logic" from
"side effects with host services." The benchmark confirms the cut: keep
**all** of the side-effect surface (lock acquisition, atomic write,
timestamp recording, archive moves, mentor-flag mutation, suffix
branch rename, sibling reverts, VCS) on the Python side. There is no
performance reason to move any of it.

### Recommended Rust API surface for Phase 4B–4E

These are the operations Phase 4C should implement in
`../sase-core/crates/sase_core/src/status/` and Phase 4D/4E should
register on `sase.core.status_facade`:

1. `is_valid_status_transition(from_status: str, to_status: str) -> bool`
   — matches `sase.status_state_machine.constants.is_valid_transition`,
   including workspace-suffix stripping. Pure.
2. `remove_workspace_suffix(status: str) -> str` — pure regex helper.
   Optional from a routing standpoint but useful as a debug/test entry
   point.
3. `read_status_from_lines(lines: list[str], changespec_name: str) -> str | None`
   — already on the facade. Phase 4D wires the Rust impl.
4. `apply_status_update(lines: list[str], changespec_name: str, new_status: str) -> str`
   — already on the facade. Phase 4D wires the Rust impl.
5. `plan_status_transition(request: StatusTransitionRequestWire) -> StatusTransitionPlanWire`
   — new operation introduced by Phase 4B. Pure decision: validates the
   transition, classifies suffix action (`none` / `strip` / `append`),
   classifies archive movement (`none` / `to_archive` / `from_archive`),
   indicates mentor-flag intent (`none` / `set_draft` / `clear_draft`),
   and emits a structured `StatusTransitionPlanWire` that Python then
   executes. Phase 4E routes the planner step of
   `transition_changespec_status_python` through this entry point.

### Out of scope (do not port to Rust in Phase 4)

- `transition_changespec_status` orchestrator (it owns lock + writes).
- `handle_*_transition` handlers (they call into Python parsers,
  mentor mutators, archive movers, and timestamp recorders).
- `revert_sibling_draft_changespecs` (calls `revert_changespec`, which
  invokes VCS).
- `handle_suffix_strip` / `handle_suffix_append` (subprocess git ops).
- `_apply_cl_update`, `_apply_parent_update`, `_apply_bug_update`,
  `_apply_description_update` and other field updates not in the status
  state machine itself; Phase 4 should stay focused on STATUS.

### Wire contract notes for Phase 4B

- Inputs Python must gather *before* calling Rust (so Rust stays
  side-effect free):
  - current status of the changespec (already known from
    `read_status_from_lines`);
  - target status;
  - changespec name + suffix facts (`has_suffix`,
    `strip_reverted_suffix`);
  - parent record's status (from `parse_project_file`);
  - sibling summary used by
    `check_siblings_for_unreverted_children` (sibling name + status +
    children-status flags). Compute this in Python because
    `find_all_changespecs()` and `parse_project_file()` are how we get
    sibling and parent state today.
  - `validate` flag.
- The Rust planner returns a structured plan; Python interprets it:
  - whether to write the new STATUS line (always yes on success, but
    the plan should still emit the rewritten content via
    `apply_status_update_rs` so dual-run can compare bytes);
  - suffix action (`none` / `strip` / `append`) plus the resolved name
    pair when applicable;
  - mentor-flag intent (no-op / set-draft / clear-draft);
  - archive-movement classification (`none` / `to_archive` /
    `from_archive`);
  - timestamp event detail string (`"<old> -> <new>"`);
  - error message on failure (matches Python error wording so the
    existing CLI/TUI tests do not need to relax).
- Wire records must be primitives (`str`, `bool`, `int`, `list[str]`,
  `dict[str, ...]`). No `Path`, no `Console`, no callable, no
  `ChangeSpec` object. `validate=False` must be honored verbatim.

### Dual-run caveat

`SASE_CORE_DUAL_RUN=1` for `transition_changespec_status` would run
side effects twice. Phase 4E must compare *plans* (the pure decision
output) before executing side effects exactly once, as the plan calls
out. The dual-run instrumentation already in `sase.core.dual_run` is
fine for the four pure helpers; the planner needs a parity comparison
that runs *before* `handle_*_transition` execution. Phase 4B should
ship a Python `plan_status_transition_python(request)` that mirrors
the current decision behavior so this comparison is well-defined.

## Risks visible from the bench

- **`apply_status_update` allocates a fresh string per call.** At
  254 µs on 128 KB it is the most expensive pure helper. A Rust port
  should keep returning a Python `str`, but copying twice (once to
  Rust, once back) may erase any gain. Phase 4C should benchmark its
  PyO3 binding before claiming any speedup; the gate is parity, not
  speedup.
- **Linear `read_status_from_lines` walk** is unavoidable without an
  index. Do not over-engineer — the current implementation is fine.
- **Test fixtures that synthesize names like `spec_1`** trigger the
  `has_suffix` regex (`^.+_\d+$`) and exercise the sibling-revert
  path even when not intended. Phase 4 tests that mean to exercise
  the suffix path should do so explicitly; tests that don't should
  use names like `spec-1`. The benchmark file documents this.

## Exit criteria check

- A focused status-machine benchmark exists and is wired into the
  Justfile (`just bench-status-state-machine`).
- Pure-decision cost is visible separately from side-effect cost.
- Phase 3 dominant refresh cost is recorded for context.
- Phase 4 scope and Rust API surface are pinned for 4B–4E above.
- Recommendation: proceed with Phase 4 as planned, motivated by
  shared-core hygiene; do not measure success in raw speedup.

## Next phase

Phase 4B (`sase-19.2`) — define the Python wire records
(`StatusTransitionRequestWire`, `StatusTransitionPlanWire`) and
golden parity tests, without routing any production call through
Rust yet. The agent for 4B should read this handoff,
`plans/202604/rust_backend_phase4_status_machine.md`, and
`sdd/research/202604/rust_backend_migration.md` before editing.
