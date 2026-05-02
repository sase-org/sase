---
create_time: 2026-04-29 15:00:00
bead_id: sase-1a.3
status: complete
---
# Rust Backend Phase 5C Handoff: Rust Pure Git Parser Module and PyO3 Bindings

## Scope

Phase 5C ports the five deterministic Git query parsers pinned by
Phase 5B into `../sase-core` and exposes them through the existing
`sase_core_rs` PyO3 module. **No production Python caller is routed
through Rust yet** — that is Phase 5D (facade dispatcher registration)
and Phase 5E (Git provider integration). The wire contract was frozen
by Phase 5B in `src/sase/core/git_query_wire.py`; this phase mirrors it
on the Rust side and pins the parser semantics with Rust-only golden
tests.

## What landed

### Rust pure crate (`crates/sase_core/src/git_query/`)

New module split into one file per concern, mirroring the Python
`sase.core.git_query_*` modules:

- `wire.rs` — `GitNameStatusEntryWire` (serde-compatible struct with
  `status: String`, `path: String`) plus
  `GIT_QUERY_WIRE_SCHEMA_VERSION = 1`. Field declaration order matches
  the Python dataclass so JSON output is byte-for-byte identical. The
  remaining Phase 5 parsers cross the wire as primitives
  (`Option<String>`, `Vec<String>`) and need no struct.
- `parsers.rs` — pure-function ports of the five Phase 5B helpers:
  - `parse_git_name_status_z(stdout: &str) -> Vec<GitNameStatusEntryWire>`
  - `parse_git_branch_name(stdout: &str) -> Option<String>`
  - `derive_git_workspace_name(remote_url: Option<&str>, root_path: Option<&str>) -> Option<String>`
  - `parse_git_conflicted_files(stdout: &str) -> Vec<String>`
  - `parse_git_local_changes(stdout: &str) -> Option<String>`

  All inline `#[cfg(test)] mod tests` cases mirror
  `sase_100/tests/test_core_git_query.py` byte-for-byte (rename/copy
  ``"<old>\t<new>"`` encoding, detached-HEAD sentinel, remote-vs-root
  priority, blank-line stripping for conflicted files, clean-vs-dirty
  porcelain normalization, trailing-NUL tolerance, truncated-rename
  fall-through to single-path entry). No `git` invocation, no `.git`
  introspection, no filesystem access.
- `mod.rs` — re-exports the parsers, `GitNameStatusEntryWire`, and the
  schema version. Wired into `crates/sase_core/src/lib.rs` alongside
  the existing `agent_scan` / `query` / `status` modules.

### Parity tests (`crates/sase_core/tests/git_query_parity.rs`)

Standalone integration test that mirrors every case in
`sase_100/tests/test_core_git_query.py`. Adding the test file here
(rather than relying solely on the inline unit tests) keeps the
fixture inputs/expected outputs visible at the parity-gate layer the
agent-scan and golden-corpus suites already use, so a Phase 5B test
edit fails the Rust side first. Two extra cases pin the Rust JSON
shape:

- `git_name_status_entry_wire_serializes_to_python_shape` — `serde_json`
  output equals `{"status": ..., "path": ...}` (the same dict shape the
  Python facade rehydrates via `git_name_status_entry_from_dict`).
- `git_name_status_entry_wire_round_trips_through_json` — the wire
  struct round-trips through `serde_json::Value`.

### PyO3 bindings (`crates/sase_core_py/src/lib.rs`)

Five new functions registered on the `sase_core_rs` module. Names match
the Python facade exactly so Phase 5D can register them as
``rust_impl`` callbacks one-for-one with no rename layer.

| Python binding                  | Returns                       |
| ------------------------------- | ----------------------------- |
| `parse_git_name_status_z`       | `list[dict]` (`{status,path}`)|
| `parse_git_branch_name`         | `str` or `None`               |
| `derive_git_workspace_name`     | `str` or `None`               |
| `parse_git_conflicted_files`    | `list[str]`                   |
| `parse_git_local_changes`       | `str` or `None`               |

`parse_git_name_status_z` returns plain `dict` objects (not the Phase 4
`PyDict::set_item` JSON round-trip used for `ChangeSpecWire`) because
the wire only has two fields — going through `serde_json` would add
an unnecessary translation. The Phase 5D facade will rehydrate each
dict via `git_name_status_entry_from_dict` and flatten back to
`list[tuple[str, str]]` so existing call sites keep their legacy shape.

The module-level docstring on `sase_core_py/src/lib.rs` was extended
to list the new bindings alongside the Phase 1–4 entries.

