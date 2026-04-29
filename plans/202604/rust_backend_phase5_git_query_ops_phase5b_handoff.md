---
create_time: 2026-04-29 14:30:00
bead_id: sase-1a.2
status: complete
---
# Rust Backend Phase 5B Handoff: Python Facade, Wire Contract, and Golden Tests

## Summary

Phase 5B carved out the stable Python seam for the Git query parser
facade and pinned the contract with a Python-only golden test suite.
The implementation lives entirely on the Python side; no
``sase_core_rs`` import or PyO3 binding is referenced from the new
modules. Phase 5C will mirror this contract in Rust under
``../sase-core`` and expose PyO3 functions; Phase 5D will register
those functions as ``rust_impl`` callbacks via
:func:`sase.core.backend.dispatch`.

## Files Changed (this repo)

- `src/sase/core/git_query_wire.py` (new) — wire records for the Git
  query facade. Currently a single dataclass
  (``GitNameStatusEntryWire``) plus ``GIT_QUERY_WIRE_SCHEMA_VERSION``,
  ``git_query_wire_to_json_dict``, and
  ``git_name_status_entry_from_dict``. Other Phase 5 helpers use
  primitive return types and need no record.
- `src/sase/core/git_query_facade.py` (new) — five pure helpers
  (`parse_git_name_status_z`, `parse_git_branch_name`,
  `derive_git_workspace_name`, `parse_git_conflicted_files`,
  `parse_git_local_changes`). Implementations are Python-only;
  signatures are designed so Phase 5D can plug in a ``rust_impl``
  without changing call sites or return shapes.
- `src/sase/core/__init__.py` — added the new module to the docstring
  module index. No re-exports; callers import the helpers from their
  defining module.
- `tests/test_core_git_query.py` (new) — golden tests for every helper
  including the rename/copy ``"<old>\t<new>"`` paired-path encoding,
  malformed/truncated NUL streams, detached-HEAD branch normalization,
  https/ssh/path-like/no-remote workspace name derivation, the
  remote-vs-root priority order, conflicted-file blank-line stripping,
  and clean-vs-dirty ``git status --porcelain`` normalization.
- `docs/rust_backend.md` — added the new modules to the facade module
  table and recorded the Phase 5B roadmap entry.
- `plans/202604/rust_backend_phase5_git_query_ops_phase5b_handoff.md`
  (this file).

## Wire Contract

The schema version is ``GIT_QUERY_WIRE_SCHEMA_VERSION = 1``.

`GitNameStatusEntryWire` is the only structured record:

```python
@dataclass(frozen=True)
class GitNameStatusEntryWire:
    status: str   # raw token from `git diff -z` ("A", "M", "R100", ...)
    path: str     # "<old>\t<new>" for renames/copies, otherwise a single path
```

The public facade flattens entries back to ``list[tuple[str, str]]`` so
``GitQueryOpsMixin.vcs_diff_name_status`` keeps its current return
shape. Phase 5C will mirror this dataclass with serde-compatible Rust
structs and expose them as plain dicts via PyO3; the facade adapter in
Phase 5D will rehydrate them with ``git_name_status_entry_from_dict``
before flattening.

The remaining four helpers cross the wire as primitives:

- ``parse_git_branch_name(stdout: str) -> str | None``
- ``derive_git_workspace_name(remote_url: str | None, root_path: str | None) -> str | None``
- ``parse_git_conflicted_files(stdout: str) -> list[str]``
- ``parse_git_local_changes(stdout: str) -> str | None``

## Pinned Behavior (highlights)

These properties are now contract and the Rust port must match
byte-for-byte:

- ``parse_git_name_status_z`` tolerates a trailing NUL terminator,
  silently drops trailing entries that are missing required path
  fields, and skips empty status tokens. Rename/copy entries are
  encoded as ``f"{old}\t{new}"`` for the path field.
- ``parse_git_branch_name`` returns ``None`` for both empty stdout and
  the literal ``"HEAD"`` sentinel, matching the Git provider's
  detached-HEAD contract.
- ``derive_git_workspace_name`` strips a single trailing ``.git``
  suffix and uses ``rsplit("/", 1)`` for the basename so SSH-style
  remotes (``git@host:owner/repo.git``) and path-like remotes
  (``/srv/git/repo.git``) parse identically. The remote URL takes
  priority over the root path; the root fallback is only consulted
  when the remote is empty/``None`` *or* strips down to an empty name
  (for example, the pathological ``".git"`` input).
- ``parse_git_conflicted_files`` drops blank/whitespace-only lines but
  preserves order. ``parse_git_local_changes`` returns ``None`` on a
  whitespace-only stdout and the stripped text otherwise.

## Out of Scope (Phase 5B)

- No ``sase_core_rs`` import. Phase 5C lands the Rust module + bindings.
- No call-site changes in ``GitQueryOpsMixin`` — Phase 5E swaps the
  inline parsing for facade calls.
- No backend dispatcher wiring. Phase 5D registers ``rust_impl``
  callbacks once the bindings exist.

## Verification

- `just install` and `just check` were run to confirm the new module
  compiles, tests pass, lint is clean, and mypy is happy.
- ``tests/test_core_git_query.py`` runs as part of the default suite.
  All goldens pass under the Python backend (the only backend that
  exists for this facade today).

## Hand-off Notes for Phase 5C

- Mirror the wire contract under
  ``../sase-core/crates/sase_core/src/git_query/`` (or a similarly
  named module). Use serde-compatible structs that round-trip through
  ``git_query_wire_to_json_dict`` and
  ``git_name_status_entry_from_dict``.
- Expose the five PyO3 functions on ``sase_core_rs`` with the names
  used in :mod:`sase.core.git_query_facade`. Returning Python lists
  of dicts (for name-status) and primitive ``str | None`` /
  ``list[str]`` values for the rest is fine; the facade adapter will
  rehydrate dicts.
- Reuse the Phase 5B test cases as Rust unit/integration fixtures so a
  parity drift fails the Rust-side ``cargo test`` before the Python
  facade ever sees the binding.
- Pure Rust only: no ``git`` invocation, no ``.git`` introspection,
  no filesystem access. The host (Python) keeps every side effect.
