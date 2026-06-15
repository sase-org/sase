---
create_time: 2026-06-15 19:02:59
status: done
prompt: sdd/prompts/202606/live_agent_pencil.md
---
# Plan: Live Agent Pencil Badge

## Problem

Live Agents-tab rows do not show the pencil badge when the agent has made real workspace edits but has not completed
yet. The example `sase-4p.3` shows this: the selected detail pane renders live Deltas from the agent workspace, while
the left list row has no pencil badge.

## Root Cause

The row badge path and the detail-pane delta path use different signals:

- The detail pane calls the live diff path for active agents, resolving `workspace_dir` and asking the VCS provider for
  the current workspace diff.
- The list row calls `agent_file_change_hint(agent)`, which only checks `agent.diff_has_real_edits` and
  `agent.diff_path`.
- Running agents normally have `workspace_dir` in `agent_meta.json`, but no persisted `diff_path` until finalization.
  Therefore legitimate live workspace edits are visible in the detail pane but invisible to the row badge.

The concrete `sase-4p.3` artifact confirms this shape: its metadata has
`workspace_dir=/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10/` and no `diff_path`; `git status` in that
workspace reports modified source and test files.

## Constraints

- Do not perform synchronous VCS or disk-heavy work in row rendering or on the Textual event loop.
- Preserve the existing persisted-diff behavior for completed agents, including hiding plan/prompt bookkeeping-only
  diffs.
- Make cache invalidation explicit so a row can update when the live hint changes.
- Keep the fix local to the TUI presentation layer unless a reusable backend contract is clearly needed.

## Implementation Approach

1. Add a TUI-only precomputed live file-change hint on `Agent`.
   - Use a nullable field, separate from `diff_path`, for active workspace dirtiness.
   - Exclude it from dismissed bundle persistence, like `diff_has_real_edits`.

2. Populate that hint during the agent load/normalization path, not during row rendering.
   - Reuse the active-agent workspace resolution and VCS-provider access already used by the detail pane where
     practical.
   - Run it only for active/live statuses with a resolvable workspace and no persisted `diff_path` classification.
   - Fail closed for unsupported or unreadable live workspace checks so row rendering stays stable.

3. Preserve "real edits" semantics.
   - Prefer deriving changed paths from live diff text and applying the same bookkeeping-path exclusion used for
     persisted diffs.
   - If the provider cannot produce a live diff, avoid adding broad false positives unless an existing API can expose
     paths cheaply and reliably.

4. Update row hint and render cache logic.
   - `agent_file_change_hint()` should return the persisted classification when present, otherwise the live precomputed
     hint, otherwise the historical `diff_path` fallback.
   - `agent_render_key()` should continue to include the effective hint so selective row patching invalidates when the
     badge appears or disappears.

5. Add focused tests.
   - Row rendering: a running agent with the live hint shows the pencil without a `diff_path`; a false live hint omits
     it.
   - Render cache: the key changes when the live hint changes.
   - Loader/status normalization: active agents with live workspace diffs get the hint, bookkeeping-only diffs do not,
     and completed `diff_path` classification remains authoritative.

6. Verify.
   - Run the focused unit tests for row rendering/cache/live hint behavior.
   - Run `just install` and `just check` after implementation, per project instructions, unless only exempt files
     changed.

## Risk Management

The main risk is adding expensive live VCS checks to a hot refresh path. The fix will keep those checks out of rendering
and off the event loop, and will keep the first implementation scoped to live rows that already have workspace metadata.
If the focused checks are too expensive in practice, the follow-up is to memoize live badge checks by workspace path and
short TTL, mirroring the detail-pane diff cache.
