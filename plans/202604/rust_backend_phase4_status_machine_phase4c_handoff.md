---
create_time: 2026-04-29 13:28:30
bead_id: sase-19.3
status: complete
---
# Rust Backend Phase 4C Handoff: Pure Rust Status Module and PyO3 Bindings

## Scope

Phase 4C ports the pure status decision logic into `../sase-core` and
exposes it through the existing `sase_core_rs` PyO3 module. **No
production Python caller is routed through Rust yet** — that is Phase 4D
(line helpers) and Phase 4E (planner). The wire contract was frozen by
Phase 4B in `src/sase/core/status_wire.py`; this phase mirrors it on the
Rust side.

## What landed

### Rust pure crate (`crates/sase_core/src/status/`)

New module split into one file per concern, mirroring the Python
`status_state_machine` package layout:

- `wire.rs` — serde-compatible structs for `StatusTransitionRequestWire`,
  `StatusTransitionPlanWire`, `ChangespecChildWire`, `StatusFieldReadWire`,
  and `StatusFieldUpdateWire`. Schema-version constants and action-string
  enumerations (`SUFFIX_ACTION_*`, `MENTOR_ACTION_*`, `ARCHIVE_ACTION_*`)
  match the Python literals exactly. `status_request_from_json_value` and
  `status_plan_from_json_value` validate the schema version with the same
  `"status wire schema mismatch: got X, expected Y"` message format
  Python uses.
- `constants.rs` — `VALID_STATUSES`, `ARCHIVE_STATUSES`, the transition
  table, `is_valid_transition`, and `remove_workspace_suffix`. The
  workspace-suffix regex (`r" \([a-zA-Z0-9_-]+_\d+\)$"`) and legacy READY
  TO MAIL regex (`r" - \(!: READY TO MAIL\)$"`) are lazily compiled via
  `OnceLock`. `remove_workspace_suffix` deliberately does **not** trim
  the result — matches the Python helper byte-for-byte (note: this is
  separate from `query::matchers::get_base_status`, which does trim, and
  the two helpers have separate Python sources for the same reason).
- `name.rs` — `has_suffix` and `get_next_suffix_number`. The legacy
  double-underscore namespace (`<base>__<N>`) is reserved alongside the
  current single-underscore one, so the lowest-free-suffix search skips
  any N where either form exists. `strip_reverted_suffix` is reused from
  `crate::query::matchers` rather than duplicated.
- `field_updates.rs` — `read_status_from_lines` and `apply_status_update`.
  Both work on `&[String]` slices of project-file lines and are pure
  side-effect-free helpers. `apply_status_update` returns the rewritten
  file as a single owned `String` so the host can pass it straight into
  its existing atomic-write path.
- `planner.rs` — `plan_status_transition`, the pure decision engine.
  Mirrors `plan_status_transition_python` in
  `sase_100/src/sase/core/status_wire_conversion.py` branch-for-branch:
  - Ready → Draft (blocking-children check, validate, suffix append,
    mentor draft set);
  - WIP → Draft (validate-only);
  - Reverted / Archived (own branches, validate-only);
  - generic "ready" branch (parent constraint, validate, sibling-
    unreverted-children check, suffix strip, mentor clear on
    Draft → Ready).
  Error strings are byte-for-byte equal to the Python rejection messages,
  including the Python list-repr for the allowed-transitions tail
  (`['Mailed', 'Draft']` / `[]`). Schema-version mismatches surface as
  `Err(String)` so the PyO3 binding can map them to `ValueError`.

The crate root `lib.rs` re-exports the new module's public surface and
the new module is wired through `pub mod status;`. The pure crate keeps
its existing serde/regex-only dependency footprint — no PyO3 leaks.

### Rust unit tests

48 new module tests across the four submodules, mirroring the Python
golden corpus in `tests/test_core_status_wire.py` and
`tests/test_core_status_lines.py`. Coverage includes:

- valid/invalid transitions under `validate=True` and the `validate=False`
  archive-restore escape hatch;
- workspace-suffix and legacy READY TO MAIL stripping (via the planner
  *and* directly through `remove_workspace_suffix`);
- WIP → Draft (no suffix, no mentor);
- Ready → Draft (suffix append, mentor set, blocking-children rejection,
  lowest-free-suffix selection that reserves the legacy `__<N>` slot);
- WIP/Draft → Ready (suffix strip, sibling-unreverted-children rejection,
  Draft → Ready mentor clear);
- parent-constraint enforcement for the generic "ready" branch and the
  Reverted-branch escape;
- terminal statuses (Reverted / Archived / Submitted) reject further
  transitions;
- archive-action classification (`to_archive`, `from_archive`, `none` for
  same-class transitions);
- JSON round-trip parity for both wire records and a `null`-shape check
  on the plan record's optional fields;
- the verbatim invalid-transition error string format used by Phase 4B's
  parity tests.

### PyO3 bindings (`crates/sase_core_py/src/lib.rs`)

Five new functions on the existing `sase_core_rs` module:

- `remove_workspace_suffix(status: str) -> str`
- `is_valid_status_transition(from_status: str, to_status: str) -> bool`
- `read_status_from_lines(lines: list[str], changespec_name: str) -> str | None`
- `apply_status_update(lines: list[str], changespec_name: str, new_status: str) -> str`
- `plan_status_transition(request: dict) -> dict`

