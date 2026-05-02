---
create_time: 2026-04-29 11:50:51
status: done
prompt: sdd/prompts/202604/rust_backend_parse_project_file_fallback.md
---
# Plan: Keep `parse_project_file` usable under `SASE_CORE_BACKEND=rust`

## Root Cause

`sase ace` loads ChangeSpecs through `find_all_changespecs_cached()`, which calls the public
`sase.ace.changespec.parser.parse_project_file()` entry point. That function routes through
`sase.core.parser_facade.parse_project_file()`.

The facade documentation and `docs/rust_backend.md` say `parse_project_file()` is intentionally Python-only: the Rust
parser binding consumes `(file_path, bytes)` through `parse_project_bytes()`, and routing the file-path API through Rust
would require a second disk read or compromise dual-run comparison fidelity.

The implementation still calls the strict `dispatch()` helper without a `rust_impl`. Under `SASE_CORE_BACKEND=rust`,
`dispatch()` correctly raises `RustBackendUnavailableError` for operations that claim to be dispatched but have no Rust
implementation. That strict behavior is valuable for real Rust-eligible operations, but it is the wrong mechanism for
this Python-only compatibility API.

## Approach

1. Change `sase.core.parser_facade.parse_project_file()` so it calls `parse_project_file_python(file_path)` directly
   instead of going through `dispatch()`.
2. Keep strict `dispatch()` semantics unchanged. Operations such as query parsing, status helpers, agent scanning, and
   `parse_project_bytes()` should still raise under `SASE_CORE_BACKEND=rust` when they are genuinely configured for
   backend dispatch but have no Rust implementation.
3. Update tests that currently codify the accidental `parse_project_file()` raise. The new expected behavior is:
   `SASE_CORE_BACKEND=rust` does not break file-path parsing, and `parse_project_file()` still returns the same
   `ChangeSpec` objects as the direct Python parser.
4. Add or adjust a regression test that mirrors the ACE startup path enough to cover the cache path:
   `ChangeSpecSnapshotCache.get_file_specs()` should successfully parse a `.gp` file when `SASE_CORE_BACKEND=rust`.
5. Refresh nearby documentation comments if they still describe Phase 0A as the current state for parser behavior.

## Validation

1. Re-run the focused reproduction:
   `SASE_CORE_BACKEND=rust .venv/bin/python -c 'from sase.core import parser_facade; parser_facade.parse_project_file(...)'`.
2. Run focused tests: `just test tests/test_core_facade.py tests/ace/changespec/test_snapshot_cache.py`.
3. Because this repo requires it after source changes, run `just check` before reporting completion.

## Non-Goals

- Do not change the Rust extension API or add a file-path Rust binding.
- Do not weaken `dispatch()` globally; it should still fail loudly for dispatched operations with no registered Rust
  implementation.
- Do not change ACE startup behavior beyond fixing the parser facade compatibility issue.
