---
create_time: 2026-05-28 15:02:01
status: done
prompt: sdd/prompts/202605/tui_diff_workspace_resolution.md
---
# Plan: Remove workspace materialization from TUI diff rendering

## Objective

Improve perceived Agents-tab navigation performance by ensuring prompt-panel agent detail rendering never resolves or
materializes workspaces on the UI thread. The specific target is the hot path:

`build_detail_header_summary -> agent_delta_entries -> get_agent_diff -> _compute_diff_cache_key -> _resolve_workspace_dir`.

Today `_resolve_workspace_dir()` calls `sase.running_field.get_workspace_directory()`, which can create or repair
managed workspaces and write registry/marker files with fsync. That is appropriate for launch/checkout workflows, but
too expensive and surprising for a render path.

## Current Code Shape

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` builds `_DetailHeaderSummary` and includes agent delta
  entries.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py` asks `get_agent_diff()` for unified diff text and parses it
  into `DeltaEntry` rows.
- `src/sase/ace/tui/widgets/file_panel/_diff.py` handles both persisted completed-agent diffs and live running-agent
  diffs. Its cache key currently derives the workspace by calling `get_workspace_directory(project, workspace_num)`.
- `Agent.workspace_dir` already exists and is populated from launch/artifact metadata, status override propagation, and
  workflow child metadata. Directory-mode agents depend on it because `workspace_num` can be `0`.
- The file panel intentionally starts `get_agent_diff()` in a Textual background worker; the prompt-panel summary path
  calls it synchronously during detail rendering.

## Design

1. Change live diff workspace resolution to be read-only.
   - Prefer `Agent.workspace_dir` when present.
   - For agents without explicit workspace metadata, use only the project file's recorded `WORKSPACE_DIR` via
     `sase.workspace_provider.utils.parse_workspace_dir()`.
   - For managed numbered workspaces, derive the conventional sibling path from the recorded primary workspace path and
     `workspace_num` without calling `get_workspace_directory()`.
   - Return `None` if the path cannot be derived or does not exist. A missing live diff is better than blocking the UI
     to create or repair a checkout.

2. Keep completed-agent behavior unchanged.
   - If `diff_path` exists, continue reading the persisted diff first.
   - If the agent is terminal and no persisted diff exists, continue returning `None`.

3. Preserve plan-chain behavior.
   - Keep `_resolve_agent_diff_source()` selecting the newest active coder child for a root plan workflow.
   - Resolve the selected child using its own `workspace_dir` or project metadata, so root plan details show the coder's
     live diff when metadata is available.

4. Keep the existing diff cache semantics.
   - The cache key should still include agent identity, workspace path, provider name, `.git/index` fingerprint, and TTL
     bucket.
   - The change should remove side effects from cache-key creation, not weaken invalidation.

5. Add regression tests around the performance contract.
   - Verify `_compute_diff_cache_key()` and `get_agent_diff()` use `Agent.workspace_dir` and do not call
     `get_workspace_directory()`.
   - Verify numbered workspace fallback can derive `primary_3` from a project file with `WORKSPACE_DIR: primary`.
   - Verify the function returns `None` rather than materializing a workspace when neither explicit metadata nor project
     metadata can provide a usable path.
   - Update existing tests that patch `get_workspace_directory()` to set `workspace_dir` or project file metadata
     instead.

## Verification

- Run focused tests for the diff module: `pytest tests/ace/tui/widgets/file_panel/test_diff_cache.py`
- Because source files will change, run the project-required full check after implementation: `just install`
  `just check`

## Risks And Tradeoffs

- Some legacy running agents may have a `workspace_num` but no `workspace_dir` and no parseable project `WORKSPACE_DIR`;
  their prompt-panel live DELTAS section may disappear instead of forcing a workspace checkout. This is an intentional
  tradeoff for UI responsiveness.
- If a managed workspace directory uses a non-conventional provider-specific path, the read-only derivation may miss it.
  Existing launch and artifact metadata should cover the normal live-agent cases, and explicit `workspace_dir` remains
  authoritative.
- The file panel's background diff fetch will also avoid materialization. That keeps behavior consistent and prevents
  background workers from mutating workspace registry state during passive display.
