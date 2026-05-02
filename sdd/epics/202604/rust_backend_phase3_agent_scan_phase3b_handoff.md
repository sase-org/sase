---
create_time: 2026-04-29
status: done
bead_id: sase-18.2
---

# Rust Backend Phase 3B — Pure-Rust Snapshot Scanner

Closes the Phase 3B subphase of
`plans/202604/rust_backend_phase3_agent_scan.md`. This document records
what landed in `../sase-core` and what Phase 3C must wire up on the
Python side.

## What landed

| Area              | File / module                                                   |
| ----------------- | --------------------------------------------------------------- |
| Wire types (Rust) | `../sase-core/crates/sase_core/src/agent_scan/wire.rs`          |
| Scanner           | `../sase-core/crates/sase_core/src/agent_scan/scanner.rs`       |
| Module re-exports | `../sase-core/crates/sase_core/src/agent_scan/mod.rs`           |
| Crate re-exports  | `../sase-core/crates/sase_core/src/lib.rs`                      |
| Parity tests      | `../sase-core/crates/sase_core/tests/agent_scan_parity.rs`      |
| Docs              | `../sase-core/README.md`                                        |

`Cargo.toml` gains a `tempfile` dev-dependency for the parity-test
fixture builder; no new runtime dependencies were added (pure
`std::fs` + `serde_json`). No PyO3 wiring landed in 3B — that is
Phase 3C's job.

## Wire shape

`AgentArtifactScanWire` and the eleven nested wire records in
`agent_scan/wire.rs` mirror
`sase_100/src/sase/core/agent_scan_wire.py` 1:1 (same field names, same
declaration order, same defaults). `AGENT_SCAN_WIRE_SCHEMA_VERSION = 1`
matches the Python constant. The four workflow-directory constant
arrays (`DONE_WORKFLOW_DIR_NAMES`,
`DONE_WORKFLOW_DIR_PREFIXES`, `WORKFLOW_STATE_DIR_NAMES`,
`WORKFLOW_STATE_DIR_PREFIXES`) are exposed as `&'static [&str]` so
Phase 3C can verify they agree between Python and Rust.

The scanner uses `serde_json::Map<String, Value>` for the arbitrary-JSON
fields (`step_output`, `output`) and `BTreeMap<String, String>` for the
typed `output_types` field. Both round-trip through
`serde_json::to_value` / `from_value` without surprises.

## Behavior

`scan_agent_artifacts(projects_root: &Path, options) -> AgentArtifactScanWire`
walks the artifact tree the Python facade walks, with the same soft-error
contract:

- Missing root → empty snapshot, all stats zero.
- `read_dir` failures other than `NotFound` → `os_errors += 1`.
- `serde_json::from_slice` failures → `json_decode_errors += 1`.
- JSON files whose top level is not an object → `json_decode_errors += 1`
  (matches the Python `isinstance(data, dict)` guard).
- `done.json` exists but is unreadable → record carries
  `has_done_marker = true` AND `done = Some(DoneMarkerWire::default())`,
  matching the Python facade's "expose default DoneMarker so the boolean
  truthiness of `record.done` agrees with file presence" rule.

Scan ordering: `read_dir` results are sorted by file name at every level,
then records are sorted by
`(project_name, workflow_dir_name, timestamp)` once at the end. The
walk order already matches; the final sort is a cheap insurance against
future refactors that introduce internal parallelism.

Coercion helpers mirror the Python facade's:

- `coerce_int` / `coerce_float`: reject `bool` (Python's `bool` subclass
  guard), accept ints / floats / parseable strings.
- `coerce_strict_int`: exactly one site (`retry_attempt`) accepts only
  real `int` values, matching the Python field type annotation.
- `coerce_bool_truthy`: Python `bool(x)` semantics (truthy non-empty
  collections / non-zero numbers / non-empty strings count as true).
- `coerce_str_str_map`: filters non-string values, returns `None` when
  the resulting map is empty, matching `_coerce_str_str_dict`.

