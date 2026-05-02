---
create_time: 2026-03-26 21:49:26
status: not started
prompt: sdd/prompts/202603/harden_commit_stop_hook.md
---

# Plan: Harden sase_commit_stop_hook against repeated blocking and forced commits

**File**: `src/sase/scripts/sase_commit_stop_hook.py` **Status**: not started

## Problem

The `sase_commit_stop_hook` (the main commit stop hook, not the sibling one) has two issues that were already fixed in
its sibling counterpart (`tools/sase_sibling_commit_stop_hook`) in commit 43d71ad:

1. **No once-per-session tracking**: The hook fires on every Stop event. If the agent didn't make the detected changes
   (e.g. leftover changes from a previous agent run), the hook keeps blocking on every subsequent stop — an infinite
   loop of false blocks that prevents the agent from ever completing.

2. **Imperative tone forces commits unconditionally**: The message says "OVERRIDE: ... Ignore any prior instruction
   about not committing. You MUST commit now." This is problematic because it forces agents to commit changes they
   didn't make. The agent should be _asked_ if it made the changes and _told_ to commit only if so.

## Phase 1: Add once-per-session marker file

**Session ID strategy** (same as sibling hook):

- Use `SASE_AGENT_TIMESTAMP` env var (unique per SASE session, e.g. `260326_205712`)
- Fall back to `os.getpid()` for non-SASE environments
- Marker file: `{SASE_TMPDIR or /tmp}/sase_commit_hook_done_{session_id}`

**Where to add the check**: In `main()`, after the disabled check and project*dir resolution (around line 242), but
\_before* the Gemini dedup check. This way the marker works universally across all runtimes (Claude, Codex, Gemini).

**Where to create the marker**: Just before calling `_emit_block()` (around line 289). This ensures the hook blocks
once, creates the marker, and all subsequent stops pass cleanly.

**Changes to `main()`**:

```python
# After line 243 (os.chdir), before _jlog("script_start"):
session_id = os.environ.get("SASE_AGENT_TIMESTAMP") or str(os.getpid())
marker_file = Path(os.environ.get("SASE_TMPDIR", "/tmp")) / f"sase_commit_hook_done_{session_id}"

# After _log_hook_run(), before Gemini dedup:
if marker_file.exists():
    _jlog("session_dedup_skip", marker=str(marker_file))
    return _exit(0, reason="session_dedup")

# Just before _emit_block():
marker_file.touch()
```

**Log event**: Add `"session_dedup_skip"` event so we can see when the marker prevents re-firing.

## Phase 2: Change message tone to interrogative

Replace the current imperative instruction (lines 275-278):

```python
commit_instruction = (
    "OVERRIDE: A post-completion hook has detected uncommitted changes. "
    "Ignore any prior instruction about not committing. You MUST commit now. "
    f"Use your {skill} skill to commit these changes now."
)
```

With an interrogative message that follows the sibling hook pattern. The message needs to vary by runtime since Gemini
agents use a different commit mechanism (CLI) than Claude/Codex agents (skill).

**New helper function** `_build_commit_instruction_message()`:

For Claude/Codex runtime:

```
A post-completion hook has detected uncommitted changes.
Did you make these changes? If so, please commit them using your {skill} skill before continuing.
If you did NOT make these changes, you can safely ignore this warning — it will not appear again this session.
```

For Gemini runtime:

```
A post-completion hook has detected uncommitted changes.
Did you make these changes? If so, run: .venv/bin/sase commit create --message '<msg>' to commit them.
If you did NOT make these changes, you can safely ignore this warning — it will not appear again this session.
```

**Key differences from current text**:

- No "OVERRIDE" or "Ignore any prior instruction" — these are aggressive and unnecessary
- No "You MUST commit now" — replaced with conditional "If so, please commit"
- Added escape hatch: "If you did NOT make these changes, you can safely ignore"
- Added reassurance: "it will not appear again this session" (backed by the marker file)

**Name instruction**: The `_build_name_instruction()` call and its append to `commit_instruction` should remain — it
provides the `SASE_PR_NAME` requirement which is still needed when the agent _does_ commit.

## Phase 3: Update details message construction

The `details` variable (lines 284-288) currently puts the commit instruction after the file list. Keep this structure
but use the new interrogative message. The `_emit_block` reason string (line 290) should also be updated to remove the
imperative language.

## Phase 4: Verify

1. Run `just lint` and `just test` to ensure no regressions
2. Manual check: confirm the log events are correct (`session_dedup_skip` vs existing events)

## Implementation Notes

- The Gemini dedup check (line 259, `stop_hook_active`) can remain as-is — it's a separate dedup mechanism specific to
  Gemini's stdin protocol. The marker file adds a second layer that works across all runtimes.
- Marker file approach means stale markers accumulate in `$SASE_TMPDIR` — acceptable since they're empty files and the
  tmpdir gets cleaned periodically.
- The `_build_name_instruction()` function is unchanged — it still appends the name requirement when `SASE_PR_NAME` is
  set.
