---
create_time: 2026-03-26 21:17:09
status: done
prompt: sdd/prompts/202603/fix_sibling_stop_hook.md
---

# Plan: Fix sase_sibling_commit_stop_hook

**File**: `tools/sase_sibling_commit_stop_hook` **Status**: not started

## Problem

The `sase_sibling_commit_stop_hook` has three bugs and one design issue:

1. **False positives on ephemeral workspaces**: The glob `"$PROJECT_DIR"/../sase-*/` matches ephemeral workspace
   directories like `sase-telegram_100` and `retired Mercurial plugin_100`. These are agent clones and should be ignored — only
   primary repos (e.g., `sase-github`, `sase-telegram`) should be checked.

2. **Imperative tone forces commits**: The message says "Use your /sase*git_commit skill to commit these changes now."
   Agents should be \_asked* if they made the changes and _told_ to commit if so, not commanded unconditionally.

3. **No once-per-session tracking**: The hook fires on every Stop event. If the agent declines to commit (because the
   changes aren't theirs), the hook keeps blocking on every subsequent stop — an infinite loop of false blocks.

4. **Unnecessary VCS complexity**: `resolve_commit_skill()` handles hg/google VCS providers. This hook only needs to
   support git repos (`/sase_git_commit`).

## Verified Behavior

Running the hook with `sase-telegram_100` dirty confirms the bug:

```
Uncommitted changes detected in sibling repo(s): sase-telegram_100. Use your /sase_git_commit skill to commit these changes now.
exit code: 2
```

## Phase 1: Filter ephemeral workspace directories

In `check_sibling_repos()`, skip directories whose basename matches `*_[0-9]*` (the ephemeral workspace naming pattern).

**Change**: After `[ -d "$repo_dir" ] || continue`, add a check:

```bash
# Skip ephemeral workspace directories (e.g., sase-telegram_100)
local repo_basename
repo_basename=$(basename "$repo_dir")
if [[ "$repo_basename" =~ _[0-9]+$ ]]; then
    continue
fi
```

**Test**: Run the hook with only `sase-telegram_100` dirty → should exit 0. Then dirty a primary repo → should block.

## Phase 2: Add once-per-session marker file tracking

**Session ID strategy**:

- Use `SASE_AGENT_TIMESTAMP` (unique per SASE session, e.g., `260326_205712`)
- Fall back to `PPID` for non-SASE environments (the Claude Code / Codex / Gemini parent process)
- Marker file location: `${SASE_TMPDIR:-/tmp}/sase_sibling_hook_done_<session_id>`

**Logic** (at the top of `check_sibling_repos()`, after the disable check):

```bash
SESSION_ID="${SASE_AGENT_TIMESTAMP:-$$}"
MARKER_FILE="${SASE_TMPDIR:-/tmp}/sase_sibling_hook_done_${SESSION_ID}"

if [ -f "$MARKER_FILE" ]; then
    exit 0
fi
```

Create the marker file _only after_ detecting changes and emitting the block message (just before returning non-zero).
This way, the hook blocks once, creates the marker, and subsequent stops pass cleanly.

**Note**: Use `$$` (current shell PID) as the ultimate fallback — less ideal but prevents the hook from never creating a
marker in unknown environments.

## Phase 3: Change message tone to ask, not command

Replace the imperative message with an interrogative one that:

1. Lists the dirty repos
2. Asks the agent if it made those changes
3. Tells it to commit with `/sase_git_commit` _if so_

New message template:

```
Uncommitted changes detected in sibling repo(s): <repos>.
Did you make these changes? If so, please commit them using your /sase_git_commit skill before continuing.
If you did NOT make these changes, you can safely ignore this warning — it will not appear again this session.
```

For Gemini runtime, use the CLI equivalent:

```
Uncommitted changes detected in sibling repo(s): <repos>.
Did you make these changes? If so, run: .venv/bin/sase commit create --message '<msg>' to commit them.
If you did NOT make these changes, you can safely ignore this warning — it will not appear again this session.
```

## Phase 4: Simplify — remove VCS-agnostic commit resolution

Delete:

- `resolve_commit_skill()` function (30 lines)
- `resolve_commit_instruction()` function (5 lines)

Replace with inline strings in the message construction since git is the only target.

Also simplify `repo_has_changes()` — remove the `.hg` branch since we only care about git repos for sibling checks.

## Phase 5: Test

1. **Ephemeral filtering**: With only `sase-telegram_100` dirty → exit 0
2. **Primary detection**: Dirty `sase-github` → blocks with ask-style message
3. **Once-per-session**: Run hook twice with same `SASE_AGENT_TIMESTAMP` → first blocks, second exits 0
4. **Clean state**: All siblings clean → exit 0
5. **Marker cleanup**: Verify marker file gets created in `$SASE_TMPDIR`

## Implementation Notes

- The `.gemini/settings.json` hook config does not need changes (same script path)
- The `.claude/settings.json` hook config does not need changes
- The Codex JSON output path (`emit_block` with `is_codex_runtime`) should also use the new ask-style message
- The marker file approach means stale markers can accumulate in `$SASE_TMPDIR` — acceptable for now since they're tiny
  and the tmpdir gets cleaned periodically
