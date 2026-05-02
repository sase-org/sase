---
create_time: 2026-04-27 14:36:23
status: done
prompt: sdd/prompts/202604/agent_loader_bundle_cache.md
---
# Plan: Fix Flaky Agent Loader Bundle Test

## Context

GitHub Actions reports one failing test:
`tests/test_agent_loader_self_heal.py::test_load_agents_from_disk_includes_bundles_missing_from_index`. The assertion
expects `load_agents_from_disk()` to include a dismissed bundle returned by a mock of
`sase.ace.dismissed_agents.load_dismissed_bundles()`, but CI receives an empty dismissed-loader list.

The current loader no longer calls `load_dismissed_bundles()` directly. It calls
`get_global_snapshot_cache().dismissed_bundles()`, which memoizes bundle loads by a signature of JSON files under the
dismissed bundles directory. If an earlier test warms the global cache while the directory signature is empty, a later
test that mocks `load_dismissed_bundles()` can get the cached empty value instead of invoking the mock. That matches a
full-suite-only CI failure after thousands of tests passed.

## Root Cause

The failing test patches the pre-cache dependency rather than the cache boundary used by `load_agents_from_disk()`.
Because `load_agents_from_disk()` uses a process-global `AgentSnapshotCache`, the test is order-dependent: a prior test
can cache `dismissed_bundles == []` for the empty bundle signature, so the mock is bypassed.

This is primarily a test isolation/wiring bug, not evidence that bundle revival is broken in production. In production,
creating or removing bundle JSON files changes the directory signature and invalidates the cached value.

## Implementation

1. Update `test_load_agents_from_disk_includes_bundles_missing_from_index` to mock the current loader boundary:
   `sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache.dismissed_bundles`.
2. Keep the behavioral assertion intact: bundle-only agents are included in `dismissed_from_loader`, marked with
   `_loaded_from_dismissed_bundle`, and not added to `all_agents`.
3. Adjust the mock assertion to verify `dismissed_bundles()` was called once instead of asserting a direct
   `load_dismissed_bundles()` call.
4. Run focused tests for `test_agent_loader_self_heal.py` and the snapshot-cache tests.
5. Because this repo requires it after edits, run `just check`. If dependencies are missing in this workspace, run
   `just install` first.

## Risk

The fix is narrowly scoped to a test that had drifted from the production call graph. It should not change runtime
behavior. The main verification risk is environment setup: this workspace currently lacks at least `textual` outside the
repo virtualenv, so tests should be run through `just` after ensuring the local `.venv` is installed.