## Wire Contract (matches Phase 5B byte-for-byte)

`GIT_QUERY_WIRE_SCHEMA_VERSION = 1` on both sides. The Rust struct is
field-for-field identical to the Python dataclass:

```rust
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GitNameStatusEntryWire {
    pub status: String,
    pub path: String,
}
```

Pinned semantics that the Rust port must match (and the parity tests
guarantee):

- `parse_git_name_status_z` tolerates trailing NUL terminators, skips
  empty status tokens, and silently drops trailing entries with no
  following path. Rename/copy entries are encoded as
  ``f"{old}\t{new}"`` for the path field. A truncated rename with one
  path falls through to the single-path branch.
- `parse_git_branch_name` returns `None` for empty stdout *and* the
  literal `"HEAD"` sentinel.
- `derive_git_workspace_name` strips a single trailing `.git` suffix
  and uses `rsplit_once('/')` for the basename so SSH-style and
  path-like remotes parse identically. Remote URL takes priority over
  root path; the root fallback is consulted when the remote is
  empty/`None` *or* strips down to an empty name (e.g. the
  pathological `".git"` input).
- `parse_git_conflicted_files` drops blank/whitespace-only lines but
  preserves order. `parse_git_local_changes` returns `None` on
  whitespace-only input and the stripped text otherwise.

## Out of Scope (Phase 5C)

- No `sase_core_rs` import added to `sase.core.git_query_facade`.
  Phase 5D registers `rust_impl` callbacks via
  `sase.core.backend.dispatch` once these bindings exist. The Python
  facade already has the right call-site shape.
- No call-site changes in `GitQueryOpsMixin`. Phase 5E swaps the
  inline parsing for facade calls with parity tests across both
  backends.
- No benchmark updates. Phase 5E re-runs the Phase 5A harness with
  Python-facade, Rust-facade, and dual-run numbers to feed the Phase
  5F default-backend decision.

## Verification

- `cargo fmt --all -- --check` — clean.
- `cargo clippy --workspace --all-targets -- -D warnings` — clean.
- `cargo test --workspace` — 33 unit/integration tests pass in
  `git_query::parsers::tests` and `git_query_parity.rs`; the rest of
  the suite (Phase 1–4) still passes unchanged.
- `just install` and `just rust-install` — wheel builds and installs
  into `.venv` cleanly under CPython 3.14.
- Smoke import from `sase_core_rs`:

  ```text
  parse_git_name_status_z('M\0a.py\0R100\0old.py\0new.py\0')
    → [{'status': 'M', 'path': 'a.py'},
       {'status': 'R100', 'path': 'old.py\tnew.py'}]
  parse_git_branch_name('HEAD\n') → None
  parse_git_branch_name('feature-x\n') → 'feature-x'
  derive_git_workspace_name('https://github.com/sase-org/sase_100.git', None) → 'sase_100'
  derive_git_workspace_name(None, '/tmp/foo') → 'foo'
  parse_git_conflicted_files('a.py\n\nb.py\n') → ['a.py', 'b.py']
  parse_git_local_changes('') → None
  parse_git_local_changes('M src/a.py\n') → 'M src/a.py'
  ```

- `just check` — green (fmt, lint, mypy, pyvision, tests).

## Hand-off Notes for Phase 5D

- Register the five `sase_core_rs` callables as `rust_impl` callbacks
  on `sase.core.backend.dispatch` from inside
  `sase.core.git_query_facade`. The dispatch entry should classify
  these helpers as **shipped** Rust operations (matching the Phase 4
  status helpers): under `SASE_CORE_BACKEND=rust` a missing binding
  must raise `RustBackendUnavailableError`, not silently fall back.
- The PyO3 binding for `parse_git_name_status_z` already returns the
  exact dict shape Python expects (`{"status": str, "path": str}`).
  Rehydrate each dict with `git_name_status_entry_from_dict` and
  flatten with `[(e.status, e.path) for e in entries]` so the public
  facade keeps returning `list[tuple[str, str]]`.
- For dual-run, the comparison key is the flat tuple shape for
  `parse_git_name_status_z`, primitives for the other four. Use the
  existing dual-run harness from Phase 4D — no new wire serializer is
  needed.
- Add `pytest.importorskip("sase_core_rs")` parity tests that exercise
  each binding against the same fixtures as
  `tests/test_core_git_query.py`. Skipping is the right call here so
  pure-Python CI keeps passing.
- `GitQueryOpsMixin` should stay untouched until Phase 5E. Phase 5D's
  scope is the dispatcher registration plus dual-run/parity tests.