Snippet truncation matches `Path.read_text(...)[:max_bytes].strip()`:
the Rust implementation truncates by **bytes** (UTF-8 boundary safe) and
then trims whitespace.

## Tests

`tests/agent_scan_parity.rs` materializes the same synthetic tree
`sase_100/tests/agent_scan_golden/fixture_builder.py` writes (same
timestamps, same JSON payloads, same intentional decode errors) and
asserts the same record/stats expectations
`sase_100/tests/test_core_agent_scan.py` pins on the Python facade. 19
test functions cover:

- one-record-per-artifact-dir invariant + schema/projects-root pinning
- deterministic record sort
- decode-error / OS-error / projects-visited / artifact-dirs-visited /
  prompt-step-parsed counters
- per-fixture record assertions (running, done, failed, retry parent +
  child, home-mode running, workflow root + steps, mentor-prefix done,
  malformed waiting, malformed agent_meta)
- options behavior (`only_workflow_dirs`, `include_prompt_step_markers`,
  `include_raw_prompt_snippets`, `max_prompt_snippet_bytes`)
- options round-trip through the snapshot
- empty-snapshot for missing root
- top-level JSON serialization shape

The fixture is built programmatically rather than copied so this crate
stays self-contained — no Python toolchain needed to run `cargo test`.
The constants comment notes that updates to the Python fixture must be
mirrored here.

## Verification performed

```bash
cd ../sase-core
cargo fmt --all -- --check          # clean (stable channel; nightly-only opts ignored)
cargo clippy --workspace --all-targets -- -D warnings   # clean
cargo test --workspace              # 143 tests pass (19 new + 124 pre-existing)
```

## Open questions handed to Phase 3C

1. **Glob vs. directory scan for `prompt_step_*.json`** — handed off
   as-is from the Phase 3A note. The Rust scanner currently uses a single
   `read_dir` per artifact dir and filters by name prefix/suffix, which
   is the cheaper "process each directory's entries once" shape the
   Phase 3A note suggested. Phase 3C just needs to confirm the Python
   facade and the Rust scanner agree on the filename match (they do for
   the corpus, but a `prompt_step.json` without the trailing
   underscore-and-suffix would be excluded by the Rust prefix check —
   leave the corpus pinned).
2. **`only_workflow_dirs` semantics** — Phase 3A's Python facade
   short-circuits before iterating timestamp dirs when an
   `only_workflow_dirs` filter excludes a family. The Rust scanner does
   the same. The semantics chosen are: when the filter is non-empty,
   honor it exactly (do **not** fall back to the
   `is_supported_workflow_dir` check). This matches Phase 3A exactly.
3. **Streaming** — out of scope. Phase 3G decides; Phase 3C should keep
   the snapshot API.
4. **Parallelism** — out of scope. Phase 3B keeps the walker
   single-threaded and deterministic. Internal `rayon` parallelism can
   be added later without changing the wire because the final sort is
   already in place.

## What Phase 3C should do first

- Add a PyO3 function in `crates/sase_core_py/src/lib.rs`:

  ```rust
  fn scan_agent_artifacts(
      py: Python<'_>,
      projects_root: &str,
      options: Option<&PyDict>,
  ) -> PyResult<PyObject>
  ```

  release the GIL while calling
  `sase_core::agent_scan::scan_agent_artifacts`, then convert the
  returned `AgentArtifactScanWire` to plain Python `dict`/`list`/
  primitive values (the same shape `agent_scan_wire_to_json_dict`
  produces).
- Register the Rust impl in `sase.core.agent_scan_facade` only when
  `sase_core_rs` exposes `scan_agent_artifacts`.
- Use the existing Phase 3A parity tests (`tests/test_core_agent_scan.py`
  with `SASE_CORE_BACKEND=rust` / `SASE_CORE_DUAL_RUN=1`) as the gate.

The Rust wire and the Python wire produce identical JSON when serialized
through `serde_json::to_value` / `dataclasses.asdict` respectively, so
the Phase 3C dual-run comparator can diff snapshots directly.
