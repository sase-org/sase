---
create_time: 2026-04-30 03:33:06
status: done
prompt: sdd/prompts/202604/fix_agent_cleanup_rs_validation.md
---
# Fix agent-cleanup Rust facade test failures

## Context

The reported `just test` failures are both in `tests/test_core_facade/test_agent_cleanup_execution.py`.

- `try_release_workspace_from_content(...)` returned `None` for a valid `RUNNING:` block.
- `mark_*_agents_as_killed_rust(...)` returned `None` where the Python helpers returned updated entries.

The Python facade returns `None` only when `require_rust_binding(...)` raises `ImportError` or `AttributeError`. Since
the tests use `pytest.importorskip("sase_core_rs")`, the failure mode is an importable but stale `sase_core_rs` wheel
that lacks one or more of the agent-cleanup execution bindings.

The sibling `../sase-core` source already contains the needed implementations and PyO3 exports:

- `release_workspace_from_content`
- `mark_hook_agents_as_killed`
- `mark_mentor_agents_as_killed`
- `mark_comment_agents_as_killed`

The local `Justfile` already tries to prevent stale Rust wheels by running `tools/validate_sase_core_rs` during
`_setup`, but that helper's `REQUIRED_BINDINGS` list currently covers older parser/status/git/agent-scan surfaces and
does not include these agent-cleanup execution bindings. That lets `just test` proceed with a stale extension.

## Plan

1. Extend Rust extension validation.
   - Add the agent-cleanup planning/execution bindings to `tools/validate_sase_core_rs`'s required binding list.
   - Include `plan_agent_cleanup` as well, so the validation surface matches the current hard-runtime cleanup facade
     expectations.
   - Keep the validation focused on binding presence plus the existing scalar timestamp behavior probe; do not duplicate
     all facade tests in the setup helper.

2. Rebuild/install the local Rust extension in this workspace.
   - Run `just install` or `just rust-install` after the validation change so `.venv` gets the current `../sase-core`
     bindings.
   - Confirm `sase_core_rs` imports and exposes the newly-required cleanup bindings.

3. Verify the reported failures directly.
   - Run the focused failing test file: `just test tests/test_core_facade/test_agent_cleanup_execution.py`
   - If the local `just test` recipe does not accept file arguments, use the repo venv pytest equivalent.

4. Run the repo-required verification.
   - Because this changes the `sase` repo, run `just check` before final response, per `memory/short/build_and_run.md`.
   - If `just check` is too broad or fails for unrelated environmental reasons, capture the exact failure and report it.

## Expected outcome

Fresh workspaces and stale developer environments will no longer silently accept an old `sase_core_rs` wheel that lacks
agent-cleanup execution exports. `_setup` will rebuild from `../sase-core` before tests, and the reported facade tests
will receive real Rust results instead of `None`.
