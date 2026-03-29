---
create_time: 2026-03-29 18:11:02
status: done
---
# Plan: Prevent Silent PR Misses When Agents Skip Commit Skill

## Problem
In `#pr` runs, agents can report that they committed/pushed/opened a PR, but no `commit_result.json` is written and no PR actually exists. The current `sase_commit_stop_hook` writes a per-session dedup marker immediately after the first block. That allows subsequent turns in the same run to bypass the hook even if there are still uncommitted changes.

This creates false-success outcomes in ace snapshots:
- Agent text claims a PR was created.
- `#pr` post-steps see no `commit_result.json` and emit no `meta_pr_url`.
- Run still completes, so users see a “done” agent without a real PR.

## Root Cause
`src/sase/scripts/sase_commit_stop_hook.py` currently:
1. Checks for an existing marker at start and exits early (`session_dedup_skip`).
2. On first block, creates the marker unconditionally before returning block/deny.

So if the agent ignores the instruction to run `/sase_git_commit`, all following turns in that session bypass blocking.

## Goals
1. Keep blocking while local changes remain uncommitted.
2. Avoid changing commit workflow semantics or xprompt contract.
3. Preserve runtime compatibility (Codex/Claude/Gemini).
4. Add focused tests so regressions are caught.

## Proposed Changes
1. **Tighten stop-hook marker semantics** in `sase_commit_stop_hook.py`:
   - Remove early `marker_file.exists()` bypass for active dirty state.
   - Only create/update dedup marker in success path (`no_changes`) so dedup represents “already clean”.
   - Continue honoring Gemini’s `stop_hook_active` guard to avoid Gemini-specific double-prompt behavior.

2. **Improve logging signals**:
   - Emit explicit structured event when a stale marker is ignored while changes still exist.
   - Keep existing `block_emitted` / `script_exit` events unchanged for downstream tooling.

3. **Add unit tests** for stop-hook behavior:
   - When changes exist and marker exists, hook still blocks (no silent bypass).
   - When no changes, hook exits cleanly and writes dedup marker.
   - (Gemini) `stop_hook_active` still short-circuits as before.

## Validation
1. Run targeted tests for new stop-hook coverage.
2. Run full `just check` in this workspace.
3. Verify style/lint/type checks pass.

## Expected Outcome
Agents in `#pr` flows can no longer silently continue after ignoring commit instructions. They must produce a real commit path (and therefore `commit_result.json`) before the run can complete with PR metadata.