All inputs/outputs are plain Python primitives matching the wire shapes,
so the Phase 4D adapter can rehydrate a returned plan via
`status_plan_from_dict` without a custom JSON re-encode step. Schema
mismatches and structurally invalid request dicts surface as
`ValueError`. The existing `py_to_json_value` helper grew tuple support
so callers can pass the wire dataclasses' tuple fields (e.g.
`existing_names`) without converting through `json.dumps`/`loads` first.

These functions are **not** registered on `status_facade.py` yet — that
is Phase 4D.

### Documentation

`README.md` in `../sase-core` is unchanged in this phase; the Phase 4
roadmap section will be updated alongside the Phase 4D facade
registration so the docs reflect the actually-routed surface.

## What did not change

- `sase_100/src/sase/core/status_facade.py` — still routes everything to
  Python.
- `sase_100/src/sase/core/status_wire.py` /
  `sase_100/src/sase/core/status_wire_conversion.py` — Phase 4B contract
  unchanged.
- Default backend stays `python`. `SASE_CORE_BACKEND=rust` does not yet
  pick up any of the new bindings.
- No `sase_100/tests/` golden update.

## Files added (in `../sase-core`)

- `crates/sase_core/src/status/mod.rs`
- `crates/sase_core/src/status/wire.rs`
- `crates/sase_core/src/status/constants.rs`
- `crates/sase_core/src/status/name.rs`
- `crates/sase_core/src/status/field_updates.rs`
- `crates/sase_core/src/status/planner.rs`

## Files changed (in `../sase-core`)

- `crates/sase_core/src/lib.rs` — adds `pub mod status;` and re-exports.
- `crates/sase_core_py/src/lib.rs` — five new `#[pyfunction]`s registered
  on the `sase_core_rs` module; module-level docstring updated; tuple
  support added to `py_to_json_value` so request dicts with tuple fields
  decode without a JSON round-trip.

## Files added/changed in `sase_100`

- `plans/202604/rust_backend_phase4_status_machine_phase4c_handoff.md`
  (this file).

## Commands run

```bash
# In ../sase-core:
cargo build -p sase_core
cargo test -p sase_core status::         # 48 passed
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
cargo test --workspace                   # all suites green

# In sase_100:
just install
just rust-install                        # maturin develop --release
.venv/bin/pytest tests/test_status_state_machine_constants.py \
  tests/test_status_state_machine_field_updates.py \
  tests/test_status_state_machine_transitions.py \
  tests/test_core_backend.py \
  tests/test_core_dual_run.py \
  tests/test_core_status_wire.py \
  tests/test_core_status_lines.py        # 97 passed
```

A direct Python-vs-Rust parity sweep (driven from `sase_100/.venv`) ran
14 representative request shapes — including invalid transitions,
workspace-suffix and legacy READY TO MAIL inputs, parent-constraint
rejections, terminal statuses, suffix append + lowest-free-N, suffix
strip, and sibling-unreverted-children rejection — and confirmed
byte-identical plans for every case (mismatch count = 0).

## Hand-off to Phase 4D

The Phase 4D agent should:

1. Register the new Rust helpers on the facade in
   `src/sase/core/status_facade.py`. Suggested operation names:
   `read_status_from_lines`, `apply_status_update`,
   `is_valid_status_transition`, and `plan_status_transition`. The
   binding accepts/returns the same dict shapes as
   `status_wire_to_json_dict` produces, so the adapter can call
   `status_plan_from_dict` to rehydrate.
2. Route only the **line helpers** (`read_status_from_lines`,
   `apply_status_update`) under `SASE_CORE_BACKEND=rust` for now —
   `plan_status_transition` is the Phase 4E integration target.
3. Wire dual-run logging via the existing `core_dual_run.jsonl` channel
   and add tests that fake a `sase_core_rs` module exposing the new
   functions, plus a real-extension parity test that skips cleanly when
   the binding is missing.
4. Keep the Python implementation as the in-process fallback for any
   helper classified as "intentionally unported" — none of the helpers
   added in 4C should fall into that bucket given they are now shipped
   in Rust.

The Rust-side schema mismatch surfaces as `ValueError("status wire
schema mismatch: got X, expected Y")` — identical wording to the Python
helper, so existing tests that match on `"schema mismatch"` keep working
with either backend.

## Notes for follow-ups

- The PyO3 binding releases the GIL only where it actually matters; none
  of these functions are hot enough to warrant `py.allow_threads(...)`,
  so they hold it. If a future profiling pass shows the planner is
  spilling into a tight Python loop, revisit.
- The lowest-free-suffix search in `name::get_next_suffix_number` is
  linear in N. Real ChangeSpec name sets are tiny so this is fine; if a
  benchmark shows the linear search dominating in a synthetic workload,
  the Python helper has the same shape and both should change together.
- `ARCHIVE_STATUSES` is duplicated as a Rust `&[&str]` and a Python
  `frozenset`. Phase 4D's facade registration should expose just the
  `is_valid_status_transition` helper to Python — no need to re-export
  the constant set.
- The Python helper formats the allowed-transitions tail using Python's
  list `repr` (`['Mailed', 'Draft']`). The Rust planner reproduces this
  via `format!("[{inner}]")`. If a future status appears whose name
  contains a single quote, both implementations would need updating
  together — none of the current statuses do.
